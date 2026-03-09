# MMR (Monthly Metrics Review) Agent

Automate the review of Monthly Metrics Review documents in three phases: initial investigation, deep investigation, then execution after human review.

## Overview

The team generates an MMR Confluence doc each month with quality metrics across operational health, service SLAs, KTLO, and experimentation. Each metric has a status: green (OK), yellow (warning), or red (critical). This agent automates the review of non-green metrics and the creation of follow-up action items.

The user will provide an MMR doc link or page ID. See CLAUDE.local.md for the Confluence space and team context.

## Three-Phase Workflow

### Phase 1: Initial Investigation (AI-driven, outputs local file)

**Trigger**: User provides an MMR doc link or page ID.

**Steps**:
1. Fetch the MMR page and parse all sections
2. Identify every non-green metric with values, thresholds, and trends
3. Read all existing inline comments on the page
4. Check the MMR AIs section for existing JIRA tickets (via embedded JQL)
5. **Read the MMR mixin code** to get exact V2 metric namespaces, thresholds, and filters (see "MMR Mixin Code" below)
6. **Launch parallel investigation agents** (see "Investigation Parallelism")
7. Cluster non-green metrics into related groups and assign severity tiers (P1/P2/P3)
8. For each cluster, synthesize findings and propose an AI or note if one already exists
9. Write results to `memory/mmr/{month}-{year}-{team}-investigation.md`

**Severity Tiers**:
| Tier | Description | Criteria |
|------|-------------|----------|
| P1 - Active Incident | Acute regression, NOT recovered | Current V2 >> MMR average, actively degraded |
| P2 - Chronic/Worsening | Persistently red 2+ months or getting worse | Month-over-month trend worsening |
| P3 - Minor/Threshold Sensitivity | Low severity, expected to self-resolve | Threshold noise, first-month data, low volume |

### Phase 2: Deep Investigation (AI-driven, after human review of Phase 1)

**Trigger**: User asks to investigate further / reduce engineer follow-up.

This phase digs into code paths, lock contention, deadline enforcement, git history, and runtime config changes. It produces actionable findings with specific file:line references so engineers can start work immediately.

**Deep investigation types** (launch as parallel background agents):

1. **Code path tracing** — For P1/P2 latency regressions, trace the full call chain from RPC entry to downstream calls. Identify: sequential vs parallel patterns, N+1 queries, lock acquisition, retry/timeout configs. Use Sourcegraph + local file reads.

2. **Lock/contention analysis** — If a lock mechanism is found in the code path, find ALL callers of that lock. Categorize as: API handlers, background processors, cron jobs, admin tools. Assess which can hold the lock for extended periods.

3. **Deadline/timeout enforcement** — Trace the timeout chain from external client to handler. Check for gaps: client-only deadlines without server enforcement, advisory-only context timeouts, handlers that never check deadlines.

4. **Git log analysis** — Check for code changes in the regression window across all relevant paths. If NO code changes found, the trigger is likely a runtime config change (feature flag, percentage rollout, cron schedule).

5. **Runtime config investigation** — Search for feature flags / gates that were recently ramped. Flags using `realtime_percents` or similar can be changed via admin UI without git commits.

6. **Error log analysis** — Pull actual error logs and stack traces via Loki or equivalent. When tool access is blocked, provide recommended queries for engineers.

7. **Error type breakdown** — Query V2 for error_type tag to distinguish failure modes. Error type transitions over time reveal whether fixes addressed symptoms or root causes.

**Update the investigation file** with all deep findings, including:
- Full call chains with file:line references
- Ranked bottleneck candidates
- Specific remediation suggestions
- Recommended Loki/V2 queries for engineers

### Phase 3: Execute (AI-driven, after human approval)

**Trigger**: User says to execute the approved AIs from the research file.

**Steps**:
1. Read the research file from `memory/mmr/`
2. For each metric with `Proposed AI: APPROVED`:
   a. Create a JIRA ticket with the specified title, description, project, and label `MMR-AI`
   b. Create an inline comment on the MMR Confluence page anchored to that metric's "Comments" marker
   c. The inline comment should be concise: one sentence summarizing the issue + a link to the JIRA ticket
3. Update the research file with created ticket IDs and comment IDs

**Inline comment format** (keep it short, matching the style of existing human comments):
```
{Brief description of issue}. MMR AI: {PROJ-123}
```

## MMR Mixin Code

