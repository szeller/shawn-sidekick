---
name: incident_analysis
description: Analyze PagerDuty incidents for a service over a time range, with alert-level detail and trend analysis
argument-hint: <service-id-or-name> [since] [until]
allowed-tools: Bash, Read
---

# Incident Analysis Agent

Analyze PagerDuty incident and alert data for a service to identify noise sources, recurring patterns, and trends over time.

## Overview

This agent takes a PagerDuty service (by ID or name) and a time range, then:

1. Resolves the service ID (if a name was given)
2. Fetches all incidents for the service in the time range
3. Fetches alerts for every incident (alert body contains root cause details)
4. Generates a summary report with pattern analysis and weekly trends
5. Exports raw data to CSV for historical record
6. Converts report to HTML and opens in browser

## Prerequisites

- PagerDuty API token configured in `.env` (`PAGERDUTY_API_TOKEN`)

## Usage Pattern

### Step 0: Setup

Parse arguments. The first argument is a service ID (e.g., `PABC123`) or a service name to search for. Optional second/third arguments are `since` and `until` dates. Defaults to last 60 days if not specified.

```bash
SERVICE_ARG=$1        # e.g., "PABC123" or "central-data-eng"
SINCE_ARG=$2          # e.g., "2026-01" or "2025-12-22" (optional, default: 60 days ago)
UNTIL_ARG=$3          # e.g., "2026-02" or "2026-02-19" (optional, default: today)

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
TMP_DIR=/tmp/incident_analysis_$$
mkdir -p $TMP_DIR
```

If `SINCE_ARG` is not provided, default to 60 days before today:
```bash
SINCE_DEFAULT=$(date -v-60d +%Y-%m-%d)
UNTIL_DEFAULT=$(date +%Y-%m-%d)
```

### Step 1: Resolve Service

Use inline Python to resolve the service. If the argument looks like a PagerDuty ID (starts with `P` and is alphanumeric), look it up directly. Otherwise, search by name.

```python
from sidekick.clients.pagerduty import PagerDutyClient
from sidekick.config import get_pagerduty_config

config = get_pagerduty_config()
client = PagerDutyClient(api_token=config['api_token'])

# If arg looks like a PD ID, verify it exists
services = client.list_services(query=SERVICE_ARG)
# Find exact or best match
# Print: service_id, service_name, team(s)
```

If multiple services match a name search, list them and ask the user to pick one.

### Step 2: Fetch All Incidents

```python
incidents = client.list_incidents(
    since=SINCE,
    until=UNTIL,
    service_ids=[SERVICE_ID]
)
```

Print the count and confirm before proceeding to fetch alerts (which requires one API call per incident).

### Step 3: Fetch Alerts for Every Incident

For each incident, fetch its alerts. This is the expensive step (one API call per incident).

```python
incident_alerts = []  # list of (incident, alerts) tuples
for inc in incidents:
    alerts = client.list_alerts(inc['id'])
    incident_alerts.append((inc, alerts))
```

Print progress every 100 incidents.

From each alert, extract:
- `summary` — the alert title/description
- `body.cef_details.description` — longer description
- `body.cef_details.details` — structured details (often contains root cause info)
- `body.contexts` — links to monitoring tools (internal monitoring tools, etc.)

**Important**: Handle `None` values defensively — `body`, `cef_details`, `details`, and `contexts` can all be `None` rather than empty dicts/lists.

### Step 4: Analyze Patterns

Compute the following analyses:

#### 4a. Overall Summary
Use `PagerDutyClient.summarize_incidents(incidents)` for the standard breakdown (by service, urgency, status, day-of-week, hour, top titles, avg resolution time).

#### 4b. Alert-Level Grouping
Group alerts by `summary` text. For each unique alert summary, compute:
- Total count
- Percentage of all alerts
- First and last occurrence date
- Weekly occurrence counts (for trend analysis)

#### 4c. Weekly Volume Trend
Compute total incidents per ISO week to show whether volume is increasing, decreasing, or stable.

#### 4d. Trend Classification
For each of the top alert summaries, classify the trend. **Important**: Use the alert's first-seen week as the baseline, not the start of the analysis window. This prevents alerts that emerged mid-period from being misclassified.

