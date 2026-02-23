---
name: markdown-html
description: Convert markdown files to styled HTML
argument-hint: <markdown-file> [output.html] [--open]
allowed-tools: Bash, Read
---

# Markdown to HTML Skill

Convert markdown files to styled, self-contained HTML using pandoc.

When invoked, use the markdown HTML converter to handle the request: $ARGUMENTS

## Available Commands

### Convert Markdown to HTML
```bash
python -m sidekick.clients.markdown_html <input.md> [output.html] [--title TITLE] [--open]
```

## Options

- `input.md` - Path to input markdown file (required)
- `output.html` - Path to output HTML file (optional, defaults to input filename with .html extension)
- `--title TITLE` - Set the HTML page title (optional, extracted from first H1 if not provided)
- `--open` - Open the result in the default browser

## Example Usage

When the user asks to:
- "Convert this report to HTML" - Basic conversion
- "Open the digest in the browser" - Use `--open` flag
- "Make an HTML version of the meeting notes" - Convert and optionally open

## Examples

```bash
# Basic conversion (creates report.html)
python -m sidekick.clients.markdown_html report.md

# Specify output and open in browser
python -m sidekick.clients.markdown_html digest.md /tmp/digest.html --open

# With custom title
python -m sidekick.clients.markdown_html report.md --title "Weekly Report" --open
```

## Features

- YAML frontmatter is automatically stripped (not displayed)
- Self-contained HTML with embedded CSS (no external dependencies)
- Clean, professional styling suited for reports and briefings
- Tables, task lists, links, and code blocks all styled
- Print-friendly styles included

## Requirements

- `pandoc` must be installed: `brew install pandoc`

## Related Skills

- [markdown-pdf](../markdown-pdf/SKILL.md) - Convert markdown to PDF
