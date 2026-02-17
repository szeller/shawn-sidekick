# Microsoft To Do Skill

Manage tasks in Microsoft To Do via the Microsoft Graph API.

## Quick Setup

### 1. Register an Azure AD Application

1. Go to [Azure Portal - App Registrations](https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade)
2. Click **New registration**
3. Name: `chase-sidekick` (or anything you like)
4. Supported account types: **Accounts in any organizational directory and personal Microsoft accounts**
5. Click **Register**

### 2. Configure the Application

1. Go to **Authentication** > **Add a platform** > **Mobile and desktop applications**
2. Add redirect URI: `http://localhost`
3. Click **Configure**

4. Go to **API permissions** > **Add a permission** > **Microsoft Graph** > **Delegated permissions**
5. Search for and add: `Tasks.ReadWrite`
6. Click **Add permissions**

5. Go to **Certificates & secrets** > **New client secret**
6. Add a description and choose an expiry period
7. Copy the secret **Value** (not the ID)

### 3. Get Your Refresh Token

```bash
python3 tools/get_microsoft_refresh_token.py
```

This walks you through the OAuth2 authorization flow and gives you the refresh token.

### 4. Add to .env

```
MICROSOFT_CLIENT_ID=your-application-client-id
MICROSOFT_CLIENT_SECRET=your-client-secret-value
MICROSOFT_REFRESH_TOKEN=your-refresh-token
```

### 5. Test

```bash
python3 -m sidekick.clients.mstodo lists
python3 -m sidekick.clients.mstodo tasks
```

## Command Reference

### List Task Lists

```bash
python3 -m sidekick.clients.mstodo lists
```

Output:
```
Task Lists (3):
  AAk...abc: Tasks (default)
  BBl...def: Shopping
  CCm...ghi: Work Projects
```

### List Tasks

```bash
# Incomplete tasks from default list
python3 -m sidekick.clients.mstodo tasks

# Completed tasks
python3 -m sidekick.clients.mstodo tasks --status completed

# All tasks from a specific list
python3 -m sidekick.clients.mstodo tasks --list LIST_ID --status all --limit 20
```

Output:
```
Found 5 incomplete tasks (showing 50):
AAk...xyz: Review quarterly goals [notStarted] [high] [due: 2026-02-20]
BBl...uvw: Schedule team offsite [inProgress]
CCm...rst: Order new monitors [notStarted] [due: 2026-02-25]
```

### Get Task Details

```bash
python3 -m sidekick.clients.mstodo get TASK_ID
```

Output:
```
Task ID: AAk...xyz
Title: Review quarterly goals
  Status: notStarted
  Importance: high
  Due: 2026-02-20
  Created: 2026-02-10T14:30:00Z
  Modified: 2026-02-12T09:15:00Z
  Body: Review Q1 goals doc and prepare talking points
```

### Create Task

```bash
# Simple task
python3 -m sidekick.clients.mstodo create "Review budget proposal"

# Task with details
python3 -m sidekick.clients.mstodo create "Prepare Q1 report" \
  --due 2026-03-01 \
  --importance high \
  --body "Include metrics from all five teams"
```

### Update Task

```bash
python3 -m sidekick.clients.mstodo update TASK_ID --title "Updated title" --importance low
```

### Complete Task

```bash
python3 -m sidekick.clients.mstodo complete TASK_ID
```

### Delete Task

```bash
python3 -m sidekick.clients.mstodo delete TASK_ID
```

## Python Usage

```python
from sidekick.clients.mstodo import MicrosoftTodoClient

client = MicrosoftTodoClient(
    client_id="your-client-id",
    client_secret="your-client-secret",
    refresh_token="your-refresh-token"
)

# List task lists
lists = client.list_task_lists()

# List incomplete tasks from default list
tasks = client.list_tasks()

# Create a task
task = client.create_task(
    title="Review budget",
    due_date="2026-03-01",
    importance="high",
    body="Check Q1 figures"
)

# Complete a task
client.complete_task(task["id"])

# Delete a task
client.delete_task(task["id"])
```

## Troubleshooting

### "Failed to refresh access token"
- Verify your MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET, and MICROSOFT_REFRESH_TOKEN in .env
- The client secret may have expired - create a new one in Azure Portal
- Re-run `python3 tools/get_microsoft_refresh_token.py` to get a new refresh token

### "Resource not found"
- Check that the task/list ID is correct
- Use `python3 -m sidekick.clients.mstodo lists` to see valid list IDs

### "Client error 403"
- Ensure `Tasks.ReadWrite` permission is granted in Azure Portal
- You may need admin consent if using a work account
