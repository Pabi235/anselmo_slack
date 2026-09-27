import os
import json
import datetime
import requests
import re
import itertools
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

if GEMINI_API_KEY:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
    model_id = "gemini-2.5-pro"
else:
    ai_client = None

def get_calendar_id():
    if not CALENDAR_URL: return None
    match = re.search(r'/ical/([^/]+)/private', CALENDAR_URL)
    if match:
        return match.group(1).replace('%40', '@')
    return None

def discover_absences_with_ai(ledger):
    if not ai_client: return
    calendar_id = get_calendar_id()
    if not calendar_id: return

    print("🔍 [Discovery] Scanning Slack for new absence mentions...")
    one_week_ago = (datetime.datetime.now() - datetime.timedelta(days=7)).timestamp()
    try:
        res = client.conversations_history(channel=CHANNEL_ID, oldest=one_week_ago)
        messages = res.get("messages", [])
        if not messages: return
        thread_text = "\n".join([f"<@{m.get('user')}>: {m.get('text')}" for m in messages])
    except Exception as e:
        print(f"❌ Slack Error: {e}")
        return

    user_context = ", ".join([f"{u['name']} (ID: {uid})" for uid, u in ledger["users"].items()])
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    
    prompt = f"""
    Identify anyone mentioned as away/out/on holiday for the COMING WEEK or longer.
    Today: {today_str}. Housemates: {user_context}.
    Messages: {thread_text}
    Return JSON list: [{{"user_id": "...", "name": "...", "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "sublet": bool}}]
    """

    try:
        response = ai_client.models.generate_content(model=model_id, contents=prompt)
        json_match = re.search(r'\[.*\]', response.text, re.DOTALL)
        if not json_match: return
        new_absences = json.loads(json_match.group(0))
        if not new_absences: return

        cal_service = get_calendar_service()
        for abs_info in new_absences:
            name = abs_info['name']
            event_title = f"Away: {name}" + (" (Sublet)" if abs_info['sublet'] else "")
            time_min = f"{abs_info['start']}T00:00:00Z"
            time_max = f"{abs_info['end']}T23:59:59Z"
            existing = cal_service.events().list(calendarId=calendar_id, q=event_title, timeMin=time_min, timeMax=time_max).execute()
            if not existing.get('items'):
                print(f"📅 [Calendar] Creating: {event_title}")
                event_body = {'summary': event_title, 'start': {'date': abs_info['start']}, 'end': {'date': abs_info['end']}}
                cal_service.events().insert(calendarId=calendar_id, body=event_body).execute()
    except Exception as e:
        print(f"❌ AI Discovery failed: {e}")

def get_away_status(ledger, week_start, week_end):
    """Checks Calendar for overlaps with the chore week."""
    away_skip = []
    away_sublet = []
    calendar_id = get_calendar_id()
    if not calendar_id: return [], []

    try:
        cal_service = get_calendar_service()
        # Fetch events for the next month to be safe
        time_min = week_start.strftime("%Y-%m-%dT00:00:00Z")
        time_max = (week_end + datetime.timedelta(days=30)).strftime("%Y-%m-%dT23:59:59Z")
        
        events_result = cal_service.events().list(
            calendarId=calendar_id, timeMin=time_min, timeMax=time_max,
            singleEvents=True, orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])

        for event in events:
            summary = event.get('summary', '').lower()
            if not any(word in summary for word in ['away', 'holiday', 'out', 'vacation']):
                continue
            
            start_raw = event['start'].get('date') or event['start'].get('dateTime')
            end_raw = event['end'].get('date') or event['end'].get('dateTime')
            ev_start = datetime.datetime.fromisoformat(start_raw.split('T')[0]).date()
            ev_end = datetime.datetime.fromisoformat(end_raw.split('T')[0]).date()

            # CHECK OVERLAP WITH CHORE WEEK (week_start to week_end)
            # Overlap exists if (start1 <= end2) AND (end1 >= start2)
            if ev_start < week_end and ev_end > week_start:
                is_sublet = "sublet" in summary or "guest" in summary
                for user_id, user_data in ledger["users"].items():
                    if user_data["name"].lower() in summary:
                        print(f"🚩 [Status] {user_data['name']} OVERLAPS with this week ({ev_start} to {ev_end})")
                        if is_sublet:
                            away_sublet.append(user_id)
                        else:
                            away_skip.append(user_id)
            else:
                print(f"⏭️ [Status] Skipping future/past event '{summary}' ({ev_start} to {ev_end})")
                        
    except Exception as e:
        print(f"❌ Calendar API check failed: {e}")
        
    return list(set(away_skip)), list(set(away_sublet))

