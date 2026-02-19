"""PagerDuty API Client - single file implementation with CLI support."""

import sys
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from typing import Optional, List
from datetime import datetime
from collections import defaultdict


class PagerDutyClient:
    """PagerDuty API client using native Python stdlib."""

    BASE_URL = "https://api.pagerduty.com"

    def __init__(self, api_token: str, timeout: int = 60):
        """Initialize PagerDuty client with token auth.

        Args:
            api_token: PagerDuty API token
            timeout: Request timeout in seconds
        """
        self.api_token = api_token
        self.timeout = timeout
        self.api_call_count = 0

    def _get_auth_headers(self) -> dict:
        """Generate PagerDuty auth headers."""
        return {
            "Authorization": f"Token token={self.api_token}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.pagerduty+json;version=2"
        }

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        json_data: Optional[dict] = None
    ) -> dict:
        """Make HTTP request to PagerDuty API.

        Args:
            method: HTTP method (GET, POST, PUT)
            endpoint: API endpoint (e.g., /incidents)
            params: URL query parameters (lists are expanded as repeated keys)
            json_data: JSON body data

        Returns:
            Parsed JSON response as dict

        Raises:
            ConnectionError: For network errors
            ValueError: For 4xx client errors
            RuntimeError: For 5xx server errors
        """
        url = f"{self.BASE_URL}{endpoint}"
        if params:
            # Build query string manually to handle list params (e.g., service_ids[])
            query_parts = []
            for key, value in params.items():
                if isinstance(value, list):
                    for v in value:
                        query_parts.append(
                            f"{urllib.parse.quote(key)}={urllib.parse.quote(str(v))}"
                        )
                else:
                    query_parts.append(
                        f"{urllib.parse.quote(key)}={urllib.parse.quote(str(value))}"
                    )
            url += "?" + "&".join(query_parts)

        headers = self._get_auth_headers()
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
            error_body = e.read().decode() if e.fp else ""
            if e.code == 401 or e.code == 403:
                raise ValueError(
                    f"PagerDuty authentication failed (HTTP {e.code}). "
                    "Your API token may be invalid or lack permissions. "
                    "Generate a new token at: Settings > API Access Keys"
                )
            elif e.code == 404:
                raise ValueError(f"Resource not found: {endpoint}")
            elif 400 <= e.code < 500:
                raise ValueError(f"Client error {e.code}: {error_body}")
            else:
                raise RuntimeError(f"Server error {e.code}: {error_body}")
        except urllib.error.URLError as e:
            raise ConnectionError(f"Network error: {e.reason}")

    def _paginate(
        self,
        endpoint: str,
        result_key: str,
        params: Optional[dict] = None,
        limit: int = 100,
        max_results: Optional[int] = None
    ) -> list:
        """Auto-paginate through all results for a GET endpoint.

        Args:
            endpoint: API endpoint
            result_key: Key in response containing the results array
            params: Base query parameters
            limit: Per-page limit (max 100 for PagerDuty)
            max_results: Optional cap on total results to fetch

        Returns:
            Combined list of all result items
        """
        if params is None:
            params = {}
        params["limit"] = min(limit, 100)
        params["offset"] = 0

        all_results = []
        while True:
            response = self._request("GET", endpoint, params=params)
            items = response.get(result_key, [])
            all_results.extend(items)

            if max_results and len(all_results) >= max_results:
                return all_results[:max_results]

            if not response.get("more", False):
                break

            params["offset"] += len(items)

        return all_results

    # -- Date parsing helpers --

    @staticmethod
    def _parse_date(date_str: str) -> str:
        """Parse flexible date input into ISO 8601 format.

        Accepts:
            "2026-01"              -> "2026-01-01T00:00:00Z"
            "2026-01-15"           -> "2026-01-15T00:00:00Z"
            "2026-01-15T10:00:00Z" -> passed through as-is

        Returns:
            ISO 8601 date string
        """
        if "T" in date_str:
            return date_str
        parts = date_str.split("-")
        if len(parts) == 2:
            return f"{date_str}-01T00:00:00Z"
        elif len(parts) == 3:
            return f"{date_str}T00:00:00Z"
        else:
            raise ValueError(
                f"Invalid date format: {date_str}. "
                "Use YYYY-MM, YYYY-MM-DD, or full ISO 8601."
            )

    @staticmethod
    def _month_end(year: int, month: int) -> str:
        """Get ISO 8601 start of the month after year/month."""
        if month == 12:
            return f"{year + 1:04d}-01-01T00:00:00Z"
        return f"{year:04d}-{month + 1:02d}-01T00:00:00Z"

    @staticmethod
    def _is_month_shorthand(date_str: str) -> bool:
        """Check if date_str is YYYY-MM format."""
        parts = date_str.split("-")
        return len(parts) == 2 and "T" not in date_str

    # -- Core API methods --

    def list_incidents(
        self,
        since: str,
        until: Optional[str] = None,
        service_ids: Optional[List[str]] = None,
        team_ids: Optional[List[str]] = None,
        statuses: Optional[List[str]] = None,
        urgencies: Optional[List[str]] = None,
        max_results: Optional[int] = None
    ) -> list:
        """List incidents in a time range.

        Args:
            since: Start date ("2026-01", "2026-01-15", or ISO 8601).
                   If month shorthand and until is None, returns full month.
            until: End date (same formats). If None with month shorthand,
                   defaults to end of that month.
            service_ids: Filter by service IDs
            team_ids: Filter by team IDs
            statuses: Filter by status (triggered, acknowledged, resolved)
            urgencies: Filter by urgency (high, low)
            max_results: Cap on total incidents to return

        Returns:
            List of incident dicts
        """
        if until is None:
            if self._is_month_shorthand(since):
                parts = since.split("-")
                year, month = int(parts[0]), int(parts[1])
                since_iso = f"{since}-01T00:00:00Z"
                until_iso = self._month_end(year, month)
            else:
                raise ValueError(
                    "'until' is required unless 'since' is month shorthand (YYYY-MM)"
                )
        else:
            since_iso = self._parse_date(since)
            if self._is_month_shorthand(until):
                parts = until.split("-")
                year, month = int(parts[0]), int(parts[1])
                until_iso = self._month_end(year, month)
            else:
                until_iso = self._parse_date(until)

        params = {
            "since": since_iso,
            "until": until_iso,
            "sort_by": "created_at",
        }
        if service_ids:
            params["service_ids[]"] = service_ids
        if team_ids:
            params["team_ids[]"] = team_ids
        if statuses:
            params["statuses[]"] = statuses
        if urgencies:
            params["urgencies[]"] = urgencies

        return self._paginate(
            "/incidents", "incidents", params=params, max_results=max_results
        )

    def get_incident(self, incident_id: str) -> dict:
        """Get a single incident by ID.

        Args:
            incident_id: PagerDuty incident ID (e.g., "P1ABC2D")

        Returns:
            Full incident dict
        """
        result = self._request("GET", f"/incidents/{incident_id}")
        return result.get("incident", {})

    def list_alerts(self, incident_id: str) -> list:
        """List alerts for an incident.

        Args:
            incident_id: PagerDuty incident ID

        Returns:
            List of alert dicts with body/details for root cause info
        """
        return self._paginate(f"/incidents/{incident_id}/alerts", "alerts")

    def list_services(
        self,
        query: Optional[str] = None,
        team_ids: Optional[List[str]] = None,
        max_results: Optional[int] = None
    ) -> list:
        """List services, optionally filtered.

        Args:
            query: Search string to filter services by name
            team_ids: Filter by team IDs
            max_results: Cap on total services to return

        Returns:
            List of service dicts
        """
        params = {}
        if query:
            params["query"] = query
        if team_ids:
            params["team_ids[]"] = team_ids

        return self._paginate(
            "/services", "services", params=params, max_results=max_results
        )

    def list_oncalls(
        self,
        schedule_ids: Optional[List[str]] = None,
        escalation_policy_ids: Optional[List[str]] = None,
        since: Optional[str] = None,
        until: Optional[str] = None
    ) -> list:
        """List current on-call entries.

        Args:
            schedule_ids: Filter by schedule IDs
            escalation_policy_ids: Filter by escalation policy IDs
            since: Start of on-call window
            until: End of on-call window

        Returns:
            List of oncall dicts
        """
        params = {}
        if schedule_ids:
            params["schedule_ids[]"] = schedule_ids
        if escalation_policy_ids:
            params["escalation_policy_ids[]"] = escalation_policy_ids
        if since:
            params["since"] = self._parse_date(since)
        if until:
            params["until"] = self._parse_date(until)

        return self._paginate("/oncalls", "oncalls", params=params)

    # -- Analysis helpers --

    @staticmethod
    def summarize_incidents(incidents: list) -> dict:
        """Analyze a list of incidents for patterns.

        Computes breakdowns by service, urgency, status, day of week, hour,
        recurring titles, and average resolution time. All analysis is
        client-side on already-fetched data.

        Args:
            incidents: List of incident dicts from list_incidents()

        Returns:
            dict with keys: total, by_service, by_urgency, by_status,
            by_day_of_week, by_hour, top_titles, avg_resolution_minutes,
            busiest_day, busiest_hour
        """
        by_service = defaultdict(int)
        by_urgency = defaultdict(int)
        by_status = defaultdict(int)
        by_day = defaultdict(int)
        by_hour = defaultdict(int)
        title_counts = defaultdict(int)
        resolution_minutes = []

        day_names = [
            "Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday"
        ]

        for inc in incidents:
            service_name = inc.get("service", {}).get("summary", "Unknown")
            by_service[service_name] += 1

            by_urgency[inc.get("urgency", "unknown")] += 1
            by_status[inc.get("status", "unknown")] += 1

            created = inc.get("created_at", "")
            if created:
                try:
                    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    by_day[day_names[dt.weekday()]] += 1
                    by_hour[dt.hour] += 1
                except (ValueError, IndexError):
                    pass

            title_counts[inc.get("title", "")] += 1

            if inc.get("status") == "resolved":
                resolved_at = inc.get("last_status_change_at", "")
                if created and resolved_at:
                    try:
                        created_dt = datetime.fromisoformat(
                            created.replace("Z", "+00:00")
                        )
                        resolved_dt = datetime.fromisoformat(
                            resolved_at.replace("Z", "+00:00")
                        )
                        delta = (resolved_dt - created_dt).total_seconds() / 60
                        if delta >= 0:
                            resolution_minutes.append(delta)
                    except ValueError:
                        pass

        top_titles = sorted(
            title_counts.items(), key=lambda x: x[1], reverse=True
        )[:20]

        avg_resolution = None
        if resolution_minutes:
            avg_resolution = sum(resolution_minutes) / len(resolution_minutes)

        busiest_day = max(by_day, key=by_day.get) if by_day else None
        busiest_hour = max(by_hour, key=by_hour.get) if by_hour else None

        return {
            "total": len(incidents),
            "by_service": dict(
                sorted(by_service.items(), key=lambda x: x[1], reverse=True)
            ),
            "by_urgency": dict(by_urgency),
            "by_status": dict(by_status),
            "by_day_of_week": dict(by_day),
            "by_hour": dict(sorted(by_hour.items())),
            "top_titles": top_titles,
            "avg_resolution_minutes": avg_resolution,
            "busiest_day": busiest_day,
            "busiest_hour": busiest_hour,
        }


