#!/usr/bin/env python3
"""
Drupal.org Issue Tracker
Polls the Drupal.org REST API for issue updates and sends Telegram notifications.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

import requests
import yaml

DRUPAL_API = "https://www.drupal.org/api-d7"
STATE_FILE = "state/state.json"
USER_AGENT = "drupal-issue-tracker/1.0 (github.com/drupal-issue-tracker)"
MAX_PAGES = 10  # Safety cap to avoid hammering API on first run or outages

STATUS_LABELS = {
    "1": "Active",
    "2": "Fixed",
    "3": "Closed (duplicate)",
    "4": "Postponed",
    "5": "Closed (won't fix)",
    "6": "Closed (works as designed)",
    "7": "Closed (fixed)",
    "8": "Needs review",
    "13": "Needs work",
    "14": "RTBC",
    "15": "Patch (to be ported)",
    "16": "Postponed (maintainer needs info)",
    "17": "Closed (outdated)",
    "18": "Closed (cannot reproduce)",
}

PRIORITY_LABELS = {
    "400": "Critical",
    "300": "Major",
    "200": "Normal",
    "100": "Minor",
}

PRIORITY_FILTER_MAP = {
    "critical": {"400"},
    "major": {"300"},
    "normal": {"200"},
    "minor": {"100"},
    "all": {"400", "300", "200", "100"},
}

STATUS_FILTER_MAP = {
    "active": {"1"},
    "needs_review": {"8"},
    "needs_work": {"13"},
    "rtbc": {"14"},
    "fixed": {"2", "7"},
    "all": set(STATUS_LABELS.keys()),
}


def api_get(path, params=None):
    headers = {"User-Agent": USER_AGENT}
    url = f"{DRUPAL_API}/{path}"
    response = requests.get(url, params=params, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    os.makedirs("state", exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def load_config():
    with open("projects.yml") as f:
        return yaml.safe_load(f)


def resolve_project_nid(machine_name):
    data = api_get("node.json", {"field_project_machine_name": machine_name, "limit": 1})
    nodes = data.get("list", [])
    if not nodes:
        raise ValueError(f"Project not found on drupal.org: '{machine_name}'")
    return str(nodes[0]["nid"])


def fetch_updated_issues(project_nid, since_timestamp, priority_codes, status_codes):
    """Fetch issues changed after since_timestamp, filtered by priority and status."""
    results = []

    for page in range(MAX_PAGES):
        data = api_get("node.json", {
            "type": "project_issue",
            "field_project": project_nid,
            "sort": "changed",
            "direction": "DESC",
            "limit": 50,
            "page": page,
        })

        issues = data.get("list", [])
        if not issues:
            break

        reached_old = False
        for issue in issues:
            changed = int(issue.get("changed", 0))
            if changed <= since_timestamp:
                reached_old = True
                break
            priority = str(issue.get("field_issue_priority", ""))
            status = str(issue.get("field_issue_status", ""))
            if priority in priority_codes and status in status_codes:
                results.append(issue)

        if reached_old:
            break

        if page < MAX_PAGES - 1:
            time.sleep(1)  # Be polite between paginated requests

    return results


def send_telegram(bot_token, chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    response = requests.post(url, json=payload, timeout=15)
    response.raise_for_status()


def format_issue_message(issue, project_label):
    title = issue.get("title", "(no title)")
    url = issue.get("url", "")
    status = STATUS_LABELS.get(str(issue.get("field_issue_status", "")), "Unknown")
    priority = PRIORITY_LABELS.get(str(issue.get("field_issue_priority", "")), "Unknown")
    changed_ts = int(issue.get("changed", 0))
    changed_str = datetime.fromtimestamp(changed_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    comments = issue.get("comment_count", "0")

    return (
        f"<b>[{project_label}]</b> Issue updated\n"
        f"<b>{title}</b>\n"
        f"\n"
        f"Status: {status}\n"
        f"Priority: {priority}\n"
        f"Comments: {comments}\n"
        f"Updated: {changed_str}\n"
        f"\n"
        f'<a href="{url}">View on drupal.org</a>'
    )


def main():
    is_test = "--test" in sys.argv

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not bot_token or not chat_id:
        print("ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables must be set.")
        sys.exit(1)

    if is_test:
        print("Sending test message to Telegram...")
        send_telegram(bot_token, chat_id, (
            "<b>Drupal Issue Tracker — Setup OK</b>\n"
            "\n"
            "Your tracker is configured correctly. "
            "Notifications will arrive here when issues are updated."
        ))
        print("Test message sent successfully.")
        return

    config = load_config()
    state = load_state()
    now = int(time.time())
    total_sent = 0

    projects = config.get("projects", [])
    if not projects:
        print("No projects configured in projects.yml. Nothing to do.")
        return

    for project in projects:
        machine_name = project.get("machine_name", "").strip()
        label = project.get("label", machine_name)
        filters = project.get("filters", {})

        if not machine_name:
            print("WARNING: Skipping project entry with no machine_name.")
            continue

        priority_key = filters.get("priority", "all")
        status_key = filters.get("status", "all")
        priority_codes = PRIORITY_FILTER_MAP.get(priority_key, PRIORITY_FILTER_MAP["all"])
        status_codes = STATUS_FILTER_MAP.get(status_key, STATUS_FILTER_MAP["all"])

        project_state = state.get(machine_name, {})

        # Resolve and cache the project NID
        nid = project_state.get("nid")
        if not nid:
            try:
                nid = resolve_project_nid(machine_name)
                print(f"Resolved '{machine_name}' → nid {nid}")
            except Exception as e:
                print(f"ERROR: Could not resolve project '{machine_name}': {e}")
                continue

        last_checked = project_state.get("last_checked", 0)

        # First run for this project: don't send historical spam, just start tracking from now
        if last_checked == 0:
            print(f"First run for '{machine_name}' — starting tracking from now.")
            send_telegram(bot_token, chat_id, (
                f"<b>Now tracking: {label}</b>\n"
                f"You'll receive notifications when issues are updated."
            ))
            state[machine_name] = {"nid": nid, "last_checked": now}
            time.sleep(0.5)
            continue

        try:
            issues = fetch_updated_issues(nid, last_checked, priority_codes, status_codes)
            print(f"'{machine_name}': {len(issues)} new/updated issue(s).")

            for issue in reversed(issues):  # Oldest first
                msg = format_issue_message(issue, label)
                send_telegram(bot_token, chat_id, msg)
                total_sent += 1
                time.sleep(0.5)

            state[machine_name] = {"nid": nid, "last_checked": now}

        except Exception as e:
            print(f"ERROR processing '{machine_name}': {e}")
            # Preserve existing state on error so we don't lose the last checkpoint
            state.setdefault(machine_name, {"nid": nid, "last_checked": last_checked})

    save_state(state)
    print(f"Done. Sent {total_sent} notification(s).")


if __name__ == "__main__":
    main()
