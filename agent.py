import os
import requests
import json

CLARITY_TOKEN = os.environ.get("CLARITY_TOKEN")
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL")

def fetch_clarity_data():
    url = "https://www.clarity.ms/export-data/api/v1/project-live-insights?numOfDays=1"
    headers = {
        "Authorization": f"Bearer {CLARITY_TOKEN}",
        "Content-type": "application/json"
    }
    
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

def send_to_slack(data):
    # Truncate the JSON to avoid hitting Slack's 3000 character block limit
    raw_data_string = json.dumps(data, indent=2)
    if len(raw_data_string) > 2800:
        raw_data_string = raw_data_string[:2800] + "\n... [Data Truncated]"

    message = {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "📊 Daily Microsoft Clarity Report"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Raw Insights Data (Last 24h):*\n```\n{raw_data_string}\n```"
                }
            }
        ]
    }
    
    response = requests.post(SLACK_WEBHOOK, json=message)
    
    # Print the response from Slack to the GitHub logs for debugging
    print(f"Slack Response Code: {response.status_code}")
    print(f"Slack Response Body: {response.text}")
    
    # This ensures the GitHub Action fails (turns red) if Slack rejects the message
    response.raise_for_status()

if __name__ == "__main__":
    print("Fetching data from Clarity...")
    clarity_data = fetch_clarity_data()
    print("Sending report to Slack...")
    send_to_slack(clarity_data)
    print("Agent finished successfully.")