# -- Formatting helpers --


def _format_incident(incident: dict) -> str:
    """Format incident as one-liner.

    Format: #NUMBER: title [status] (urgency) {service} created_date
    """
    number = incident.get("incident_number", "?")
    title = incident.get("title", "No title")
    status = incident.get("status", "unknown")
    urgency = incident.get("urgency", "?")
    service = incident.get("service", {}).get("summary", "Unknown")
    created = incident.get("created_at", "")[:16].replace("T", " ")
    return f"#{number}: {title} [{status}] ({urgency}) {{{service}}} {created}"


def _print_incident_details(incident: dict) -> None:
    """Print detailed incident view."""
    print(f"#{incident.get('incident_number', '?')}: "
          f"{incident.get('title', 'No title')}")
    print(f"  ID: {incident.get('id', 'Unknown')}")
    print(f"  Status: {incident.get('status', 'unknown')}")
    print(f"  Urgency: {incident.get('urgency', 'unknown')}")
    print(f"  Service: {incident.get('service', {}).get('summary', 'Unknown')}")

    ep = incident.get("escalation_policy", {})
    if ep:
        print(f"  Escalation Policy: {ep.get('summary', 'Unknown')}")

    teams = incident.get("teams", [])
    if teams:
        team_names = [t.get("summary", "?") for t in teams]
        print(f"  Teams: {', '.join(team_names)}")

    assignments = incident.get("assignments", [])
    if assignments:
        assignees = [
            a.get("assignee", {}).get("summary", "?") for a in assignments
        ]
        print(f"  Assigned to: {', '.join(assignees)}")

    print(f"  Created: {incident.get('created_at', 'Unknown')}")
    last_change = incident.get("last_status_change_at")
    if last_change:
        print(f"  Last Status Change: {last_change}")

    desc = incident.get("description", "")
    if desc:
        preview = desc[:200] + "..." if len(desc) > 200 else desc
        print(f"  Description: {preview}")

    html_url = incident.get("html_url", "")
    if html_url:
        print(f"  URL: {html_url}")


