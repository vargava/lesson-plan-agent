"""
fetch_lessons.py — Reads the next lesson tab (or two with --two) from Google Sheets and prints JSON to stdout.

Claude Code runs this script, parses the output, and generates lesson plans directly.

Output (stdout, JSON):
{
  "tab_a": "<tab name>",
  "tab_b": "<tab name or null>",
  "data_a": "<pipe-delimited cell grid or raw text>",
  "data_b": "<pipe-delimited cell grid or null>",
  "dry_run": true/false,
  "sheet_id": "<Google Sheet ID>",
  "unit_name": "<spreadsheet title>"
}

Flags:
  --start-from <tab_name>   Override state.json: use this tab as tab_a (for re-runs).
                            tab_b is null unless --two is also passed.
  --two                     Fetch two consecutive lessons instead of one.

Exit codes:
  0 — success
  1 — fatal error (message printed to stderr)
"""

import argparse
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
    "roll-out",              # Unit ROLL-OUT Guide structural tab
    "copy of",               # duplicate/copy tabs
)


def load_state(sheet_id=None):
    if not STATE_FILE.exists():
        return {"last_completed_lesson": None}
    with open(STATE_FILE) as f:
        state = json.load(f)
    if sheet_id and "sheets" in state:
        sheet_entry = state.get("sheets", {}).get(sheet_id, {})
        return {"last_completed_lesson": sheet_entry.get("last_completed_lesson")}
    # Legacy flat format
    return {"last_completed_lesson": state.get("last_completed_lesson")}


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
    unit_name = spreadsheet.get("properties", {}).get("title", "")
    sheets = spreadsheet.get("sheets", [])
    all_tabs = [s["properties"]["title"] for s in sheets]
    lesson_tabs = [t for t in all_tabs if not is_overview_tab(t)]
    return lesson_tabs, unit_name


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


def pick_next(all_tabs, last_completed, two=False):
    if not all_tabs:
        raise ValueError("No lesson tabs found in the spreadsheet.")
    if last_completed is None or last_completed not in all_tabs:
        start = 0
    else:
        start = all_tabs.index(last_completed) + 1
    remaining = all_tabs[start:]
    if not remaining:
        raise ValueError(
            f"No lesson tabs remain after '{last_completed}'. "
            "All lessons may be processed — reset state.json to restart."
        )
    tab_a = remaining[0]
    tab_b = remaining[1] if two and len(remaining) >= 2 else None
    return tab_a, tab_b


def pick_from(all_tabs, start_tab, two=False):
    """For re-runs: use start_tab as tab_a. tab_b is next in sequence only if --two is set."""
    if start_tab not in all_tabs:
        raise ValueError(
            f"Tab '{start_tab}' not found in the spreadsheet. "
            f"Available tabs: {all_tabs}"
        )
    idx = all_tabs.index(start_tab)
    tab_b = all_tabs[idx + 1] if two and idx + 1 < len(all_tabs) else None
    return start_tab, tab_b


def main():
    parser = argparse.ArgumentParser(description="Fetch the next lesson tab(s) from Google Sheets.")
    parser.add_argument(
        "--start-from",
        metavar="TAB_NAME",
        default=None,
        help="Override state.json: use this tab as tab_a (for re-runs). "
             "tab_b is the next tab in sequence, or null if tab_a is last.",
    )
    parser.add_argument(
        "--two",
        action="store_true",
        default=False,
        help="Fetch two lessons instead of one. tab_b will be the lesson after tab_a.",
    )
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")

    sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
    creds_path = PROJECT_ROOT / os.getenv(
        "GOOGLE_SERVICE_ACCOUNT_JSON", "credentials/service_account.json"
    )
    dry_run = not creds_path.exists() or not sheet_id

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
            "sheet_id": "",
            "unit_name": "Sample Unit",
        }
    else:
        try:
            service = build_google_sheets_service(creds_path)
            all_tabs, unit_name = get_lesson_tabs(service, sheet_id)
            state = load_state(sheet_id)
            last_completed = state.get("last_completed_lesson")

            if args.start_from:
                tab_a, tab_b = pick_from(all_tabs, args.start_from, two=args.two)
            else:
                tab_a, tab_b = pick_next(all_tabs, last_completed, two=args.two)

            grid_a = read_lesson_tab(service, sheet_id, tab_a)
            grid_b = read_lesson_tab(service, sheet_id, tab_b) if tab_b else None
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
            "data_b": grid_to_text(grid_b) if grid_b is not None else None,
            "dry_run": False,
            "sheet_id": sheet_id,
            "unit_name": unit_name,
        }

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
