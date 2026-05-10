import os
import json
import datetime
import requests
import re
from icalendar import Calendar
from slack_sdk import WebClient
from google import genai
from drive_storage import load_ledger, save_ledger, get_calendar_service

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")
CALENDAR_URL = os.environ.get("ICAL_URL")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

CHORE_DETAILS = {
    "Kitchen": "Disinfectant wipe of counters, clean stove/walls, clean sink/tap area, vacuum/sweep and mop, trash & recycling, check microwave/airfryer",
    "Living Room": "Vacuum and sweep, tidy table, wash/replace tablecloth if needed, fluff cushions, fold blankets, water plants",
    "Hallways": "Vacuum/sweep and mop hallways, sweep stairs, tidy hallway tables and entry area, water plants",
    "Garden": "Clear ashtrays, weed concrete patio, wipe table/chairs, tidy basin, quick clean outside toilet",
    "Upstairs Bathroom": "Scrub shower (floor/walls), wipe sink, toilet disinfectant, take out trash, vacuum/mop floors",
    "Downstairs Bathroom": "Scrub shower (floor/walls), wipe sink, toilet disinfectant, take out trash, vacuum/mop floors"
}

MAIN_ZONES = ["Kitchen", "Living Room", "Hallways", "Garden"]
UPSTAIRS_USERS = ["U0AU4DWH2V7", "U0ATA3JK24X", "U0ATA3GRBRD"] # Kika, Josie, Angela
DOWNSTAIRS_USER = "U0AN4FD067K" # Pab

client = WebClient(token=SLACK_BOT_TOKEN)

# Initialize Gemini
if GEMINI_API_KEY:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
    model_id = "gemini-2.5-pro"
else:
    ai_client = None

def get_calendar_id():
    """Extracts the calendar ID from the private ICAL URL."""
    if not CALENDAR_URL: return None
    # Typical format: https://calendar.google.com/calendar/ical/[ID]/private-[SECRET]/basic.ics
    match = re.search(r'/ical/([^/]+)/private', CALENDAR_URL)
    if match:
        return match.group(1).replace('%40', '@')
    return None

def discover_absences_with_ai(ledger):
    """Scans Slack history for absence mentions and updates Google Calendar."""
    if not ai_client: return
    
    calendar_id = get_calendar_id()
    if not calendar_id:
        print("⚠️ Could not determine Calendar ID. Skipping AI discovery.")
        return

    # 1. Fetch last 7 days of messages
    one_week_ago = (datetime.datetime.now() - datetime.timedelta(days=7)).timestamp()
    try:
        res = client.conversations_history(channel=CHANNEL_ID, oldest=one_week_ago)
        messages = res.get("messages", [])
        if not messages: return
        
        thread_text = "\n".join([f"<@{m.get('user')}>: {m.get('text')}" for m in messages])
    except Exception as e:
        print(f"❌ Error fetching Slack history: {e}")
        return

    # 2. Ask Gemini to parse
    user_context = ", ".join([f"{u['name']} (ID: {uid})" for uid, u in ledger["users"].items()])
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    
    prompt = f"""
    Analyze the following Slack messages from a house group chat. 
    Identify anyone who mentioned being away, out of the house, or on holiday for the COMING WEEK or longer.
    
    Today's Date: {today_str}
    Housemates: {user_context}
    
    Messages:
    {thread_text}
    
    INSTRUCTIONS:
    1. Look for mentions of absences. 
    2. Support proxy reporting (e.g., if Pabi says "Kika is away for 2 months", mark Kika as away).
    3. Identify if they mentioned a "subletter" or "guest" covering for them.
    4. Estimate start/end dates. If "next 2 months" is said today ({today_str}), start is today, end is {today_str} + 60 days.
    5. Return a JSON list of objects:
       [{{"user_id": "...", "name": "...", "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "sublet": true/false}}]
    
    Return ONLY valid JSON. If no one is away, return [].
    """

    try:
        response = ai_client.models.generate_content(model=model_id, contents=prompt)
        json_match = re.search(r'\[.*\]', response.text, re.DOTALL)
        if not json_match: return
        
        new_absences = json.loads(json_match.group(0))
        if not new_absences: return

        # 3. Write to Google Calendar
        cal_service = get_calendar_service()
        for abs_info in new_absences:
            name = abs_info['name']
            event_title = f"Away: {name}" + (" (Sublet)" if abs_info['sublet'] else "")
            
            # Check if event already exists to avoid duplicates
            # (Simple check: search for title in that date range)
            time_min = f"{abs_info['start']}T00:00:00Z"
            time_max = f"{abs_info['end']}T23:59:59Z"
            
            existing = cal_service.events().list(
                calendarId=calendar_id, q=event_title, 
                timeMin=time_min, timeMax=time_max
            ).execute()
            
            if not existing.get('items'):
                print(f"📅 Creating Calendar event for {name} ({abs_info['start']} to {abs_info['end']})")
                event_body = {
                    'summary': event_title,
                    'start': {'date': abs_info['start']},
                    'end': {'date': abs_info['end']},
                    'description': f"Automatically added by ChoreBot based on Slack message."
                }
                cal_service.events().insert(calendarId=calendar_id, body=event_body).execute()
                
    except Exception as e:
        print(f"❌ AI Absence Discovery failed: {e}")