def ensure_user_state(ledger):
    """Initializes or reconstructs historical zone counts and recent zones from history."""
    history = ledger.get("history", {})
    sorted_weeks = sorted(history.keys())
    
    for uid, udata in ledger.setdefault("users", {}).items():
        if "zone_counts" not in udata:
            udata["zone_counts"] = {zone: 0 for zone in MAIN_ZONES}
            for w in sorted_weeks:
                w_assign = history[w].get("assignments", {}).get(uid, [])
                for task in w_assign:
                    if task in MAIN_ZONES:
                        udata["zone_counts"][task] += 1
                        
        if "recent_zones" not in udata:
            udata["recent_zones"] = []
            for w in sorted_weeks[-4:]:
                w_assign = history[w].get("assignments", {}).get(uid, [])
                for task in w_assign:
                    if task in MAIN_ZONES:
                        udata["recent_zones"].append(task)
                        
        if "upstairs_bathroom_count" not in udata:
            udata["upstairs_bathroom_count"] = 0
            udata["last_upstairs_bathroom_week"] = None
            for w in sorted_weeks:
                w_assign = history[w].get("assignments", {}).get(uid, [])
                if "Upstairs Bathroom" in w_assign:
                    udata["upstairs_bathroom_count"] += 1
                    udata["last_upstairs_bathroom_week"] = w

def calculate_assignments(ledger, home_users, current_week_str=""):
    print(f"🧮 [Logic] Assigning for: {', '.join([ledger['users'][u]['name'] for u in home_users])}")
    ensure_user_state(ledger)
    assignments = {user: [] for user in home_users}

    # 1. MAIN COMMUNAL ZONES (Optimal Permutation Matching)
    num_users = len(home_users)
    num_zones = len(MAIN_ZONES)
    active_zones = MAIN_ZONES[:min(num_users, num_zones)]
    user_list = list(home_users)[:len(active_zones)]

    best_perm = None
    best_cost = float('inf')

    for perm in itertools.permutations(active_zones):
        cost = 0
        for u, z in zip(user_list, perm):
            u_data = ledger["users"][u]
            z_counts = u_data.get("zone_counts", {})
            recent = u_data.get("recent_zones", [])

            # Lifetime balance: strongly prefer zones this user has cleaned fewer times
            cost += z_counts.get(z, 0) * 10

            # Strict recency penalties (anti-repeat within cycle)
            if len(recent) >= 1 and recent[-1] == z:
                # Same zone back-to-back: forbidden if more than 1 person home
                cost += 100000 if len(user_list) > 1 else 0
            if len(recent) >= 2 and recent[-2] == z:
                cost += 1000
            if len(recent) >= 3 and recent[-3] == z:
                cost += 50

        if cost < best_cost:
            best_cost = cost
            best_perm = perm

    if best_perm:
        for u, z in zip(user_list, best_perm):
            assignments[u].append(z)
            u_data = ledger["users"][u]
            u_data.setdefault("zone_counts", {zone: 0 for zone in MAIN_ZONES})[z] += 1
            recent = u_data.setdefault("recent_zones", [])
            recent.append(z)
            u_data["recent_zones"] = recent[-4:]
            u_data["last_main_index"] = MAIN_ZONES.index(z)

    # 2. UPSTAIRS BATHROOM (Fair Long-Term Proportion)
    upstairs_candidates = [u for u in UPSTAIRS_USERS if u in home_users]
    if upstairs_candidates:
        def bathroom_sort_key(u):
            u_data = ledger["users"][u]
            return (u_data.get("upstairs_bathroom_count", 0), u_data.get("last_upstairs_bathroom_week") or "")

        chosen_upstairs = min(upstairs_candidates, key=bathroom_sort_key)
        assignments[chosen_upstairs].append("Upstairs Bathroom")

        u_data = ledger["users"][chosen_upstairs]
        u_data["upstairs_bathroom_count"] = u_data.get("upstairs_bathroom_count", 0) + 1
        u_data["last_upstairs_bathroom_week"] = current_week_str
        ledger["metadata"]["upstairs_bathroom_pointer"] = (UPSTAIRS_USERS.index(chosen_upstairs) + 1) % len(UPSTAIRS_USERS)

    # 3. DOWNSTAIRS BATHROOM (Pab)
    if DOWNSTAIRS_USER in home_users:
        assignments[DOWNSTAIRS_USER].append("Downstairs Bathroom")

    return assignments