def _format_alert(alert: dict) -> str:
    """Format alert as one-liner."""
    severity = alert.get("severity", "?")
    status = alert.get("status", "?")
    summary = alert.get("summary", "No summary")
    created = alert.get("created_at", "")[:16].replace("T", " ")
    return f"  {summary} [{status}] ({severity}) {created}"


def _print_alert_details(alert: dict) -> None:
    """Print detailed alert view."""
    print(f"Alert: {alert.get('id', 'Unknown')}")
    print(f"  Status: {alert.get('status', 'unknown')}")
    print(f"  Severity: {alert.get('severity', 'unknown')}")
    print(f"  Summary: {alert.get('summary', 'No summary')}")
    print(f"  Created: {alert.get('created_at', 'Unknown')}")

    body = alert.get("body", {})
    if body:
        cef = body.get("cef_details", {})
        if cef:
            source = cef.get("source_origin", "")
            if source:
                print(f"  Source: {source}")
            desc = cef.get("description", "")
            if desc:
                print(f"  Description: {desc}")
            details = cef.get("details", {})
            if details and isinstance(details, dict):
                print("  Details:")
                for k, v in details.items():
                    print(f"    {k}: {v}")

        contexts = body.get("contexts", [])
        for ctx in contexts:
            if ctx.get("type") == "link":
                print(f"  Link: {ctx.get('href', '')} - {ctx.get('text', '')}")


