import os
import json
import re
from slack_sdk import WebClient

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")
client = WebClient(token=SLACK_BOT_TOKEN)

def load_ledger():
    with open("ledger.json", "r") as f: return json.load(f)

def save_ledger(data):
    with open("ledger.json", "w") as f: json.dump(data, f, indent=2)

def main():
    ledger = load_ledger()
    thread_ts = ledger["metadata"].get("current_thread_ts")
    current_week = ledger["metadata"].get("current_week")
    assigned_users = ledger["metadata"].get("assigned_users_this_week", [])
    
    audit_messages = []

    # --- 1. PROCESS RETROACTIVE CLAIMS ---
    # Fetch recent messages in the main channel
    history = client.conversations_history(channel=CHANNEL_ID, limit=50)
    for msg in history.get("messages", []):
        text = msg.get("text", "").lower()
        user_id = msg.get("user")
        
        # Look for "cleaned-YYYY-WW"
        match = re.search(r'cleaned-(\d{4}-\d{2})', text)
        if match and user_id in ledger["users"]:
            claimed_week = match.group(1)
            if claimed_week in ledger["users"][user_id]["missed_weeks"]:
                # Reverse the fine!
                ledger["users"][user_id]["missed_weeks"].remove(claimed_week)
                ledger["users"][user_id]["total_fines"] -= 10
                audit_messages.append(f"✅ <@{user_id}> retroactively claimed {claimed_week}. 10€ fine removed.")

    # --- 2. AUDIT THIS WEEK'S THREAD ---
    if thread_ts and assigned_users:
        replies = client.conversations_replies(channel=CHANNEL_ID, ts=thread_ts)
        # Get users who replied with an approval word
        completed_users = set()
        for reply in replies.get("messages", []):
            text = reply.get("text", "").lower()
            if any(word in text for word in ["done", "cleaned", "finished"]):
                completed_users.add(reply.get("user"))
        
        # Fine those who missed it
        for user_id in assigned_users:
            if user_id not in completed_users:
                ledger["users"][user_id]["missed_weeks"].append(current_week)
                ledger["users"][user_id]["total_fines"] += 10
                audit_messages.append(f"🚨 <@{user_id}> failed to report chores. Added 10€ fine.")

# --- 3. POST AUDIT REPORT ---
    report_blocks = [{"type": "header", "text": {"type": "plain_text", "text": f"📊 End of Week Audit: {current_week}"}}]
    
    if audit_messages:
        report_blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(audit_messages)}})
    else:
        report_blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "Everyone did their chores this week! 🥳"}})
        
    # Calculate Total Pot
    total_pot = sum([u["total_fines"] for u in ledger["users"].values()])
    report_blocks.append({"type": "divider"})
    report_blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"💰 *Current Cleaning Fund Pot: {total_pot}€*"}})
    
    # FIX 1: Add the 'text' argument for mobile push notifications
    client.chat_postMessage(
        channel=CHANNEL_ID, 
        blocks=report_blocks,
        text=f"📊 Weekly Audit Results are in! Pot: {total_pot}€" 
    )
    
    # FIX 2: Use Python's 'None' instead of JSON's 'null'
    ledger["metadata"]["current_thread_ts"] = None
    save_ledger(ledger)

if __name__ == "__main__":
    main()