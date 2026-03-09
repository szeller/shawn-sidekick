---
name: incident_investigation
description: Deep-dive investigation of a single PagerDuty alert for on-call triage and resolution
argument-hint: <incident-id-or-number-or-alert-name> [lookback-days]
allowed-tools: Bash, Read
---

# Incident Investigation Agent

Deep-dive into a single PagerDuty incident/alert to help an on-call engineer triage and resolve it. Gathers alert details, playbook, historical patterns, code context, and related tickets.

## Overview

This agent takes a PagerDuty incident (by ID, number, or alert name) and investigates it:

1. Fetches the incident and alert details (what is firing, severity, monitoring links)
2. Attempts to fetch the playbook/runbook (if URL is in the alert body)
3. Checks for other active incidents on the same service
4. Searches historical occurrences for patterns (frequency, day-of-week, resolution times)
5. Searches the codebase for the alert definition (thresholds, metrics, conditions)
6. Checks recent code changes — both to the alert definition AND to the service code that may have caused the issue
7. Searches JIRA for related tickets
8. Searches sev-announce emails for past incident communications
9. Synthesizes findings into an investigation summary with recommended next steps
10. Generates an HTML report as a detailed reference artifact

**Conversational output is the primary delivery**. Print key findings as each step completes so the engineer sees results building up in real-time. The HTML report is a secondary reference artifact, not the main output.

## Prerequisites

- PagerDuty API token configured in `.env` (`PAGERDUTY_API_TOKEN`)
- Optional: JIRA credentials for ticket search
- Optional: Gmail credentials for sev-announce search
- Optional: Dropbox/Confluence credentials for playbook fetching
- Optional: `~/src/server` checkout for code search

## Usage Pattern

### Step 0: Setup

Parse arguments. The first argument is one of:
- A PagerDuty incident ID (alphanumeric string like `Q133FER79S2LBG`)
- A PagerDuty incident number (purely numeric like `24791730`)
- An alert name (contains underscores/hyphens/colons, like `NoInitialPaymentSucess_Braintree_Braintreex20PayPal_TEAM`)

Optional second argument is the lookback period in days for historical search (default: 90).

```bash
INPUT_ARG=$1        # incident ID, number, or alert name
LOOKBACK_DAYS=${2:-90}

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
TMP_DIR=/tmp/incident_investigation_$$
mkdir -p $TMP_DIR

LOOKBACK_SINCE=$(date -v-${LOOKBACK_DAYS}d +%Y-%m-%d)
TODAY=$(date +%Y-%m-%d)
```

**Input resolution logic:**

```python
import re

input_arg = INPUT_ARG

if input_arg.isdigit():
    # Purely numeric — incident number
    # Search recent incidents to find the matching one
    pass
elif re.match(r'^[A-Z0-9]+$', input_arg):
    # Alphanumeric, looks like a PD incident ID
    incident = client.get_incident(input_arg)
else:
    # Treat as alert name — search recent incidents by title
    # First try last 7 days, then widen to 30 days
    pass
```

If the input is an alert name and no matching incident is found in the last 30 days, report the failure and suggest the user provide an incident ID instead.

### Step 1: Fetch Incident and Alert Details

```python
from sidekick.clients.pagerduty import PagerDutyClient
from sidekick.config import get_pagerduty_config

config = get_pagerduty_config()
client = PagerDutyClient(api_token=config['api_token'])

incident = client.get_incident(INCIDENT_ID)
alerts = client.list_alerts(INCIDENT_ID)
```

Extract and print immediately (engineer needs this in 30 seconds):
- Incident: number, title, status, urgency, service name, service ID, escalation policy, teams, assigned to, created_at, html_url
- For each alert: summary, severity, status, created_at
- Alert body details and monitoring links

**Defensive null handling** — every field through the `body` chain can be `None`:
```python
body = alert.get('body') or {}
cef = body.get('cef_details') or {}
description = cef.get('description', '')
details = cef.get('details') or {}
contexts = body.get('contexts') or []
```

Save `SERVICE_ID` and `ALERT_TITLE` (from the alert summary or incident title) for subsequent steps.

