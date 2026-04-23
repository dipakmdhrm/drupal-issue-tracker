#!/usr/bin/env python3
"""
Drupal.org Issue Tracker — Multi-user Telegram bot
- Any Telegram user can chat with the bot to track projects
- Each user has their own subscription list
- Projects are polled once globally; notifications fan out to all subscribers
- Commands: /track, /untrack, /list, /help
"""

import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests

DRUPAL_API = "https://www.drupal.org/api-d7"
STATE_FILE = "state/state.json"
USER_AGENT = "drupal-issue-tracker/1.0 (github.com/drupal-issue-tracker)"
MAX_PAGES = 10

STATUS_LABELS = {
    "1": "Active", "2": "Fixed", "3": "Closed (duplicate)", "4": "Postponed",
    "5": "Closed (won't fix)", "6": "Closed (works as designed)", "7": "Closed (fixed)",
    "8": "Needs review", "13": "Needs work", "14": "RTBC", "15": "Patch (to be ported)",
    "16": "Postponed (maintainer needs info)", "17": "Closed (outdated)",
    "18": "Closed (cannot reproduce)",
}

PRIORITY_LABELS = {
    "400": "Critical", "300": "Major", "200": "Normal", "100": "Minor",
}

ALL_PRIORITIES = set(PRIORITY_LABELS.keys())
ALL_STATUSES = set(STATUS_LABELS.keys())


# ---------------------------------------------------------------------------
# State
#
# Structure:
# {
#   "_telegram_offset": 0,
#   "users": {
#     "123456789": {"name": "alice", "projects": ["drupal", "token"]}
#   },
#   "projects": {
#     "drupal": {"nid": "3060", "title": "Drupal", "last_checked": 1714000000}
#   }
# }
# ---------------------------------------------------------------------------

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"_telegram_offset": 0, "users": {}, "projects": {}}


