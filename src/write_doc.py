"""
write_doc.py — Writes two lesson plans to a Google Doc with tabs and rich formatting.

Architecture:
  - Creates an empty Google Doc via Docs API (so it's owned by the OAuth user)
  - Moves it to the configured Drive folder
  - Renames the default tab to Lesson A's name; creates a second tab for Lesson B
  - Inserts and formats each lesson via batchUpdate (headings, EN/ES/MX colors,
    teacher script italics, role label bold)

Usage:
  python src/write_doc.py --tab-a "Tab Name" --tab-b "Tab Name" \
                          --plan-a tmp/lesson_a.txt --plan-b tmp/lesson_b.txt \
                          [--dry-run]

Prints the Google Doc URL on success, or "[dry-run]" in dry-run mode.
Also updates state.json with tab_b as last_completed_lesson.

Auth:
  Requires credentials/token.json (OAuth2 user credentials).
  Run src/auth_setup.py once to generate it.
"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
STATE_FILE   = PROJECT_ROOT / "state.json"
TOKEN_FILE   = PROJECT_ROOT / "credentials/token.json"

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]


# ── Auth ──────────────────────────────────────────────────────────────────────

def build_services():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    if not TOKEN_FILE.exists():
        raise RuntimeError(
            "No OAuth2 token found. Run: python src/auth_setup.py"
        )

    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json())

    docs  = build("docs",  "v1", credentials=creds)
    drive = build("drive", "v3", credentials=creds)
    return docs, drive


# ── Doc creation ──────────────────────────────────────────────────────────────

def _batch(docs, doc_id, requests):
    """Execute a batchUpdate, splitting into chunks to stay under API limits."""
    CHUNK = 500
    for i in range(0, len(requests), CHUNK):
        docs.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": requests[i : i + CHUNK]},
        ).execute()


def create_doc(docs, drive, folder_id, title, tab_a_name,
               segments_a, tab_b_name=None, segments_b=None,
               font_size=None, font_family=None):
    from format_doc import segments_to_requests

    # ── 1. Create empty doc (owned by the OAuth user) ──
    doc    = docs.documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]

    # ── 2. Move to target folder ──
    if folder_id:
        drive.files().update(
            fileId=doc_id,
            addParents=folder_id,
            removeParents="root",
            fields="id, parents",
        ).execute()

    # ── 3. Get default tab ID ──
    doc_full = docs.documents().get(documentId=doc_id).execute()
    tabs     = doc_full.get("tabs", [])
    tab1_id  = tabs[0]["tabProperties"]["tabId"] if tabs else None

    # ── 4. Rename tab 1; create tab 2 only if Lesson B is provided ──
    tab_requests = []
    if tab1_id:
        tab_requests.append({
            "updateTabProperties": {
                "tabProperties": {"tabId": tab1_id, "title": _short(tab_a_name)},
                "fields": "title",
            }
        })
    if tab_b_name:
        tab_requests.append({
            "createTab": {
                "tabProperties": {"title": _short(tab_b_name), "index": 1},
            }
        })

    tab2_id = None
    if tab_requests:
        try:
            resp = docs.documents().batchUpdate(
                documentId=doc_id, body={"requests": tab_requests}
            ).execute()
            for reply in resp.get("replies", []):
                if "createTab" in reply:
                    tab2_id = reply["createTab"]["tabProperties"]["tabId"]
        except Exception as e:
            print(f"[warn] Tab setup partial failure: {e}", file=sys.stderr)

    # ── 5. Insert and format Lesson A (tab 1) ──
    ins_a, fmt_a = segments_to_requests(segments_a, tab_id=tab1_id, insert_at=1,
                                        font_size=font_size, font_family=font_family)
    _batch(docs, doc_id, ins_a)
    _batch(docs, doc_id, fmt_a)

    # ── 6. Insert and format Lesson B (only if provided) ──
    if segments_b is not None:
        if tab2_id:
            ins_b, fmt_b = segments_to_requests(segments_b, tab_id=tab2_id, insert_at=1,
                                                font_size=font_size, font_family=font_family)
            _batch(docs, doc_id, ins_b)
            _batch(docs, doc_id, fmt_b)
        else:
            # Tabs not available: insert lesson B after a page break in the same tab
            text_a   = "".join(s.text for s in segments_a)
            pb_index = len(text_a)  # last valid insert position (segment end is exclusive)
            loc      = {"index": pb_index}
            if tab1_id:
                loc["tabId"] = tab1_id
            _batch(docs, doc_id, [{"insertText": {"location": loc, "text": "\f"}}])

            ins_b, fmt_b = segments_to_requests(
                segments_b, tab_id=tab1_id, insert_at=pb_index + 1,
                font_size=font_size, font_family=font_family
            )
            _batch(docs, doc_id, ins_b)
            _batch(docs, doc_id, fmt_b)

    return f"https://docs.google.com/document/d/{doc_id}/edit"


def _short(name, max_len=100):
    return name[:max_len]


def find_unique_title(drive, folder_id, base_title):
    """Return base_title, or base_title + ' (2)'/'(3)'/... if a doc with that name already exists."""
    if not folder_id:
        return base_title
    title = base_title
    suffix = 2
    while True:
        escaped = title.replace("'", "\\'")
        q = (
            f"name='{escaped}' and '{folder_id}' in parents"
            f" and trashed=false and mimeType='application/vnd.google-apps.document'"
        )
        results = drive.files().list(q=q, fields="files(id)", pageSize=1).execute()
        if not results.get("files"):
            return title
        title = f"{base_title} ({suffix})"
        suffix += 1


# ── State ─────────────────────────────────────────────────────────────────────

def save_state(last_completed):
    with open(STATE_FILE, "w") as f:
        json.dump({"last_completed_lesson": last_completed}, f, indent=2)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tab-a",  required=True)
    parser.add_argument("--tab-b",  required=False, default=None)
    parser.add_argument("--plan-a", required=True)
    parser.add_argument("--plan-b", required=False, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--title", default=None,
                        help="Human-readable doc title override (e.g. 'Unit 2: Lessons 5 and 6 (Fractions)'). "
                             "If omitted, falls back to the date-based default.")
    parser.add_argument("--folder-id", default=None,
                        help="Override GOOGLE_DRIVE_FOLDER_ID for this doc.")
    parser.add_argument("--font-size", type=int, default=None,
                        help="Apply a fixed font size (pt) to all content, e.g. 14 for worksheets.")
    parser.add_argument("--font-family", default=None,
                        help="Apply a fixed font family to all content, e.g. Arial for worksheets.")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")

    # Add src/ to path so format_doc can be imported
    sys.path.insert(0, str(Path(__file__).parent))
    from format_doc import parse_lesson

    plan_a = Path(args.plan_a).read_text()
    plan_b = Path(args.plan_b).read_text() if args.plan_b else None

    today = date.today().strftime("%Y-%m-%d")
    if args.title:
        base_title = args.title
    elif args.tab_b:
        base_title = f"{today} \u2014 {args.tab_a} & {args.tab_b}"
    else:
        base_title = f"{today} \u2014 {args.tab_a}"

    folder_id = args.folder_id or os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip()
    dry_run   = args.dry_run or not TOKEN_FILE.exists()

    if dry_run:
        print(f"\n[DRY RUN] Would create doc: {base_title}")
        print("\n--- LESSON A ---\n")
        print(plan_a)
        if plan_b:
            print("\n--- LESSON B ---\n")
            print(plan_b)
        doc_url = "[dry-run]"
    else:
        try:
            segments_a = parse_lesson(plan_a)
            segments_b = parse_lesson(plan_b) if plan_b else None
            docs, drive = build_services()
            title = find_unique_title(drive, folder_id, base_title)
            if title != base_title:
                print(f"[info] Doc title '{base_title}' already exists — using '{title}'", file=sys.stderr)
            doc_url = create_doc(
                docs, drive, folder_id, title,
                args.tab_a, segments_a,
                tab_b_name=args.tab_b, segments_b=segments_b,
                font_size=args.font_size, font_family=args.font_family,
            )
        except Exception as e:
            print(f"ERROR writing Google Doc: {e}", file=sys.stderr)
            sys.exit(1)

    if not dry_run and args.tab_b:
        save_state(args.tab_b)

    print(doc_url)


if __name__ == "__main__":
    main()
