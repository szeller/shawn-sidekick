---
name: daily_digest
description: Morning digest of emails, calendar, and JIRA updates across all data sources
argument-hint: [date]
allowed-tools: Bash, Read
---

# Daily Digest Agent

Generate a morning briefing by pulling updates from Gmail labels, inbox, and Google Calendar.

## Overview

This agent reviews data sources and produces a single digest report:
1. Today's calendar + tomorrow preview (timed meetings only; skip declined; PTO from all-day events)
2. Inbox emails (unread -- summarized but NOT marked read)
3. Paper doc update notifications (Gmail label `paper-updates`)
4. Confluence update notifications (Gmail label `confluence`)
5. Incident notifications (Gmail label `sev-announce`) -- filtered to Commerce-relevant SEVs
6. Microsoft To Do tasks with due dates (from "Dropbox 2026" list)

**Not included**: JIRA email notifications (low signal, skip for now).

All label-based emails (paper-updates, confluence, sev-announce) are marked as read at the end after the full report is generated. This makes the agent re-runnable -- if interrupted before the final mark-read step, re-running picks up the same messages.

Inbox emails are never marked read (user handles those manually via inbox-zero).

## Prerequisites

- Google OAuth2 credentials configured in `.env` (Gmail + Calendar)
- Gmail labels exist: `paper-updates`, `confluence`, `sev-announce`
- Dropbox credentials configured in `.env` (for fetching Paper docs)
- Atlassian credentials configured in `.env` (for fetching Confluence pages)
- Microsoft To Do credentials configured in `.env` (for tasks with due dates)

## Usage Pattern

### Step 0: Setup

Determine the target date. If an argument was provided, use it. Otherwise **always use the system clock** (`date` command) -- never use a date from conversation context or CLAUDE.local.md, as those may be stale.

```bash
# Set TARGET_DATE - use argument if provided, otherwise today from system clock
TARGET_DATE=$(date +%Y-%m-%d)
DAY_OF_WEEK=$(date +%A)
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

# Create temp directory for intermediate files
TMP_DIR=/tmp/daily_digest_$$
mkdir -p $TMP_DIR
```

### Step 1: Fetch Today's Calendar + Tomorrow Preview

Get calendar events for today and tomorrow. Use the local timezone (America/Los_Angeles).

```bash
# Today
python3 -m sidekick.clients.gcalendar list \
  "${TARGET_DATE}T00:00:00-08:00" \
  "${TARGET_DATE}T23:59:59-08:00" \
  30 > $TMP_DIR/calendar_today.txt

# Tomorrow
TOMORROW=$(date -v+1d +%Y-%m-%d)
python3 -m sidekick.clients.gcalendar list \
  "${TOMORROW}T00:00:00-08:00" \
  "${TOMORROW}T23:59:59-08:00" \
  30 > $TMP_DIR/calendar_tomorrow.txt
```

Read the calendar output. Process events as follows:

**Skip declined events**: If the user's response status is "declined", omit the event entirely.

**All-day events**: Mostly ignore. The only all-day events to include are those that indicate someone is on PTO/leave (look for "Time-Off", "OOO", "PTO", "Leave", "Vacation" in the title). List these as a brief "Out today" note at the top of the calendar section.

**Timed events**: List each with:
- Time (start - end, in local time)
- Event title/summary
- Number of attendees (distinguish 1:1 vs group meetings)
- Description links (include links to agenda docs if present)

**Tomorrow's preview**: Show a brief list of tomorrow's meetings (time + title only) so the user can see what's coming.

### Step 2: Fetch Inbox Emails

Search for unread emails in inbox.

```bash
python3 -m sidekick.clients.gmail search "in:inbox is:unread" 50 > $TMP_DIR/inbox.txt
```

Read the output. For each email:
- Read the full message body (not just snippet)
- Extract sender, subject
- Write a 1-2 sentence summary of what the email is about and any action needed
- Note the message ID for reference

