import os
import time
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# Use your existing token and channel ID
SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")

client = WebClient(token=SLACK_TOKEN)

def clear_channel():
    if not SLACK_TOKEN or not CHANNEL_ID:
        print("❌ Error: SLACK_BOT_TOKEN or SLACK_CHANNEL_ID not set.")
        return

    print(f"🚀 Starting to clear channel {CHANNEL_ID}...")
    
    try:
        # 1. Fetch messages
        result = client.conversations_history(channel=CHANNEL_ID, limit=100)
        messages = result.get("messages", [])
        
        if not messages:
            print("✅ Channel is already empty.")
            return

        print(f"Found {len(messages)} messages. Starting deletion...")

        # 2. Delete messages one by one
        for msg in messages:
            ts = msg.get("ts")
            try:
                client.chat_delete(channel=CHANNEL_ID, ts=ts)
                print(f"  Successfully deleted message: {ts}")
                # Slack rate limits: ~1 request per second for deletions
                time.sleep(1.2) 
            except SlackApiError as e:
                if e.response["error"] == "cant_delete_message":
                    print(f"  ⚠️ Could not delete message {ts}: Bots can usually only delete their own messages.")
                    print("     (To delete everything, use a User Token starting with 'xoxp-')")
                else:
                    print(f"  ❌ Error deleting {ts}: {e.response['error']}")

        print("\n✨ Finished clearing attempt.")

    except SlackApiError as e:
        print(f"❌ Failed to fetch history: {e.response['error']}")

if __name__ == "__main__":
    clear_channel()