def get_away_status(ledger):
    """Checks the .ics and returns who is away and who is subletting."""
    away_skip = []
    away_sublet = []
    
    if not CALENDAR_URL: return away_skip, away_sublet
    
    try:
        cal_data = requests.get(CALENDAR_URL).text
        cal = Calendar.from_ical(cal_data)
        today = datetime.date.today()
        
        for component in cal.walk('vevent'):
            start = component.get('dtstart').dt
            end = component.get('dtend').dt
            if isinstance(start, datetime.datetime): start = start.date()
            if isinstance(end, datetime.datetime): end = end.date()
            
            # Event is active today
            if start <= today < end: # End date is usually exclusive
                summary = str(component.get('summary')).lower()
                is_sublet = "sublet" in summary or "guest" in summary
                
                for user_id, user_data in ledger["users"].items():
                    if user_data["name"].lower() in summary:
                        if is_sublet:
                            away_sublet.append(user_id)
                        else:
                            away_skip.append(user_id)
    except Exception as e:
        print(f"Calendar check failed: {e}")
        
    return list(set(away_skip)), list(set(away_sublet))

def calculate_assignments(ledger, home_users):
    """Core logic shared between the bot and the simulation."""
    assignments = {user: [] for user in home_users}

    # --- 1. MAIN LOOP ASSIGNMENT ---
    user_to_intended_zone_idx = {}
    zone_idx_to_user = {}
    
    for user_id in home_users:
        last_idx = ledger["users"][user_id].get("last_main_index", -1)
        next_idx = (last_idx + 1) % len(MAIN_ZONES)
        user_to_intended_zone_idx[user_id] = next_idx
        zone_idx_to_user[next_idx] = user_id

    unassigned_main_indices = [i for i in range(len(MAIN_ZONES)) if i not in zone_idx_to_user]
    
    if unassigned_main_indices:
        unassigned_main_indices.sort()
        assigned_main_indices = sorted(zone_idx_to_user.keys(), reverse=True)
        for unassigned_idx in unassigned_main_indices:
            if not assigned_main_indices: break
            lowest_priority_assigned_idx = assigned_main_indices[0]
            if unassigned_idx < lowest_priority_assigned_idx:
                user_id = zone_idx_to_user[lowest_priority_assigned_idx]
                user_to_intended_zone_idx[user_id] = unassigned_idx
                del zone_idx_to_user[lowest_priority_assigned_idx]
                zone_idx_to_user[unassigned_idx] = user_id
                assigned_main_indices.pop(0)

    for user_id, zone_idx in user_to_intended_zone_idx.items():
        assignments[user_id].append(MAIN_ZONES[zone_idx])
        ledger["users"][user_id]["last_main_index"] = zone_idx

    # --- 2. UPSTAIRS BATHROOM LOOP ---
    upstairs_home_users = [u for u in UPSTAIRS_USERS if u in home_users]
    if upstairs_home_users:
        pointer = ledger["metadata"].get("upstairs_bathroom_pointer", 0)
        assigned_upstairs = False
        for i in range(len(UPSTAIRS_USERS)):
            current_target = UPSTAIRS_USERS[(pointer + i) % len(UPSTAIRS_USERS)]
            if current_target in home_users:
                assignments[current_target].append("Upstairs Bathroom")
                ledger["metadata"]["upstairs_bathroom_pointer"] = (pointer + i + 1) % len(UPSTAIRS_USERS)
                assigned_upstairs = True
                break
    
    # --- 3. DOWNSTAIRS BATHROOM ---
    if DOWNSTAIRS_USER in home_users:
        assignments[DOWNSTAIRS_USER].append("Downstairs Bathroom")

    return assignments

