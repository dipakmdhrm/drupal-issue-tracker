#!/usr/bin/env python3
"""
Drupal.org Issue Tracker
- Processes Telegram bot commands (/track, /untrack, /list, /help)
- Polls the Drupal.org REST API for issue updates
- Sends Telegram notifications for new/updated issues
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
PROJECTS_FILE = "projects.yml"
USER_AGENT = "drupal-issue-tracker/1.0 (github.com/drupal-issue-tracker)"
MAX_PAGES = 10

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def api_get(path, params=None):
    response = requests.get(
        f"{DRUPAL_API}/{path}",
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
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
    with open(PROJECTS_FILE) as f:
        return yaml.safe_load(f) or {}


def write_projects(projects):
    """Write projects list back to projects.yml in a clean, human-readable format."""
    lines = [
        "# Drupal Issue Tracker — Project Configuration\n",
        "# Manage via bot commands (/track, /untrack, /list) or edit directly.\n",
        "#\n",
        "# priority options: critical | major | normal | minor | all\n",
        "# status options:   active | needs_review | needs_work | rtbc | fixed | all\n",
        "\n",
        "projects:\n",
    ]
    for p in projects:
        lines += [
            "\n",
            f"  - machine_name: {p['machine_name']}\n",
            f"    label: \"{p.get('label', p['machine_name'])}\"\n",
            f"    filters:\n",
            f"      priority: {p.get('filters', {}).get('priority', 'all')}\n",
            f"      status: {p.get('filters', {}).get('status', 'all')}\n",
        ]
    with open(PROJECTS_FILE, "w") as f:
        f.writelines(lines)


def resolve_project(machine_name):
    """Return (nid, title) for a drupal.org project machine name."""
    data = api_get("node.json", {"field_project_machine_name": machine_name, "limit": 1})
    nodes = data.get("list", [])
    if not nodes:
        raise ValueError(f"Project not found: '{machine_name}'")
    return str(nodes[0]["nid"]), nodes[0].get("title", machine_name)


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def send_telegram(bot_token, chat_id, text):
    response = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": True},
        timeout=15,
    )
    response.raise_for_status()


def get_updates(bot_token, offset):
    response = requests.get(
        f"https://api.telegram.org/bot{bot_token}/getUpdates",
        params={"offset": offset, "limit": 100, "timeout": 0},
        timeout=15,
    )
    response.raise_for_status()
    return response.json().get("result", [])


# ---------------------------------------------------------------------------
# Bot command handlers
# ---------------------------------------------------------------------------

def cmd_track(bot_token, chat_id, machine_name, state):
    if not machine_name:
        send_telegram(bot_token, chat_id,
                      "Usage: /track <code>machine_name</code>\n\n"
                      "The machine name is the last part of the drupal.org project URL.\n"
                      "Example: drupal.org/project/<code>token</code> → /track token")
        return

    config = load_config()
    projects = config.get("projects") or []

    if any(p["machine_name"] == machine_name for p in projects):
        send_telegram(bot_token, chat_id, f"Already tracking <b>{machine_name}</b>.")
        return

    send_telegram(bot_token, chat_id, f"Looking up <code>{machine_name}</code> on drupal.org…")

    try:
        nid, title = resolve_project(machine_name)
    except Exception:
        send_telegram(bot_token, chat_id,
                      f"Project <code>{machine_name}</code> was not found on drupal.org.\n"
                      f"Check the machine name and try again.")
        return

    projects.append({
        "machine_name": machine_name,
        "label": title,
        "filters": {"priority": "all", "status": "all"},
    })
    write_projects(projects)

    # Initialise state so the next poll doesn't send historical spam
    state[machine_name] = {"nid": nid, "last_checked": int(time.time())}

    send_telegram(bot_token, chat_id,
                  f"Now tracking <b>{title}</b>.\n"
                  f"You'll receive notifications when issues are updated.")
    print(f"Added project '{machine_name}' ({title}, nid {nid})")


def cmd_untrack(bot_token, chat_id, machine_name, state):
    if not machine_name:
        send_telegram(bot_token, chat_id, "Usage: /untrack <code>machine_name</code>")
        return

    config = load_config()
    projects = config.get("projects") or []
    updated = [p for p in projects if p["machine_name"] != machine_name]

    if len(updated) == len(projects):
        send_telegram(bot_token, chat_id,
                      f"<code>{machine_name}</code> is not in your tracking list.")
        return

    write_projects(updated)
    state.pop(machine_name, None)

    send_telegram(bot_token, chat_id, f"Stopped tracking <b>{machine_name}</b>.")
    print(f"Removed project '{machine_name}'")


def cmd_list(bot_token, chat_id):
    config = load_config()
    projects = config.get("projects") or []

    if not projects:
        send_telegram(bot_token, chat_id,
                      "No projects tracked yet.\n"
                      "Use /track <code>machine_name</code> to add one.")
        return

    lines = ["<b>Tracked projects:</b>\n"]
    for p in projects:
        label = p.get("label", p["machine_name"])
        name = p["machine_name"]
        priority = p.get("filters", {}).get("priority", "all")
        status = p.get("filters", {}).get("status", "all")
        lines.append(f"• <b>{label}</b> (<code>{name}</code>)"
                     f"\n  Priority: {priority} | Status: {status}")

    send_telegram(bot_token, chat_id, "\n".join(lines))


def cmd_help(bot_token, chat_id):
    send_telegram(bot_token, chat_id,
                  "<b>Drupal Issue Tracker — Commands</b>\n\n"
                  "/track <code>machine_name</code> — Start tracking a project\n"
                  "/untrack <code>machine_name</code> — Stop tracking a project\n"
                  "/list — Show all tracked projects\n"
                  "/help — Show this message\n\n"
                  "The machine name is the last part of the drupal.org project URL.\n"
                  "Example: drupal.org/project/<code>token</code> → "
                  "/track <code>token</code>")


def handle_commands(bot_token, chat_id, state):
    """Fetch and process any new Telegram messages sent to the bot."""
    offset = state.get("_telegram_offset", 0)
    updates = get_updates(bot_token, offset)

    for update in updates:
        # Always advance offset so we never reprocess the same message
        state["_telegram_offset"] = update["update_id"] + 1

        message = update.get("message", {})
        if not message:
            continue

        # Security: ignore messages from anyone other than the authorised chat
        if str(message.get("chat", {}).get("id", "")) != str(chat_id):
            print(f"Ignoring message from unauthorised chat id")
            continue

        text = (message.get("text") or "").strip()
        if not text or not text.startswith("/"):
            continue

        parts = text.split()
        command = parts[0].split("@")[0].lower()  # Strip @BotName suffix
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

        print(f"Command received: {command} {arg}")

        if command == "/track":
            cmd_track(bot_token, chat_id, arg, state)
        elif command == "/untrack":
            cmd_untrack(bot_token, chat_id, arg, state)
        elif command == "/list":
            cmd_list(bot_token, chat_id)
        elif command in ("/help", "/start"):
            cmd_help(bot_token, chat_id)
        else:
            send_telegram(bot_token, chat_id,
                          f"Unknown command: <code>{command}</code>\n"
                          "Send /help to see available commands.")


# ---------------------------------------------------------------------------
# Issue polling
# ---------------------------------------------------------------------------

def fetch_updated_issues(project_nid, since_timestamp, priority_codes, status_codes):
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
            if (str(issue.get("field_issue_priority", "")) in priority_codes and
                    str(issue.get("field_issue_status", "")) in status_codes):
                results.append(issue)

        if reached_old:
            break
        if page < MAX_PAGES - 1:
            time.sleep(1)

    return results


def format_issue_message(issue, project_label):
    title = issue.get("title", "(no title)")
    url = issue.get("url", "")
    status = STATUS_LABELS.get(str(issue.get("field_issue_status", "")), "Unknown")
    priority = PRIORITY_LABELS.get(str(issue.get("field_issue_priority", "")), "Unknown")
    changed_str = datetime.fromtimestamp(
        int(issue.get("changed", 0)), tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")

    return (
        f"<b>[{project_label}]</b> Issue updated\n"
        f"<b>{title}</b>\n\n"
        f"Status: {status}\n"
        f"Priority: {priority}\n"
        f"Comments: {issue.get('comment_count', '0')}\n"
        f"Updated: {changed_str}\n\n"
        f'<a href="{url}">View on drupal.org</a>'
    )


def poll_issues(bot_token, chat_id, state):
    config = load_config()
    projects = config.get("projects") or []

    if not projects:
        print("No projects configured. Nothing to poll.")
        return

    now = int(time.time())
    total_sent = 0

    for project in projects:
        machine_name = project.get("machine_name", "").strip()
        label = project.get("label", machine_name)
        filters = project.get("filters", {})

        if not machine_name:
            continue

        priority_codes = PRIORITY_FILTER_MAP.get(
            filters.get("priority", "all"), PRIORITY_FILTER_MAP["all"])
        status_codes = STATUS_FILTER_MAP.get(
            filters.get("status", "all"), STATUS_FILTER_MAP["all"])

        project_state = state.get(machine_name, {})

        nid = project_state.get("nid")
        if not nid:
            try:
                nid, _ = resolve_project(machine_name)
                print(f"Resolved '{machine_name}' → nid {nid}")
            except Exception as e:
                print(f"ERROR: Could not resolve '{machine_name}': {e}")
                continue

        last_checked = project_state.get("last_checked", 0)

        if last_checked == 0:
            print(f"First run for '{machine_name}' — initialising.")
            send_telegram(bot_token, chat_id,
                          f"<b>Now tracking: {label}</b>\n"
                          f"You'll receive notifications when issues are updated.")
            state[machine_name] = {"nid": nid, "last_checked": now}
            time.sleep(0.5)
            continue

        try:
            issues = fetch_updated_issues(nid, last_checked, priority_codes, status_codes)
            print(f"'{machine_name}': {len(issues)} updated issue(s).")

            for issue in reversed(issues):
                send_telegram(bot_token, chat_id, format_issue_message(issue, label))
                total_sent += 1
                time.sleep(0.5)

            state[machine_name] = {"nid": nid, "last_checked": now}

        except Exception as e:
            print(f"ERROR polling '{machine_name}': {e}")
            state.setdefault(machine_name, {"nid": nid, "last_checked": last_checked})

    print(f"Polling done. Sent {total_sent} notification(s).")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    is_test = "--test" in sys.argv

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not bot_token or not chat_id:
        print("ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set.")
        sys.exit(1)

    if is_test:
        print("Sending test message…")
        send_telegram(bot_token, chat_id,
                      "<b>Drupal Issue Tracker — Setup OK</b>\n\n"
                      "Your tracker is configured correctly.\n\n"
                      "Send /help to see available bot commands.")
        print("Test message sent.")
        return

    state = load_state()

    print("--- Checking for bot commands ---")
    handle_commands(bot_token, chat_id, state)

    print("--- Polling for issue updates ---")
    poll_issues(bot_token, chat_id, state)

    save_state(state)


if __name__ == "__main__":
    main()