**Do NOT mark inbox emails as read.** The user operates on inbox-zero and handles these manually.

### Step 3: Fetch Paper Update Notifications

Search for unread emails in the `paper-updates` label:

```bash
python3 -m sidekick.clients.gmail search "label:paper-updates is:unread" 50 > $TMP_DIR/paper_updates.txt
```

Read the output. For each notification:
- **Get the Paper doc URL**: Paper notification emails use HTML-only bodies. Read the full message (including HTML parts) to find the doc URL. The emails contain `links.dropbox.com/u/click?_paper_track=...` tracking URLs. Resolve these to `dropbox.com/scl/fi/...` share links:
```bash
python3 -m sidekick.clients.dropbox resolve-tracking-url "TRACKING_URL"
```
  If a `_paper_track` URL is not available, check CLAUDE.local.md for known doc URLs (1:1 docs, meeting docs).
- Note the message ID (save for mark-as-read at the end)
- **Determine the notification type**:

**For edit notifications**: The email says "N edits" but does NOT tell you what changed. You MUST fetch the actual Paper doc to summarize what the edits contain:
```bash
python3 -m sidekick.clients.dropbox get-paper-contents-from-link "PAPER_URL"
```
Then provide a meaningful summary of the recent content. The goal is that the user does NOT need to re-open the doc. Don't just say "1 edit by Person" -- describe what was actually added or changed. For 1:1 docs, list the actual topics that were added. For meeting docs (which are often pre-reads rather than agendas), summarize the key content, discussion points, or decisions that were added.

**For comment notifications**: Summarize what the comment says (visible in the email body).

**For new doc share notifications** (someone shared a doc with you for the first time): Fetch the full doc and provide a 1-3 paragraph summary depending on doc length (roughly 1 paragraph per page of content).

**Important**: Include the Paper doc URL as a link in the report for every entry so the user can click through to the original.

**Triage each doc as "Needs Attention" or "FYI"** as you process it. A doc needs attention if: someone is waiting on Shawn's response, a comment is directed at him or replies to his comment, a decision was made that he should weigh in on, or something requires his action. Everything else is FYI. Format each entry with bullet points and sub-lists -- never write a paragraph of prose. Lead with the action or key takeaway.

### Step 4: Fetch Confluence Update Notifications

Search for unread emails in the `confluence` label:

```bash
python3 -m sidekick.clients.gmail search "label:confluence is:unread" 50 > $TMP_DIR/confluence_updates.txt
```

Read the output. For each notification:
- Extract the Confluence page URL from the email body
- Note the message ID (save for mark-as-read at the end)

**For page edit notifications**: Fetch the Confluence page for context if the email doesn't make the changes clear:
```bash
python3 -m sidekick.clients.confluence get-content-from-link "CONFLUENCE_URL"
```

**For comment notifications**:
- Summarize what the comment actually says (extract from email body)
- **Explicitly flag if the comment appears to be a response to one of Shawn's own comments** (look for reply-to patterns, @-mentions of Shawn, or threading indicators)
- If someone @-mentioned Shawn, call this out prominently as requiring a response

**Important**: Include the Confluence page URL as a link in the report for every entry.

### Step 5: Fetch Incident Notifications (sev-announce)

Search for unread emails in the `sev-announce` label:

```bash
python3 -m sidekick.clients.gmail search "label:sev-announce is:unread" 50 > $TMP_DIR/sev_announce.txt
```

Read the output. **Only include SEVs related to Commerce or monetization.** Include a SEV if:
- The topic sounds like one of the user's teams owns it or is potentially involved (check CLAUDE.local.md for sub-team mapping)
- Keywords to look for: check CLAUDE.local.md for team names, JIRA projects, and domain keywords that indicate relevance

**Skip everything else** -- even SEV1s, unless they touch Commerce or monetization. The digest is already long; non-Commerce incidents are noise.

