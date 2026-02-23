"""Dropbox client - single-file implementation using Python stdlib only."""
import sys
import json
import urllib.request
import urllib.parse
import urllib.error
import time
import re
from typing import Optional, Union


class DropboxClient:
    """Client for Dropbox API v2.

    Supports:
    - Regular file content operations (get/write)
    - Paper doc content operations (get/create/update)
    - Share link resolution
    - No external dependencies (Python stdlib only)
    """

    def __init__(
        self,
        access_token: str = None,
        timeout: int = 30,
        app_key: str = None,
        app_secret: str = None,
        refresh_token: str = None
    ):
        """Initialize Dropbox client with OAuth credentials.

        Supports two modes:
        1. Refresh token (preferred): Provide app_key, app_secret, and refresh_token.
           Access tokens are obtained and refreshed automatically.
        2. Static access token (legacy): Provide access_token directly.

        Args:
            access_token: Static OAuth 2.0 access token (legacy)
            timeout: Request timeout in seconds (default: 30)
            app_key: Dropbox app key (for refresh token flow)
            app_secret: Dropbox app secret (for refresh token flow)
            refresh_token: OAuth 2.0 refresh token (for refresh token flow)
        """
        self.app_key = app_key
        self.app_secret = app_secret
        self.refresh_token = refresh_token
        self._access_token = access_token
        self.timeout = timeout
        self.api_call_count = 0

    def _refresh_access_token(self) -> str:
        """Refresh OAuth2 access token using refresh token.

        Returns:
            New access token

        Raises:
            ValueError: If token refresh fails
        """
        token_url = "https://api.dropboxapi.com/oauth2/token"
        data = {
            "client_id": self.app_key,
            "client_secret": self.app_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token"
        }

        encoded_data = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(token_url, data=encoded_data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                result = json.loads(response.read().decode())
                return result["access_token"]
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            raise ValueError(f"Failed to refresh Dropbox access token: {e.code} - {error_body}")
        except (KeyError, json.JSONDecodeError):
            raise ValueError("Invalid token response from Dropbox")

    def _get_access_token(self) -> str:
        """Get valid access token, refreshing if necessary."""
        if not self._access_token and self.refresh_token:
            self._access_token = self._refresh_access_token()
        return self._access_token

    def _get_auth_headers(self) -> dict:
        """Get authorization headers for API requests.

        Returns:
            dict with Authorization header
        """
        return {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Content-Type": "application/json"
        }

    def _request_api(self, endpoint: str, data: dict = None, content: bytes = None,
                     retry_auth: bool = True) -> dict:
        """Make API request to api.dropboxapi.com.

        Used for metadata operations, sharing, and Paper export/import.

        Args:
            endpoint: API endpoint (e.g., "/2/files/get_metadata")
            data: JSON data to send in request body
            content: Optional binary content for requests like /files/import
            retry_auth: Whether to retry once on 401 (token refresh)

        Returns:
            dict with API response (parsed JSON)

        Raises:
            ValueError: For 4xx client errors (invalid path, auth failure, etc.)
            RuntimeError: For 5xx server errors
            ConnectionError: For network errors
        """
        url = f"https://api.dropboxapi.com{endpoint}"

        headers = self._get_auth_headers()

        # Prepare request body
        if content is not None:
            # For requests that send both JSON and binary content (like /files/import)
            # The JSON goes in the Dropbox-API-Arg header
            if data:
                headers["Dropbox-API-Arg"] = json.dumps(data)
                headers["Content-Type"] = "application/octet-stream"
            request_body = content
        elif data:
            request_body = json.dumps(data).encode('utf-8')
        else:
            request_body = b''

        req = urllib.request.Request(url, data=request_body, headers=headers, method='POST')

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                self.api_call_count += 1
                response_body = response.read().decode('utf-8')

                # Some endpoints return empty response
                if not response_body:
                    return {}

                return json.loads(response_body)

        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else ''

            if e.code == 401 and retry_auth and self.refresh_token:
                self._access_token = None  # Force token refresh
                return self._request_api(endpoint, data, content, retry_auth=False)
            elif e.code == 401:
                raise ValueError(
                    f"Dropbox authentication failed (401 Unauthorized). "
                    f"Check your access token or refresh token configuration."
                )
            elif e.code == 403:
                raise ValueError(
                    f"Dropbox access forbidden (403). Check app permissions. "
                    f"Error: {error_body}"
                )
            elif e.code == 404:
                raise ValueError(f"Resource not found (404): {endpoint}")
            elif e.code == 409:
                # Parse error for more specific message
                try:
                    error_data = json.loads(error_body) if error_body else {}
                    error_summary = error_data.get('error_summary', 'Conflict')
                    raise ValueError(f"Dropbox API conflict (409): {error_summary}")
                except json.JSONDecodeError:
                    raise ValueError(f"Dropbox API conflict (409): {error_body}")
            elif e.code == 429:
                raise ValueError(
                    f"Rate limit exceeded (429). Please wait and retry. "
                    f"Error: {error_body}"
                )
            elif 400 <= e.code < 500:
                # Other client errors
                try:
                    error_data = json.loads(error_body) if error_body else {}
                    error_summary = error_data.get('error_summary', error_body)
                    raise ValueError(f"Dropbox API error ({e.code}): {error_summary}")
                except json.JSONDecodeError:
                    raise ValueError(f"Dropbox API error ({e.code}): {error_body}")
            else:
                # Server errors (5xx)
                raise RuntimeError(f"Dropbox server error ({e.code}): {error_body}")

        except urllib.error.URLError as e:
            raise ConnectionError(f"Network error connecting to Dropbox: {e.reason}")

    def _request_content(self, endpoint: str, api_arg: dict, upload_content: bytes = None,
                         retry_auth: bool = True) -> tuple:
        """Make content request to content.dropboxapi.com.

        Used for file download and upload operations.

        Args:
            endpoint: API endpoint (e.g., "/2/files/download")
            api_arg: JSON data for Dropbox-API-Arg header
            upload_content: Optional binary content for uploads
            retry_auth: Whether to retry once on 401 (token refresh)

        Returns:
            tuple of (response_metadata: dict, content: bytes)

        Raises:
            ValueError: For 4xx client errors
            RuntimeError: For 5xx server errors
            ConnectionError: For network errors
        """
        url = f"https://content.dropboxapi.com{endpoint}"

        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Dropbox-API-Arg": json.dumps(api_arg)
        }

        if upload_content is not None:
            headers["Content-Type"] = "application/octet-stream"
            req = urllib.request.Request(url, data=upload_content, headers=headers, method='POST')
        else:
            # For downloads, don't pass data parameter at all
            req = urllib.request.Request(url, headers=headers, method='POST')

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                self.api_call_count += 1

                # Get metadata from response header
                result_header = response.headers.get('Dropbox-API-Result', '{}')
                metadata = json.loads(result_header)

                # Get content from response body
                content = response.read()

                return metadata, content

        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else ''

            if e.code == 401 and retry_auth and self.refresh_token:
                self._access_token = None  # Force token refresh
                return self._request_content(endpoint, api_arg, upload_content, retry_auth=False)
            elif e.code == 401:
                raise ValueError(
                    f"Dropbox authentication failed (401 Unauthorized). "
                    f"Check your access token or refresh token configuration."
                )
            elif e.code == 409:
                # Parse error for more specific message
                try:
                    error_data = json.loads(error_body) if error_body else {}
                    error_summary = error_data.get('error_summary', 'Conflict')
                    raise ValueError(f"Dropbox API conflict (409): {error_summary}")
                except json.JSONDecodeError:
                    raise ValueError(f"Dropbox API conflict (409): {error_body}")
            elif 400 <= e.code < 500:
                try:
                    error_data = json.loads(error_body) if error_body else {}
                    error_summary = error_data.get('error_summary', error_body)
                    raise ValueError(f"Dropbox API error ({e.code}): {error_summary}")
                except json.JSONDecodeError:
                    raise ValueError(f"Dropbox API error ({e.code}): {error_body}")
            else:
                raise RuntimeError(f"Dropbox server error ({e.code}): {error_body}")

        except urllib.error.URLError as e:
            raise ConnectionError(f"Network error connecting to Dropbox: {e.reason}")

    @staticmethod
    def resolve_tracking_url(tracking_url: str) -> str:
        """Resolve a links.dropbox.com tracking URL to its final destination.

        Paper notification emails contain _paper_track URLs that redirect
        to dropbox.com/scl/fi/... share links. This method follows the
        redirect without auto-following to extract the Location header.

        Args:
            tracking_url: A links.dropbox.com/u/click?_paper_track=... URL

        Returns:
            str with the resolved URL (typically a dropbox.com/scl/fi/... URL)

        Raises:
            ValueError: If the URL doesn't redirect or isn't a tracking URL
        """
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None  # Don't follow, just capture

        opener = urllib.request.build_opener(_NoRedirect)
        req = urllib.request.Request(tracking_url)
        try:
            resp = opener.open(req, timeout=10)
            # No redirect -- unexpected
            raise ValueError(f"Tracking URL did not redirect (status {resp.status})")
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                location = e.headers.get('Location', '')
                if not location:
                    raise ValueError("Redirect had no Location header")
                return location
            raise ValueError(f"Tracking URL returned HTTP {e.code}")
        except urllib.error.URLError as e:
            raise ConnectionError(f"Network error resolving tracking URL: {e.reason}")

    def _is_paper_link(self, link: str) -> bool:
        """Check if link is for Paper doc based on URL.

        Args:
            link: Share link URL

        Returns:
            True if Paper doc link, False otherwise
        """
        return 'paper.dropbox.com' in link.lower()

    def _is_paper_file(self, metadata: dict) -> bool:
        """Check if file metadata indicates a Paper doc.

        Args:
            metadata: File metadata from API

        Returns:
            True if Paper doc, False otherwise
        """
        # Paper docs have export_info field
        return 'export_info' in metadata or metadata.get('.tag') == 'paper'

    def get_metadata(self, path: str) -> dict:
        """Get file or folder metadata.

        Args:
            path: Dropbox path (e.g., "/Documents/notes.txt")

        Returns:
            dict with metadata (name, size, modified time, etc.)

        Raises:
            ValueError: If path not found or invalid
        """
        data = {"path": path}
        return self._request_api("/2/files/get_metadata", data)

    def resolve_share_link(self, share_link: str) -> dict:
        """Resolve share link to get path and metadata.

        Works for both regular files and Paper docs.

        Args:
            share_link: Dropbox share link URL

        Returns:
            dict with path, name, and metadata

        Raises:
            ValueError: If link is invalid or inaccessible
        """
        data = {"url": share_link}
        return self._request_api("/2/sharing/get_shared_link_metadata", data)

    def get_file_contents(self, path: str, export_format: str = None) -> bytes:
        """Get file content by Dropbox path.

        For Paper docs, automatically exports using /files/export.

        Args:
            path: Dropbox path (e.g., "/Documents/notes.txt")
            export_format: For Paper docs - 'markdown' or 'html' (optional)

        Returns:
            bytes with file content

        Raises:
            ValueError: If path not found or is not a file
        """
        # First check if this is a Paper doc
        metadata = self.get_metadata(path)

        if self._is_paper_file(metadata):
            # Use /files/export endpoint for Paper docs (uses content API)
            api_arg = {
                "path": path
            }

            # Add export_format if specified
            if export_format:
                api_arg["export_format"] = export_format

            url = "https://content.dropboxapi.com/2/files/export"
            headers = {
                "Authorization": f"Bearer {self._get_access_token()}",
                "Dropbox-API-Arg": json.dumps(api_arg)
            }

            req = urllib.request.Request(url, headers=headers, method='POST')

            try:
                self.api_call_count += 1
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    content = response.read()
                    return content
            except urllib.error.HTTPError as e:
                error_body = e.read().decode('utf-8') if e.fp else ''
                if e.code == 404:
                    raise ValueError(
                        f"File export failed (404). This may indicate:\n"
                        f"1. The file is not exportable (check metadata)\n"
                        f"2. Missing app permissions for Paper/cloud doc export\n"
                        f"3. Invalid path: {path}\n"
                        f"Error: {error_body}"
                    )
                elif e.code == 409:
                    try:
                        error_data = json.loads(error_body) if error_body else {}
                        error_summary = error_data.get('error_summary', 'Conflict')
                        raise ValueError(f"Dropbox API conflict (409): {error_summary}")
                    except json.JSONDecodeError:
                        raise ValueError(f"Dropbox API conflict (409): {error_body}")
                elif 400 <= e.code < 500:
                    raise ValueError(f"Dropbox API error ({e.code}): {error_body}")
                else:
                    raise RuntimeError(f"Dropbox server error ({e.code}): {error_body}")
            except urllib.error.URLError as e:
                raise ConnectionError(f"Network error connecting to Dropbox: {e.reason}")
        else:
            # Use regular download for non-Paper files
            api_arg = {"path": path}
            metadata, content = self._request_content("/2/files/download", api_arg)
            return content

    def get_paper_contents(self, path: str, export_format: str = 'markdown') -> str:
        """Get Paper doc content.

        Args:
            path: Dropbox path or file ID to Paper doc (e.g., "/Paper/MyDoc.paper" or "id:...")
            export_format: Export format - 'markdown' (default) or 'html'

        Returns:
            str with Paper doc content in requested format

        Raises:
            ValueError: If path not found or is not a Paper doc
        """
        # Use get_file_contents which handles Paper docs via /files/export
        content_bytes = self.get_file_contents(path, export_format=export_format)
        return content_bytes.decode('utf-8')

    def get_paper_contents_from_link(self, share_link: str, export_format: str = 'markdown') -> str:
        """Get Paper doc content via share link.

        Tries the file ID approach first (/files/export), which returns clean
        markdown. If that fails (e.g., file is in another user's namespace),
        falls back to export_shared_link (/sharing/export_shared_link) which
        returns HTML that is then converted to approximate markdown.

        Args:
            share_link: Dropbox Paper share link URL
            export_format: Export format - 'markdown' (default) or 'html'

        Returns:
            str with Paper doc content in requested format

        Raises:
            ValueError: If link is invalid or not a Paper doc
        """
        # First resolve to get the ID
        link_metadata = self.resolve_share_link(share_link)

        # Try to get the file ID
        file_id = link_metadata.get('id')
        if file_id:
            path = f"{file_id}"
        else:
            path = link_metadata.get('path_lower') or link_metadata.get('path')
            if not path:
                raise ValueError("Could not extract path or ID from share link metadata")

        # Try the clean export path first
        try:
            return self.get_paper_contents(path, export_format)
        except (ValueError, RuntimeError):
            pass

        # Fallback: use export_shared_link (works for docs in other namespaces)
        content = self.export_shared_link(share_link)
        html_text = content.decode('utf-8', errors='ignore')

        if export_format == 'html':
            return html_text

        # Convert Paper HTML to approximate markdown
        return self._paper_html_to_markdown(html_text)

    @staticmethod
    def _paper_html_to_markdown(html_text: str) -> str:
        """Convert Paper doc HTML from export_shared_link to approximate markdown.

        Handles Paper-specific HTML structures:
        - Comment thread markers (attrcomment spans) → [comment] annotation
        - Inline code (span.inline-code) → backtick code
        - Tables (standard HTML tables with ace-line content) → markdown tables
        - Nested lists (listindent1-4) → indented bullet points
        - Headings, bold, italic, links → standard markdown
        """
        import re as _re
        from html import unescape

        # Extract body content
        body_match = _re.search(r'<body[^>]*>(.*)</body>', html_text, _re.DOTALL)
        text = body_match.group(1) if body_match else html_text

        # --- Phase 1: Convert structured elements before stripping tags ---

        # Comment thread markers: Paper marks commented-on text with attrcomment
        # spans. The actual comment content is not in the export, only the marker.
        # Unwrap the attrcomment span and its inner comment-extra-inner-span,
        # then append a [comment] marker to the text content.
        def _replace_comment_span(m):
            inner = m.group(1)
            # Strip the inner comment-extra-inner-span wrapper if present
            inner = _re.sub(r"<span[^>]*class=['\"]comment-extra-inner-span['\"][^>]*>", '', inner)
            inner = inner.replace('</span>', '', 1) if 'comment-extra-inner-span' not in inner else inner
            return inner + ' [comment]'

        text = _re.sub(
            r"<span[^>]*class=\"[^\"]*attrcomment[^\"]*\"[^>]*>(.*?)</span>\s*</span>",
            _replace_comment_span,
            text, flags=_re.DOTALL
        )

        # Inline code spans
        text = _re.sub(
            r'<span[^>]*class="inline-code"[^>]*>(.*?)</span>',
            r'`\1`',
            text
        )

        # Tables: convert to markdown tables
        text = _re.sub(
            r'<table[^>]*>(.*?)</table>',
            lambda m: DropboxClient._convert_table_to_markdown(m.group(0)),
            text, flags=_re.DOTALL
        )

        # Headings (Paper uses h1/h2/h3 inside line-list-type divs, or inline)
        text = _re.sub(r'<h1[^>]*>(.*?)</h1>', r'\n# \1\n', text, flags=_re.DOTALL)
        text = _re.sub(r'<h2[^>]*>(.*?)</h2>', r'\n## \1\n', text, flags=_re.DOTALL)
        text = _re.sub(r'<h3[^>]*>(.*?)</h3>', r'\n### \1\n', text, flags=_re.DOTALL)

        # Paper title (40px font-size div)
        text = _re.sub(
            r'<div[^>]*font-size:\s*40px[^>]*>(.*?)</div>',
            r'\n# \1\n',
            text, flags=_re.DOTALL
        )

        # Paper section headers (24px font-size div)
        text = _re.sub(
            r'<div[^>]*font-size:\s*24px[^>]*>(.*?)</div>',
            r'\n## \1\n',
            text, flags=_re.DOTALL
        )

        # Nested lists: handle indentation levels before flattening
        for level in range(4, 0, -1):
            indent = '  ' * (level - 1)
            text = _re.sub(
                rf'<li[^>]*class="[^"]*listindent{level}[^"]*"[^>]*>(.*?)</li>',
                rf'{indent}- \1\n',
                text, flags=_re.DOTALL
            )
        # Also handle li with listindent in parent ul
        for level in range(4, 0, -1):
            indent = '  ' * (level - 1)
            text = _re.sub(
                rf'<ul[^>]*class="[^"]*listindent{level}[^"]*"[^>]*>\s*<li[^>]*>(.*?)</li>\s*</ul>',
                rf'{indent}- \1\n',
                text, flags=_re.DOTALL
            )

        # Remaining list items (no indentation class)
        text = _re.sub(r'<li[^>]*>(.*?)</li>', r'- \1\n', text, flags=_re.DOTALL)

        # Paragraphs and line breaks
        text = _re.sub(r'<br\s*/?>', '\n', text)
        text = _re.sub(r'<p[^>]*>(.*?)</p>', r'\1\n\n', text, flags=_re.DOTALL)

        # Inline formatting
        text = _re.sub(r'<strong>(.*?)</strong>', r'**\1**', text)
        text = _re.sub(r'<b>(.*?)</b>', r'**\1**', text)
        text = _re.sub(r'<em>(.*?)</em>', r'*\1*', text)
        text = _re.sub(r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', r'[\2](\1)', text)

        # Div-based line breaks (Paper uses divs for lines)
        text = _re.sub(r'</div>\s*<div', '</div>\n<div', text)

        # --- Phase 2: Strip remaining HTML tags ---
        text = _re.sub(r'<[^>]+>', '', text)
        text = unescape(text)

        # --- Phase 3: Clean up ---
        # Merge adjacent bold markers from Paper's split <b> tags: **foo****bar** → **foo bar**
        text = _re.sub(r'\*\*\s*\*\*', ' ', text)
        text = _re.sub(r'[ \t]+\n', '\n', text)   # trailing whitespace
        text = _re.sub(r'\n{3,}', '\n\n', text)    # excessive blank lines
        return text.strip()

    @staticmethod
    def _convert_table_to_markdown(table_html: str) -> str:
        """Convert an HTML table to a markdown table.

        Paper tables use <td> cells containing <div class="ace-line"><span>text</span></div>.

        Args:
            table_html: HTML string of a single <table>...</table>

        Returns:
            Markdown table string
        """
        import re as _re
        from html import unescape

        rows = _re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, _re.DOTALL)
        if not rows:
            return ''

        md_rows = []
        for row_html in rows:
            cells = _re.findall(r'<td[^>]*>(.*?)</td>', row_html, _re.DOTALL)
            cell_texts = []
            for cell in cells:
                # Extract text from spans within ace-line divs
                text = _re.sub(r'<[^>]+>', '', cell)
                text = unescape(text).strip()
                # Replace pipes that would break table formatting
                text = text.replace('|', '\\|')
                cell_texts.append(text)
            if cell_texts:
                md_rows.append('| ' + ' | '.join(cell_texts) + ' |')

        if not md_rows:
            return ''

        # Add separator after header row
        num_cols = md_rows[0].count('|') - 1
        separator = '| ' + ' | '.join(['---'] * num_cols) + ' |'
        result = [md_rows[0], separator] + md_rows[1:]
        return '\n' + '\n'.join(result) + '\n'

    def export_shared_link(
        self,
        url: str,
        path: Optional[str] = None,
        link_password: Optional[str] = None,
        override_download_setting: bool = False
    ) -> bytes:
        """Export content from file accessed via shared link.

        Downloads file content directly from a shared link without resolving to path first.
        Primary use case: Accessing files in team space that you don't own.
        This is the ONLY way to get content of a Paper doc you don't own.

        IMPORTANT for Paper docs:
        - The returned HTML includes extensive CSS and formatting not present in get-paper-contents
        - Use get-paper-contents for Paper docs you own when doing read-write workflows
        - Use export-shared-link for Paper docs you don't own (read-only team space access)

        Args:
            url: Dropbox share link URL
            path: Optional path within shared folder to specific file
            link_password: Optional password for password-protected links
            override_download_setting: Internal flag to override download restrictions

        Returns:
            bytes with file content

        Raises:
            ValueError: If link not found, access denied, or file not exportable
        """
        # Build API arguments - only include optional params if provided
        api_arg = {"url": url}

        if path is not None:
            api_arg["path"] = path

        if link_password is not None:
            api_arg["link_password"] = link_password

        if override_download_setting:
            api_arg["override_download_setting"] = True

        # Use _request_content for consistent error handling
        metadata, content = self._request_content("/2/sharing/export_shared_link", api_arg)

        return content

    def create_paper_contents(self, path: str, content: Union[bytes, str], import_format: str = 'markdown') -> dict:
        """Create new Paper doc.

        Args:
            path: Dropbox path for new Paper doc (e.g., "/Paper/NewDoc.paper")
            content: Paper doc content (str or bytes)
            import_format: Import format - 'markdown' (default) or 'html' (ignored, kept for API compatibility)

        Returns:
            dict with file metadata

        Raises:
            ValueError: If path already exists or creation fails
        """
        # Use write_file_contents with mode='add' to create new file
        return self.write_file_contents(path, content, mode='add')

    def update_paper_contents(self, path: str, content: Union[bytes, str], import_format: str = 'html') -> dict:
        """Update existing Paper doc using Paper API.

        Uses the /2/files/paper/update endpoint with overwrite policy.
        Automatically strips the title (first 40px font-size div) from HTML content.

        Args:
            path: Dropbox path to existing Paper doc (e.g., "/Paper/MyDoc.paper")
            content: New Paper doc content (str or bytes) - HTML or markdown
            import_format: Import format - 'html' (default) or 'markdown'

        Returns:
            dict with file metadata

        Raises:
            ValueError: If path not found, is in team space, or update fails
        """
        # Check if this is a team space Paper doc (no proper path)
        # Team space docs don't have a regular file path and cannot be updated
        try:
            metadata = self.get_metadata(path)
            # Check if this is a Paper doc without a proper path (team space)
            if self._is_paper_file(metadata):
                # Team space docs won't have path_lower or path_display
                if not metadata.get('path_lower') and not metadata.get('path_display'):
                    raise ValueError(
                        f"Cannot update Paper doc in team space. "
                        f"Paper docs in the team space (shared docs you don't own) cannot be updated via API. "
                        f"Only Paper docs in your own Dropbox can be updated."
                    )
        except ValueError as e:
            # Re-raise if it's our team space error or a legitimate API error
            if "team space" in str(e):
                raise
            # For other errors, let them propagate during the actual update call
            pass

        # Convert bytes to str if needed for processing
        if isinstance(content, bytes):
            content_str = content.decode('utf-8')
        else:
            content_str = content

        # For HTML format, strip out the title div (40px font-size)
        # Paper API will use the document's own title, so we don't want it duplicated in the body
        if import_format == 'html':
            # Remove the first div with font-size: 40px (the title)
            content_str = re.sub(
                r'<div[^>]*font-size:\s*40px[^>]*>.*?</div>',
                '',
                content_str,
                count=1,
                flags=re.DOTALL
            )

        # Convert to bytes for sending
        content_bytes = content_str.encode('utf-8')

        # Prepare API arg for Dropbox-API-Arg header
        api_arg = {
            "path": path,
            "import_format": import_format,
            "doc_update_policy": "overwrite"
        }

        url = "https://api.dropboxapi.com/2/files/paper/update"
        headers = {
            "Authorization": f"Bearer {self._get_access_token()}",
            "Dropbox-API-Arg": json.dumps(api_arg),
            "Content-Type": "application/octet-stream"
        }

        req = urllib.request.Request(url, data=content_bytes, headers=headers, method='POST')

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                self.api_call_count += 1
                response_body = response.read().decode('utf-8')

                # Parse response as JSON
                if response_body:
                    return json.loads(response_body)
                return {}

        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else ''

            if e.code == 401:
                raise ValueError(
                    f"Dropbox authentication failed (401 Unauthorized). "
                    f"Check your access token."
                )
            elif e.code == 409:
                try:
                    error_data = json.loads(error_body) if error_body else {}
                    error_summary = error_data.get('error_summary', 'Conflict')
                    raise ValueError(f"Dropbox API conflict (409): {error_summary}")
                except json.JSONDecodeError:
                    raise ValueError(f"Dropbox API conflict (409): {error_body}")
            elif 400 <= e.code < 500:
                try:
                    error_data = json.loads(error_body) if error_body else {}
                    error_summary = error_data.get('error_summary', error_body)
                    raise ValueError(f"Dropbox API error ({e.code}): {error_summary}")
                except json.JSONDecodeError:
                    raise ValueError(f"Dropbox API error ({e.code}): {error_body}")
            else:
                raise RuntimeError(f"Dropbox server error ({e.code}): {error_body}")

        except urllib.error.URLError as e:
            raise ConnectionError(f"Network error connecting to Dropbox: {e.reason}")


