import os
import json
import requests

CLARITY_TOKEN = os.environ.get("CLARITY_TOKEN")
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL")

SLACK_CHAR_LIMIT = 3000  # per-block text limit (mrkdwn section text)


def fetch_clarity_data():
    url = "https://www.clarity.ms/export-data/api/v1/project-live-insights?numOfDays=1"
    headers = {
        "Authorization": f"Bearer {CLARITY_TOKEN}",
        "Content-type": "application/json"
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()


def get_metric(data, name):
    """Return the first information[0] dict for a given metricName, or {}."""
    for item in data:
        if item.get("metricName") == name:
            info = item.get("information", [])
            return info[0] if info else {}
    return {}


def get_metric_list(data, name):
    """Return the full information list for a given metricName, or []."""
    for item in data:
        if item.get("metricName") == name:
            return item.get("information", [])
    return []


def chunk_text_blocks(lines, prefix=""):
    """
    Slack section text (mrkdwn) has a 3000-char limit per block.
    Given a list of already-formatted lines, pack them into as few
    mrkdwn section blocks as possible without exceeding that limit.
    Returns a list of block dicts.
    """
    blocks = []
    current = prefix
    for line in lines:
        candidate = current + ("\n" if current and current != prefix else "") + line
        if len(candidate) > SLACK_CHAR_LIMIT:
            # flush current, start new chunk (without repeating prefix on continuation)
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": current}})
            current = line
        else:
            current = candidate
    if current:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": current}})
    return blocks


def build_message(data):
    traffic = get_metric(data, "Traffic")
    engagement = get_metric(data, "EngagementTime")
    scroll = get_metric(data, "ScrollDepth")
    dead_click = get_metric(data, "DeadClickCount")
    quickback = get_metric(data, "QuickbackClick")
    rage_click = get_metric(data, "RageClickCount")
    popular_pages = get_metric_list(data, "PopularPages")
    referrers = get_metric_list(data, "ReferrerUrl")

    total_sessions = traffic.get("totalSessionCount", 0)
    bot_sessions = traffic.get("totalBotSessionCount", 0)
    real_sessions = total_sessions - bot_sessions
    users = traffic.get("distinctUserCount", "N/A")
    pages_per_session = traffic.get("pagesPerSessionPercentage", "N/A")

    active_time = engagement.get("activeTime", "N/A")
    avg_scroll = scroll.get("averageScrollDepth", "N/A")

    # Quick-glance line at the very top
    header_line = f"*{real_sessions} real sessions* (of {total_sessions} total, {bot_sessions} bot) · {users} users"

    # Only surface behavior signals that are non-zero (actual issues)
    signal_lines = []
    if dead_click.get("sessionsWithMetricPercentage", 0) > 0:
        signal_lines.append(f"⚠️ Dead clicks: {dead_click.get('sessionsWithMetricPercentage')}% of sessions")
    if quickback.get("sessionsWithMetricPercentage", 0) > 0:
        signal_lines.append(f"⚠️ Quick-backs: {quickback.get('sessionsWithMetricPercentage')}% of sessions")
    if rage_click.get("sessionsWithMetricPercentage", 0) > 0:
        signal_lines.append(f"🔴 Rage clicks: {rage_click.get('sessionsWithMetricPercentage')}% of sessions")
    signals_text = "\n".join(signal_lines) if signal_lines else "No dead/rage/quick-back clicks detected ✅"

    # FULL traffic overview (all fields, not trimmed)
    traffic_lines = [
        f"*Traffic Overview:*",
        f"• Total sessions: {total_sessions}",
        f"• Bot sessions: {bot_sessions}",
        f"• Real sessions: {real_sessions}",
        f"• Distinct users: {users}",
        f"• Pages/session: {pages_per_session}",
        f"• Active time: {active_time}s",
        f"• Avg scroll depth: {avg_scroll}%",
    ]

    # FULL top pages list (not trimmed to top N)
    pages_sorted = sorted(popular_pages, key=lambda p: p.get("visitsCount", 0), reverse=True)
    pages_lines = [f"*Top Pages ({len(pages_sorted)}):*"]
    for p in pages_sorted:
        url = p.get("url", "")
        short_url = url.replace("https://www.crelands.com", "").replace("https://crelands.com", "") or "/"
        pages_lines.append(f"• {short_url} — {p.get('visitsCount')} visits")

    # FULL referrers list (not trimmed)
    ref_sorted = sorted(referrers, key=lambda r: r.get("sessionsCount", 0), reverse=True)
    ref_lines = [f"*Referrers ({len(ref_sorted)}):*"]
    for r in ref_sorted:
        name = r.get("name") or "Direct / unknown"
        ref_lines.append(f"• {name} — {r.get('sessionsCount')} sessions")

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "📊 Crelands — Daily Clarity Report"}
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": header_line}
        },
        {"type": "divider"},
    ]

    blocks += chunk_text_blocks(traffic_lines)
    blocks.append({"type": "divider"})
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Behavior signals:*\n{signals_text}"}})
    blocks.append({"type": "divider"})
    blocks += chunk_text_blocks(pages_lines)
    blocks.append({"type": "divider"})
    blocks += chunk_text_blocks(ref_lines)

    return {"blocks": blocks}


def send_to_slack(data):
    message = build_message(data)

    # Slack also caps total blocks per message at 50 — guard against that too
    if len(message["blocks"]) > 50:
        raise ValueError(
            f"Message has {len(message['blocks'])} blocks, exceeding Slack's 50-block limit. "
            "Consider splitting into multiple messages."
        )

    response = requests.post(SLACK_WEBHOOK, json=message)
    response.raise_for_status()


if __name__ == "__main__":
    clarity_data = fetch_clarity_data()
    send_to_slack(clarity_data)
