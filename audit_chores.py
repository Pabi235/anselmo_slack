import os
import json
import re
import datetime
from google import genai
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from drive_storage import load_ledger, save_ledger

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

client = WebClient(token=SLACK_BOT_TOKEN)

# Initialize Gemini with the new SDK
if GEMINI_API_KEY:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
    # Using the 2.5 Pro model as requested and available in your list
    model_id = "gemini-2.5-pro"
else:
    ai_client = None

def classify_replies_with_ai(thread_text, user_ids, current_week):
    """Uses Gemini Flash to classify who has completed their chores."""
    
    def fallback_match():
        print("💡 Using fallback keyword matching logic...")
        results = {}
        for uid in user_ids:
            user_pattern = rf"<@{uid}>"
            user_messages = [m for m in thread_text.split("\n") if user_pattern in m]
            
            is_done = False
            for msg in user_messages:
                text = msg.lower()
                if any(word in text for word in ["done", "cleaned", "finished", "did it", "completed"]):
                    is_done = True
                    break
            results[uid] = "completed" if is_done else "not_done"
        return results

    if not ai_client:
        return fallback_match()

    user_context = ", ".join([f"ID: {uid}" for uid in user_ids])

    prompt = f"""
    You are an assistant auditing house chores. 
    Below are messages from a Slack thread for the week: {current_week}.

    Users to audit: {user_context}

    Messages:
    {thread_text}

    INSTRUCTIONS:
    1. For each User ID, determine if they completed their chore.
    2. Look for messages from that user or messages mentioning that user.
    3. Accept "done", "finished", "I did the [zone]", "cleaned", and even "forgot to text but I did it".
    4. Ignore year typos (e.g., if they say 2020 but it is 2026).
    5. Return a JSON object where the keys are the EXACT User IDs (e.g., "U0AN4FD067K") and the values are either "completed" or "not_done".

    Output ONLY the JSON.
    """

    try:
        print(f"--- Sending to Gemini ---\nUsers: {user_ids}\n---")
        response = ai_client.models.generate_content(
            model=model_id,
            contents=prompt
        )
        print(f"--- Gemini Response ---\n{response.text}\n---")

        json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
    except Exception as e:
        print(f"❌ Gemini Error: {e}")
        if "404" in str(e):
            print("🔍 Debug: Listing available models for this API key:")
            try:
                for m in ai_client.models.list():
                    print(f"  - {m.name}")
            except:
                print("  (Could not list models)")
    
    return fallback_match()

def main():
    ledger = load_ledger()
    recent_threads = ledger["metadata"].get("recent_threads", [])
    current_week = ledger["metadata"].get("current_week")
    
    if not recent_threads:
        print("No threads to audit. Skipping.")
        return

    # Calculate date range for the current week header
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

    valid_threads = []

    for thread_info in recent_threads:
        ts = thread_info["ts"]
        week = thread_info["week"]
        is_current_week = (week == current_week)
        
        try:
            replies_res = client.conversations_replies(channel=CHANNEL_ID, ts=ts)
            messages = replies_res.get("messages", [])
            valid_threads.append(thread_info)

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
                            if week not in ledger["users"][user_id]["missed_weeks"]:
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

        except SlackApiError as e:
            if e.response["error"] == "thread_not_found":
                print(f"⚠️ Thread {ts} for week {week} not found. Removing from history.")
            else:
                print(f"❌ Slack API Error auditing thread {ts}: {e}")
                valid_threads.append(thread_info)
        except Exception as e:
            print(f"❌ Error auditing thread {ts}: {e}")
            valid_threads.append(thread_info)

    ledger["metadata"]["recent_threads"] = valid_threads[-3:]

    # --- POST AUDIT REPORT ---
    report_blocks = [{"type": "header", "text": {"type": "plain_text", "text": f"📊 End of Week Audit: Week {year} {date_range_str}"}}]
    
    sections = []
    if audit_report["on_time"]:
        names = ", ".join([f"<@{u}>" for u in audit_report["on_time"]])
        sections.append(f"✅ *Completed on time:* {names}")
    
    if audit_report["missed"]:
        really_missed = [u for u in audit_report["missed"] if u not in audit_report["on_time"]]
        if really_missed:
            names = ", ".join([f"<@{u}>" for u in really_missed])
            sections.append(f"🚨 *Missed Deadline:* {names}")
        
    if audit_report["late_approved"]:
        late_names = ", ".join([f"<@{u}> ({w})" for u, w in audit_report["late_approved"]])
        sections.append(f"🕰️ *Late Updates Approved:* {late_names}")

    if not sections:
        sections.append("No activity detected this week.")
        
    report_blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n\n".join(sections)}})
    
    client.chat_postMessage(
        channel=CHANNEL_ID, 
        blocks=report_blocks,
        text=f"📊 Weekly Audit Results are in for {date_range_str}" 
    )
    
    save_ledger(ledger)

if __name__ == "__main__":
    main()