def _format_metadata(metadata: dict) -> str:
    """Format metadata for readable display.

    Args:
        metadata: File metadata from API

    Returns:
        str with formatted metadata
    """
    lines = []

    # Path/name
    name = metadata.get('name', metadata.get('path_display', 'Unknown'))
    lines.append(name)

    # Type
    file_type = metadata.get('.tag', 'unknown')
    if 'export_info' in metadata or file_type == 'paper':
        lines.append("  Type: paper")
    elif file_type == 'file':
        lines.append("  Type: file")
    elif file_type == 'folder':
        lines.append("  Type: folder")
    else:
        lines.append(f"  Type: {file_type}")

    # Size
    if 'size' in metadata:
        size_bytes = metadata['size']
        if size_bytes < 1024:
            size_str = f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            size_str = f"{size_bytes / 1024:.1f} KB"
        else:
            size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
        lines.append(f"  Size: {size_str}")

    # Modified time
    if 'server_modified' in metadata:
        # Parse ISO timestamp and format nicely
        timestamp = metadata['server_modified']
        # Just show the date and time part (YYYY-MM-DD HH:MM:SS)
        if 'T' in timestamp:
            date_time = timestamp.split('T')
            date = date_time[0]
            time_part = date_time[1].split('.')[0] if '.' in date_time[1] else date_time[1].split('Z')[0]
            lines.append(f"  Modified: {date} {time_part}")

    # Shared status (if available in metadata)
    if 'sharing_info' in metadata:
        lines.append("  Shared: Yes")

    return '\n'.join(lines)