For each relevant SEV:
- Severity level (SEV1/SEV2/SEV3)
- Incident name
- Brief description of what's affected
- Teams involved
- Note the message ID (save for mark-as-read at the end)

### Step 5b: Fetch Tasks with Due Dates

Get outstanding tasks from the "Dropbox 2026" Microsoft To Do list, filtered to only those with due dates:

```bash
python3 -m sidekick.clients.mstodo list \
  --list AQMkADAwATMwMAItZGYwOC1lZQBiZi0wMAItMDAKAC4AAAOJWr01L1CHQqhm9pObh6XgAQBCQ7fh_16lRYyJ5A_dwCBaAAe26DMDAAAA \
  --status notCompleted > $TMP_DIR/tasks.txt
```

Read the output. **Only include tasks that are overdue or due within the next 2 days** (today, tomorrow, or the day after). Skip tasks without due dates and tasks due further out -- those are backlog and just add noise to the digest.

Sort by due date (overdue first, then soonest). Flag any overdue tasks prominently.

### Step 6: Identify Action Items

Review all sections of the digest and compile a list of **action items (AIs)** -- things that require Shawn's direct response or action. These include:
- @-mentions asking a question
- Comments that appear to be waiting for Shawn's response
- Assignments or requests directed at Shawn
- Review requests
- Approvals needed

For each action item:
- Describe what needs to be done
- Include a link to the source (Confluence page, Paper doc, JIRA issue, or email)
- Note who is waiting on the response

**Ask the user if they want a Microsoft To Do task created for each AI.** If yes, create them:
```bash
python3 -m sidekick.clients.mstodo create "AI description" \
  --list AQMkADAwATMwMAItZGYwOC1lZQBiZi0wMAItMDAKAC4AAAOJWr01L1CHQqhm9pObh6XgAQBCQ7fh_16lRYyJ5A_dwCBaAAe26DMDAAAA \
  --body "Context and link to source"
```

### Step 7: Generate Digest Report

Compile all findings into a single Markdown report with clickable links throughout.

**Section order: Summary → Action Items → Calendar → Inbox → Paper → Confluence → Incidents → Tasks**

```markdown
---
prompt: "Daily digest"
client: daily-digest
command: daily-digest
created: YYYY-MM-DD HH:MM:SS
updated: YYYY-MM-DD HH:MM:SS
---

# Daily Digest - YYYY-MM-DD (Day of Week)

## Summary

- **Calendar**: N meetings today (N 1:1s, N group); N tomorrow
- **Inbox**: N unread emails (not marked read)
- **Paper updates**: N notifications across N docs
- **Confluence updates**: N
- **Incidents**: N Commerce-relevant SEVs
- **Tasks due**: N (N overdue)
- **All label notifications marked as read**

---

## Action Items

- [ ] **Respond to Alice** re: question about X on [Page Title](confluence-url)
- [ ] **Review migration timeline** -- overdue task (was due MM/DD)

---

## Today's Calendar

**Out today:** Alice (PTO), Bob (Leave)

| Time | Meeting | Attendees | Notes |
|------|---------|-----------|-------|
| 9:00-9:30 | Eng Leadership Team | 8 attendees | [Agenda](link) |
| 10:00-10:30 | 1:1 with Alice | 1:1 | |

**N meetings today** (N 1:1s, N group meetings)

### Tomorrow Preview

| Time | Meeting |
|------|---------|
| 9:00-9:30 | Earnings Call |
| 10:00-10:30 | SEV Review |

---

## Inbox (N unread)

**These emails have NOT been marked as read.**

- **From Alice** - Re: Q1 Planning follow-up
  Summary of what the email is about and any action needed.

---

## Paper Updates (N notifications)

### Needs Attention

Docs where someone is waiting on Shawn, a decision was made that affects his teams, or action is needed.

- **[Doc Title](paper-url)** -- comment by Alice (edit/comment)
  - **Action**: What Shawn needs to do or respond to
  - **Context**: Key details in scannable bullet points
  - **Who's waiting**: Alice, since MM/DD

### FYI

Routine updates, status changes, and background context. No action needed.

- **[Doc Title](paper-url)** -- N edits by Alice
  - One-sentence summary of what changed
  - Key data points as sub-bullets if relevant

---

## Confluence Updates (N notifications)

- **[Page Title](confluence-url)** -- comment by Alice
  Summary of the comment. **This is a reply to your comment about X.**

- **[Page Title](confluence-url)** -- **@-mentioned you**: "Quoted question"
  ACTION NEEDED: respond to this question.

---

## Incidents (N Commerce-relevant)

- **SEV2 (Witty Crocodile)** - Sign uploads broken
  Teams: sign-core. Affects Sign file operations.

(Only Commerce/monetization-related SEVs shown. Non-Commerce incidents omitted.)

---

## Tasks Due

- **OVERDUE** (was due MM/DD): Review migration timeline
- **Due MM/DD**: Update T3.1 status in Dropbox OS
```

