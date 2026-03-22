# Lesson Plan Agent

## What This Project Does
A weekly agent that reads a Google Sheet containing a math curriculum unit, extracts two lesson tabs per run, generates detailed publication-ready lesson plans using Claude, and writes the output to a new Google Doc.

## Architecture
```
You (terminal) → main.py → sheets_reader.py → prompt_builder.py → claude_caller.py → docs_writer.py → Google Doc
```

## File Structure
- `src/main.py` — entrypoint, orchestrates the full pipeline
- `src/sheets_reader.py` — reads tab names and lesson content from Google Sheets API
- `src/prompt_builder.py` — assembles SKILL.md + lesson data into the Claude prompt
- `src/claude_caller.py` — calls Anthropic API, runs Lesson A then Lesson B sequentially
- `src/docs_writer.py` — creates a new Google Doc and writes the formatted lesson plans
- `SKILL.md` — the full instructional design spec that drives Claude's output
- `state.json` — tracks which lesson was last completed (auto-generated, never committed)
- `credentials/` — Google service account JSON key lives here (never committed)
- `.env` — API keys and config (never committed)

## Environment Variables (.env)
```
ANTHROPIC_API_KEY=
GOOGLE_SERVICE_ACCOUNT_JSON=credentials/service_account.json
GOOGLE_SHEET_ID=
GOOGLE_DRIVE_FOLDER_ID=
```

## How Lesson Sequencing Works
- The Google Sheet has one tab per lesson
- Tab names encode order and optionally start dates (e.g. "Week 12 - Lesson 5 - Ratios")
- On each run, the agent reads all tab names, sorts them, checks state.json for the last completed lesson, and selects the next two
- After a successful run, state.json is updated

## How to Run
```bash
python src/main.py
```

## Output
- A new Google Doc created in the configured Drive folder
- Named: `YYYY-MM-DD — [Lesson A tab name] & [Lesson B tab name]`
- Terminal summary printed on completion: lessons processed, Doc URL, token usage

## Model
Use `claude-sonnet-4-20250514`. Max tokens 8000 per lesson call. Run lessons sequentially, not in parallel.

## Key Constraints
- The SKILL.md is the source of truth for all prompt instructions — load it fresh from disk on every run, do not hardcode its contents
- Credentials folder is never committed — remind the user if the JSON key is missing
- state.json lives at the project root, is created on first run if absent
- Google auth uses a service account (not OAuth) — scoped only to the explicitly shared Sheet and Drive folder