def _read_stdin_content() -> str:
    """Read content from stdin.

    Returns:
        str with stdin content
    """
    return sys.stdin.read()


def main():
    """CLI entry point for Dropbox client."""
    if len(sys.argv) < 2:
        print("Usage: python -m sidekick.clients.dropbox <command> [args...]", file=sys.stderr)
        print("", file=sys.stderr)
        print("Commands:", file=sys.stderr)
        print("  get-file-contents <path>", file=sys.stderr)
        print("  resolve-tracking-url <tracking_url>", file=sys.stderr)
        print("  export-shared-link <url> [--path <path>] [--password <password>] [--override-download]", file=sys.stderr)
        print("  get-metadata <path>", file=sys.stderr)
        print("  get-paper-contents <path> [--format markdown|html]", file=sys.stderr)
        print("  get-paper-contents-from-link <share_link> [--format markdown|html]", file=sys.stderr)
        print("  create-paper-contents <path> [--content <text>] [--format markdown|html]", file=sys.stderr)
        print("  update-paper-contents <path> [--content <text>] [--format markdown|html]", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    # Load config and create client
    try:
        from sidekick.config import get_dropbox_config
        config = get_dropbox_config()
        client = DropboxClient(**config)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    start_time = time.time()

    try:
        if command == "get-file-contents":
            if len(sys.argv) < 3:
                print("Error: Missing path argument", file=sys.stderr)
                sys.exit(1)

            path = sys.argv[2]
            content = client.get_file_contents(path)

            # Write binary content to stdout
            sys.stdout.buffer.write(content)

        elif command == "get-metadata":
            if len(sys.argv) < 3:
                print("Error: Missing path argument", file=sys.stderr)
                sys.exit(1)

            path = sys.argv[2]
            metadata = client.get_metadata(path)
            print(_format_metadata(metadata))

        elif command == "get-paper-contents":
            if len(sys.argv) < 3:
                print("Error: Missing path argument", file=sys.stderr)
                sys.exit(1)

            path = sys.argv[2]
            export_format = "markdown"

            # Check for --format flag
            i = 3
            while i < len(sys.argv):
                if sys.argv[i] == "--format" and i + 1 < len(sys.argv):
                    export_format = sys.argv[i + 1]
                    i += 2
                else:
                    i += 1

            content = client.get_paper_contents(path, export_format)
            print(content)

        elif command == "get-paper-contents-from-link":
            if len(sys.argv) < 3:
                print("Error: Missing share_link argument", file=sys.stderr)
                sys.exit(1)

            share_link = sys.argv[2]
            export_format = "markdown"

            # Check for --format flag
            i = 3
            while i < len(sys.argv):
                if sys.argv[i] == "--format" and i + 1 < len(sys.argv):
                    export_format = sys.argv[i + 1]
                    i += 2
                else:
                    i += 1

            content = client.get_paper_contents_from_link(share_link, export_format)
            print(content)

        elif command == "create-paper-contents":
            if len(sys.argv) < 3:
                print("Error: Missing path argument", file=sys.stderr)
                sys.exit(1)

            path = sys.argv[2]
            content_text = None
            import_format = "markdown"

            # Parse flags
            i = 3
            while i < len(sys.argv):
                if sys.argv[i] == "--content" and i + 1 < len(sys.argv):
                    content_text = sys.argv[i + 1]
                    i += 2
                elif sys.argv[i] == "--format" and i + 1 < len(sys.argv):
                    import_format = sys.argv[i + 1]
                    i += 2
                else:
                    i += 1

            # Read from stdin if --content not provided
            if content_text is None:
                content_text = _read_stdin_content()

            metadata = client.create_paper_contents(path, content_text, import_format)
            print(f"Created Paper doc at {path}", file=sys.stderr)

        elif command == "update-paper-contents":
            if len(sys.argv) < 3:
                print("Error: Missing path argument", file=sys.stderr)
                sys.exit(1)

            path = sys.argv[2]
            content_text = None
            import_format = "markdown"

            # Parse flags
            i = 3
            while i < len(sys.argv):
                if sys.argv[i] == "--content" and i + 1 < len(sys.argv):
                    content_text = sys.argv[i + 1]
                    i += 2
                elif sys.argv[i] == "--format" and i + 1 < len(sys.argv):
                    import_format = sys.argv[i + 1]
                    i += 2
                else:
                    i += 1

            # Read from stdin if --content not provided
            if content_text is None:
                content_text = _read_stdin_content()

            metadata = client.update_paper_contents(path, content_text, import_format)
            print(f"Updated Paper doc at {path}", file=sys.stderr)

        elif command == "resolve-tracking-url":
            if len(sys.argv) < 3:
                print("Error: Missing tracking_url argument", file=sys.stderr)
                sys.exit(1)

            tracking_url = sys.argv[2]
            resolved = DropboxClient.resolve_tracking_url(tracking_url)
            print(resolved)

        elif command == "export-shared-link":
            if len(sys.argv) < 3:
                print("Error: Missing url argument", file=sys.stderr)
                sys.exit(1)

            url = sys.argv[2]
            path = None
            link_password = None
            override_download_setting = False

            # Parse optional flags
            i = 3
            while i < len(sys.argv):
                if sys.argv[i] == "--path" and i + 1 < len(sys.argv):
                    path = sys.argv[i + 1]
                    i += 2
                elif sys.argv[i] == "--password" and i + 1 < len(sys.argv):
                    link_password = sys.argv[i + 1]
                    i += 2
                elif sys.argv[i] == "--override-download":
                    override_download_setting = True
                    i += 1
                else:
                    i += 1

            content = client.export_shared_link(url, path, link_password, override_download_setting)

            # Write binary content to stdout
            sys.stdout.buffer.write(content)

        else:
            print(f"Error: Unknown command '{command}'", file=sys.stderr)
            sys.exit(1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Debug output
    elapsed_time = time.time() - start_time
    print(f"\n[Debug] API calls: {client.api_call_count}, Time: {elapsed_time:.2f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
