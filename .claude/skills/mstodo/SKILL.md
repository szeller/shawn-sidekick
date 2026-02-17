---
name: mstodo
description: Manage Microsoft To Do tasks
argument-hint: <operation> [args]
allowed-tools: Bash, Read
---

# Microsoft To Do Skill

Manage tasks in Microsoft To Do using the command line.

When invoked, use the Microsoft To Do client to handle the request: $ARGUMENTS

## Available Commands

### List Task Lists
```bash
python3 -m sidekick.clients.mstodo lists
```

### List Tasks
```bash
python3 -m sidekick.clients.mstodo tasks [--list LIST_ID] [--status notCompleted|completed|all] [--limit N]
```
Default: shows incomplete tasks from the default "Tasks" list.

### Get Task Details
```bash
python3 -m sidekick.clients.mstodo get TASK_ID [--list LIST_ID]
```

### Create Task
```bash
python3 -m sidekick.clients.mstodo create "Task title" [--list LIST_ID] [--body TEXT] [--due YYYY-MM-DD] [--importance high|normal|low]
```

### Update Task
```bash
python3 -m sidekick.clients.mstodo update TASK_ID [--list LIST_ID] [--title TEXT] [--body TEXT] [--due YYYY-MM-DD] [--importance high|normal|low]
```

### Complete Task
```bash
python3 -m sidekick.clients.mstodo complete TASK_ID [--list LIST_ID]
```

### Delete Task
```bash
python3 -m sidekick.clients.mstodo delete TASK_ID [--list LIST_ID]
```

## Notes

- All task commands default to the user's "Tasks" list. Use `--list LIST_ID` to target a different list.
- Use `lists` command to discover available list IDs.
- Write operations (create, update, complete, delete) require user confirmation before execution.

## Example Usage

When the user asks to:
- "Show my tasks" or "What's on my to-do list?" - Use `tasks` command
- "Add a task to review the budget" - Use `create` command
- "Mark task X as done" - Use `complete` command
- "What tasks are due this week?" - Use `tasks` and filter by due date
- "Show completed tasks" - Use `tasks --status completed`

For full documentation, see the detailed Microsoft To Do skill documentation in this folder.