def main():
    ledger = load_ledger()
    
    # 0. AI Absence Discovery
    discover_absences_with_ai(ledger)
    
    today = datetime.date.today()
    days_to_subtract = (today.weekday() + 1) % 7
    start_of_week = today - datetime.timedelta(days=days_to_subtract)
    end_of_week = start_of_week + datetime.timedelta(days=7)
    
    year, week_num = start_of_week.isocalendar()[:2]
    current_week_str = f"{year}-{week_num:02d}"
    date_range_str = f"{start_of_week.strftime('%Y-%m-%d')} to {end_of_week.strftime('%Y-%m-%d')}"
    
    audit_deadline = today + datetime.timedelta(days=(1 - today.weekday() + 7) % 7 if today.weekday() != 1 else 7)
    deadline_str = audit_deadline.strftime('%A, %B %d')

    # 1. Determine who is home
    all_users = list(ledger["users"].keys())
    away_skip, away_sublet = get_away_status(ledger)
    
    # Home users = everyone not skipping
    home_users = [u for u in all_users if u not in away_skip]
    
    # CALL CORE LOGIC
    assignments = calculate_assignments(ledger, home_users)

    # --- 4. FORMAT SLACK MESSAGE ---
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": f"🧹 Chore Rotation: Week {year} {date_range_str}"}}]
    
    if away_skip:
        away_names = ", ".join([ledger["users"][u]["name"] for u in away_skip])
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"🌴 _Skipping {away_names} (Away). Rotation paused._"}})
    
    if away_sublet:
        for u in away_sublet:
            name = ledger["users"][u]["name"]
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"🏠 *{name} is away but subletting.* {name}, please coordinate with your guest!"}]})
    
    for user_id, tasks in assignments.items():
        task_list = []
        for t in tasks:
            desc = CHORE_DETAILS.get(t, "No description")
            task_list.append(f"• *{t}*: _{desc}_")
        
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*<@{user_id}>*\n" + "\n".join(task_list)}})
        
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"✨ *Friendly reminder: Please ensure your cleaning is done by {deadline_str}!*"}]})

    # --- 5. SEND MESSAGE & UPDATE LEDGER ---
    response = client.chat_postMessage(channel=CHANNEL_ID, blocks=blocks, text=f"🧹 Chore Rotation: Week {year} {date_range_str}")
    
    recent_threads = ledger["metadata"].get("recent_threads", [])
    recent_threads.append({"ts": response["ts"], "week": current_week_str})
    ledger["metadata"]["recent_threads"] = recent_threads[-3:]
    
    ledger["metadata"]["current_thread_ts"] = response["ts"]
    ledger["metadata"]["current_week"] = current_week_str
    ledger["metadata"]["assigned_users_this_week"] = home_users
    
    if "history" not in ledger: ledger["history"] = {}
    ledger["history"][current_week_str] = {
        "assignments": assignments,
        "completions": {u: None for u in home_users}
    }
    
    save_ledger(ledger)

if __name__ == "__main__":
    main()
