import os
import json
from drive_storage import load_ledger, save_ledger

def migrate():
    try:
        ledger = load_ledger()
        print("Successfully loaded ledger from Google Drive.")
        
        # 1. Update users
        for user_id, user_data in ledger["users"].items():
            if "last_zone_index" not in user_data:
                user_data["last_zone_index"] = -1 # Start fresh
                print(f"Added last_zone_index to {user_data['name']}")

        # 2. Add history object
        if "history" not in ledger:
            ledger["history"] = {}
            print("Added history object to ledger.")

        # 3. Initialize extra task pointer if not present
        if "extra_task_pointer" not in ledger["metadata"]:
            ledger["metadata"]["extra_task_pointer"] = 0
            print("Added extra_task_pointer to metadata.")

        save_ledger(ledger)
        print("✅ Migration complete. Ledger updated on Google Drive.")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")

if __name__ == "__main__":
    migrate()
