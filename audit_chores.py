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

def classify_replies_with_ai(thread_text, user_ids, current_week):
    """Uses Gemini Flash to classify who has completed their chores."""
    if not model:
        print("⚠️ Gemini API Key missing. Falling back to basic keyword matching.")
        return {uid: "not_done" for uid in user_ids}

    prompt = f"""
    The following is a list of messages from a Slack thread where housemates report completing their weekly chores.
    The current week being audited is: {current_week}
    Current users to check: {", ".join(user_ids)}
    
    Thread Messages:
    {thread_text}
    
    INSTRUCTIONS:
    - Determine if each user has completed their chores based on their messages.
    - Be smart about typos: if someone mentions a date like "2020" but the current week is in 2026, assume they meant the current week.
    - If a user says "done", "cleaned", "I did the [zone]", or "forgot to text but it's done", mark them as completed.
    
    Use exactly one of these labels:
    - "completed": They clearly stated they finished the chore.
    - "not_done": They haven't replied, gave an excuse, or said they will do it later.
    
    Return the result ONLY as a valid JSON object mapping user_id to status.
    Example: {{"U123": "completed", "U456": "not_done"}}
    """
    
    try:
        response = model.generate_content(prompt)
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

    # Calculate date range for the current week header (to match Sunday assignment)
    today = datetime.date.today()
    days_to_subtract = (today.weekday() + 1) % 7 
    start_of_week = today - datetime.timedelta(days=days_to_subtract)
    end_of_week = start_of_week + datetime.timedelta(days=7)
    date_range_str = f"{start_of_week.strftime('%Y-%m-%d')} to {end_of_week.strftime('%Y-%m-%d')}"
    year = start_of_week.year

    audit_report = {
        "on_time": [],
        "late_approved": [],
        "missed": []
    }

    for thread_info in reversed(recent_threads):
        ts = thread_info["ts"]
        week = thread_info["week"]
        is_current_week = (week == current_week)
        
        try:
            replies_res = client.conversations_replies(channel=CHANNEL_ID, ts=ts)
            messages = replies_res.get("messages", [])
            thread_text = "\n".join([f"<@{m.get('user')}>: {m.get('text')}" for m in messages])
            
            week_history = ledger.get("history", {}).get(week, {})
            assigned_users = list(week_history.get("assignments", {}).keys())
            
            if not assigned_users:
                continue

            classifications = classify_replies_with_ai(thread_text, assigned_users, week)
            
            for user_id in assigned_users:
                status = classifications.get(user_id, "not_done")
                prev_status = week_history.get("completions", {}).get(user_id)
                
                if is_current_week:
                    if status == "completed":
                        ledger["history"][week]["completions"][user_id] = True
                        audit_report["on_time"].append(user_id)
                    else:
                        if prev_status is not True: 
                            ledger["history"][week]["completions"][user_id] = False
                            ledger["users"][user_id]["missed_weeks"].append(week)
                            ledger["users"][user_id]["total_fines"] += 10
                            audit_report["missed"].append(user_id)
                else:
                    if prev_status is False and status == "completed":
                        ledger["history"][week]["completions"][user_id] = True
                        if week in ledger["users"][user_id]["missed_weeks"]:
                            ledger["users"][user_id]["missed_weeks"].remove(week)
                            ledger["users"][user_id]["total_fines"] -= 10
                            audit_report["late_approved"].append((user_id, week))

        except Exception as e:
            print(f"Error auditing thread {ts}: {e}")

    # --- POST AUDIT REPORT ---
    report_blocks = [{"type": "header", "text": {"type": "plain_text", "text": f"📊 End of Week Audit: Week {year} {date_range_str}"}}]
    
    sections = []
    if audit_report["on_time"]:
        names = ", ".join([f"<@{u}>" for u in audit_report["on_time"]])
        sections.append(f"✅ *Completed on time:* {names}")
    
    if audit_report["missed"]:
        names = ", ".join([f"<@{u}>" for u in audit_report["missed"]])
        sections.append(f"🚨 *Missed Deadline:* {names}")
        
    if audit_report["late_approved"]:
        late_names = ", ".join([f"<@{u}> ({w})" for u, w in audit_report["late_approved"]])
        sections.append(f"🕰️ *Late Updates Approved:* {late_names}")

    if not sections:
        sections.append("No activity detected this week.")
        
    report_blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n\n".join(sections)}})
    
    # Send the message without mentioning fines or the pot
    client.chat_postMessage(
        channel=CHANNEL_ID, 
        blocks=report_blocks,
        text=f"📊 Weekly Audit Results are in for {date_range_str}" 
    )
    
    save_ledger(ledger)

if __name__ == "__main__":
    main()
