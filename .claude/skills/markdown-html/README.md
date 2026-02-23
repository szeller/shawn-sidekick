# Markdown to HTML Skill

Convert markdown files to styled, self-contained HTML using pandoc.

## Configuration

No configuration needed beyond having pandoc installed:

```bash
brew install pandoc
```

## Commands

### Convert Markdown to HTML

```bash
# Basic conversion (creates README.html in same directory)
python -m sidekick.clients.markdown_html README.md

# Specify output file
python -m sidekick.clients.markdown_html report.md /tmp/report.html

# Set page title
python -m sidekick.clients.markdown_html report.md --title "Weekly Report"

# Open in default browser after conversion
python -m sidekick.clients.markdown_html report.md --open

# All options together
python -m sidekick.clients.markdown_html digest.md /tmp/digest.html --title "Daily Digest" --open
```

## Python API

```python
from sidekick.clients.markdown_html import MarkdownHtmlConverter

converter = MarkdownHtmlConverter()

# Basic conversion
output_path = converter.convert('report.md')

# With all options
output_path = converter.convert(
    'digest.md',
    output_path='/tmp/digest.html',
    title='Daily Digest - 2026-02-17',
    open_browser=True
)
```

## Features

- **Self-contained**: All CSS is embedded in the HTML file -- no external stylesheets needed
- **Frontmatter stripping**: YAML frontmatter (`---...---`) is automatically removed
- **Title extraction**: Page title is auto-extracted from the first H1 heading, or set manually
- **Professional styling**: Clean typography, styled tables with alternating rows, clickable links, task list checkboxes, and print-friendly output
- **Browser opening**: `--open` flag opens the result in the default browser

## Styling

The embedded CSS provides:

- System font stack (San Francisco on macOS)
- Centered content card with subtle shadow
- H1 as a title bar with accent border
- H2 sections with bottom borders
- Tables with header shading and alternating row stripes
- Task list checkboxes for action items
- Blue links, underlined on hover
- Blockquotes with left accent border
- Code blocks with monospace font and subtle background
- Print styles that expand links to show URLs

## Related Skills

- [markdown-pdf](../markdown-pdf/README.md) - Convert markdown to PDF
