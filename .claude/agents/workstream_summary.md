---
name: workstream_summary
description: Collect initiative data from a JIRA workstream hierarchy and generate a summary report
argument-hint: ISSUE-KEY
allowed-tools: Bash, Read
---

# Workstream Summary Agent

Generate a summary report for a JIRA workstream by collecting initiative details from its hierarchy: master workstream → sub-workstreams (linked issues) → initiatives (children).

## Overview

This agent takes a master workstream JIRA key and:

1. Fetches the master workstream and its linked sub-workstreams
2. For each sub-workstream, fetches child initiatives
3. Extracts description and bi-weekly summary (`customfield_13327`) from each initiative
4. Generates a Markdown report grouped by sub-workstream
5. Converts to HTML and opens in Chrome

## Prerequisites

- Atlassian credentials configured in `.env`

## Usage Pattern

### Step 0: Setup

Determine the target issue. The argument is the master workstream JIRA key (e.g., `DBX-1697`).

```bash
MASTER_KEY=$1  # e.g., DBX-1697
TIMESTAMP=$(date +%Y-%m-%d)
TMP_DIR=/tmp/workstream_summary_$$
mkdir -p $TMP_DIR
```

### Step 1: Fetch Master Workstream and Sub-workstreams

Use inline Python to fetch the master issue and extract its linked sub-workstreams:

```python
from sidekick.clients.jira import JiraClient
from sidekick.config import get_atlassian_config

config = get_atlassian_config()
client = JiraClient(base_url=config['url'], email=config['email'], api_token=config['api_token'])

issue = client.get_issue('MASTER_KEY')
master_summary = issue['fields']['summary']

# Extract linked sub-workstreams (outward links of type "Sub-workstream")
links = issue.get('fields', {}).get('issuelinks', [])
sub_workstreams = []
for link in links:
    outward = link.get('outwardIssue', {})
    if outward:
        sub_workstreams.append({
            'key': outward.get('key'),
            'summary': outward.get('fields', {}).get('summary', '')
        })
```

Sort sub-workstreams by the T-number in their summary (e.g., T3.1.1 before T3.1.2).

### Step 2: Fetch Initiatives for Each Sub-workstream

For each sub-workstream, query for child issues with these fields:
- `key`, `summary`, `status`, `description`, `customfield_13327` (bi-weekly summary), `customfield_10069` (health/color)

```python
result = client.query_issues(
    f'parent = {sub_key}',
    fields=['key', 'summary', 'status', 'description', 'customfield_13327', 'customfield_10069']
)
```

For each initiative, extract:
- **Key and summary** (linked to `{ATLASSIAN_URL}/browse/KEY`)
- **Status** from the status field
- **Health** from `customfield_10069` (value field)
- **Description** — if in ADF format (dict with `content`), extract plain text recursively
- **Bi-weekly summary** from `customfield_13327` — this is a plain text string

### Step 3: Generate Markdown Report

Compile into a Markdown report with this structure:

```markdown
# {Master Summary} — Initiative Summary

**Master Workstream**: [KEY]({ATLASSIAN_URL}/browse/KEY) — {summary}
**Generated**: {date}
**Source**: Bi-weekly summaries + initiative descriptions

---

## {Sub-workstream T-number} — {Short Title}

**[SUB-KEY](link)**: {full sub-workstream summary}

### [INIT-KEY](link): {initiative summary}

| | |
|---|---|
| **Status** | {status} |
| **Health** | {health, with ⚠️ for At Risk/Delayed} |
| **Target** | {if known} |

**Objective**: {description text}

**Bi-weekly ({date})**: {bi-weekly summary text, or "No update — initiative has not started."}

**Key risks**: {if status is At Risk or Delayed, extract risk details from bi-weekly}

---

## Risks & Attention Items

| Initiative | Risk | Impact |
|---|---|---|
| [KEY](link) {short name} | {risk description} | {impact} |
```

**Formatting rules**:
- Every JIRA key MUST be a link: `[KEY]({ATLASSIAN_URL}/browse/KEY)`
- Use ⚠️ emoji only for At Risk or Delayed health indicators
- Include "Key risks" subsection only for initiatives that are At Risk, Delayed, or blocked
- Group initiatives under their parent sub-workstream
- Sort sub-workstreams by T-number
- Include a summary Risks table at the end with all at-risk/delayed/blocked items
- If a sub-workstream has no children, note "No child initiatives currently tracked in JIRA."

Save the report to `$TMP_DIR/report.md`.

### Step 4: Convert to HTML and Open

```bash
python3 -m sidekick.clients.markdown_html $TMP_DIR/report.md /tmp/workstream-summary.html \
  --title "{Master Summary} — Initiative Summary" --open
```

### Step 5: Clean Up

```bash
rm -rf $TMP_DIR
```

## Design Notes

### Data Fields

- **`customfield_13327`** is the bi-weekly summary field. It's a plain text string, typically prefixed with "AI (MM/DD):".
- **`customfield_10069`** is the health/color indicator. It's an object with a `value` field (e.g., "Grey", "Yellow", "Red", "Green").
- **Description** may be in Atlassian Document Format (ADF) — a nested JSON structure. Extract text by recursively walking `content` arrays and collecting nodes with `type: "text"`.

### Content Depth

The goal is to produce a summary rich enough to brief someone one level up. Each initiative should include:
- What it is (from description)
- Where it stands (from bi-weekly)
- What's at risk and why (synthesized from both)

Don't just copy fields verbatim — synthesize a coherent narrative per initiative.

### Links

Every JIRA key must be a clickable link. The base URL is `{ATLASSIAN_URL}/browse/` (get ATLASSIAN_URL from `.env`).

### Re-runnability

The agent is stateless — it reads JIRA data fresh each time. Running it again produces an updated report. The HTML is written to `/tmp` (ephemeral). The markdown can optionally be saved to memory if the user requests it.