def save_state(state):
    os.makedirs("state", exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def subscribers_for(state, machine_name):
    """Return list of chat_ids subscribed to a given project."""
    return [
        cid for cid, u in state.get("users", {}).items()
        if machine_name in u.get("projects", [])
    ]


def all_tracked_projects(state):
    """Return set of all project machine names subscribed to by any user."""
    names = set()
    for u in state.get("users", {}).values():
        names.update(u.get("projects", []))
    return names


# ---------------------------------------------------------------------------
# Drupal.org API
# ---------------------------------------------------------------------------

def api_get(path, params=None):
    r = requests.get(
        f"{DRUPAL_API}/{path}",
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def resolve_project(machine_name):
    """Return (nid, title) for a drupal.org project machine name."""
    data = api_get("node.json", {"field_project_machine_name": machine_name, "limit": 1})
    nodes = data.get("list", [])
    if not nodes:
        raise ValueError(f"Not found: '{machine_name}'")
    return str(nodes[0]["nid"]), nodes[0].get("title", machine_name)


def fetch_issues_with_new_comments(project_nid, since_timestamp):
    """Return issues whose last comment is newer than since_timestamp."""
    results = []
    for page in range(MAX_PAGES):
        data = api_get("node.json", {
            "type": "project_issue",
            "field_project": project_nid,
            "sort": "last_comment_timestamp",
            "direction": "DESC",
            "limit": 50,
            "page": page,
        })
        issues = data.get("list", [])
        if not issues:
            break
        reached_old = False
        for issue in issues:
            if int(issue.get("last_comment_timestamp") or 0) <= since_timestamp:
                reached_old = True
                break
            results.append(issue)
        if reached_old:
            break
        if page < MAX_PAGES - 1:
            time.sleep(1)
    return results


def fetch_new_comments(issue_nid, since_timestamp):
    """Return comments on an issue created after since_timestamp, oldest first."""
    data = api_get("comment.json", {
        "node": issue_nid,
        "sort": "created",
        "direction": "DESC",
        "limit": 50,
    })
    results = []
    for comment in data.get("list", []):
        if int(comment.get("created", 0)) <= since_timestamp:
            break
        results.append(comment)
    results.reverse()
    return results


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def send_telegram(bot_token, chat_id, text):
    requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": text,
              "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=15,
    ).raise_for_status()


def get_updates(bot_token, offset):
    r = requests.get(
        f"https://api.telegram.org/bot{bot_token}/getUpdates",
        params={"offset": offset, "limit": 100, "timeout": 0},
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("result", [])


def strip_html(text):
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


def truncate(text, max_len=500):
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(' ', 1)[0] + '…'


def format_comment_message(comment, issue, project_title):
    status = STATUS_LABELS.get(str(issue.get("field_issue_status", "")), "Unknown")
    priority = PRIORITY_LABELS.get(str(issue.get("field_issue_priority", "")), "Unknown")
    author = comment.get("name") or "Anonymous"
    body = truncate(strip_html((comment.get("comment_body") or {}).get("value", "")))
    return (
        f"<b>[{project_title}]</b> New comment\n"
        f'<a href="{issue.get("url", "")}"><b>{issue.get("title", "")}</b></a>\n'
        f"<i>{status} · {priority}</i>\n\n"
        f"<b>{author}:</b>\n"
        f"{body}\n\n"
        f'<a href="{comment.get("url", issue.get("url", ""))}">View comment</a>'
    )


# ---------------------------------------------------------------------------
# Bot command handlers
# ---------------------------------------------------------------------------

def cmd_help(bot_token, chat_id, name="there"):
    send_telegram(bot_token, chat_id,
        f"Hi {name}! I notify you when new comments are posted on Drupal.org issues.\n\n"
        "<b>Commands:</b>\n"
        "/track <code>machine_name</code> — Track a project\n"
        "/untrack <code>machine_name</code> — Stop tracking a project\n"
        "/list — Your tracked projects\n"
        "/help — This message\n\n"
        "The machine name is the last part of the drupal.org project URL.\n"
        "Example: drupal.org/project/<code>token</code> → /track <code>token</code>")


def cmd_track(bot_token, chat_id, user_name, machine_name, state):
    if not machine_name:
        send_telegram(bot_token, chat_id,
            "Usage: /track <code>machine_name</code>\n\n"
            "Example: drupal.org/project/<code>token</code> → /track <code>token</code>")
        return

    users = state.setdefault("users", {})
    user = users.setdefault(chat_id, {"name": user_name, "projects": []})

    if machine_name in user["projects"]:
        send_telegram(bot_token, chat_id, f"You're already tracking <code>{machine_name}</code>.")
        return

    send_telegram(bot_token, chat_id, f"Looking up <code>{machine_name}</code> on drupal.org…")

    projects = state.setdefault("projects", {})

    # Resolve NID if not already cached globally
    if machine_name not in projects:
        try:
            nid, title = resolve_project(machine_name)
        except Exception:
            send_telegram(bot_token, chat_id,
                f"<code>{machine_name}</code> was not found on drupal.org.\n"
                "Check the machine name and try again.")
            return
        projects[machine_name] = {
            "nid": nid,
            "title": title,
            "last_checked": int(time.time()),  # Start from now — no historical spam
        }
        print(f"New project '{machine_name}' ({title}, nid {nid})")
    else:
        title = projects[machine_name].get("title", machine_name)

    user["projects"].append(machine_name)

    send_telegram(bot_token, chat_id,
        f"You're now tracking <b>{title}</b>.\n"
        "You'll get a message here for every new comment on its issues.")
    print(f"User {chat_id} subscribed to '{machine_name}'")


def cmd_untrack(bot_token, chat_id, machine_name, state):
    if not machine_name:
        send_telegram(bot_token, chat_id, "Usage: /untrack <code>machine_name</code>")
        return

    user = state.get("users", {}).get(chat_id, {})
    projects_list = user.get("projects", [])

    if machine_name not in projects_list:
        send_telegram(bot_token, chat_id,
            f"You're not tracking <code>{machine_name}</code>.")
        return

    projects_list.remove(machine_name)

    # Remove project from global cache if nobody else is subscribed
    if not subscribers_for(state, machine_name):
        state.get("projects", {}).pop(machine_name, None)
        print(f"Project '{machine_name}' removed (no subscribers left)")

    title = state.get("projects", {}).get(machine_name, {}).get("title", machine_name)
    send_telegram(bot_token, chat_id, f"Stopped tracking <b>{title or machine_name}</b>.")
    print(f"User {chat_id} unsubscribed from '{machine_name}'")


def cmd_list(bot_token, chat_id, state):
    user = state.get("users", {}).get(chat_id, {})
    project_names = user.get("projects", [])

    if not project_names:
        send_telegram(bot_token, chat_id,
            "You're not tracking any projects yet.\n"
            "Use /track <code>machine_name</code> to add one.")
        return

    lines = ["<b>Your tracked projects:</b>\n"]
    for name in project_names:
        title = state.get("projects", {}).get(name, {}).get("title", name)
        lines.append(f"• <b>{title}</b> (<code>{name}</code>)")

    send_telegram(bot_token, chat_id, "\n".join(lines))


def handle_commands(bot_token, state):
    """Fetch and process all new Telegram messages from any user."""
    offset = state.get("_telegram_offset", 0)
    updates = get_updates(bot_token, offset)

    for update in updates:
        state["_telegram_offset"] = update["update_id"] + 1

        message = update.get("message", {})
        if not message:
            continue

        chat_id = str(message.get("chat", {}).get("id", ""))
        if not chat_id:
            continue

        from_user = message.get("from", {})
        user_name = from_user.get("username") or from_user.get("first_name") or "there"

        text = (message.get("text") or "").strip()
        if not text or not text.startswith("/"):
            continue

        parts = text.split()
        command = parts[0].split("@")[0].lower()
        arg = parts[1].strip().lower() if len(parts) > 1 else ""

        print(f"User {chat_id} ({user_name}): {command} {arg}")

        if command == "/track":
            cmd_track(bot_token, chat_id, user_name, arg, state)
        elif command == "/untrack":
            cmd_untrack(bot_token, chat_id, arg, state)
        elif command == "/list":
            cmd_list(bot_token, chat_id, state)
        elif command in ("/help", "/start"):
            cmd_help(bot_token, chat_id, user_name)
        else:
            send_telegram(bot_token, chat_id,
                f"Unknown command: <code>{command}</code>\nSend /help for help.")


# ---------------------------------------------------------------------------
# Comment polling
# ---------------------------------------------------------------------------

def poll_comments(bot_token, state):
    tracked = all_tracked_projects(state)

    if not tracked:
        print("No projects tracked by any user. Nothing to poll.")
        return

    now = int(time.time())
    total_sent = 0
    projects = state.setdefault("projects", {})

    for machine_name in tracked:
        proj = projects.get(machine_name, {})
        nid = proj.get("nid")
        title = proj.get("title", machine_name)
        last_checked = proj.get("last_checked", 0)
        subs = subscribers_for(state, machine_name)

        if not nid:
            try:
                nid, title = resolve_project(machine_name)
                proj.update({"nid": nid, "title": title})
                projects[machine_name] = proj
            except Exception as e:
                print(f"ERROR resolving '{machine_name}': {e}")
                continue

        if last_checked == 0:
            # First poll — initialise silently (confirmation already sent by /track)
            projects[machine_name]["last_checked"] = now
            continue

        try:
            issues = fetch_issues_with_new_comments(nid, last_checked)
            print(f"'{machine_name}': {len(issues)} issue(s) with new comments "
                  f"({len(subs)} subscriber(s)).")

            for issue in issues:
                comments = fetch_new_comments(issue["nid"], last_checked)
                print(f"  Issue {issue['nid']}: {len(comments)} new comment(s).")
                for comment in comments:
                    msg = format_comment_message(comment, issue, title)
                    for chat_id in subs:
                        send_telegram(bot_token, chat_id, msg)
                        total_sent += 1
                        time.sleep(0.3)
                time.sleep(1)

            projects[machine_name]["last_checked"] = now

        except Exception as e:
            print(f"ERROR polling '{machine_name}': {e}")

    print(f"Polling done. Sent {total_sent} notification(s).")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

    if not bot_token:
        print("ERROR: TELEGRAM_BOT_TOKEN must be set.")
        sys.exit(1)

    if "--test" in sys.argv:
        print("Verifying bot token…")
        r = requests.get(f"https://api.telegram.org/bot{bot_token}/getMe", timeout=10)
        data = r.json()
        if data.get("ok"):
            print(f"Bot verified: @{data['result']['username']}")
        else:
            print(f"ERROR: {data}")
            sys.exit(1)
        return

    state = load_state()

    print("--- Checking for bot commands ---")
    handle_commands(bot_token, state)

    print("--- Polling for new comments ---")
    poll_comments(bot_token, state)

    save_state(state)


if __name__ == "__main__":
    main()