### Step 8: Mark Label Emails as Read

After the report is fully generated, mark all collected label-based message IDs as read:

```bash
# Mark all paper-updates, confluence, and sev-announce notification emails as read
python3 -m sidekick.clients.gmail mark-read MESSAGE_ID
```

Process each message ID one at a time. If any mark-read fails, log the error but continue with remaining messages.

### Step 9: Save Report

Save the digest report to memory:

```bash
cat $TMP_DIR/digest_report.md | python3 -m sidekick.clients.memory write \
  "Daily digest for $TARGET_DATE" \
  daily-digest \
  "daily-digest" \
  --md
```

### Step 10: Clean Up

Remove temporary files:

```bash
rm -rf $TMP_DIR
```

### Step 11: Generate HTML and Open in Browser

Convert the saved markdown report to styled HTML in the `output/` directory with a date-based filename, and open it in the browser.

```bash
mkdir -p output/daily-digest

python3 -m sidekick.clients.markdown_html SAVED_REPORT_PATH output/daily-digest/daily-digest-${TARGET_DATE}.html --title "Daily Digest - $TARGET_DATE" --open
```

Where `SAVED_REPORT_PATH` is the file path returned by the memory write command in Step 9. The markdown lives in `memory/daily-digest/`, the HTML in `output/daily-digest/`.

## Design Notes

### Calendar Filtering
- **Declined events are skipped.** If the user's response status is "declined", the event is omitted.
- **All-day events are mostly ignored.** Only PTO/leave all-day events are included (as an "Out today" note). Holidays, multi-day reminders, and other all-day events are skipped.
- **Timed events** are the focus -- actual meetings with start/end times.
- **Tomorrow's preview** is included as a brief look-ahead (time + title only).

### Paper Update Depth
- **Never just say "N edits by Person"** -- that's what the email already says and adds no value.
- **Always fetch the Paper doc** and summarize the actual content that was changed or added. The goal is that the user does NOT need to re-open the doc or read the email.
- For **1:1 docs**, list the actual topics/bullet points added to the "Next Time" section.
- For **meeting docs** (often pre-reads, not just agendas), summarize the key content, discussion points, or decisions that were added.
- For **new doc shares**, provide a 1-3 paragraph summary (roughly 1 paragraph per page of doc content).

### Paper Update Formatting
- **Split into "Needs Attention" and "FYI" sub-sections.** "Needs Attention" is for docs where someone is waiting on Shawn, a decision was made that affects his teams, or he needs to act. "FYI" is for routine updates, status changes, and background info.
- **Lead with what matters.** For each doc, the first line after the title should say what Shawn needs to do (if anything), or the single most important takeaway. Push supporting detail into sub-bullets.
- **Use bullet points and sub-lists, not paragraphs.** Every entry should be scannable. Bold key names, decisions, and dates. Never write a wall of text.
- **Keep it concise.** One sentence per bullet. If a doc has many changes (e.g., a migration timeline with 6 updates), summarize the 2-3 most important and list the rest as terse sub-bullets rather than full sentences for each.

