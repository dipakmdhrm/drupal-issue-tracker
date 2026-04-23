# Drupal Issue Tracker

Get Telegram notifications when issues are updated on drupal.org — for any core or contrib project you care about.

Runs entirely on GitHub Actions. No server, no hosting, no cost.

---

## How It Works

A scheduled GitHub Actions workflow polls the [Drupal.org REST API](https://www.drupal.org/drupalorg/docs/apis/rest-and-other-apis) every 5 minutes. When it finds new or updated issues matching your filters, it sends you a Telegram message.

---

## Setup (~10 minutes)

### Step 1 — Copy this repository

Click the **"Use this template"** button at the top of this page, then select **"Create a new repository"**.

- Give it any name (e.g. `my-drupal-tracker`)
- Set visibility to **Private** (your Telegram credentials will be stored as secrets, but private is safer)
- Click **"Create repository"**

---

### Step 2 — Create a Telegram bot

1. Open Telegram and search for **@BotFather**
2. Send the message `/newbot`
3. Follow the prompts — choose any name and username for your bot
4. BotFather will give you a **Bot API Token** that looks like:
   ```
   123456789:ABCdefGHIjklMNOpqrsTUVwxyz
   ```
   Save this. You will need it in Step 4.

---

### Step 3 — Get your Telegram Chat ID

1. Open a chat with your new bot and send it any message (e.g. "hello")
2. In your phone browser, open this URL — replace `YOUR_TOKEN` with your bot token:
   ```
   https://api.telegram.org/botYOUR_TOKEN/getUpdates
   ```
3. Look for `"chat":{"id":` in the response. The number after it is your **Chat ID**:
   ```json
   "chat": { "id": 123456789, ... }
   ```
   Save this number.

> **If the response is empty (`"result":[]`)**, send another message to your bot and refresh the URL.

---

### Step 4 — Add secrets to your GitHub repository

In your new repository, go to:
**Settings → Secrets and variables → Actions → New repository secret**

Add these two secrets:

| Name | Value |
|------|-------|
| `TELEGRAM_BOT_TOKEN` | The token from Step 2 |
| `TELEGRAM_CHAT_ID` | The chat ID from Step 3 |

---

### Step 5 — Configure which projects to track

Edit the file `projects.yml` in your repository (click the file, then the pencil icon to edit).

Add any Drupal.org projects you want to track:

```yaml
projects:

  - machine_name: drupal        # From the drupal.org URL: drupal.org/project/drupal
    label: "Drupal Core"
    filters:
      priority: all             # critical | major | normal | minor | all
      status: all               # active | needs_review | needs_work | rtbc | fixed | all

  - machine_name: token
    label: "Token"
    filters:
      priority: critical        # Only notify for critical issues
      status: all
```

The `machine_name` is the last part of the project URL on drupal.org.
For example, `https://www.drupal.org/project/views` → `machine_name: views`

Commit the file when done.

---

### Step 6 — Verify your setup

1. In your repository, go to the **Actions** tab
2. Click **"Test Setup"** in the left sidebar
3. Click **"Run workflow"** → **"Run workflow"**
4. Wait ~30 seconds, then check your Telegram

You should receive a confirmation message from your bot. If you do, everything is working.

---

### Step 7 — Enable the scheduled workflow (if needed)

GitHub may ask you to enable workflows on a newly created repository.

Go to the **Actions** tab. If you see a prompt to enable workflows, click **"I understand my workflows, go ahead and enable them"**.

The tracker will now run automatically every 5 minutes.

---

## Customising Filters

Edit `projects.yml` any time to adjust which issues you get notified about.

### Priority options

| Value | Meaning |
|-------|---------|
| `all` | All priorities |
| `critical` | Critical only |
| `major` | Major only |
| `normal` | Normal only |
| `minor` | Minor only |

### Status options

| Value | Drupal.org status |
|-------|------------------|
| `all` | All statuses |
| `active` | Active |
| `needs_review` | Needs review |
| `needs_work` | Needs work |
| `rtbc` | Reviewed & tested by the community |
| `fixed` | Fixed / Closed (fixed) |

---

## First Run Behaviour

On the very first run, the tracker will **not** send you all historical issues. Instead, it sends one confirmation message per project ("Now tracking: …") and then only notifies you about changes going forward.

---

## Troubleshooting

**No message received after running "Test Setup"**
- Double-check the `TELEGRAM_BOT_TOKEN` secret — it must match exactly what BotFather gave you
- Make sure you sent at least one message to your bot before getting the Chat ID
- Confirm `TELEGRAM_CHAT_ID` is a number (no quotes, no spaces)

**Workflow not running on schedule**
- GitHub disables scheduled workflows on repositories with no activity for 60 days. Push any small change (e.g. edit a comment in `projects.yml`) to re-activate it.
- Scheduled runs can be delayed by up to 15 minutes during GitHub's peak hours.

**"Project not found" error in workflow logs**
- Check the `machine_name` in your `projects.yml` matches the URL on drupal.org exactly (lowercase, hyphens not underscores)

---

## Notes on Drupal.org API Usage

This tracker follows the informal rate-limit guidelines from the Drupal.org infrastructure team:
- Sends a `User-Agent` header identifying the app
- Makes all requests sequentially (no parallelism)
- Caches project IDs locally in `state/state.json`
- Fetches only issues changed since the last run

There are no hard rate limits documented. Polling every 5 minutes across a reasonable number of projects is well within acceptable use.

---

## License

MIT
