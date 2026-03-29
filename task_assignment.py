import os
import json
import datetime
import requests
from icalendar import Calendar
from slack_sdk import WebClient

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")
CALENDAR_URL = os.environ.get("ICAL_URL") # Add this secret to GitHub!

ZONES = ["Kitchen", "Living Room", "Hallway", "Bathrooms", "Gardens"]
client = WebClient(token=SLACK_BOT_TOKEN)

def load_ledger():
    with open("ledger.json", "r") as f:
        return json.load(f)

def save_ledger(data):
    with open("ledger.json", "w") as f:
        json.dump(data, f, indent=2)

def get_away_users(ledger):
    """Downloads the .ics and checks if any housemate is away today."""
    away_users = []
    if not CALENDAR_URL: return away_users
    
    try:
        cal_data = requests.get(CALENDAR_URL).text
        cal = Calendar.from_ical(cal_data)
        today = datetime.date.today()
        
        for component in cal.walk('vevent'):
            # Basic check: if event is happening today
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
    
    # 1. Determine who is home and active zones
    all_users = list(ledger["users"].keys())
    away_users = get_away_users(ledger)
    home_users = [u for u in all_users if u not in away_users]
    
    # Drop zones from the end based on missing people
    active_zones = ZONES[:len(home_users) + 1] if len(home_users) < len(all_users) else ZONES
    
    # 2. Assign chores
    assignments = {user: [] for user in home_users}
    for i, user in enumerate(home_users):
        zone_index = (i + week_num) % len(active_zones)
        assignments[user].append(active_zones[zone_index])
        
        # Double duty for the offset person
        if i == (week_num % len(home_users)):
            fifth_zone_index = (len(home_users) + week_num) % len(active_zones)
            if active_zones[fifth_zone_index] not in assignments[user]:
                assignments[user].append(active_zones[fifth_zone_index])

    # 3. Format Message
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": f"🧹 Chore Rotation: Week {current_week_str}"}}]
    if away_users:
        away_names = ", ".join([ledger["users"][u]["name"] for u in away_users])
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"🌴 _Skipping {away_names} (Away). Dropping lowest priority zones._"}})
    
    for user_id, tasks in assignments.items():
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*<@{user_id}>*\n" + " & ".join(tasks)}})
        
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "⚠️ *Reply 'done' in this thread by Sunday night to avoid a 10€ fine!*"}]})

    # 4. Send Message & Update Ledger
    response = client.chat_postMessage(channel=CHANNEL_ID, blocks=blocks)
    
    ledger["metadata"]["current_thread_ts"] = response["ts"]
    ledger["metadata"]["current_week"] = current_week_str
    ledger["metadata"]["assigned_users_this_week"] = home_users
    save_ledger(ledger)

if __name__ == "__main__":
    main()