def main():
    print(f"\n🚀 --- Chore Assignment Job: {datetime.datetime.now()} ---")
    ledger = load_ledger()
    discover_absences_with_ai(ledger)
    
    today = datetime.date.today()
    days_to_subtract = (today.weekday() + 1) % 7
    start_of_week = today - datetime.timedelta(days=days_to_subtract)
    end_of_week = start_of_week + datetime.timedelta(days=7)
    
    year, week_num = start_of_week.isocalendar()[:2]
    current_week_str = f"{year}-{week_num:02d}"
    date_range_str = f"{start_of_week.strftime('%Y-%m-%d')} to {end_of_week.strftime('%Y-%m-%d')}"
    
    # Deadline: Tuesday following the end of the chore week (allowing the full week + weekend)
    deadline_date = end_of_week + datetime.timedelta(days=2)
    deadline = deadline_date.strftime('%A, %B ') + str(deadline_date.day)
    deadline_iso = deadline_date.strftime('%Y-%m-%d')

    # Status check with full week window
    away_skip, away_sublet = get_away_status(ledger, start_of_week, end_of_week)
    home_users = [u for u in ledger["users"].keys() if u not in away_skip]
    
    assignments = calculate_assignments(ledger, home_users, current_week_str)

    # Message
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": f"🧹 Chore Rotation: Week {year} {date_range_str}"}}]
    if away_skip:
        names = ", ".join([ledger["users"][u]["name"] for u in away_skip])
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"🌴 _Skipping {names} (Away). Rotation paused._"}})
    if away_sublet:
        for u in away_sublet:
            name = ledger["users"][u]["name"]
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"🏠 *{name} is away but subletting.* Please coordinate with your guest!"}})
    
    for user_id, tasks in assignments.items():
        task_list = [f"• *{t}*: _{CHORE_DETAILS.get(t, '')}_" for t in tasks]
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*<@{user_id}>*\n" + "\n".join(task_list)}})
    
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"✨ *Friendly reminder: Please ensure cleaning is done by {deadline}!*"}]})
    
    response = client.chat_postMessage(channel=CHANNEL_ID, blocks=blocks, text=f"🧹 Chore Rotation: Week {year} {date_range_str}")
    print(f"📢 [Slack] Message posted to channel {CHANNEL_ID}! ts: {response['ts']}")
    try:
        permalink_res = client.chat_getPermalink(channel=CHANNEL_ID, message_ts=response["ts"])
        if permalink_res.get("permalink"):
            print(f"🔗 [Slack] Direct message link: {permalink_res['permalink']}")
    except Exception as e:
        print(f"ℹ️ (Could not generate permalink: {e})")

    print("📋 [Assignments]:")
    for u, tasks in assignments.items():
        print(f"  • {ledger['users'][u]['name']}: {', '.join(tasks)}")
    
    thread_entry = {"ts": response["ts"], "week": current_week_str, "deadline": deadline_iso}
    ledger["metadata"]["recent_threads"] = (ledger["metadata"].get("recent_threads", []) + [thread_entry])[-3:]
    ledger["metadata"]["current_thread_ts"] = response["ts"]
    ledger["metadata"]["current_week"] = current_week_str
    ledger["metadata"]["assigned_users_this_week"] = home_users
    ledger.setdefault("history", {})[current_week_str] = {
        "assignments": assignments,
        "completions": {u: None for u in home_users},
        "deadline": deadline_iso,
        "audited": False
    }
    save_ledger(ledger)
    print("💾 State saved. Done!")

if __name__ == "__main__":
    main()
