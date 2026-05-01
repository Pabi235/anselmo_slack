from collections import Counter
import task_assignment # Import directly from your production script

# User mapping for readable output
USER_NAMES = {
    "U0AN4FD067K": "Pab",
    "U0ATA3GRBRD": "Angela",
    "U0ATA3JK24X": "Josie",
    "U0AU4DWH2V7": "Kika"
}

def run_simulation(weeks=12):
    # Initial Mock Ledger (matches your starting state)
    ledger = {
        "metadata": {"upstairs_bathroom_pointer": 0},
        "users": {
            "U0AN4FD067K": {"name": "Pab", "last_main_index": 3},
            "U0ATA3GRBRD": {"name": "Angela", "last_main_index": 0},
            "U0ATA3JK24X": {"name": "Josie", "last_main_index": 1},
            "U0AU4DWH2V7": {"name": "Kika", "last_main_index": 2}
        }
    }

    stats = {uid: Counter() for uid in USER_NAMES.keys()}
    
    print(f"--- Starting {weeks}-Week Simulation using PRODUCTION logic ---")
    
    for week in range(1, weeks + 1):
        # Simulate someone being away every 4th week
        away_ids = []
        if week % 4 == 0:
            away_ids = [list(USER_NAMES.keys())[week % 4]]
            print(f"Week {week}: {USER_NAMES[away_ids[0]]} is AWAY.")
        
        home_users = [u for u in USER_NAMES.keys() if u not in away_ids]
        
        # EXECUTE PRODUCTION LOGIC
        assignments = task_assignment.calculate_assignments(ledger, home_users)
        
        # Log stats
        for uid, tasks in assignments.items():
            for task in tasks:
                stats[uid][task] += 1
                
    # --- REPORTING ---
    print("\n--- Simulation Results (Total Times Assigned) ---")
    all_chores = task_assignment.MAIN_ZONES + ["Upstairs Bathroom", "Downstairs Bathroom"]
    
    # Header
    header = f"{'User':<10}" + "".join([f"| {chore[:10]:<10}" for chore in all_chores])
    print(header)
    print("-" * len(header))
    
    for uid, name in USER_NAMES.items():
        row = f"{name:<10}"
        for chore in all_chores:
            count = stats[uid][chore]
            row += f"| {count:<10}"
        print(row)
    
    print("\nFairness Check:")
    print("- Main Loop chores (Kitchen to Garden) should be balanced.")
    print("- Downstairs Bathroom: Pab only.")
    print("- Upstairs Bathroom: Girls only.")

if __name__ == "__main__":
    run_simulation(weeks=12)
