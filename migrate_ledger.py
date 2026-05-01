import os
import json
from drive_storage import load_ledger, save_ledger

def migrate():
    try:
        ledger = load_ledger()
        print("Successfully loaded ledger from Google Drive.")
        
        # Hard reset of indices to spread everyone across the 4 zones
        # We set 'last_main_index' so that the NEXT assignment (last + 1) is unique.
        mapping = {
            "U0AN4FD067K": 3, # Pab -> Next: 0 (Kitchen)
            "U0ATA3GRBRD": 0, # Angela -> Next: 1 (Living Room)
            "U0ATA3JK24X": 1, # Josie -> Next: 2 (Hallways)
            "U0AU4DWH2V7": 2  # Kika -> Next: 3 (Garden)
        }
        
        for user_id, last_idx in mapping.items():
            if user_id in ledger["users"]:
                ledger["users"][user_id]["last_main_index"] = last_idx
                print(f"Reset {ledger['users'][user_id]['name']} to index {last_idx}")
            else:
                print(f"Warning: User ID {user_id} not found in ledger.")

        # Ensure other metadata is correct
        if "history" not in ledger: ledger["history"] = {}
        ledger["metadata"]["upstairs_bathroom_pointer"] = 0
        ledger["metadata"]["extra_task_pointer"] = 0 # No longer used but good to reset

        save_ledger(ledger)
        print("✅ Hard reset complete. Run the assignment now to see the result.")
        
    except Exception as e:
        print(f"❌ Reset failed: {e}")

if __name__ == "__main__":
    migrate()
