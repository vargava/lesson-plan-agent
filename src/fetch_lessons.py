"""
fetch_lessons.py — Reads the next two lesson tabs from Google Sheets and prints JSON to stdout.

Claude Code runs this script, parses the output, and generates lesson plans directly.

Output (stdout, JSON):
{
  "tab_a": "<tab name>",
  "tab_b": "<tab name>",
  "data_a": "<pipe-delimited cell grid or raw text>",
  "data_b": "<pipe-delimited cell grid or raw text>",
  "dry_run": true/false
}

Exit codes:
  0 — success
  1 — fatal error (message printed to stderr)
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
STATE_FILE = PROJECT_ROOT / "state.json"
SAMPLE_LESSON_FILE = PROJECT_ROOT / "sample_lesson.txt"

# Tabs matching any of these patterns are structural/assessment tabs — not lesson plans
SKIP_TAB_PATTERNS = (
    "overview",
    "index",
    "contents",
    "summary",
    "cover",
    "directions",
    "form responses",
    "unit plan",
    "assessments",       # the Assessments structural tab
    "pre assessment",    # the Pre Assessment class day (not a lesson)
    "post assessment",   # the Post Assessment class day
    "post assesment",    # common typo variant
    "error analysis",
    "checkpoint",
)


def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_completed_lesson": None}


def is_overview_tab(name):
    lower = name.lower()
    return any(p in lower for p in SKIP_TAB_PATTERNS)


def grid_to_text(grid):
    if not grid:
        return "(empty tab)"
    return "\n".join(" | ".join(str(cell) for cell in row) for row in grid)


def build_google_sheets_service(creds_path):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = service_account.Credentials.from_service_account_file(
        str(creds_path), scopes=scopes
    )
    return build("sheets", "v4", credentials=creds)


def get_lesson_tabs(service, sheet_id):
    spreadsheet = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
    sheets = spreadsheet.get("sheets", [])
    all_tabs = [s["properties"]["title"] for s in sheets]
    return [t for t in all_tabs if not is_overview_tab(t)]


def read_lesson_tab(service, sheet_id, tab_name):
    result = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=sheet_id,
            range=f"'{tab_name}'",
            valueRenderOption="FORMATTED_VALUE",
        )
        .execute()
    )
    return result.get("values", [])


def pick_next_two(all_tabs, last_completed):
    if not all_tabs:
        raise ValueError("No lesson tabs found in the spreadsheet.")
    if last_completed is None or last_completed not in all_tabs:
        start = 0
    else:
        start = all_tabs.index(last_completed) + 1
    remaining = all_tabs[start:]
    if len(remaining) < 2:
        raise ValueError(
            f"Fewer than 2 lesson tabs remain after '{last_completed}'. "
            "All lessons may be processed — reset state.json to restart."
        )
    return remaining[0], remaining[1]


def main():
    load_dotenv(PROJECT_ROOT / ".env")

    sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
    creds_path = PROJECT_ROOT / os.getenv(
        "GOOGLE_SERVICE_ACCOUNT_JSON", "credentials/service_account.json"
    )
    dry_run = not creds_path.exists() or not sheet_id

    state = load_state()
    last_completed = state.get("last_completed_lesson")

    if dry_run:
        print("[DRY RUN] No credentials or GOOGLE_SHEET_ID — using sample_lesson.txt", file=sys.stderr)
        if not SAMPLE_LESSON_FILE.exists():
            print(
                "ERROR: sample_lesson.txt not found.\n"
                "Either:\n"
                "  1. Add credentials/service_account.json + GOOGLE_SHEET_ID in .env, OR\n"
                "  2. Create sample_lesson.txt with pasted lesson content.",
                file=sys.stderr,
            )
            sys.exit(1)
        sample = SAMPLE_LESSON_FILE.read_text()
        result = {
            "tab_a": "Sample Lesson A",
            "tab_b": "Sample Lesson B",
            "data_a": sample,
            "data_b": sample,
            "dry_run": True,
        }
    else:
        try:
            service = build_google_sheets_service(creds_path)
            all_tabs = get_lesson_tabs(service, sheet_id)
            tab_a, tab_b = pick_next_two(all_tabs, last_completed)
            grid_a = read_lesson_tab(service, sheet_id, tab_a)
            grid_b = read_lesson_tab(service, sheet_id, tab_b)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"ERROR reading from Google Sheets: {e}", file=sys.stderr)
            sys.exit(1)

        result = {
            "tab_a": tab_a,
            "tab_b": tab_b,
            "data_a": grid_to_text(grid_a),
            "data_b": grid_to_text(grid_b),
            "dry_run": False,
        }

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
