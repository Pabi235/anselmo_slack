import os
import json
from drive_storage import load_ledger, save_ledger

def migrate():
    try:
        ledger = load_ledger()
        print("Successfully loaded ledger from Google Drive.")
        
        # 1. Update users for Main Loop (4 zones instead of 5)
        # We reset last_zone_index because the previous cycle was based on 5 zones.
        for user_id, user_data in ledger["users"].items():
            user_data["last_main_index"] = -1
            print(f"Initialized last_main_index for {user_data['name']}")

        # 2. Add history object
        if "history" not in ledger:
            ledger["history"] = {}
            print("Added history object to ledger.")

        # 3. Add Upstairs pointer
        if "upstairs_bathroom_pointer" not in ledger["metadata"]:
            ledger["metadata"]["upstairs_bathroom_pointer"] = 0
            print("Added upstairs_bathroom_pointer to metadata.")

        save_ledger(ledger)
        print("✅ Migration complete. Ledger updated on Google Drive.")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")

if __name__ == "__main__":
    migrate()