**Critical first step**: Before querying V2 metrics, read the MMR mixin Python files to get exact metric namespaces, thresholds, and filter configurations. These define what the MMR report actually measures.

**Location**: `dropbox/mmr/reports/` — search for the team's mixin files under the relevant subdirectory.

**What to extract from mixin files**:
- `availability_metric` / `latency_metric` — exact V2 namespace
- Filter configurations (e.g., `storefront_type`, `rpc_service`, `method`)
- Method names — may differ from code names (e.g., V2 tags may use CamelCase while Python uses snake_case)
- SLA thresholds — yellow and red boundaries
- `count_condition` — minimum request count for metric to be meaningful
- Mixin base class (e.g., `EnvoyMixin` vs custom V2 queries) — determines how to query V2

**Important**: Always use `get-v2-tag-values` to discover actual tag values before querying. Method names in V2 often don't match the Python function names.

## Automated Investigation

### V2 Metrics (MCP tools)

Use `mcp__dropbox-devtools__query-v2` and related tools to query current metric values. For each non-green metric:

1. **Find the right metric**: Read the mixin file first (see above). If not available, use `search-v2-metric-names`.

2. **Discover tags**: Use `get-v2-tag-names` and `get-v2-tag-values` to understand available dimensions (method, status, error_type, storefront_type, etc.)

3. **Query current state vs MMR period**: Run queries at two time ranges:
   - **30d** — covers the full MMR month plus recent days, reveals trend
   - **7d** — shows current state clearly

4. **Standard queries by metric type**:

   **For availability metrics**:
   ```
   # Error rate breakdown
   {namespace}[status]{method="METHOD_NAME", ...filters} | per_second
   # Error type breakdown (if errors present)
   {namespace}[error_type]{method="METHOD_NAME", status="server-error"} | per_second
   ```

   **For latency metrics**:
   ```
   # P95 latency trend
   {namespace}{method="METHOD_NAME", _p="p95", ...filters} | histogram_resample 6h
   ```

5. **Compare MMR monthly average vs current**: Flag discrepancies:
   - **Current >> MMR average**: Issue is active, possibly worse than report suggests
   - **Current << MMR average**: Transient spike that resolved
   - **Current ~ MMR average**: Stable at reported level

6. **Convert timestamps**: V2 returns nanosecond-epoch timestamps.

### JIRA Investigation

Use the sidekick JIRA client (`python -m sidekick.clients.jira` from `~/shawn-sidekick/`):

1. **Find existing MMR-AI tickets** (adjust project to match the team):
   ```bash
   python -m sidekick.clients.jira query 'labels in (GMMR-AI, MMR-AI) AND project in (PROJECT_KEY) AND (resolution = EMPTY OR resolution = Unresolved)'
   ```

2. **Search for related tickets** (by keyword):
   ```bash
   python -m sidekick.clients.jira query 'project = PROJECT_KEY AND text ~ "KEYWORD" AND created >= -90d'
   ```

3. **Get ticket details**:
   ```bash
   python -m sidekick.clients.jira get-issue PROJ-123
   ```

Determine the correct JIRA project key from the MMR page's embedded JQL or the existing AIs section.

### PagerDuty / Oncall Health

For oncall-related non-greens (sleep-hour interruptions, alert fatigue, etc.):

1. **Check for PagerDuty client**: Look in `~/shawn-sidekick/sidekick/clients/` for a pagerduty client
2. **Search alert configs in codebase**: Alert configs are in `configs/services/{service}/alerts/*.pyst`
3. **Look for**: threshold values, PagerDuty routing (PAGE_24_7 vs PAGE_SUPPORT_HOURS), min_num_data_points, alert window durations, specific lines to change for routing adjustments

### Code Search (Sourcegraph)

```bash
bzl tool //dropbox/devtools/sourcegraph:sourcegraph_cli -- search -stream 'r:github.com/dropbox-internal/server "SEARCH_TERM" lang:python count:30'
```

### Loki Logs

Use `mcp__dropbox-devtools__loki-query-logs`. Note: access is limited — most production services (including `store`) return 403. Check available services first with `mcp__dropbox-devtools__loki-list-services`. When blocked, provide recommended LogCLI/Grafana queries for engineers.

### Investigation Parallelism

**Phase 1 agents** (launch simultaneously):
- **Agent 1**: JIRA queries (existing tickets, ticket details, SEV AIs)
- **Agent 2**: V2 metric queries (error rates, latency trends, error type breakdowns)
- **Agent 3**: PagerDuty/oncall data + alert config search
- **Main thread**: Read MMR mixin code, Sourcegraph code search

