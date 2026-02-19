---
name: pagerduty
description: Query PagerDuty incidents and analyze on-call patterns
argument-hint: <operation> [args]
allowed-tools: Bash, Read
---

# PagerDuty Skill

Query PagerDuty incidents, alerts, and services. Analyze incident patterns.

When invoked, use the PagerDuty client to handle the request: $ARGUMENTS

## Available Commands

### List Services
```bash
python3 -m sidekick.clients.pagerduty list-services [query]
```

### List Incidents
```bash
python3 -m sidekick.clients.pagerduty list-incidents <since> [until] [--service SVC_ID] [--team TEAM_ID]
```

### Get Incident Details
```bash
python3 -m sidekick.clients.pagerduty get-incident INCIDENT_ID
```

### List Alerts for Incident
```bash
python3 -m sidekick.clients.pagerduty list-alerts INCIDENT_ID
```

### Incident Summary (Pattern Analysis)
```bash
python3 -m sidekick.clients.pagerduty incident-summary <since> [until] [--service SVC_ID] [--team TEAM_ID]
```

## Date Formats

- `2026-01` - Full month (January 2026)
- `2026-01-15` - Specific date
- `2026-01-15T10:00:00Z` - Full ISO 8601

## Example Usage

When the user asks to:
- "How many incidents did we have last month?" - Use incident-summary with month shorthand
- "What services page us the most?" - Use incident-summary, look at by_service breakdown
- "Show me details on incident X" - Use get-incident + list-alerts
- "What are the root causes for service Y pages?" - List incidents filtered by service, then list-alerts for each
- "Find all services" - Use list-services

## Workflow: Investigating Incident Patterns

1. Use `list-services` to find service IDs
2. Use `incident-summary` for the time period to see patterns
3. Use `list-incidents` to get specific incidents
4. Use `get-incident` + `list-alerts` to drill into root causes
