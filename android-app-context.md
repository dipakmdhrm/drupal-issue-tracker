# Drupal.org Issue Tracker — Android App Context

This document summarises all research and decisions made in a prior session. Use this as the starting context when building the Android app in a new Claude session.

---

## Goal

A personal tool that monitors Drupal.org issues (core + contrib modules) and sends push notifications when issues are created or updated.

---

## Drupal.org API — Full Reference

### Available APIs

| API | Base URL | Format | Use case |
|-----|----------|--------|----------|
| REST API (api-d7) | `https://www.drupal.org/api-d7/` | JSON / XML | Issues, comments, projects |
| Update Status XML | `https://updates.drupal.org/release-history/` | XML | Module/core releases only |
| RSS/Atom Feeds | `https://www.drupal.org/project/issues/rss/{machine_name}` | RSS 2.0 | Simpler, less structured |

The **REST API** is the primary API to use. It is a Drupal 7 RESTful Web Services module endpoint.

---

### Authentication

- **None required.** Fully public, no API keys, no OAuth.
- Read-only (GET only). No write/POST access exists publicly.

---

### Rate Limits

- **No documented hard limits.** No rate-limit headers in responses.
- Informal guidelines from the Drupal.org infrastructure team:
  - Set a descriptive `User-Agent` header identifying your app
  - Make requests sequentially (no parallelism/concurrency)
  - Cache results locally to avoid redundant requests
  - Reactive IP blocking only — "abuse will be blocked as needed"
- **Hard technical limit:** Max **50 records per page** (pagination required for more)
- Polling every 2 minutes across ~10 projects (~5 sequential requests/min) was assessed as safe and unlikely to trigger blocking.

---

### Issue Endpoints

#### Get a project's node ID (NID) by machine name
```
GET https://www.drupal.org/api-d7/node.json?field_project_machine_name={machine_name}&limit=1
```
Returns a list; use `list[0].nid`. Cache this — it never changes.

Examples:
- `drupal` (Drupal Core) → nid `3060`
- `token` → nid `106016`
- `views` → nid `6424`

#### List issues for a project
```
GET https://www.drupal.org/api-d7/node.json
  ?type=project_issue
  &field_project={nid}
  &sort=changed
  &direction=DESC
  &limit=50
  &page=0
```

#### Filter by status and/or priority
```
GET https://www.drupal.org/api-d7/node.json
  ?type=project_issue
  &field_project={nid}
  &field_issue_status={status_code}
  &field_issue_priority={priority_code}
  &sort=changed
  &direction=DESC
  &limit=50
```

#### Get comments on an issue
```
GET https://www.drupal.org/api-d7/comment.json?node={issue_nid}&limit=50
```

---

### Issue Field Reference

| Field | Type | Description |
|-------|------|-------------|
| `nid` | String | Issue node ID |
| `title` | String | Issue title |
| `created` | String | Unix timestamp — creation time |
| `changed` | String | Unix timestamp — last modification |
| `field_issue_status` | String | Status code (see below) |
| `field_issue_priority` | String | Priority code (see below) |
| `field_issue_category` | String | Category code (see below) |
| `field_issue_component` | String | Component name (e.g. `views.module`) |
| `field_issue_version` | String | Affected version (e.g. `11.x-dev`) |
| `field_project` | Object | `{uri, id, resource}` — project reference |
| `author` | Object | `{uri, id, resource}` — reporter reference |
| `comment_count` | String | Total comment count |
| `last_comment_timestamp` | String | Unix timestamp of last comment |
| `url` | String | Full URL to the issue page |
| `body` | Object | `{value, summary, format}` — HTML body |

---

### Status Codes (`field_issue_status`)