- **Fixed/Resolved**: No occurrences in the most recent 2 weeks
- **Getting Worse**: Last 2 weeks average > first 2 weeks *of the alert's existence* average, with at least 2x increase or 3+ more per week
- **Getting Better**: Opposite of getting worse (last 2 weeks lower than first 2 weeks of existence)
- **Chronic/Stable**: Roughly consistent throughout the period (present in most weeks, no strong trend)
- **Burst**: 80%+ of occurrences concentrated in a 1-2 week window

#### 4e. Double-Page Detection
Identify alerts that likely represent the same underlying issue firing through multiple monitors. **Cap at 5 candidates max** — only the most meaningful pairs.

**High-confidence pairs** (always include):
- Alerts that share the same base alert name but fire across different namespaces/services (e.g., `store: AutoAlert-TooManyUnexpectedExits` and `revenue_data_platform: AutoAlert-TooManyUnexpectedExits`)
- Alert summaries that are substrings of each other

**Keyword-based pairs** (filter aggressively):
- Tokenize summaries, find pairs sharing distinctive keywords (not common words like "Alert", "failed", "AutoAlert")
- Require temporal overlap >= 40% on **both** sides of the pair (not just the smaller set)
- **Filter out** pairs where one alert is >10x the volume of the other (unless they share the same base alert name) — high-volume alerts trivially overlap with everything

#### 4f. Alert Body Analysis
For each of the top 10 alert summaries, show the body/description from the first occurrence. This provides root cause context without having to drill into each incident individually.

### Step 5: Generate Markdown Report

The report is structured for a director audience: scannable summary up front, detail only for actionable items.

**Important markdown formatting**: Always leave a **blank line** before and after every markdown table. Pandoc will not render tables that immediately follow inline text.

```markdown
---
prompt: "Incident analysis"
client: incident-analysis
command: incident-analysis
created: YYYY-MM-DD HH:MM:SS
updated: YYYY-MM-DD HH:MM:SS
---

# Incident Analysis: {Service Name}

**Service**: {service_name} ({service_id})
**Team**: {team_name}
**Period**: {since} to {until}
**Generated**: {date}

---

## Executive Summary

- **Total incidents**: N over N weeks (~N/week average)
- **Trend**: {Improving/Worsening/Stable} — {one sentence}
- **Top noise source**: {alert summary} (N occurrences, N% of total)
- **Active issues**: N unique alert types still firing in the last 2 weeks
- **Avg resolution time**: N hours

---

## Overall Weekly Volume

| Week | Count | Trend |
|------|-------|-------|
| 2025-W52 | 132 | ############# |
| 2026-W01 | 197 | ################### |
| ... | ... | ... |

---

## Trend Summary

All top alert types at a glance. Detail sections follow only for actionable items.

| # | Alert | Total | % | Trend | Last 2 Weeks |
|---|-------|-------|---|-------|-------------|
| 1 | {summary} | N | N% | Getting Worse | N/week |
| 2 | {summary} | N | Chronic | N/week |
| 3 | {summary} | N | Fixed | 0 |
| ... | ... | ... | ... | ... | ... |

---

## Actionable Alerts

Detail sections ONLY for alerts classified as **Getting Worse**, **Chronic**, or **Burst** (still active in last 2 weeks). Fixed and Getting Better alerts do not get their own sections — they appear only in the Trend Summary table above.

### 1. {Alert Summary} (Nx, N%) — Getting Worse

**First seen**: YYYY-MM-DD | **Last seen**: YYYY-MM-DD

**Weekly breakdown**:

| Week | Count |
|------|-------|
| ... | ... |

**Alert body** (from first occurrence):
> {description and details from alert body}

**Links**: {monitoring tool URLs from alert contexts}

---

### 2. {Next Actionable Alert} — Chronic

...

---

## Double-Page Candidates

These alerts may represent the same underlying issue firing through multiple monitors (max 5):

- **{shared alert name or keyword}**: "{alert A}" (Nx) + "{alert B}" (Nx) = {combined}x — N% mutual overlap
  Consider suppressing or deduplicating.

---

## Recommendations

1. **Immediate**: {Getting Worse alerts — one bullet each with specific detail}
2. **Noise reduction**: {double-page candidates to deduplicate, active bursts to investigate}
3. **Chronic toil**: {Chronic alerts needing root cause work or threshold tuning}
4. **Resolved**: N alert types resolved in this period: {comma-separated list of names}.
```

