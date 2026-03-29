import os
import datetime
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# 1. Configuration: Pulling secrets from environment variables (for security)
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID")

# Initialize the Slack Client
client = WebClient(token=SLACK_BOT_TOKEN)

# 2. Your Data
# IMPORTANT: You must use Slack User IDs (e.g., U12345678), not display names, to tag people.
USERS = ["U0AN4FD067K"] 
ZONES = ["Kitchen", "Living Room", "Hallway", "Bathrooms", "Gardens"]

def get_assignments():
    """Calculates the offset rotation for the current week."""
    week_num = datetime.date.today().isocalendar()[1]
    assignments = {user: [] for user in USERS}
    
    for i, user in enumerate(USERS):
        # Primary zone
        zone_index = (i + week_num) % len(ZONES)
        assignments[user].append(ZONES[zone_index])
        
        # 5th Zone (Double Duty)
        if i == (week_num % len(USERS)):
            fifth_zone_index = (4 + week_num) % len(ZONES)
            if ZONES[fifth_zone_index] not in assignments[user]:
                assignments[user].append(ZONES[fifth_zone_index])
                
    return assignments, week_num

def create_slack_blocks(assignments, week_num):
    """Formats the data into a clean Slack UI block."""
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🧹 Weekly Chore Rotation: Week {week_num}",
                "emoji": True
            }
        },
        {"type": "divider"}
    ]
    
    # Add each person's assignment as a formatted section
    for user, tasks in assignments.items():
        task_string = " & ".join(tasks)
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*<@{user}>*\n{task_string}"
            }
        })
        
    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": "⏳ _Next rotation happens next Monday._"
            }
        ]
    })
    
    return blocks

def main():
    assignments, week_num = get_assignments()
    blocks = create_slack_blocks(assignments, week_num)
    
    try:
        # Post the message to Slack
        response = client.chat_postMessage(
            channel=CHANNEL_ID,
            blocks=blocks,
            text="This week's chore rotation is live!" # Fallback text for notifications
        )
        print(f"Message sent successfully to {CHANNEL_ID}")
    except SlackApiError as e:
        print(f"Error posting message: {e.response['error']}")

if __name__ == "__main__":
    main()