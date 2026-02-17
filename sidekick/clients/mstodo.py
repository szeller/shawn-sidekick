"""Microsoft To Do API Client - single file implementation with CLI support.

Uses Microsoft Graph API to manage To Do tasks.
"""

import sys
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from typing import Optional, List
from datetime import datetime, timezone


class MicrosoftTodoClient:
    """Microsoft To Do client using Microsoft Graph API and native Python stdlib."""

    def __init__(self, client_id: str, refresh_token: str, client_secret: str = None, timeout: int = 30):
        """Initialize Microsoft To Do client with OAuth2 credentials.

        Args:
            client_id: Azure AD application (client) ID
            refresh_token: OAuth2 refresh token
            client_secret: Azure AD client secret (optional for public clients)
            timeout: Request timeout in seconds
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.timeout = timeout
        self.access_token = None
        self.api_call_count = 0
        self._default_list_id = None

    def _refresh_access_token(self) -> str:
        """Refresh OAuth2 access token using refresh token.

        Returns:
            New access token

        Raises:
            ValueError: If token refresh fails
        """
        token_url = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
        data = {
            "client_id": self.client_id,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
            "scope": "Tasks.ReadWrite offline_access"
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret

        encoded_data = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(token_url, data=encoded_data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                result = json.loads(response.read().decode())
                return result["access_token"]
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            raise ValueError(f"Failed to refresh access token: {e.code} - {error_body}")
        except (KeyError, json.JSONDecodeError) as e:
            raise ValueError(f"Invalid token response: {e}")

    def _get_access_token(self) -> str:
        """Get valid access token, refreshing if necessary."""
        if not self.access_token:
            self.access_token = self._refresh_access_token()
        return self.access_token

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        json_data: Optional[dict] = None,
        retry_auth: bool = True
    ) -> Optional[dict]:
        """Make HTTP request to Microsoft Graph API.

        Args:
            method: HTTP method (GET, POST, PATCH, DELETE)
            endpoint: API endpoint path or full URL (for pagination)
            params: URL query parameters
            json_data: JSON body data
            retry_auth: Whether to retry once on auth failure

        Returns:
            Parsed JSON response as dict, or None for DELETE (204)

        Raises:
            ConnectionError: For network errors
            ValueError: For 4xx client errors
            RuntimeError: For 5xx server errors
        """
        # Build URL - support both relative endpoints and full URLs (for pagination)
        if endpoint.startswith("http"):
            url = endpoint
        else:
            base_url = "https://graph.microsoft.com/v1.0"
            url = f"{base_url}{endpoint}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        # Prepare request
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        data = json.dumps(json_data).encode() if json_data else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                self.api_call_count += 1
                body = response.read().decode()
                if not body or body.strip() == "":
                    return None
                return json.loads(body)
        except urllib.error.HTTPError as e:
            # Handle 204 No Content (success for DELETE)
            if e.code == 204:
                self.api_call_count += 1
                return None

            error_body = e.read().decode() if e.fp else ""

            # Retry once on 401 (token might be expired)
            if e.code == 401 and retry_auth:
                self.access_token = None  # Force token refresh
                return self._request(method, endpoint, params, json_data, retry_auth=False)

            if e.code == 404:
                raise ValueError(f"Resource not found: {endpoint}")
            elif e.code >= 400 and e.code < 500:
                raise ValueError(f"Client error {e.code}: {error_body}")
            elif e.code >= 500:
                raise RuntimeError(f"Server error {e.code}: {error_body}")
            else:
                raise ConnectionError(f"HTTP error {e.code}: {error_body}")
        except urllib.error.URLError as e:
            raise ConnectionError(f"Network error: {e.reason}")

    # --- Task Lists ---

    def list_task_lists(self) -> List[dict]:
        """List all task lists.

        Returns:
            List of task list dicts with keys: id, displayName, isOwner,
            isShared, wellknownListName
        """
        result = self._request("GET", "/me/todo/lists")
        return result.get("value", [])

    def get_default_list_id(self) -> str:
        """Get the default task list ID.

        Finds the list with wellknownListName == 'defaultList' (Microsoft's
        built-in 'Tasks' list). Falls back to the first list if not found.
        Caches the result for the session.

        Returns:
            Task list ID string

        Raises:
            ValueError: If no task lists exist
        """
        if self._default_list_id:
            return self._default_list_id

        lists = self.list_task_lists()
        if not lists:
            raise ValueError("No task lists found. Create a list in Microsoft To Do first.")

        # Look for the default list
        for task_list in lists:
            if task_list.get("wellknownListName") == "defaultList":
                self._default_list_id = task_list["id"]
                return self._default_list_id

        # Fall back to first list
        self._default_list_id = lists[0]["id"]
        return self._default_list_id

    # --- Tasks ---

    def list_tasks(
        self,
        list_id: Optional[str] = None,
        status: str = "notCompleted",
        top: int = 50,
        order_by: Optional[str] = None
    ) -> List[dict]:
        """List tasks from a task list.

        Args:
            list_id: Task list ID (defaults to default list)
            status: Filter - 'notCompleted', 'completed', or 'all'
            top: Maximum number of tasks to return
            order_by: Sort field (e.g., 'createdDateTime', 'dueDateTime/dateTime')

        Returns:
            List of task dicts
        """
        if not list_id:
            list_id = self.get_default_list_id()

        params = {"$top": min(top, 100)}

        if status == "notCompleted":
            params["$filter"] = "status ne 'completed'"
        elif status == "completed":
            params["$filter"] = "status eq 'completed'"
        # 'all' = no filter

        if order_by:
            params["$orderby"] = order_by

        endpoint = f"/me/todo/lists/{list_id}/tasks"
        all_tasks = []

        while endpoint and len(all_tasks) < top:
            result = self._request("GET", endpoint, params=params)
            all_tasks.extend(result.get("value", []))

            # Handle pagination
            next_link = result.get("@odata.nextLink")
            if next_link and len(all_tasks) < top:
                endpoint = next_link  # Full URL for next page
                params = None  # Params are embedded in the nextLink URL
            else:
                break

        return all_tasks[:top]

    def get_task(self, task_id: str, list_id: Optional[str] = None) -> dict:
        """Get a specific task by ID.

        Args:
            task_id: Task ID
            list_id: Task list ID (defaults to default list)

        Returns:
            Task dict with full details
        """
        if not list_id:
            list_id = self.get_default_list_id()
        return self._request("GET", f"/me/todo/lists/{list_id}/tasks/{task_id}")

    def create_task(
        self,
        title: str,
        list_id: Optional[str] = None,
        body: Optional[str] = None,
        importance: Optional[str] = None,
        due_date: Optional[str] = None,
        categories: Optional[List[str]] = None
    ) -> dict:
        """Create a new task.

        Args:
            title: Task title (required)
            list_id: Task list ID (defaults to default list)
            body: Task body/description text
            importance: 'high', 'normal', or 'low'
            due_date: Due date in YYYY-MM-DD format
            categories: List of category strings

        Returns:
            Created task dict
        """
        if not list_id:
            list_id = self.get_default_list_id()

        task_data = {"title": title}

        if body:
            task_data["body"] = {"content": body, "contentType": "text"}
        if importance:
            task_data["importance"] = importance
        if due_date:
            task_data["dueDateTime"] = {
                "dateTime": f"{due_date}T00:00:00",
                "timeZone": "UTC"
            }
        if categories:
            task_data["categories"] = categories

        return self._request("POST", f"/me/todo/lists/{list_id}/tasks", json_data=task_data)

    def update_task(
        self,
        task_id: str,
        list_id: Optional[str] = None,
        title: Optional[str] = None,
        body: Optional[str] = None,
        importance: Optional[str] = None,
        due_date: Optional[str] = None,
        status: Optional[str] = None,
        categories: Optional[List[str]] = None
    ) -> dict:
        """Update an existing task.

        Args:
            task_id: Task ID
            list_id: Task list ID (defaults to default list)
            title: New title
            body: New body text
            importance: 'high', 'normal', or 'low'
            due_date: Due date in YYYY-MM-DD format
            status: 'notStarted', 'inProgress', or 'completed'
            categories: List of category strings

        Returns:
            Updated task dict
        """
        if not list_id:
            list_id = self.get_default_list_id()

        task_data = {}
        if title is not None:
            task_data["title"] = title
        if body is not None:
            task_data["body"] = {"content": body, "contentType": "text"}
        if importance is not None:
            task_data["importance"] = importance
        if due_date is not None:
            task_data["dueDateTime"] = {
                "dateTime": f"{due_date}T00:00:00",
                "timeZone": "UTC"
            }
        if status is not None:
            task_data["status"] = status
        if categories is not None:
            task_data["categories"] = categories

        if not task_data:
            raise ValueError("No fields to update")

        return self._request("PATCH", f"/me/todo/lists/{list_id}/tasks/{task_id}", json_data=task_data)

    def complete_task(self, task_id: str, list_id: Optional[str] = None) -> dict:
        """Mark a task as completed.

        Args:
            task_id: Task ID
            list_id: Task list ID (defaults to default list)

        Returns:
            Updated task dict
        """
        if not list_id:
            list_id = self.get_default_list_id()

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.0000000")
        task_data = {
            "status": "completed",
            "completedDateTime": {
                "dateTime": now,
                "timeZone": "UTC"
            }
        }

        return self._request("PATCH", f"/me/todo/lists/{list_id}/tasks/{task_id}", json_data=task_data)

    def delete_task(self, task_id: str, list_id: Optional[str] = None) -> None:
        """Delete a task.

        Args:
            task_id: Task ID
            list_id: Task list ID (defaults to default list)
        """
        if not list_id:
            list_id = self.get_default_list_id()
        self._request("DELETE", f"/me/todo/lists/{list_id}/tasks/{task_id}")


# --- Formatting functions ---

def _format_task_oneline(task: dict) -> str:
    """Format task as one-line summary.

    Format: {id}: {title} [{status}] [{importance}] [due: {date}]
    """
    task_id = task.get("id", "")
    title = task.get("title", "(No title)")
    status = task.get("status", "notStarted")

    parts = [f"{task_id}: {title} [{status}]"]

    importance = task.get("importance", "normal")
    if importance != "normal":
        parts.append(f"[{importance}]")

    due = task.get("dueDateTime")
    if due:
        due_str = due.get("dateTime", "")[:10]  # Extract YYYY-MM-DD
        parts.append(f"[due: {due_str}]")

    categories = task.get("categories", [])
    if categories:
        parts.append(f"[{', '.join(categories)}]")

    return " ".join(parts)


def _format_task_full(task: dict) -> str:
    """Format full task details."""
    lines = [
        f"Task ID: {task.get('id', 'Unknown')}",
        f"Title: {task.get('title', '(No title)')}",
        f"  Status: {task.get('status', 'notStarted')}",
        f"  Importance: {task.get('importance', 'normal')}",
    ]

    due = task.get("dueDateTime")
    if due:
        lines.append(f"  Due: {due.get('dateTime', '')[:10]}")

    categories = task.get("categories", [])
    if categories:
        lines.append(f"  Categories: {', '.join(categories)}")

    created = task.get("createdDateTime", "")
    if created:
        lines.append(f"  Created: {created}")

    modified = task.get("lastModifiedDateTime", "")
    if modified:
        lines.append(f"  Modified: {modified}")

    body = task.get("body", {})
    content = body.get("content", "")
    if content:
        lines.append(f"  Body: {content}")

    return "\n".join(lines)


def _format_list_oneline(task_list: dict) -> str:
    """Format task list as one-line summary."""
    list_id = task_list.get("id", "")
    name = task_list.get("displayName", "(Unnamed)")
    well_known = task_list.get("wellknownListName", "")
    suffix = " (default)" if well_known == "defaultList" else ""
    return f"  {list_id}: {name}{suffix}"


# --- CLI ---

def _parse_flags(args: list, start: int = 2) -> dict:
    """Parse --flag value pairs from CLI args.

    Args:
        args: sys.argv list
        start: Index to start parsing from

    Returns:
        Dict of flag names (without --) to values
    """
    flags = {}
    i = start
    while i < len(args):
        arg = args[i]
        if arg.startswith("--") and i + 1 < len(args):
            flag_name = arg[2:]  # Remove --
            flags[flag_name] = args[i + 1]
            i += 2
        else:
            i += 1
    return flags


def main():
    """CLI interface for Microsoft To Do client."""
    if len(sys.argv) < 2:
        print("Usage: python -m sidekick.clients.mstodo <command> [args]")
        print("\nCommands:")
        print("  lists                                    - List all task lists")
        print("  tasks [--list ID] [--status STATUS]      - List tasks")
        print("         [--limit N]")
        print("  get <task_id> [--list ID]                - Get task details")
        print("  create <title> [--list ID] [--body TEXT] - Create a task")
        print("         [--due YYYY-MM-DD]")
        print("         [--importance high|normal|low]")
        print("  update <task_id> [--list ID]             - Update a task")
        print("         [--title TEXT] [--body TEXT]")
        print("         [--due YYYY-MM-DD]")
        print("         [--importance high|normal|low]")
        print("  complete <task_id> [--list ID]           - Mark task completed")
        print("  delete <task_id> [--list ID]             - Delete a task")
        print("\nExamples:")
        print('  python -m sidekick.clients.mstodo tasks')
        print('  python -m sidekick.clients.mstodo create "Review budget" --due 2026-03-01 --importance high')
        print('  python -m sidekick.clients.mstodo complete TASK_ID')
        sys.exit(1)

    # Load configuration
    try:
        from sidekick.config import get_microsoft_config
        config = get_microsoft_config()
    except ImportError:
        print("Error: Could not import config module", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)

    # Create client
    client = MicrosoftTodoClient(
        client_id=config["client_id"],
        refresh_token=config["refresh_token"],
        client_secret=config.get("client_secret")
    )

    command = sys.argv[1]
    start_time = time.time()

    try:
        if command == "lists":
            lists = client.list_task_lists()
            print(f"Task Lists ({len(lists)}):\n")
            for task_list in lists:
                print(_format_list_oneline(task_list))

        elif command == "tasks":
            flags = _parse_flags(sys.argv)
            list_id = flags.get("list")
            status = flags.get("status", "notCompleted")
            limit = int(flags.get("limit", "50"))

            tasks = client.list_tasks(list_id=list_id, status=status, top=limit)

            status_label = {"notCompleted": "incomplete", "completed": "completed", "all": "all"}
            label = status_label.get(status, status)
            print(f"Found {len(tasks)} {label} tasks (showing {limit}):\n")
            for task in tasks:
                print(_format_task_oneline(task))

        elif command == "get":
            if len(sys.argv) < 3:
                print("Error: Missing task_id argument", file=sys.stderr)
                sys.exit(1)
            task_id = sys.argv[2]
            flags = _parse_flags(sys.argv, start=3)
            list_id = flags.get("list")

            task = client.get_task(task_id, list_id=list_id)
            print(_format_task_full(task))

        elif command == "create":
            if len(sys.argv) < 3:
                print("Error: Missing title argument", file=sys.stderr)
                sys.exit(1)
            title = sys.argv[2]
            flags = _parse_flags(sys.argv, start=3)

            task = client.create_task(
                title=title,
                list_id=flags.get("list"),
                body=flags.get("body"),
                importance=flags.get("importance"),
                due_date=flags.get("due")
            )
            print("Task created:")
            print(_format_task_oneline(task))

        elif command == "update":
            if len(sys.argv) < 3:
                print("Error: Missing task_id argument", file=sys.stderr)
                sys.exit(1)
            task_id = sys.argv[2]
            flags = _parse_flags(sys.argv, start=3)

            task = client.update_task(
                task_id=task_id,
                list_id=flags.get("list"),
                title=flags.get("title"),
                body=flags.get("body"),
                importance=flags.get("importance"),
                due_date=flags.get("due"),
                status=flags.get("status")
            )
            print("Task updated:")
            print(_format_task_oneline(task))

        elif command == "complete":
            if len(sys.argv) < 3:
                print("Error: Missing task_id argument", file=sys.stderr)
                sys.exit(1)
            task_id = sys.argv[2]
            flags = _parse_flags(sys.argv, start=3)
            list_id = flags.get("list")

            task = client.complete_task(task_id, list_id=list_id)
            print("Task completed:")
            print(_format_task_oneline(task))

        elif command == "delete":
            if len(sys.argv) < 3:
                print("Error: Missing task_id argument", file=sys.stderr)
                sys.exit(1)
            task_id = sys.argv[2]
            flags = _parse_flags(sys.argv, start=3)
            list_id = flags.get("list")

            client.delete_task(task_id, list_id=list_id)
            print("Task deleted.")

        else:
            print(f"Error: Unknown command '{command}'", file=sys.stderr)
            sys.exit(1)

    except (ValueError, RuntimeError, ConnectionError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        elapsed = time.time() - start_time
        print(f"\n[Debug] API calls: {client.api_call_count}, Time: {elapsed:.2f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
