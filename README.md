# Drupal Issue Tracker

Get Telegram notifications when new comments are posted on drupal.org issues — for Drupal core or any contrib project.

Anyone can use the bot. Each person tracks their own projects by messaging it directly.

Runs entirely on GitHub Actions. No server, no hosting, no cost.

---

## How It Works

A scheduled GitHub Actions workflow runs every 5 minutes:

1. **Checks the bot inbox** — processes commands (`/track`, `/untrack`, etc.) from any user
2. **Polls the [Drupal.org REST API](https://www.drupal.org/drupalorg/docs/apis/rest-and-other-apis)** for new issue comments
3. **Sends notifications** to each user subscribed to the relevant project

---

## Setup (~5 minutes, one-time)

### Step 1 — Copy this repository

Click **"Use this template"** at the top of this page → **"Create a new repository"**.

- Visibility: **Private** is recommended (keeps your bot token safe)

---

### Step 2 — Create a Telegram bot

1. Open Telegram, search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. BotFather gives you a **Bot API Token** — save it:
   ```
   123456789:ABCdefGHIjklMNOpqrsTUVwxyz
   ```

---

### Step 3 — Add your bot token to GitHub

In your repo: **Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|------|-------|
| `TELEGRAM_BOT_TOKEN` | The token from Step 2 |

That's the only secret needed.

---

### Step 4 — Enable workflows

Go to the **Actions** tab. If prompted, click **"I understand my workflows, go ahead and enable them"**.

---

### Step 5 — Verify

1. Actions tab → **"Test Setup"** → **"Run workflow"**
2. Check the workflow logs — you should see `Bot verified: @your_bot_name`

---

### Step 6 — Share your bot

Tell people your bot's Telegram username (e.g. `@my_drupal_tracker_bot`). Anyone can find it and start tracking projects immediately — no further setup needed on their end.

---

## Using the Bot

Anyone who messages the bot can track projects. Find it by username on Telegram and send:

| Command | Description |
|---------|-------------|
| `/start` or `/help` | Get started, see available commands |
| `/track token` | Track a project by its machine name |
| `/untrack token` | Stop tracking a project |
| `/list` | See your currently tracked projects |

The machine name is the last part of the drupal.org project URL:
`drupal.org/project/token` → `/track token`

Commands are processed within 5 minutes (next scheduled run).

---

## Notification Format

For every new comment posted on a tracked issue, you receive:

```
[Token] New comment
Issue title (linked)
Needs review · Normal

username:
The comment text appears here, up to 500 characters…

View comment →
```

---

## First Use

When you `/track` a project for the first time, the bot confirms it immediately. From that point on you'll be notified of new comments — no historical backlog is sent.

---

## Troubleshooting

**"Test Setup" workflow fails**
- Check that `TELEGRAM_BOT_TOKEN` matches exactly what BotFather gave you (no spaces)

**Bot doesn't respond to commands**
- Commands are processed on the next scheduled run — wait up to 5 minutes
- Check the **Actions** tab to confirm the poll workflow is running

**Workflow not running on schedule**
- GitHub disables scheduled workflows on repos with no activity for 60 days
- Push any small change to re-activate (e.g. add a blank line to this README)
- Scheduled runs can also be delayed up to 15 minutes during GitHub peak hours

---

## Notes on Drupal.org API Usage

- Requests are made sequentially with a descriptive `User-Agent` header
- Project NIDs are cached in `state/state.json` to avoid redundant lookups
- Each project is polled once per run regardless of subscriber count
- No hard rate limits are documented by Drupal.org; polling every 5 minutes is well within reasonable use

---

## License

MIT
