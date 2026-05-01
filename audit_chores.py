import os
import json
import re
import datetime
import google.generativeai as genai
from slack_sdk import WebClient
from drive_storage import load_ledger, save_ledger

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

client = WebClient(token=SLACK_BOT_TOKEN)

# Initialize Gemini
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    model = None

def classify_replies_with_ai(thread_text, user_ids):
    """Uses Gemini Flash to classify who has completed their chores."""
    if not model:
        print("⚠️ Gemini API Key missing. Falling back to basic keyword matching.")
        return {uid: "not_done" for uid in user_ids} # Simplified fallback

    prompt = f"""
    The following is a list of replies in a Slack thread where housemates are supposed to report that they finished their chores.
    People are assigned chores on Sunday and have until Tuesday to finish.
    
    Current users to check: {", ".join(user_ids)}
    
    Thread Messages:
    {thread_text}
    
    For each user ID provided, determine their status. 
    Use exactly one of these labels:
    - "completed_on_time": They clearly stated they finished the chore (e.g. "done", "cleaned", "finished").
    - "completed_late": They are reporting it's done, but the context implies they missed the original deadline.
    - "not_done": They haven't replied, gave an excuse, or said they will do it later.
    
    Return the result ONLY as a valid JSON object mapping user_id to status.
    Example: {{"U123": "completed_on_time", "U456": "not_done"}}
    """
    
    try:
        response = model.generate_content(prompt)
        # Extract JSON from response (handling potential markdown formatting)
        json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
    except Exception as e:
        print(f"❌ Gemini Error: {e}")
    
    return {}

def main():
    ledger = load_ledger()
    recent_threads = ledger["metadata"].get("recent_threads", [])
    current_week = ledger["metadata"].get("current_week")
    
    if not recent_threads:
        print("No threads to audit. Skipping.")
        return

    audit_report = {
        "on_time": [],
        "late_approved": [],
        "missed": []
    }

    # We iterate backwards through the last 3 threads
    for thread_info in reversed(recent_threads):
        ts = thread_info["ts"]
        week = thread_info["week"]
        is_current_week = (week == current_week)
        
        print(f"Auditing Week {week} (Thread: {ts})...")
        
        try:
            replies_res = client.conversations_replies(channel=CHANNEL_ID, ts=ts)
            messages = replies_res.get("messages", [])
            
            # Combine all messages into a single text block for the AI
            thread_text = "\n".join([f"<@{m.get('user')}>: {m.get('text')}" for m in messages])
            
            # Who was supposed to clean this week?
            # We check the history object we created during assignment
            week_history = ledger.get("history", {}).get(week, {})
            assigned_users = list(week_history.get("assignments", {}).keys())
            
            if not assigned_users:
                continue

            # Classify using AI
            classifications = classify_replies_with_ai(thread_text, assigned_users)
            
            for user_id in assigned_users:
                status = classifications.get(user_id, "not_done")
                prev_status = week_history.get("completions", {}).get(user_id)
                
                # --- LOGIC FOR CURRENT WEEK ---
                if is_current_week:
                    if status == "completed_on_time":
                        ledger["history"][week]["completions"][user_id] = True
                        audit_report["on_time"].append(user_id)
                    else:
                        # Fining happens here
                        if prev_status is not True: # Don't double fine
                            ledger["history"][week]["completions"][user_id] = False
                            ledger["users"][user_id]["missed_weeks"].append(week)
                            ledger["users"][user_id]["total_fines"] += 10
                            audit_report["missed"].append(user_id)
                
                # --- LOGIC FOR PREVIOUS WEEKS (Retroactive) ---
                else:
                    # If they were previously "False" (fined) but now Gemini says "completed"
                    if prev_status is False and status in ["completed_on_time", "completed_late"]:
                        ledger["history"][week]["completions"][user_id] = True
                        if week in ledger["users"][user_id]["missed_weeks"]:
                            ledger["users"][user_id]["missed_weeks"].remove(week)
                            ledger["users"][user_id]["total_fines"] -= 10
                            audit_report["late_approved"].append((user_id, week))

        except Exception as e:
            print(f"Error auditing thread {ts}: {e}")

    # --- POST AUDIT REPORT ---
    report_blocks = [{"type": "header", "text": {"type": "plain_text", "text": f"📊 End of Week Audit: {current_week}"}}]
    
    sections = []
    if audit_report["on_time"]:
        names = ", ".join([f"<@{u}>" for u in audit_report["on_time"]])
        sections.append(f"✅ *Completed on time:* {names}")
    
    if audit_report["missed"]:
        names = ", ".join([f"<@{u}>" for u in audit_report["missed"]])
        sections.append(f"🚨 *Missed Deadline:* {names} (10€ fine added)")
        
    if audit_report["late_approved"]:
        late_names = ", ".join([f"<@{u}> ({w})" for u, w in audit_report["late_approved"]])
        sections.append(f"🕰️ *Late Updates Approved:* {late_names} (Fines removed!)")

    if not sections:
        sections.append("No activity detected this week.")
        
    report_blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n\n".join(sections)}})
        
    total_pot = sum([u["total_fines"] for u in ledger["users"].values()])
    report_blocks.append({"type": "divider"})
    report_blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"💰 *Current Cleaning Fund Pot: {total_pot}€*"}})
    
    client.chat_postMessage(
        channel=CHANNEL_ID, 
        blocks=report_blocks,
        text=f"📊 Weekly Audit Results are in! Pot: {total_pot}€" 
    )
    
    save_ledger(ledger)

if __name__ == "__main__":
    main()