def _format_service(service: dict) -> str:
    """Format service as one-liner."""
    sid = service.get("id", "?")
    name = service.get("name", "Unknown")
    status = service.get("status", "?")
    teams = service.get("teams", [])
    team_str = (
        ", ".join(t.get("summary", "?") for t in teams) if teams else "no team"
    )
    return f"{sid}: {name} [{status}] ({team_str})"


def _print_summary(summary: dict) -> None:
    """Print incident summary analysis."""
    total = summary["total"]
    print(f"Incident Summary ({total} total)")
    print("=" * 60)

    if summary["by_service"]:
        print("\nBy Service:")
        for name, count in summary["by_service"].items():
            pct = (count / total) * 100
            bar = "#" * max(1, int(pct / 2))
            print(f"  {name}: {count} ({pct:.0f}%) {bar}")

    if summary["by_urgency"]:
        print("\nBy Urgency:")
        for urg, count in summary["by_urgency"].items():
            print(f"  {urg}: {count}")

    if summary["by_status"]:
        print("\nBy Status:")
        for status, count in summary["by_status"].items():
            print(f"  {status}: {count}")

    days_order = [
        "Monday", "Tuesday", "Wednesday", "Thursday",
        "Friday", "Saturday", "Sunday"
    ]
    if summary["by_day_of_week"]:
        print("\nBy Day of Week:")
        for day in days_order:
            count = summary["by_day_of_week"].get(day, 0)
            bar = "#" * count
            print(f"  {day:9s}: {count:3d} {bar}")

    if summary["by_hour"]:
        print("\nBy Hour (UTC):")
        for hour in range(24):
            count = summary["by_hour"].get(hour, 0)
            if count > 0:
                bar = "#" * count
                print(f"  {hour:02d}:00: {count:3d} {bar}")

    if summary["avg_resolution_minutes"] is not None:
        avg = summary["avg_resolution_minutes"]
        if avg >= 60:
            print(f"\nAvg Resolution Time: {avg / 60:.1f} hours ({avg:.0f} min)")
        else:
            print(f"\nAvg Resolution Time: {avg:.0f} min")

    if summary["busiest_day"]:
        print(f"Busiest Day: {summary['busiest_day']}")
    if summary["busiest_hour"] is not None:
        print(f"Busiest Hour: {summary['busiest_hour']:02d}:00 UTC")

    if summary["top_titles"]:
        print("\nTop Recurring Incident Titles:")
        for title, count in summary["top_titles"][:10]:
            print(f"  [{count}x] {title}")