| Code | Label |
|------|-------|
| `1` | Active |
| `2` | Fixed |
| `3` | Closed (duplicate) |
| `4` | Postponed |
| `5` | Closed (won't fix) |
| `6` | Closed (works as designed) |
| `7` | Closed (fixed) |
| `8` | Needs review |
| `13` | Needs work |
| `14` | Reviewed & tested by the community (RTBC) |
| `15` | Patch (to be ported) |
| `16` | Postponed (maintainer needs info) |
| `17` | Closed (outdated) |
| `18` | Closed (cannot reproduce) |

---

### Priority Codes (`field_issue_priority`)

| Code | Label |
|------|-------|
| `400` | Critical |
| `300` | Major |
| `200` | Normal |
| `100` | Minor |

---

### Category Codes (`field_issue_category`)

| Code | Label |
|------|-------|
| `1` | Bug report |
| `2` | Task |
| `3` | Feature request |
| `4` | Support request |
| `5` | Plan |

---

### Pagination

The API uses zero-indexed page numbers. Max 50 records per page.

```
&limit=50&page=0   ← first page
&limit=50&page=1   ← second page
```

To detect new/changed issues: sort by `changed DESC`, fetch pages until you hit a `changed` timestamp older than your last-checked time, then stop.

---

### RSS Feeds (simpler alternative, less structured)

```
# All open issues for a project
https://www.drupal.org/project/issues/rss/{machine_name}

# Filtered by status
https://www.drupal.org/project/issues/rss/{machine_name}?statuses=8

# Security advisories (core)
https://www.drupal.org/security/rss.xml

# Security advisories (contrib)
https://www.drupal.org/security/contrib/rss.xml

# Releases for a project (by nid)
https://www.drupal.org/node/{nid}/release/feed
```

RSS items contain title, link, HTML description, pubDate, and dc:creator. Status/priority appear only inside the HTML blob — not as structured fields.

---

### What Does NOT Exist

| Feature | Available? |
|---------|-----------|
| Webhooks / push notifications | No — must poll |
| Write access (POST issues/comments) | No |
| GraphQL or JSON:API | No |
| OAuth or API keys | No (not needed) |
| Rate limit headers | No |
| Filter by `changed >= timestamp` | No — sort by changed DESC and stop when old |

---

## Polling Strategy (for Android app)

Since there are no webhooks, the app must poll. Recommended approach:

1. **Store last-checked timestamp** per project in local DB (Room/SQLite)
2. On each poll cycle, fetch `sort=changed&direction=DESC&limit=50` per project
3. Iterate results; stop when `changed <= last_checked_timestamp`
4. For each new/changed issue, fire a local push notification
5. Update `last_checked` to current time
6. Repeat on a schedule (WorkManager for Android background tasks)

**Minimum safe polling interval:** 2 minutes assessed as safe (5 req/min for 10 projects).

---

## What Was Built (Telegram Bot via GitHub Actions)

As a quick solution (phone-only, no server), a GitHub Actions + Telegram bot was built first:

- **Repo:** `https://github.com/dipakmdhrm/drupal-issue-tracker` (check for current URL)
- Polls every 5 minutes via GitHub Actions scheduled workflow
- Sends Telegram messages for new/updated issues
- State stored in `state/state.json` committed back to repo
- Config via `projects.yml` — no code changes needed

The Android app is the longer-term solution with true 2-minute (or better) intervals and native push notifications.

---

## Android App — Recommended Architecture

### Stack
- **Language:** Kotlin
- **Background polling:** WorkManager with `PeriodicWorkRequest` (minimum 15 minutes enforced by Android OS for battery) or foreground service for shorter intervals
- **HTTP:** Retrofit + OkHttp
- **Local DB:** Room (to store seen issue IDs and last-checked timestamps)
- **Notifications:** NotificationManager + NotificationChannel (Android 8+)
- **Config UI:** Jetpack Compose or XML layouts

### Android Background Polling Constraint

**Important:** Android's WorkManager enforces a **minimum interval of 15 minutes** for `PeriodicWorkRequest`. For 2-minute polling, you need a **foreground service** (shows a persistent notification while running). This is acceptable for a developer tool but worth noting.

Alternative: Use Firebase Cloud Messaging (FCM) with a companion server that does the polling and pushes to FCM. But this requires a server — the same constraint that led to GitHub Actions for the Telegram solution.

### Key User-Facing Features
1. Add/remove projects to watch (search by machine name or browse)
2. Per-project filter settings (priority, status, category)
3. Notification grouping by project
4. Tap notification → open issue in browser or in-app webview
5. Mark as read / dismiss
6. Settings: poll interval, notification sound, quiet hours

### No Authentication Needed
The Drupal.org API is fully public. No login, no API keys, no OAuth flow needed in the app.

---

## Useful API URLs to Test

```
# Drupal core issues (most recently changed)
https://www.drupal.org/api-d7/node.json?type=project_issue&field_project=3060&sort=changed&direction=DESC&limit=10

# Critical Drupal core issues
https://www.drupal.org/api-d7/node.json?type=project_issue&field_project=3060&field_issue_priority=400&sort=changed&direction=DESC&limit=10

# RTBC issues for Drupal core
https://www.drupal.org/api-d7/node.json?type=project_issue&field_project=3060&field_issue_status=14&sort=changed&direction=DESC&limit=10

# Get Token module project info
https://www.drupal.org/api-d7/node.json?field_project_machine_name=token&limit=1

# Comments on a specific issue
https://www.drupal.org/api-d7/comment.json?node={issue_nid}&limit=50
```
