import random
from collections import Counter
import task_assignment

USER_NAMES = {
    "U0AN4FD067K": "Pab",
    "U0ATA3JK24X": "Josie",
    "U0AU4DWH2V7": "Kika",
    "daria": "Daria"
}

def run_simulation(weeks=52):
    ledger = {
        "metadata": {},
        "users": {
            uid: {
                "name": name,
                "bathroom_type": "downstairs" if name == "Pab" else "upstairs",
                "is_slack_member": False if uid == "daria" else True
            }
            for uid, name in USER_NAMES.items()
        }
    }

    stats = {uid: Counter() for uid in USER_NAMES.keys()}
    back_to_backs = 0
    collisions = 0
    uids = list(USER_NAMES.keys())
    
    print(f"--- Starting {weeks}-Week Simulation using PRODUCTION logic ---")
    
    for week in range(1, weeks + 1):
        # Simulate different people being away periodically
        away_ids = []
        if week % 3 == 0:
            away_user = uids[(week // 3) % len(uids)]
            away_ids = [away_user]
            if weeks <= 12:
                print(f"Week {week}: {USER_NAMES[away_ids[0]]} is AWAY.")
        
        home_users = [u for u in USER_NAMES.keys() if u not in away_ids]
        
        # EXECUTE PRODUCTION LOGIC
        assignments = task_assignment.calculate_assignments(ledger, home_users, f"2026-{week:02d}")
        
        # Check collisions in communal zones
        assigned_communal = []
        for uid, tasks in assignments.items():
            for t in tasks:
                stats[uid][t] += 1
                if t in task_assignment.MAIN_ZONES:
                    assigned_communal.append(t)
        if len(assigned_communal) != len(set(assigned_communal)):
            collisions += 1

        # Check back-to-backs
        for uid in home_users:
            recent = ledger["users"][uid].get("recent_zones", [])
            if len(recent) >= 2 and recent[-1] == recent[-2]:
                back_to_backs += 1
                print(f"⚠️ Back-to-back repeat: {USER_NAMES[uid]} did {recent[-1]} twice in a row!")
                
    # --- REPORTING ---
    print("\n--- Simulation Results (Total Times Assigned) ---")
    all_chores = task_assignment.MAIN_ZONES + ["Upstairs Bathroom", "Downstairs Bathroom"]
    
    header = f"{'User':<10}" + "".join([f"| {chore[:10]:<10}" for chore in all_chores])
    print(header)
    print("-" * len(header))
    
    for uid, name in USER_NAMES.items():
        row = f"{name:<10}"
        for chore in all_chores:
            count = stats[uid][chore]
            row += f"| {count:<10}"
        print(row)
    
    print("\nValidation Checks:")
    print(f"  • Total Collisions: {collisions} (Target: 0)")
    print(f"  • Total Back-to-Back Repeats: {back_to_backs} (Target: 0)")
    
    upstairs_uids = [u for u in USER_NAMES.keys() if ledger["users"][u].get("bathroom_type") == "upstairs"]
    upstairs_counts = [stats[u]["Upstairs Bathroom"] for u in upstairs_uids]
    upstairs_spread = max(upstairs_counts) - min(upstairs_counts)
    print(f"  • Upstairs Bathroom Spread: {upstairs_spread} (Max difference: {upstairs_spread} times between upstairs housemates)")
    
    assert collisions == 0, "Collisions detected!"
    assert back_to_backs == 0, "Back-to-back repeats detected!"
    assert upstairs_spread <= 2, f"Upstairs bathroom spread too high: {upstairs_spread}"
    print("✅ All fairness and rotation constraints successfully passed!")

if __name__ == "__main__":
    run_simulation(weeks=52)

