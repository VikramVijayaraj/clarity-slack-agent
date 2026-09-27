import os
import json
import requests
from datetime import datetime, timedelta, timezone

CLARITY_TOKEN = os.environ.get("CLARITY_TOKEN")
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL")

SLACK_CHAR_LIMIT = 3000  # per-block text limit (mrkdwn section text)
IST = timezone(timedelta(hours=5, minutes=30))


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
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": current}})
            current = line
        else:
            current = candidate
    if current:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": current}})
    return blocks


def chunk_code_blocks(header_lines, row_lines):
    """
    Same idea as chunk_text_blocks, but wraps each chunk in a ``` code fence
    so it renders as a monospaced, column-aligned table in Slack.
    header_lines are repeated at the top of every chunk (e.g. table headers).
    """
    blocks = []
    header_text = "\n".join(header_lines)
    current_rows = []

    def flush():
        if not current_rows:
            return
        body = header_text + "\n" + "\n".join(current_rows) if header_lines else "\n".join(current_rows)
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"```{body}```"}})

    for row in row_lines:
        candidate_rows = current_rows + [row]
        candidate_body = header_text + "\n" + "\n".join(candidate_rows) if header_lines else "\n".join(candidate_rows)
        # +6 accounts for the ``` fences on both ends
        if len(candidate_body) + 6 > SLACK_CHAR_LIMIT:
            flush()
            current_rows = [row]
        else:
            current_rows = candidate_rows
    flush()
    return blocks


def build_page_table(pages_sorted):
    """
    Build a monospaced 'table' of URL | Visits, column-aligned.
    Slack has no native table block, so a code-fenced, padded layout
    is the standard workaround for tabular data in Block Kit.
    """
    if not pages_sorted:
        return ["No page data"]

    shortened = []
    for p in pages_sorted:
        url = p.get("url", "")
        short_url = url.replace("https://www.crelands.com", "").replace("https://crelands.com", "") or "/"
        shortened.append((short_url, p.get("visitsCount", 0)))

    url_col_width = min(max(len(u) for u, _ in shortened), 60)  # cap so it doesn't stretch huge
    rows = []
    for url, visits in shortened:
        display_url = (url[:url_col_width - 1] + "…") if len(url) > url_col_width else url.ljust(url_col_width)
        rows.append(f"{display_url}  {str(visits).rjust(6)}")

    header = [f"{'URL'.ljust(url_col_width)}  {'Visits'.rjust(6)}", "-" * (url_col_width + 8)]
    return header, rows


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

    # Report date — the data covers the last 1 day (numOfDays=1), reported at run time, in IST
    report_date = datetime.now(IST).strftime("%A, %d %B %Y")

    header_line = f"*{real_sessions} real sessions* (of {total_sessions} total, {bot_sessions} bot) · {users} users"

    signal_lines = []
    if dead_click.get("sessionsWithMetricPercentage", 0) > 0:
        signal_lines.append(f"⚠️ Dead clicks: {dead_click.get('sessionsWithMetricPercentage')}% of sessions")
    if quickback.get("sessionsWithMetricPercentage", 0) > 0:
        signal_lines.append(f"⚠️ Quick-backs: {quickback.get('sessionsWithMetricPercentage')}% of sessions")
    if rage_click.get("sessionsWithMetricPercentage", 0) > 0:
        signal_lines.append(f"🔴 Rage clicks: {rage_click.get('sessionsWithMetricPercentage')}% of sessions")
    signals_text = "\n".join(signal_lines) if signal_lines else "No dead/rage/quick-back clicks detected ✅"

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

    pages_sorted = sorted(popular_pages, key=lambda p: p.get("visitsCount", 0), reverse=True)
    page_table_header, page_table_rows = build_page_table(pages_sorted)

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
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"🗓️ Data for: *{report_date}*"}]
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
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Top Pages ({len(page_table_rows)}):*"}})
    blocks += chunk_code_blocks(page_table_header, page_table_rows)
    blocks.append({"type": "divider"})
    blocks += chunk_text_blocks(ref_lines)

    return {"blocks": blocks}


def send_to_slack(data):
    message = build_message(data)

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
