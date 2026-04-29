import os
import json
import datetime
import requests
from icalendar import Calendar
from slack_sdk import WebClient
from drive_storage import load_ledger, save_ledger

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")
CALENDAR_URL = os.environ.get("ICAL_URL")

ZONES = ["Kitchen", "Living Room", "Hallway", "Bathrooms", "Gardens"]
client = WebClient(token=SLACK_BOT_TOKEN)

def get_away_users(ledger):
    """Downloads the .ics and checks if any housemate is away today."""
    away_users = []
    if not CALENDAR_URL: return away_users
    
    try:
        cal_data = requests.get(CALENDAR_URL).text
        cal = Calendar.from_ical(cal_data)
        today = datetime.date.today()
        
        for component in cal.walk('vevent'):
            start = component.get('dtstart').dt
            end = component.get('dtend').dt
            if type(start) == datetime.datetime: start = start.date()
            if type(end) == datetime.datetime: end = end.date()
            
            if start <= today <= end:
                summary = str(component.get('summary')).lower()
                if any(word in summary for word in ['away', 'holiday', 'out']):
                    for user_id, user_data in ledger["users"].items():
                        if user_data["name"].lower() in summary:
                            away_users.append(user_id)
    except Exception as e:
        print(f"Calendar check failed: {e}")
    return away_users

def main():
    ledger = load_ledger()
    year, week_num = datetime.date.today().isocalendar()[:2]
    current_week_str = f"{year}-{week_num:02d}"
    
    all_users = list(ledger["users"].keys())
    away_users = get_away_users(ledger)
    home_users = [u for u in all_users if u not in away_users]
    
    # 1. FAIRNESS ALGORITHM: Assign Primary Zones
    assignments = {user: [] for user in home_users}
    for user_id in home_users:
        # Get next zone based on last one assigned
        last_idx = ledger["users"][user_id].get("last_zone_index", -1)
        new_idx = (last_idx + 1) % len(ZONES)
        
        assignments[user_id].append(ZONES[new_idx])
        ledger["users"][user_id]["last_zone_index"] = new_idx

    # 2. HANDLE EXTRA ZONES (If fewer people than zones)
    # Get zones not yet assigned
    assigned_zones_set = set([tasks[0] for tasks in assignments.values()])
    unassigned_zones = [z for z in ZONES if z not in assigned_zones_set]
    
    if unassigned_zones:
        # Rotate who gets the extra work using a pointer
        extra_pointer = ledger["metadata"].get("extra_task_pointer", 0)
        
        for extra_zone in unassigned_zones:
            # Pick a home user to do extra duty
            user_to_assign = home_users[extra_pointer % len(home_users)]
            assignments[user_to_assign].append(extra_zone)
            extra_pointer += 1
            
        ledger["metadata"]["extra_task_pointer"] = extra_pointer % len(home_users)

    # 3. FORMAT SLACK MESSAGE
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": f"🧹 Chore Rotation: Week {current_week_str}"}}]
    if away_users:
        away_names = ", ".join([ledger["users"][u]["name"] for u in away_users])
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"🌴 _Skipping {away_names} (Away). Rotation paused for them._"}})
    
    for user_id, tasks in assignments.items():
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*<@{user_id}>*\n" + " & ".join(tasks)}})
        
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "⚠️ *Reply 'done' in this thread by Sunday night to avoid a 10€ fine!*"}]})

    # 4. SEND MESSAGE & UPDATE LEDGER HISTORY
    response = client.chat_postMessage(
        channel=CHANNEL_ID, 
        blocks=blocks,
        text=f"🧹 Chore Rotation: Week {current_week_str}"
    )
    
    ledger["metadata"]["current_thread_ts"] = response["ts"]
    ledger["metadata"]["current_week"] = current_week_str
    ledger["metadata"]["assigned_users_this_week"] = home_users
    
    # Initialize history for this week
    if "history" not in ledger: ledger["history"] = {}
    ledger["history"][current_week_str] = {
        "assignments": assignments,
        "completions": {u: None for u in home_users} # null means pending
    }
    
    save_ledger(ledger)

if __name__ == "__main__":
    main()