**Phase 2 agents** (launch simultaneously per investigation type):
- **Agent per P1/P2 issue**: Code path tracing (full call chain, file:line refs)
- **Lock contention agent**: Find all callers of shared lock mechanisms
- **Deadline enforcement agent**: Trace timeout chain across all layers
- **Loki agent**: Pull error logs and stack traces
- **Git log agent** (launch last — git is slow): Check for code changes in regression window

## Output File Structure

```markdown
# MMR Investigation: {Month} {Year} - {Team}
Generated: {timestamp}
Source: {confluence_url}

## Executive Summary
{2-3 sentence overview, dominant issues, severity distribution}

### Severity Tiers
{P1/P2/P3 table with counts}

## Investigation N: {Cluster Name} ({Priority})

### Direct Metrics
{Table: Metric | Dec | Jan | Feb | Threshold | Status}

### Automated Investigation Findings
- **V2 Metrics**: {current values, trend, pattern, error type breakdown}
- **JIRA Status**: {existing tickets, assignees, status}
- **Code Path Analysis**: {full call chain with file:line references, bottleneck candidates}
- **Lock/Contention Analysis**: {all lock callers, risk assessment}
- **Deadline Enforcement**: {timeout chain analysis, broken enforcement}
- **Git History**: {relevant commits or "zero changes — likely runtime config"}
- **PagerDuty**: {alert counts, sleep-hour impact}
- **Alert Config**: {threshold settings, routing, specific lines to change}

### Key Finding
{1-2 sentence synthesis}

### Proposed AI
- **Title**: [MMR-AI] {Dimension}: {specific issue with data}
- **Description**: {Detailed description including file:line references, remediation suggestions}
- **Existing Ticket**: {ticket key or "None"}
- **Proposed AI**: {YES | NO - already covered | ENRICH EXISTING}

## Summary of Proposed Actions
### New AIs to Create
{Table: # | Title | Priority | Rationale | Key Code References}
### Existing Tickets Needing Action
{Table: Ticket | Action Needed}
### Critical Gaps
{Numbered list of unaddressed issues}
### Cross-Cutting Themes
{Patterns that span multiple investigations}

## V2 Metric Namespace Reference ({Team})
{Table of metric namespaces and filters}

## Data Sources Used
{Table: Source | Coverage | Findings}

### Limitations
{Known gaps in the investigation}
```

## Human Review (interactive, between phases)

After Phase 1 or Phase 2, the human reviews and can:
- Ask for deeper investigation ("Are there any steps you could take to investigate further?")
- Remove proposed AIs that aren't needed
- Adjust titles, descriptions, or priorities
- Add context the AI couldn't determine
- Mark proposed AIs as approved (`Proposed AI: APPROVED`)

## MMR Document Structure

### Sections (H1 headers)
1. **Legend** - Status definitions
2. **Summary** - Top-level dashboard table
3. **MMR AIs** - Open action items (JIRA, labels: `MMR-AI` or `GMMR-AI`)
4. **SEVs (Outages)** - SEV volume, SEV AIs
5. **Service-specific sections** - Per-endpoint availability and latency SLAs
6. **Store Envoy Services** - Envoy route health
7. **Quarantined Tests** - Flaky/broken test counts
8. **CX Escalations** - Customer experience issues
9. **Open Bugs** - P0/P1/P2 counts
10. **Toil / Alerts** - PagerDuty interruptions, oncall health
11. **Experimentation** - Stormcrow feature hygiene
12. **Alert Health** - Alert fatigue percentage

### Status Indicators (Confluence Emojis)
- `green_heart` (OK) - Meeting threshold
- `yellow_heart` (Warning) - Violated threshold
- `broken_heart` (Critical) - Significantly violated
- `white_heart` (None) - No threshold defined

### Key HTML Patterns
- **Expand macros**: `<ac:parameter ac:name="title">DIMENSION_NAME</ac:parameter>`
- **Inline comment markers**: `<ac:inline-comment-marker ac:ref="UUID">Comments</ac:inline-comment-marker>`
- **Summary table**: Inside `<ac:structured-macro ac:name="excerpt"><ac:parameter ac:name="name">summary</ac:parameter>`

### Table Row Structure
| Quality Dimension (with expand for thresholds) | Dec | Jan | Feb (Current) | Delta | Review |

## Technical Details

