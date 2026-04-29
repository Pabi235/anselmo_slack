import os
import json
import re
from slack_sdk import WebClient
from drive_storage import load_ledger, save_ledger

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")
client = WebClient(token=SLACK_BOT_TOKEN)

def main():
    ledger = load_ledger()
    thread_ts = ledger["metadata"].get("current_thread_ts")
    current_week = ledger["metadata"].get("current_week")
    assigned_users = ledger["metadata"].get("assigned_users_this_week", [])
    
    if not current_week:
        print("No active week found in ledger. Skipping audit.")
        return

    audit_messages = []
    
    # Ensure history exists for this week
    if "history" not in ledger: ledger["history"] = {}
    if current_week not in ledger["history"]:
        ledger["history"][current_week] = {"assignments": {}, "completions": {}}

    # --- 1. PROCESS RETROACTIVE CLAIMS ---
    history = client.conversations_history(channel=CHANNEL_ID, limit=50)
    for msg in history.get("messages", []):
        text = msg.get("text", "").lower()
        user_id = msg.get("user")
        
        match = re.search(r'cleaned-(\d{4}-\d{2})', text)
        if match and user_id in ledger["users"]:
            claimed_week = match.group(1)
            if claimed_week in ledger["users"][user_id]["missed_weeks"]:
                ledger["users"][user_id]["missed_weeks"].remove(claimed_week)
                ledger["users"][user_id]["total_fines"] -= 10
                
                # Update history record if it exists
                if claimed_week in ledger["history"]:
                    ledger["history"][claimed_week]["completions"][user_id] = True
                
                audit_messages.append(f"✅ <@{user_id}> retroactively claimed {claimed_week}. 10€ fine removed.")

    # --- 2. AUDIT THIS WEEK'S THREAD ---
    if thread_ts and assigned_users:
        replies = client.conversations_replies(channel=CHANNEL_ID, ts=thread_ts)
        completed_users = set()
        for reply in replies.get("messages", []):
            text = reply.get("text", "").lower()
            if any(word in text for word in ["done", "cleaned", "finished"]):
                completed_users.add(reply.get("user"))
        
        for user_id in assigned_users:
            is_done = user_id in completed_users
            
            # Update detailed history
            ledger["history"][current_week]["completions"][user_id] = is_done
            
            if not is_done:
                ledger["users"][user_id]["missed_weeks"].append(current_week)
                ledger["users"][user_id]["total_fines"] += 10
                audit_messages.append(f"🚨 <@{user_id}> failed to report chores. Added 10€ fine.")
            else:
                print(f"User {user_id} marked as done for {current_week}")

    # --- 3. POST AUDIT REPORT ---
    report_blocks = [{"type": "header", "text": {"type": "plain_text", "text": f"📊 End of Week Audit: {current_week}"}}]
    
    if audit_messages:
        report_blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(audit_messages)}})
    else:
        report_blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "Everyone did their chores this week! 🥳"}})
        
    total_pot = sum([u["total_fines"] for u in ledger["users"].values()])
    report_blocks.append({"type": "divider"})
    report_blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"💰 *Current Cleaning Fund Pot: {total_pot}€*"}})
    
    client.chat_postMessage(
        channel=CHANNEL_ID, 
        blocks=report_blocks,
        text=f"📊 Weekly Audit Results are in! Pot: {total_pot}€" 
    )
    
    ledger["metadata"]["current_thread_ts"] = None
    save_ledger(ledger)

if __name__ == "__main__":
    main()