### Confluence Comment Handling
- Always summarize the actual comment text, not just "someone commented."
- **Explicitly flag replies to Shawn's own comments** -- look for threading, @-mentions, or reply-to patterns.
- @-mentions of Shawn are always called out prominently as requiring a response.

### Paper URL Resolution
Paper notification emails are HTML-only (plain text body is empty). The emails contain three types of URLs:
- **`links.dropbox.com/u/click?_paper_track=...`** -- these are the useful ones. They 302-redirect to `dropbox.com/scl/fi/...` share links. Use `resolve-tracking-url` to follow the redirect.
- **`links.dropbox.com/u/click?_t=...&_m=...&_e=...`** -- generic email tracking URLs. These redirect to bare `paper.dropbox.com` and are NOT useful for doc resolution.
- **`paper.dropbox.com/doc/TITLE-HASHID`** -- internal Paper URLs. These don't work with the Dropbox API.

The workflow is: find the `_paper_track` URL in the email HTML → resolve it → use the resulting scl/fi URL to fetch content. If no `_paper_track` URL exists, check CLAUDE.local.md for known doc URLs.

### Links Throughout
- Every doc reference (Paper, Confluence, JIRA) must include a clickable URL.
- Paper docs: use the resolved dropbox.com/scl/fi URL.
- Confluence pages: use the atlassian.net/wiki URL from the notification email.
- JIRA issues: use `{ATLASSIAN_URL}/browse/ISSUE-KEY` (get ATLASSIAN_URL from `.env`).

### Action Items
- Action items are explicitly called out in a dedicated section at the bottom of the report.
- The agent asks the user whether to create Microsoft To Do tasks for any identified AIs.
- To Do tasks are created in the "Dropbox 2026" list with a link to the source in the body.

### Incident Filtering (sev-announce)
- **Only Commerce/monetization-related SEVs** are included. Filter by team ownership or potential involvement.
- **Do NOT include non-Commerce SEV1s** just because they're high-severity. If it doesn't touch Commerce or monetization, it's noise.
- See CLAUDE.local.md for the sub-team mapping (team names and JIRA project keys).

### Tasks
- **Only tasks that are overdue or due within 2 days** are shown. Tasks without due dates or due further out are backlog noise.
- Overdue tasks are flagged prominently.
- Sorted by due date (overdue first, then soonest).
- If no tasks match the window, show "(no tasks due soon)" rather than listing the full backlog.

### JIRA
- JIRA email notifications are **skipped** (low signal for a director). JIRA activity is better reviewed via targeted queries during 1:1 prep or project reviews.

### Volume Handling
- Each Gmail search is capped at 50 messages per label. This handles daily cadence well.
- If the user skips a day or two, 50 should still cover most cases.

### Re-runnability
- Mark-as-read happens only at the very end (Step 8), after the report is complete.
- If the agent is interrupted before Step 8, re-running produces the same report.
- Once mark-as-read completes, re-running will show "(no updates)" for label sections.

### Empty Sections
- If a section has no items, show it with "(no updates)" rather than omitting it. This confirms the agent checked that source.

### Error Handling
- If a Gmail search fails (e.g., label doesn't exist), note the error in that section and continue.
- If mark-as-read fails for a message, log the error but continue processing remaining messages.
- If Calendar fetch fails, note it and proceed with email sections.
- If a Paper/Confluence doc fetch fails, note the error and include what info is available from the email notification.

## Tips

- **First run after weekend**: May have more notifications than usual. The 50-message cap handles most cases.
- **Re-running same day**: Label emails will already be marked read, so those sections show "(no updates)". Inbox will still show current unread emails.
- **Custom date**: Pass a date argument for a past date. Calendar shows that day's events. Email labels still show currently-unread messages (not date-filtered).