Also extract all URLs from the alert body (playbook URLs, monitoring links) for use in Step 2.

### Step 2: Fetch Playbook/Runbook (Best-Effort)

Scan the alert body for playbook or runbook URLs. Check in this order:
1. `body.cef_details.details` — look for keys containing "playbook", "runbook", "documentation", or any value that's a URL
2. `body.contexts` — links where the text or href contains "playbook" or "runbook"
3. `body.cef_details.description` — scan for embedded URLs

If a playbook URL is found, attempt to fetch it:
- **Dropbox Paper URLs** (`dropbox.com/scl/fi/` or `paper.dropbox.com`): `python3 -m sidekick.clients.dropbox get-paper-contents-from-link "URL"`
- **Confluence URLs** (`atlassian.net/wiki/`): `python3 -m sidekick.clients.confluence get-content-from-link "URL"`
- **Other URLs**: Note the link for the report but do not attempt to fetch

If the fetch succeeds, summarize the playbook content (don't dump verbatim — keep it focused on the key triage steps).

If no playbook is found, note "No playbook URL found in alert body" and move on.

### Step 3: Related Active Incidents

Check PagerDuty for other active (triggered/acknowledged) incidents on the same service. Use `list_incidents` filtered to active statuses only — this is a separate call from the analytics fetch in Step 4 because the Analytics API doesn't support status filtering.

```python
from datetime import datetime, timedelta

since_24h = (datetime.utcnow() - timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ')
recent_incidents = client.list_incidents(
    since=since_24h,
    service_ids=[SERVICE_ID],
    statuses=['triggered', 'acknowledged']
)
```

List any PagerDuty incidents other than the one being investigated. This tells the engineer whether this is isolated or part of a broader outage.

If no other active incidents, note "No other active incidents on this service in the last 24 hours."

### Step 4: Historical Occurrences

This is the most critical analytical step. Use the **Analytics API** (`list_incidents_analytics`) to fetch all incidents for the service in a single API call (vs ~6 calls with the regular API). The Analytics API supports `limit=1000` per page and returns pre-computed fields like `seconds_to_resolve` and `auto_resolved`.

```python
all_incidents = client.list_incidents_analytics(
    since=LOOKBACK_SINCE,
    until=TODAY,
    service_ids=[SERVICE_ID]
)

# Match by description containment (not exact — PD may append suffixes)
# Note: Analytics API uses 'description' instead of 'title'
matching = [inc for inc in all_incidents if ALERT_TITLE in inc.get('description', '')]
```

**Also use this data for Step 3** — filter the same result set for triggered/acknowledged incidents in the last 24 hours, instead of making a separate API call.

For each matching incident, extract:
- `created_at` and `resolved_at` timestamps
- `seconds_to_resolve` (pre-computed by PagerDuty — no need to calculate)
- `auto_resolved` flag
- Day of week and hour (UTC)

Then compute:
- **Total occurrences** in the lookback window
- **Frequency**: occurrences per week average
- **Resolution time stats**: median, min, max
- **Day-of-week distribution**: count per day (surfaces weekend/weekday patterns)
- **Time-of-day distribution**: count by hour UTC (surfaces cron job or business hours patterns)
- **Recency**: when did this last fire before the current incident?
- **Trend**: compare first half vs second half of the lookback window. If second half is 2x+ the first, classify as "Getting Worse." If less than half, "Getting Better." Otherwise "Stable."

### Step 5: Alert Definition (Best-Effort)

Search the codebase for the alert definition — the threshold, metric, rollup window, and what code emits the metric. Use the `src` CLI (Sourcegraph) as the primary search tool, with local `grep` as a fallback.

#### 5a. Search with Sourcegraph (`src`)

The `src` CLI (`/opt/homebrew/bin/src`) searches the full monorepo via Sourcegraph without timeout issues:

```bash
# Search for the alert name
src search 'ALERT_NAME lang:python'

# Try variations if no results
src search 'CORE_ALERT_NAME lang:python'  # e.g., "NoInitialPaymentSucess"
src search 'ALERT_NAME_WITHOUT_SUFFIX'     # e.g., without _TEAM, _USER
```

**Important**: Grepping a full monorepo checkout will always time out. Use `src search` for broad searches. Only use local `grep` on specific subdirectories once you know the path.

#### 5b. Local search (fallback)

If `src` is not available or for targeted searches after Sourcegraph identifies the right directory:

```bash
if [ -d ~/src/server ]; then
    # Search alert config files in a specific service directory
    grep -r "ALERT_NAME" ~/src/server/configs/services/ \
        --include="*.pyst" --include="*.pyst-include" -l

    # Search a specific subdirectory for broader context
    grep -r "ALERT_NAME" ~/src/server/{SERVICE_PATH}/ \
        --include="*.py" --include="*.pyst" -l
fi
```

**Try alert name variations** if the exact name doesn't match:
- Exact alert name
- Without common suffixes like `_TEAM`, `_USER`
- Core alert name (e.g., `NoInitialPaymentSucess` from `NoInitialPaymentSucess_Braintree_Braintreex20PayPal_TEAM`)

If alert definition files are found, read them for context on how the alert is generated (some alerts are dynamically built from configuration tables).

#### 5c. Metric definition

Search for the metric that the alert monitors to understand what's being measured:

```bash
# Sourcegraph (preferred)
src search 'METRIC_NAME lang:python'

# Local (if you know the directory)
grep -r "METRIC_NAME" ~/src/server/{SERVICE_PATH}/ --include="*.py" -l
```

Read the metric definition to extract the counter/gauge dimensions and what code increments it. This tells the engineer exactly what code path needs to succeed for the alert to clear.

### Step 6: Recent Code Changes (Best-Effort)

Check two categories of recent code changes. Both require `~/src/server` to exist.

#### 6a. Changes to the alert definition

If alert definition files were found in Step 5:

```bash
cd ~/src/server
git log --oneline --since="30 days ago" -- PATH_TO_ALERT_FILE
```

This answers: "Did someone recently change the alert threshold or conditions?"

#### 6b. Changes that may have caused the alert

This is often the more useful question during an active page. Search for recent changes to the **service's application code** — the code that the alert monitors.

Use the file paths found in Step 5 (via Sourcegraph or local search) to locate the service code directory. If Step 5 didn't find files, use the alert's namespace (e.g., `payments`, `external_billing`) to guess the path:

```bash
cd ~/src/server

# If Step 5 found files, use their parent directory
# Otherwise, use Sourcegraph to locate the service directory by namespace
src search 'repo:server file:{NAMESPACE}/ type:path'

# Check recent commits to the service code
git log --oneline --since="7 days ago" -- PATH_TO_SERVICE_CODE/

# Also check the metric emission code if found in Step 5
git log --oneline --since="7 days ago" -- PATH_TO_METRIC_FILE
```

Focus on the **last 7 days** (not 30) for causal changes — if a deployment broke something, it was recent. Show the most recent 10 commits with author and date:

```bash
git log --format="%h %ad %an: %s" --date=short --since="7 days ago" -10 -- PATH_TO_SERVICE_CODE/
```

This answers: "Did a recent deployment or code change cause this alert to fire?"

### Step 7: Related JIRA Tickets (Best-Effort)

Search JIRA for tickets mentioning this alert:

```bash
python3 -m sidekick.clients.jira query "text ~ \"ALERT_NAME\" ORDER BY created DESC"
```

If the full alert name is too specific, also try the core alert name (e.g., `NoInitialPaymentSucess` without the gateway/processor/segment suffixes).

Cap at 10 results. This surfaces existing tickets about this alert (tuning requests, known issues, post-mortems).

### Step 8: sev-announce Search (Best-Effort)

Search for past incident communications about this alert:

```bash
python3 -m sidekick.clients.gmail search "label:sev-announce ALERT_NAME" 5
```

Also try the core alert name if the full name returns nothing. This surfaces any SEV announcements about this alert pattern.

### Step 9: Print Investigation Summary

Before generating the report file, **print the investigation summary directly in the conversation**. This is the primary output — the engineer should not have to open an HTML file to get the key findings.

Print the following as conversational output (not in a file):

1. **One-line status**: "Alert X on service Y — {status}, {urgency}, triggered {time ago}"
2. **What it monitors**: One sentence from the alert definition or body (e.g., "Fires when the 24h sum of successful Braintree PayPal TEAM initial payments drops to zero")
3. **Playbook**: Link if found, or "no playbook found"
4. **History**: "{N} times in {lookback} days, {trend}. {Pattern if found, e.g., 'clusters on weekends'}"
5. **Possible cause**: Based on code changes, alert definition, and historical patterns
6. **Recommended next steps**: Numbered list of actions

This summary should be readable in 30 seconds.

### Step 10: Generate Markdown Report

Compile all findings into a detailed reference report. Save to `$TMP_DIR/report.md`. This is the secondary artifact — the full investigation record with tables, code snippets, and links.

**Important**: Always leave a blank line before and after every markdown table. Pandoc will not render tables that immediately follow inline text.

```markdown
---
prompt: "Incident investigation"
client: incident-investigation
command: incident-investigation
created: YYYY-MM-DD HH:MM:SS
updated: YYYY-MM-DD HH:MM:SS
---

# Incident Investigation: {Alert Title}

**Incident**: #{incident_number} ({incident_id})
**Status**: {status} | **Urgency**: {urgency} | **Severity**: {alert_severity}
**Service**: {service_name} ({service_id})
**Team**: {team_names}
**Escalation Policy**: {escalation_policy_name}
**Assigned To**: {assignee_names}
**Triggered**: {created_at_local} ({time_ago} ago)
**PagerDuty**: {incident_url}

---

## Alert Details

**Alert Summary**: {alert_summary}

**Description**:
> {cef_details.description or "No description available"}

**Structured Details**:
{formatted key-value pairs from cef_details.details, or "No structured details available"}

**Monitoring Links**:

- {link_text}: {url}
- ...

{Or "No monitoring links in alert body."}

---

## Playbook

{If playbook fetched successfully: summarized playbook content with link to original}
{If playbook URL found but fetch failed: "Playbook found but could not be fetched automatically: [URL](URL). Open manually for triage steps."}
{If no playbook: "No playbook URL found in alert body. Consider adding a playbook_url to the alert definition."}

---

## Related Active Incidents

{If other active incidents:}

| # | Title | Status | Urgency | Triggered |
|---|-------|--------|---------|-----------|
| {number} | {title} | {status} | {urgency} | {created_at} |

**{N} other active incidents on {service_name}** — this may be part of a broader issue.

{If none: "No other active incidents on {service_name} in the last 24 hours. This appears to be an isolated event."}

---

## Historical Occurrences

**Lookback**: {lookback_days} days ({lookback_since} to {today})
**Total occurrences**: {count} ({frequency:.1f}/week average)
**Trend**: {Getting Worse / Getting Better / Stable} — {one sentence}

### Statistics

| Metric | Value |
|--------|-------|
| Total occurrences | {count} |
| First seen | {first_date} |
| Most recent (before now) | {last_date} |
| Median resolution time | {median} |
| Fastest resolution | {min} |
| Slowest resolution | {max} |

### Occurrence Timeline

| Date | Incident # | Resolution Time | Day | Hour (UTC) |
|------|-----------|-----------------|-----|------------|
| {date} | #{number} | {resolution} | {day_name} | {hour}:00 |
| ... | ... | ... | ... | ... |

### Patterns

**Day-of-week distribution**:

| Day | Count | |
|-----|-------|-|
| Monday | {N} | {bar} |
| Tuesday | {N} | {bar} |
| ... | ... | ... |

**Peak hours (UTC)**: {list of hours with most occurrences}

**Trend**: {first_half_count} occurrences in first {N} days vs {second_half_count} in last {N} days.

{If no history: "No previous occurrences found in the last {lookback_days} days. This appears to be a new alert."}

---

## Alert Definition

{If code found:}

**Alert config**: `{file_path}`

```python
{relevant code snippet — the alert definition, ~20-40 lines}
```

**What this means**: {one-sentence plain-English explanation of when the alert fires}

| Property | Value |
|----------|-------|
| Threshold | {threshold extracted from code} |
| Metric | {metric_name} |
| Rollup Window | {window} |

{If metric definition found:}

**Metric definition** (`{metric_file_path}`):

```python
{metric definition snippet}
```

**What this measures**: {one-sentence explanation of the metric and its dimensions}

{If ~/src/server not found: "Source code not available (`~/src/server` not found)."}
{If alert not found in code: "Alert definition not found in source code (may be dynamically generated)."}

---

## Recent Code Changes

### Alert Definition Changes (last 30 days)

{If changes found:}

| Date | Author | Commit | Message |
|------|--------|--------|---------|
| {date} | {author} | {hash} | {message} |

{If no changes: "No changes to the alert definition in the last 30 days."}

### Service Code Changes (last 7 days)

Recent changes to the service's application code that may have caused this alert:

{If changes found:}

| Date | Author | Commit | Message |
|------|--------|--------|---------|
| {date} | {author} | {hash} | {message} |

{If no changes: "No changes to the service code in the last 7 days."}
{If code not found: "Skipped — source code not available."}

---

## Related JIRA Tickets

{If tickets found:}

| Key | Summary | Status | Assignee |
|-----|---------|--------|----------|
| [KEY](url) | {summary} | {status} | {assignee} |

{If none: "No JIRA tickets found mentioning this alert."}

---

## Related Incident Communications

{If sev-announce emails found: brief summary of each with date and subject}
{If none: "No sev-announce emails found for this alert."}

---

## Investigation Summary

### What is happening
{1-2 sentences synthesizing alert details + description + metric being monitored}

### Is this known?
{Based on historical data: new vs recurring, frequency, trend. E.g., "This is a recurring alert that has fired 7 times in 90 days, primarily on weekends."}

### Likely cause
{Based on alert body, code analysis, and recent changes. E.g., "Low weekend TEAM transaction volume causes the 24h sum to drop to zero, triggering the <= 0 threshold." Or "Insufficient data to determine root cause" if nothing conclusive.}

### Recommended next steps
1. {Most urgent — e.g., "Check the monitoring dashboard at [link]"}
2. {Second — e.g., "Follow the playbook at [link]" or "Check recent deployments"}
3. {Third — e.g., "If this auto-resolves within {median_resolution}, no action needed"}
4. {Follow-up — e.g., "File a JIRA ticket to tune the threshold if this is noise"}

### Resolution guidance
{If auto-resolution pattern found: "This alert has historically auto-resolved in a median of {N} minutes. Consider waiting {2x median} before escalating."}
{If playbook was found: "Follow the playbook steps at [link]."}
{If recent code changes found: "Recent changes by {author} on {date} may be relevant: {commit message}."}
{If this is the first occurrence: "This is the first time this alert has fired. Investigate manually and consider documenting the resolution for future reference."}
```

### Step 11: Convert to HTML and Open

```bash
mkdir -p output/incident-investigation

# Slugify: lowercase, replace non-alphanumeric with hyphens, truncate to 60 chars
ALERT_SLUG=$(echo "$ALERT_TITLE" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | sed 's/--*/-/g' | cut -c1-60)

python3 -m sidekick.clients.markdown_html $TMP_DIR/report.md \
  output/incident-investigation/${ALERT_SLUG}-${TIMESTAMP}.html \
  --title "Investigation: ${ALERT_TITLE}" --open
```

### Step 12: Clean Up

```bash
rm -rf $TMP_DIR
```

## Design Notes

### Input Resolution
- Purely numeric input = incident number. Try `get-incident` with a recent search.
- Alphanumeric with PD-like format (all uppercase letters and digits) = incident ID. Use `get-incident` directly.
- Anything else = alert name. Search recent incidents (last 7 days first, then widen to 30 days) and match by title containment. Use the most recent match.
- If no match for an alert name, report the failure and suggest the user provide an incident ID instead.

### API Volume
- PagerDuty: ~4 API calls total:
  - `get_incident()` — 1 call
  - `list_alerts()` — 1 call
  - `list_incidents()` for active incidents — 1 call (small result set, usually 1 page)
  - `list_incidents_analytics()` for history — 1 call (supports limit=1000, fetches all incidents for the service in a single request vs ~6 paginated calls with the regular API)
- The Analytics API also returns pre-computed `seconds_to_resolve` and `auto_resolved` fields.
- Note: the Analytics API uses `description` instead of `title` for the incident name.
- Compare to incident_analysis which makes 800+ API calls for alert fetching.

### Best-Effort Steps
- **Every step after Step 1 is best-effort.** If a step fails (missing credentials, access denied, directory not found), log the error in that section and continue.
- The report always generates, even if every optional step fails. Steps 0 and 1 are the only hard requirements.

### Defensive Null Handling
- Every access through the alert body chain must check each level: `(alert.get('body') or {}).get('cef_details') or {}`.
- `body.contexts` can be `None` rather than `[]`.
- `body.cef_details.details` may have a `body` key (nested), or be a flat dict of key-value pairs, or be `None`.

### Code Search Strategy
- **Use `src` (Sourcegraph) for broad searches.** The `src` CLI searches the full monorepo. Grepping a full monorepo checkout will always time out — never attempt it.
- Use local `grep` only on specific subdirectories after Sourcegraph narrows down the location.
- First search for the alert name in `.pyst` and `.pyst-include` files (alert config), then search for the metric name in `.py` files.
- Try variations: exact name, without `_TEAM`/`_USER` suffix, core name (first segment before gateway/processor cuts).
- Read ~50 lines around each match to capture the full alert definition context.

### Historical Analysis
- The Analytics API returns `description` (not `title`). Match by containment, not exact match, because PagerDuty may prepend alert system prefixes or append segment names.
- Trend: compare average weekly rate in first half vs second half. 2x+ increase = "Getting Worse", less than half = "Getting Better", otherwise "Stable".
- Day-of-week clustering helps identify weekend-sensitive alerts (low-volume metrics) vs business-hours alerts (traffic-dependent).
- Time-of-day clustering identifies cron-triggered alerts vs user-traffic-triggered alerts.

### Conversational Output First
- **The conversation IS the primary output.** Print key findings as each step completes. The engineer should see results building up in real-time without opening any files.
- **Step 9 (Investigation Summary)** prints the synthesized findings directly in the conversation — this is what the engineer acts on.
- **The HTML report is a secondary artifact** — a detailed reference with full tables, code snippets, and links for follow-up.
- Print findings as you go, not just at the end. Each step should output its key result before moving to the next step.

### Report Design
- Sections are ordered for 2am triage: what's firing → what to do → is anything else broken → has this happened before → why is it broken → who knows about it.
- Tables use blank lines before and after for proper pandoc rendering.

### Code Change Search Strategy
- **Step 6a (alert definition changes)**: 30-day window, focused on the alert config file itself. Answers: "Did someone change the threshold?"
- **Step 6b (service code changes)**: 7-day window, focused on the service's application code. Answers: "Did a recent deployment cause this?" This is often more useful during an active page.
- Use the alert namespace to find the service code directory via Sourcegraph.
- If the metric emission code was identified in Step 5, also check changes to that file.

### Output
- Output goes to `output/incident-investigation/` with filenames including both the alert slug and a timestamp.
- Timestamped because the same alert may be investigated multiple times (each firing is a new investigation).
- No CSV export — this is a single-incident investigation, not a bulk analysis.
- No memory storage — investigations are ephemeral triage artifacts, not reference documents.

### Error Handling
- If `get-incident` fails (invalid ID), report the error and suggest checking the ID.
- If `list-alerts` returns empty, note "No alerts associated with this incident" and continue.
- If code search directory doesn't exist, skip with a note.
- If playbook fetch fails (access denied, network error), include the URL for manual access.
- If JIRA or Gmail queries fail, skip with a note.