# -- CLI --


def _parse_incident_args(args: list) -> tuple:
    """Parse CLI args for incident commands.

    Expected: <since> [until] [--service SVC_ID] [--team TEAM_ID]

    Returns:
        (since, until, service_ids, team_ids)
    """
    if not args:
        print("Error: Missing <since> date argument", file=sys.stderr)
        sys.exit(1)

    since = args[0]
    until = None
    service_ids = []
    team_ids = []

    i = 1
    # Second positional arg is until date (if not a flag)
    if i < len(args) and not args[i].startswith("--"):
        until = args[i]
        i += 1

    while i < len(args):
        if args[i] == "--service" and i + 1 < len(args):
            service_ids.append(args[i + 1])
            i += 2
        elif args[i] == "--team" and i + 1 < len(args):
            team_ids.append(args[i + 1])
            i += 2
        else:
            print(f"Error: Unknown argument '{args[i]}'", file=sys.stderr)
            sys.exit(1)

    return (
        since,
        until,
        service_ids if service_ids else None,
        team_ids if team_ids else None,
    )


def main():
    """CLI entry point for PagerDuty client."""
    from sidekick.config import get_pagerduty_config

    if len(sys.argv) < 2:
        print("Usage: python3 -m sidekick.clients.pagerduty <command> [args...]")
        print("\nCommands:")
        print("  list-services [query]")
        print("  list-incidents <since> [until] [--service ID] [--team ID]")
        print("  get-incident <incident-id>")
        print("  list-alerts <incident-id>")
        print("  incident-summary <since> [until] [--service ID] [--team ID]")
        print("\nDate formats: YYYY-MM (full month), YYYY-MM-DD, or ISO 8601")
        print("\nExamples:")
        print("  list-incidents 2026-01")
        print("  list-incidents 2026-01-01 2026-01-31 --service P1ABC2D")
        print("  incident-summary 2026-01 --service P1ABC2D")
        sys.exit(1)

    try:
        start_time = time.time()
        config = get_pagerduty_config()
        client = PagerDutyClient(api_token=config["api_token"])

        command = sys.argv[1]

        if command == "list-services":
            query = sys.argv[2] if len(sys.argv) > 2 else None
            services = client.list_services(query=query)
            print(f"Services ({len(services)}):")
            for svc in services:
                print(_format_service(svc))

        elif command == "list-incidents":
            since, until, service_ids, team_ids = _parse_incident_args(
                sys.argv[2:]
            )
            incidents = client.list_incidents(
                since=since, until=until,
                service_ids=service_ids, team_ids=team_ids
            )
            print(f"Found {len(incidents)} incidents:")
            for inc in incidents:
                print(_format_incident(inc))

        elif command == "get-incident":
            if len(sys.argv) < 3:
                print("Error: Missing incident ID", file=sys.stderr)
                sys.exit(1)
            incident = client.get_incident(sys.argv[2])
            _print_incident_details(incident)

        elif command == "list-alerts":
            if len(sys.argv) < 3:
                print("Error: Missing incident ID", file=sys.stderr)
                sys.exit(1)
            alerts = client.list_alerts(sys.argv[2])
            print(f"Alerts for incident {sys.argv[2]} ({len(alerts)}):")
            for alert in alerts:
                print(_format_alert(alert))

        elif command == "incident-summary":
            since, until, service_ids, team_ids = _parse_incident_args(
                sys.argv[2:]
            )
            incidents = client.list_incidents(
                since=since, until=until,
                service_ids=service_ids, team_ids=team_ids
            )
            summary = PagerDutyClient.summarize_incidents(incidents)
            _print_summary(summary)

        else:
            print(f"Unknown command: {command}", file=sys.stderr)
            sys.exit(1)

        elapsed_time = time.time() - start_time
        print(
            f"\n[Debug] API calls: {client.api_call_count}, "
            f"Time: {elapsed_time:.2f}s",
            file=sys.stderr
        )

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