### Fetching the Page
```python
from sidekick.config import get_atlassian_config
from sidekick.clients.confluence import ConfluenceClient

config = get_atlassian_config()
client = ConfluenceClient(base_url=config['url'], email=config['email'], api_token=config['api_token'])

page = client.get_page('PAGE_ID')
content = page['body']['storage']['value']

# Resolve short links via redirect
import urllib.request, base64, re
auth = base64.b64encode(f'{config["email"]}:{config["api_token"]}'.encode()).decode()
req = urllib.request.Request(link, headers={'Authorization': f'Basic {auth}'})
resp = urllib.request.urlopen(req)
page_id = re.search(r'/pages/(\d+)', resp.url).group(1)
```

### Reading Inline Comments
```python
result = client._request('GET', f'/wiki/api/v2/pages/{page_id}/inline-comments',
    params={'body-format': 'storage'})

for comment in result.get('results', []):
    marker_ref = comment['properties']['inlineMarkerRef']
    body_html = comment['body']['storage']['value']
    status = comment['resolutionStatus']
```

### Creating Inline Comments
```python
payload = {
    "pageId": page_id,
    "body": {
        "representation": "storage",
        "value": "<p>Brief issue description. MMR AI: PROJ-123</p>"
    },
    "inlineCommentProperties": {
        "textSelection": "Comments",
        "textSelectionMatchCount": N,
        "textSelectionMatchIndex": idx
    }
}
result = client._request('POST', '/wiki/api/v2/inline-comments', json_data=payload)
```

## Key Lessons Learned

### MMR Monthly Averages vs Current Values
The MMR reports **monthly aggregated values** (e.g., a single p95 over the full month). This can mask severity — healthy early-month days pull down the average even if the issue is currently catastrophic. **Always compare MMR values to current V2 values.**

### V2 Method Name Mismatches
V2 metric tags often use different naming than source code. Always use `get-v2-tag-values` to discover actual tag values before querying — don't assume the code's function names match.

### Code Changes vs Runtime Config Changes
When git log shows zero relevant commits in the regression window, the trigger is almost certainly a **runtime config change** (feature flag percentage rollout via admin UI, not tracked in git). Look for recently-created feature gates with percentage-based rollouts in the service's config directory.

### Timeout/Deadline Enforcement Gaps
Timeouts may be configured at multiple layers (proxy, RPC framework, handler) but NOT enforced end-to-end. Common gaps:
- Client-only deadlines with no server enforcement
- Advisory-only context timeouts that don't cancel running code
- Handlers that never check if their deadline has passed
- Proxy terminating the client connection but leaving the server handler running

When investigating latency that exceeds configured timeouts, trace the full timeout chain to find where enforcement breaks down.

### Lock Contention as Root Cause
Database locks (e.g., `SELECT ... FOR UPDATE`) may have NO application-level timeout. Background processors holding these locks during external calls can cause API handler latency to explode. When investigating lock-related latency:
- Find ALL callers of the lock (API handlers, background processors, cron jobs, admin tools)
- Assess which callers can hold the lock for extended periods
- Check if the lock has an application-level timeout or relies only on DB-level timeouts

### N+1 Query Patterns
Functions named "batch" may actually be sequential per-item. Always read the implementation, not just the name. Look for: loops with individual RPC calls, per-item coroutines run synchronously, functions that call `run_coroutine()` inside a `for` loop.

### Sequential vs Parallel Operations
Many handlers execute downstream calls sequentially when they could be parallelized. For each call chain, note which calls are independent and could use async gather/parallel execution. This is a common remediation suggestion.

### Tool Access Limitations
- **Loki**: MCP tool returns 403 for most production services. Provide LogCLI/Grafana queries for engineers to run.
- **PagerDuty**: Use sidekick pagerduty client if available, otherwise search alert configs in codebase.
- **V2 500 errors**: Broad regex patterns in V2 queries can cause 500 errors. Use specific metric names.
- **Sourcegraph**: Use `bzl tool //dropbox/devtools/sourcegraph:sourcegraph_cli` (not bare `src`).

## Reference: Previous Investigations

Investigation files from past MMR reviews are stored in `memory/mmr/` and serve as reference for patterns, V2 namespaces, and investigation techniques:
- `memory/mmr/feb-2026-billing-investigation.md` — Billing team investigation
- `memory/mmr/feb-2026-gtm-investigation.md` — GTM team investigation (includes V2 namespace reference table for GTM services)
