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

CHORE_DETAILS = {
    "Kitchen": "Disinfectant wipe of counters, clean stove/walls, clean sink/tap area, vacuum/sweep and mop, trash & recycling, check microwave/airfryer",
    "Living Room": "Vacuum and sweep, tidy table, wash/replace tablecloth if needed, fluff cushions, fold blankets, water plants",
    "Hallways": "Vacuum/sweep and mop hallways, sweep stairs, tidy hallway tables and entry area, water plants",
    "Garden": "Clear ashtrays, weed concrete patio, wipe table/chairs, tidy basin, quick clean outside toilet",
    "Upstairs Bathroom": "Scrub shower (floor/walls), wipe sink, toilet disinfectant, take out trash, vacuum/mop floors",
    "Downstairs Bathroom": "Scrub shower (floor/walls), wipe sink, toilet disinfectant, take out trash, vacuum/mop floors"
}

# Main zones ordered by priority (Importance Weights: Kitchen=5, Living Room=4, Hallways=3, Garden=2)
MAIN_ZONES = ["Kitchen", "Living Room", "Hallways", "Garden"]
UPSTAIRS_USERS = ["U0AU4DWH2V7", "U0ATA3JK24X", "U0ATA3GRBRD"] # Kika, Josie, Angela
DOWNSTAIRS_USER = "U0AN4FD067K" # Pab

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
    
    assignments = {user: [] for user in home_users}

    # --- 1. MAIN LOOP ASSIGNMENT (Kitchen, Living Room, Hallways, Garden) ---
    # a. Calculate intended assignments based on rotation state
    user_to_intended_zone_idx = {}
    zone_idx_to_user = {} # Reverse mapping for zones that ARE assigned
    
    for user_id in home_users:
        last_idx = ledger["users"][user_id].get("last_main_index", -1)
        next_idx = (last_idx + 1) % len(MAIN_ZONES)
        user_to_intended_zone_idx[user_id] = next_idx
        zone_idx_to_user[next_idx] = user_id

    # b. Priority Check: Ensure high priority zones are assigned if someone is away
    unassigned_main_indices = [i for i in range(len(MAIN_ZONES)) if i not in zone_idx_to_user]
    
    if unassigned_main_indices:
        # Sort unassigned by priority (lower index = higher priority)
        unassigned_main_indices.sort()
        
        # Sort assigned users by the priority of the zone they CURRENTLY have (descending index = lower priority)
        # We want to swap the lowest priority assigned zone for the highest priority unassigned zone.
        assigned_main_indices = sorted(zone_idx_to_user.keys(), reverse=True)
        
        for unassigned_idx in unassigned_main_indices:
            if not assigned_main_indices: break
            
            # If the unassigned zone is more important (lower index) than the least important assigned zone
            lowest_priority_assigned_idx = assigned_main_indices[0]
            if unassigned_idx < lowest_priority_assigned_idx:
                user_id = zone_idx_to_user[lowest_priority_assigned_idx]
                
                # Perform the swap in our local mapping
                print(f"Priority Swap: Assigning {MAIN_ZONES[unassigned_idx]} to {ledger['users'][user_id]['name']} instead of {MAIN_ZONES[lowest_priority_assigned_idx]}")
                user_to_intended_zone_idx[user_id] = unassigned_idx
                
                # Update tracking for next iteration of this priority loop
                del zone_idx_to_user[lowest_priority_assigned_idx]
                zone_idx_to_user[unassigned_idx] = user_id
                assigned_main_indices.pop(0)

    # c. Finalize Main Loop assignments and update state
    for user_id, zone_idx in user_to_intended_zone_idx.items():
        assignments[user_id].append(MAIN_ZONES[zone_idx])
        ledger["users"][user_id]["last_main_index"] = zone_idx

    # --- 2. UPSTAIRS BATHROOM LOOP (Kika, Josie, Angela) ---
    upstairs_home_users = [u for u in UPSTAIRS_USERS if u in home_users]
    if upstairs_home_users:
        pointer = ledger["metadata"].get("upstairs_bathroom_pointer", 0)
        
        # Find the next person in the UPSTAIRS_USERS list who is home
        # We try up to 3 times to find someone
        assigned_upstairs = False
        for i in range(len(UPSTAIRS_USERS)):
            current_target = UPSTAIRS_USERS[(pointer + i) % len(UPSTAIRS_USERS)]
            if current_target in home_users:
                assignments[current_target].append("Upstairs Bathroom")
                # Move pointer to the NEXT person for next week
                ledger["metadata"]["upstairs_bathroom_pointer"] = (pointer + i + 1) % len(UPSTAIRS_USERS)
                assigned_upstairs = True
                break
        
        if not assigned_upstairs:
            print("No one home for Upstairs Bathroom duty.")

    # --- 3. DOWNSTAIRS BATHROOM (Pab) ---
    if DOWNSTAIRS_USER in home_users:
        assignments[DOWNSTAIRS_USER].append("Downstairs Bathroom")
    else:
        print("Pab is away; Downstairs Bathroom unassigned.")

    # --- 4. FORMAT SLACK MESSAGE ---
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": f"🧹 Chore Rotation: Week {current_week_str}"}}]
    
    if away_users:
        away_names = ", ".join([ledger["users"][u]["name"] for u in away_users])
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"🌴 _Skipping {away_names} (Away). Rotation paused/skipped._"}})
    
    for user_id, tasks in assignments.items():
        task_list = []
        for t in tasks:
            desc = CHORE_DETAILS.get(t, "No description")
            task_list.append(f"• *{t}*: _{desc}_")
        
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*<@{user_id}>*\n" + "\n".join(task_list)}})
        
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "⚠️ *Reply 'done' in this thread by Sunday night to avoid a 10€ fine!*"}]})

    # --- 5. SEND MESSAGE & UPDATE LEDGER ---
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
        "completions": {u: None for u in home_users}
    }
    
    save_ledger(ledger)

if __name__ == "__main__":
    main()
