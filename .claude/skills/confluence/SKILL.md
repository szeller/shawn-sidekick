---
name: confluence
description: Manage Confluence pages with search, read, and write operations
argument-hint: <operation> [args]
allowed-tools: Bash, Read
---

# Confluence Skill

Manage Confluence pages with search, read, and write operations.

When invoked, use the Confluence client to handle the request: $ARGUMENTS

## Available Commands

### Search for Pages
```bash
python -m sidekick.clients.confluence search "query" [--space SPACE] [--limit N]
```

### Get Page Details
```bash
python -m sidekick.clients.confluence get-page PAGE_ID
```

### Get Page by Title
```bash
python -m sidekick.clients.confluence get-page-by-title "Title" SPACE
```

### Read Page Content
```bash
python -m sidekick.clients.confluence read-page PAGE_ID
```

### Create New Page
```bash
python -m sidekick.clients.confluence create-page SPACE "Title" content.html [--parent PARENT_ID]
```

### Update Page
```bash
python -m sidekick.clients.confluence update-page PAGE_ID content.html [--title "New Title"]
```

### Add Topic to 1:1 Doc
```bash
python -m sidekick.clients.confluence add-topic-to-oneonone PERSON "Topic" [--section SECTION]
```

### Get Page from Link
```bash
python -m sidekick.clients.confluence get-page-from-link "https://company.atlassian.net/wiki/x/SHORT_ID"
python -m sidekick.clients.confluence get-content-from-link "https://company.atlassian.net/wiki/x/SHORT_ID"
```

### Read Inline Comments (Python API)
```python
# v2 API - returns inline comments with marker refs and resolution status
result = client._request('GET', '/wiki/api/v2/pages/PAGE_ID/inline-comments',
    params={'body-format': 'storage'})
```

### Create Inline Comment (Python API)
```python
# v2 API - anchors comment to specific text on the page
payload = {
    "pageId": "PAGE_ID",
    "body": {"representation": "storage", "value": "<p>Comment text</p>"},
    "inlineCommentProperties": {
        "textSelection": "Text to anchor to",
        "textSelectionMatchCount": 1,
        "textSelectionMatchIndex": 0
    }
}
result = client._request('POST', '/wiki/api/v2/inline-comments', json_data=payload)
```

## Search Cache

The Confluence client automatically caches search query to page mappings for faster repeated searches.

**Cache Management:**
```bash
python -m sidekick.clients.confluence cache-show
python -m sidekick.clients.confluence cache-clear
```

## Example Usage

When the user asks to:
- "Search for API documentation in Confluence" - Use search command
- "Read the contents of my 1:1 doc with Bob" - Search for the doc and read it
- "Add a topic to my 1:1 with Alice" - Use add-topic-to-oneonone command
- "Update the team wiki page" - Use update-page command

For full documentation, see the detailed Confluence skill documentation in this folder.
