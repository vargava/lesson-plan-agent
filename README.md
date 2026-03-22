# Lesson Plan Agent

Generates publication-ready math lesson plans from a Google Sheet, powered by Claude Code. Two lessons per run, output to Google Docs.

**No Anthropic API key needed** — Claude Code is the model. The Python scripts only handle Google API I/O.

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — add GOOGLE_SHEET_ID and GOOGLE_DRIVE_FOLDER_ID
```

### 3. Google credentials

Place your service account JSON key at `credentials/service_account.json`.

Share with the service account email (`client_email` in the JSON key):
- Google Sheet → **Viewer** access
- Drive folder → **Editor** access

---

## How to Run

Open Claude Code in this repo and say:

> Run the lesson plan workflow

Claude Code will:
1. Fetch the next two lesson tabs from your Google Sheet
2. Read `SKILL.md` for the instructional design framework
3. Generate both lesson plans
4. Create a Google Doc with both plans and print the URL

---

## Dry-Run Mode (no Google auth yet)

If credentials or `GOOGLE_SHEET_ID` are missing, the pipeline runs in dry-run mode:
- Create `sample_lesson.txt` with pasted lesson content
- Claude Code generates plans from that content and prints to stdout instead of creating a Doc

---

## Sheet Structure

One tab per lesson. Tab names encode order (e.g. `Week 1 - Lesson 3 - Ratios`).

Tabs named with "overview", "unit", "summary", etc. are automatically skipped.

Lesson data is read as a raw cell grid — no hardcoded column mappings. Merged cells appear as empty strings; Claude interprets the structure contextually.

---

## State

`state.json` at the project root tracks progress:

```json
{"last_completed_lesson": "Week 1 - Lesson 2 - Equivalent Ratios"}
```

- Missing file → starts from the first lesson tab
- Each run advances by 2 lessons
- Reset by deleting or editing `state.json`

---

## File Structure

```
src/fetch_lessons.py   — reads Google Sheets, outputs lesson data as JSON
src/write_doc.py       — creates Google Doc from two lesson plan files
SKILL.md               — instructional design spec (source of truth for lesson format)
state.json             — auto-generated, tracks last completed lesson
credentials/           — service account JSON key (never committed)
.env                   — Google config (never committed)
tmp/                   — temp files during a run (auto-created, never committed)
```