Save the report to `$TMP_DIR/report.md`.

### Step 6: Export CSV

Export all incident + alert data to CSV with these columns:

```
incident_number, incident_id, incident_title, incident_status, incident_urgency,
incident_created_at, incident_resolved_at, service, incident_url,
alert_id, alert_summary, alert_severity, alert_status, alert_created_at,
alert_description, alert_details, alert_link
```

**Important**: Handle `None` values defensively when extracting `body.cef_details.description`, `body.cef_details.details`, and `body.contexts`. Any of these can be `None`.

For `alert_details`: if `body.cef_details.details` has a `body` key, use that. Otherwise, join all key=value pairs with semicolons.

For `alert_link`: extract `href` from any context with `type == "link"` and join with semicolons.

Save to `output/incident-analysis/{service_name}-incidents-{since}-to-{until}.csv`. Sanitize the service name for filesystem use (lowercase, replace spaces with hyphens). Both CSV and HTML go in `output/incident-analysis/`.

### Step 7: Convert to HTML and Open

```bash
mkdir -p output/incident-analysis

python3 -m sidekick.clients.markdown_html $TMP_DIR/report.md \
  output/incident-analysis/{service-name-slug}-{since}-to-{until}.html \
  --title "Incident Analysis: {Service Name}" --open
```

Use the same sanitized service name as the CSV (lowercase, hyphens). Both the CSV and HTML end up in `output/` for easy retrieval.

### Step 8: Clean Up

```bash
rm -rf $TMP_DIR
```

## Design Notes

### Service Resolution
- PagerDuty service IDs start with `P` followed by alphanumeric characters (e.g., `PABC123`).
- If the argument doesn't look like an ID, search by name using `list_services(query=...)`.
- If multiple matches, present them and ask the user to clarify.

### API Volume
- Fetching alerts requires one API call per incident. For a service with 800+ incidents over 60 days, this means 800+ API calls.
- Print progress every 100 incidents so the user knows it's working.
- The PagerDuty client uses a 60-second timeout per request to handle pagination.

### Trend Classification Logic
- **Fixed**: Zero occurrences in the last 14 days of the analysis window.
- **Getting Worse**: Average weekly count in last 2 complete weeks > average in first 2 weeks *of the alert's existence* (not the analysis window start), with at least 2x increase or 3+ more per week. This prevents mid-period alerts from being misclassified.
- **Getting Better**: Opposite of getting worse (last 2 weeks lower than first 2 weeks of existence).
- **Burst**: 80%+ of occurrences concentrated in a 2-week window.
- **Chronic**: Everything else (relatively stable week over week).

### Double-Page Detection
- **High-confidence**: Same base alert name across different namespaces (always include).
- **Keyword-based**: Tokenize summaries, find pairs sharing distinctive keywords. Require >= 40% temporal overlap on **both** sides of the pair. Filter out pairs where one alert is >10x the volume of the other (unless they share the same base alert name).
- **Cap at 5 candidates max** — only the most meaningful pairs.

### Report Structure
- The report is optimized for a director audience: scannable summary up front, detail only for actionable items.
- **Trend Summary table** appears right after Executive Summary and Weekly Volume — this is the overview.
- **Detail sections** are only generated for Getting Worse, Chronic, and active Burst alerts. Fixed and Getting Better alerts appear only in the Trend Summary table.
- **Recommendations** group by urgency: Immediate (worsening), Noise Reduction (double-pages/bursts), Chronic Toil, and Resolved (one-liner listing fixed alert names).
- **Tables must have blank lines** before and after them in the markdown. Pandoc will not render tables that immediately follow inline text.

### CSV Export
- One row per alert. If an incident has multiple alerts, it appears multiple times (once per alert).
- If an incident has no alerts, it still appears once with empty alert columns.
- The CSV is saved to `output/incident-analysis/` alongside the HTML report for historical tracking.

### Re-runnability
- The agent is stateless — it reads PagerDuty data fresh each time.
- Running it again for the same parameters produces an updated report.
- CSV files in `output/` accumulate as a historical record (filename includes date range).

### Error Handling
- If a single alert fetch fails, log the error and continue with remaining incidents.
- If the service is not found, list available services matching the query.
- If no incidents are found, report that and exit gracefully.
