"""Markdown to HTML converter using pandoc with Pico CSS styling."""

import os
import re
import sys
import subprocess
import shutil
import tempfile
from pathlib import Path
from typing import Optional


# Custom pandoc HTML template using Pico CSS
_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>$pagetitle$</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css" />
  <style>
    :root {
      --pico-font-size: 15px;
    }
    body {
      padding-top: 24px;
      padding-bottom: 48px;
    }
    main {
      max-width: 960px;
    }
    h1 {
      margin-bottom: 0.4em;
      padding-bottom: 0.3em;
      border-bottom: 3px solid var(--pico-primary);
    }
    h2 {
      margin-top: 1.6em;
      padding-bottom: 0.25em;
      border-bottom: 1px solid var(--pico-muted-border-color);
    }
    h3 {
      margin-top: 1.2em;
    }
    /* Tables: full width, striped rows */
    table {
      width: 100%;
    }
    thead th {
      white-space: nowrap;
    }
    tbody tr:nth-child(even) {
      background-color: var(--pico-card-background-color);
    }
    /* Task list checkboxes */
    ul.task-list {
      list-style: none;
      padding-left: 0.5em;
    }
    .task-list li {
      margin-bottom: 0.5em;
    }
    .task-list input[type="checkbox"] {
      margin-right: 0.5em;
      accent-color: var(--pico-primary);
    }
    /* Horizontal rules as section dividers */
    hr {
      margin: 2em 0;
    }
    /* List item spacing */
    li {
      margin-bottom: 0.35em;
    }
    li > p {
      margin-bottom: 0.3em;
    }
    /* Nested list content */
    li > ul, li > ol {
      margin-top: 0.2em;
    }
    /* Print styles */
    @media print {
      body { padding: 0; }
      a[href]:after {
        content: " (" attr(href) ")";
        font-size: 0.8em;
        color: var(--pico-muted-color);
      }
    }
  </style>
</head>
<body>
  <main class="container">
$body$
  </main>
</body>
</html>
"""


class MarkdownHtmlConverter:
    """Convert markdown files to styled HTML using pandoc."""

    def __init__(self):
        """Initialize converter, checking for pandoc."""
        if not shutil.which('pandoc'):
            raise RuntimeError(
                "pandoc not found. Install with: brew install pandoc"
            )

    @staticmethod
    def _strip_frontmatter(text: str) -> str:
        """Strip YAML frontmatter from markdown text."""
        return re.sub(
            r'^---\s*\n.*?\n---\s*\n',
            '',
            text,
            flags=re.DOTALL
        )

    def convert(
        self,
        input_path: str,
        output_path: Optional[str] = None,
        title: Optional[str] = None,
        open_browser: bool = False,
    ) -> str:
        """Convert markdown file to styled HTML.

        Args:
            input_path: Path to input markdown file
            output_path: Path to output HTML file (auto-generated if None)
            title: HTML page title (extracted from first H1 if None)
            open_browser: Open the result in the default browser

        Returns:
            Path to the generated HTML file

        Raises:
            FileNotFoundError: If input file doesn't exist
            RuntimeError: If conversion fails
        """
        input_file = Path(input_path)
        if not input_file.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")

        if output_path is None:
            output_path = str(input_file.with_suffix('.html'))

        # Read and strip frontmatter
        content = input_file.read_text(encoding='utf-8')
        clean_content = self._strip_frontmatter(content)

        # Extract title from first H1 if not provided
        if title is None:
            title_match = re.search(r'^#\s+(.+)$', clean_content, re.MULTILINE)
            if title_match:
                title = title_match.group(1).strip()
            else:
                title = input_file.stem

        # Write temp files for pandoc
        tmp_dir = tempfile.mkdtemp()
        try:
            # Write cleaned markdown
            tmp_md = os.path.join(tmp_dir, 'input.md')
            with open(tmp_md, 'w', encoding='utf-8') as f:
                f.write(clean_content)

            # Write custom template
            tmp_template = os.path.join(tmp_dir, 'template.html')
            with open(tmp_template, 'w', encoding='utf-8') as f:
                f.write(_TEMPLATE)

            # Build pandoc command
            cmd = [
                'pandoc',
                tmp_md,
                '-o', output_path,
                '--standalone',
                '--from', 'gfm+task_lists',
                f'--template={tmp_template}',
                f'--metadata=pagetitle:{title}',
            ]

            try:
                subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                raise RuntimeError(
                    f"Pandoc conversion failed:\n{e.stderr}\n\n"
                    f"Command: {' '.join(cmd)}"
                )

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        if open_browser:
            subprocess.run(['open', output_path], check=False)

        return output_path


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage:", file=sys.stderr)
        print("  python -m sidekick.clients.markdown_html <input.md> [output.html] [--title TITLE] [--open]", file=sys.stderr)
        print("", file=sys.stderr)
        print("Options:", file=sys.stderr)
        print("  --title TITLE  Set the HTML page title", file=sys.stderr)
        print("  --open         Open the result in the default browser", file=sys.stderr)
        print("", file=sys.stderr)
        print("Examples:", file=sys.stderr)
        print("  python -m sidekick.clients.markdown_html report.md", file=sys.stderr)
        print("  python -m sidekick.clients.markdown_html report.md output.html --open", file=sys.stderr)
        print('  python -m sidekick.clients.markdown_html digest.md --title "Daily Digest" --open', file=sys.stderr)
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = None
    title = None
    open_browser = False

    # Parse arguments
    i = 2
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == '--title' and i + 1 < len(sys.argv):
            title = sys.argv[i + 1]
            i += 2
        elif arg == '--open':
            open_browser = True
            i += 1
        elif not arg.startswith('--'):
            output_path = arg
            i += 1
        else:
            i += 1

    try:
        converter = MarkdownHtmlConverter()
        output = converter.convert(input_path, output_path, title, open_browser)
        print(output)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
