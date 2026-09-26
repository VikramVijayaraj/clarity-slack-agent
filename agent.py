import os
import requests
import json

CLARITY_TOKEN = os.environ.get("CLARITY_TOKEN")
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL")

def fetch_clarity_data():
    # Fetches live insights for the last 24 hours
    url = "https://www.clarity.ms/export-data/api/v1/project-live-insights?numOfDays=1"
    headers = {
        "Authorization": f"Bearer {CLARITY_TOKEN}",
        "Content-type": "application/json"
    }
    
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

def send_to_slack(data):
    # Format the message for Slack. You can customize this to parse specific metrics 
    # like sessions, clicks, or scroll depth, from the returned JSON.
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
                    "text": f"*Raw Insights Data (Last 24h):*\n```\n{json.dumps(data, indent=2)}\n```"
                }
            }
        ]
    }
    
    requests.post(SLACK_WEBHOOK, json=message)

if __name__ == "__main__":
    print("Fetching data from Clarity...")
    clarity_data = fetch_clarity_data()
    print("Sending report to Slack...")
    send_to_slack(clarity_data)
    print("Agent finished successfully.")
