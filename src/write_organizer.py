"""
write_organizer.py — Creates a Graphic Organizer Google Doc from a structured text file.

The organizer is a 1-page teacher reference with a table layout containing five sections:
  Do Now, Objective, Vocabulary, Activity Instructions, Summary

Usage:
  python src/write_organizer.py \
    --tab-a "L10 326 & 327 (ThF)" \
    --plan-a tmp/organizer_a.txt \
    --folder-id "<Drive folder ID>" \
    --title "Ratios : Lesson 10 Graphic Organizer"

Prints the Google Doc URL on success, or "[dry-run]" in dry-run mode.

Auth:
  Requires credentials/token.json (OAuth2 user credentials).
  Run src/auth_setup.py once to generate it.
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent
TOKEN_FILE   = PROJECT_ROOT / "credentials/token.json"

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]

SECTION_KEYS   = ["DO_NOW", "OBJECTIVE", "VOCABULARY", "ACTIVITY_INSTRUCTIONS", "SUMMARY"]
SECTION_LABELS = ["Do Now", "Objective", "Vocabulary", "Activity Instructions", "Summary"]

DARK_BLUE  = {"red": 0.051, "green": 0.278, "blue": 0.631}   # #0d47a1
DARK_GRAY  = {"red": 0.129, "green": 0.129, "blue": 0.129}   # #212121


# ── Auth ──────────────────────────────────────────────────────────────────────

def build_services():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    if not TOKEN_FILE.exists():
        raise RuntimeError("No OAuth2 token found. Run: python src/auth_setup.py")

    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json())

    docs  = build("docs",  "v1", credentials=creds)
    drive = build("drive", "v3", credentials=creds)
    return docs, drive


def _batch(docs, doc_id, requests):
    """Execute a batchUpdate, splitting into chunks to stay under API limits."""
    CHUNK = 500
    for i in range(0, len(requests), CHUNK):
        docs.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": requests[i : i + CHUNK]},
        ).execute()


def find_unique_title(drive, folder_id, base_title):
    """Return base_title, or base_title + ' (2)'/'(3)'/... if already exists."""
    if not folder_id:
        return base_title
    title  = base_title
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
        title  = f"{base_title} ({suffix})"
        suffix += 1


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_organizer(text: str) -> dict:
    """
    Parse the structured organizer text file into a dict with keys matching
    SECTION_KEYS. Each value is a list of stripped non-empty lines for that section.
    """
    result  = {k: [] for k in SECTION_KEYS}
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        # Check for section header like "DO_NOW:" or "ACTIVITY_INSTRUCTIONS:"
        header = stripped.rstrip(":")
        if header in SECTION_KEYS:
            current = header
            continue
        if current and stripped:
            result[current].append(stripped)
    return result


# ── Google Docs table helpers ─────────────────────────────────────────────────

def find_table_cell_indices(doc_body: dict) -> list:
    """
    Walk the document body and return a list of paragraph startIndex values,
    one per row, for the first table found. These are the insertion points
    for cell content.
    """
    for element in doc_body.get("content", []):
        if "table" in element:
            indices = []
            for row in element["table"]["tableRows"]:
                cell      = row["tableCells"][0]
                para_start = cell["content"][0]["startIndex"]
                indices.append(para_start)
            return indices
    return []


def find_table_start_index(doc_body: dict) -> int:
    """Return the startIndex of the first table element in the document body."""
    for element in doc_body.get("content", []):
        if "table" in element:
            return element["startIndex"]
    return -1


# ── Doc creation ──────────────────────────────────────────────────────────────

def create_organizer_doc(docs, drive, folder_id: str, title: str, data: dict) -> str:
    """
    Create a Google Doc with a 6-row table (title row + 5 content sections).
    Returns the doc URL.
    """

    # ── Phase 1: Create doc, move to folder, insert empty table ──

    doc    = docs.documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]

    if folder_id:
        drive.files().update(
            fileId=doc_id,
            addParents=folder_id,
            removeParents="root",
            fields="id, parents",
        ).execute()

    # Insert a 6-row × 1-column table at index 1 (after the empty first paragraph)
    _batch(docs, doc_id, [
        {"insertTable": {"rows": 6, "columns": 1, "location": {"index": 1}}}
    ])

    # ── Phase 2: Re-fetch doc to get actual cell indices ──

    doc_full  = docs.documents().get(documentId=doc_id).execute()
    doc_body  = doc_full.get("body", {})
    cell_idxs = find_table_cell_indices(doc_body)

    if len(cell_idxs) < 6:
        raise RuntimeError(
            f"Expected 6 table cells but found {len(cell_idxs)}. "
            "Table may not have been inserted correctly."
        )

    # Build cell content: row 0 = title, rows 1-5 = sections
    # We insert in reverse order so earlier indices stay valid as text is added.
    insert_reqs = []

    def _ins(index, text):
        insert_reqs.append({"insertText": {"location": {"index": index}, "text": text}})

    # Rows 1–5 in reverse so indices don't shift for earlier rows
    for i in range(4, -1, -1):
        key   = SECTION_KEYS[i]
        label = SECTION_LABELS[i]
        lines = data.get(key, [])
        body  = "\n".join(lines) if lines else "(not found)"
        # Cell content: label line, blank line, then body text
        cell_text = f"{label}\n\n{body}"
        _ins(cell_idxs[i + 1], cell_text)

    # Row 0: doc title
    _ins(cell_idxs[0], title)

    _batch(docs, doc_id, insert_reqs)

    # ── Phase 3: Apply formatting ──

    # Re-fetch to get updated indices after all text insertions
    doc_full2  = docs.documents().get(documentId=doc_id).execute()
    doc_body2  = doc_full2.get("body", {})
    cell_idxs2 = find_table_cell_indices(doc_body2)
    table_si   = find_table_start_index(doc_body2)

    format_reqs = []

    def _rgb(color):
        return {"color": {"rgbColor": color}}

    def _style(start, end, bold=False, font_size=11, color=None, tab_id=None):
        fields = ["bold", "fontSize", "weightedFontFamily"]
        props  = {
            "bold": bold,
            "fontSize": {"magnitude": font_size, "unit": "PT"},
            "weightedFontFamily": {"fontFamily": "Calibri"},
        }
        if color:
            props["foregroundColor"] = _rgb(color)
            fields.append("foregroundColor")
        loc = {"startIndex": start, "endIndex": end}
        return {
            "updateTextStyle": {
                "range": loc,
                "textStyle": props,
                "fields": ",".join(fields),
            }
        }

    # Row 0: title cell — bold, 12pt, dark blue
    title_start = cell_idxs2[0]
    title_end   = title_start + len(title)
    format_reqs.append(_style(title_start, title_end, bold=True, font_size=12, color=DARK_BLUE))

    # Rows 1–5: section label bold + dark gray; body text normal
    for i in range(5):
        key   = SECTION_KEYS[i]
        label = SECTION_LABELS[i]
        lines = data.get(key, [])
        body  = "\n".join(lines) if lines else "(not found)"

        cell_start  = cell_idxs2[i + 1]
        label_end   = cell_start + len(label)
        # +2 for the "\n\n" after the label
        body_start  = label_end + 2
        body_end    = body_start + len(body)

        format_reqs.append(_style(cell_start, label_end, bold=True,  font_size=11, color=DARK_GRAY))
        format_reqs.append(_style(body_start, body_end,  bold=False, font_size=11))

    # Cell borders and padding for all 6 rows
    border = {
        "width":     {"magnitude": 1, "unit": "PT"},
        "dashStyle": "SOLID",
        "color":     {"color": {"rgbColor": {"red": 0, "green": 0, "blue": 0}}},
    }
    padding_pt = {"magnitude": 5, "unit": "PT"}

    for row_i in range(6):
        format_reqs.append({
            "updateTableCellStyle": {
                "tableRange": {
                    "tableCellLocation": {
                        "tableStartLocation": {"index": table_si},
                        "rowIndex":    row_i,
                        "columnIndex": 0,
                    },
                    "rowSpan":    1,
                    "columnSpan": 1,
                },
                "tableCellStyle": {
                    "borderBottom":  border,
                    "borderTop":     border,
                    "borderLeft":    border,
                    "borderRight":   border,
                    "paddingTop":    padding_pt,
                    "paddingBottom": padding_pt,
                    "paddingLeft":   {"magnitude": 6, "unit": "PT"},
                    "paddingRight":  {"magnitude": 6, "unit": "PT"},
                },
                "fields": "borderBottom,borderTop,borderLeft,borderRight,"
                          "paddingTop,paddingBottom,paddingLeft,paddingRight",
            }
        })

    _batch(docs, doc_id, format_reqs)

    return f"https://docs.google.com/document/d/{doc_id}/edit"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Create a Graphic Organizer Google Doc from a structured text file."
    )
    parser.add_argument("--plan-a",    required=True,  help="Path to organizer text file (e.g. tmp/organizer_a.txt)")
    parser.add_argument("--tab-a",     required=True,  help="Lesson tab name")
    parser.add_argument("--folder-id", required=True,  help="Drive folder ID")
    parser.add_argument("--title",     required=True,  help="Doc title (e.g. 'Topic : Lesson X Graphic Organizer')")
    parser.add_argument("--dry-run",   action="store_true", help="Print parsed content without creating a doc")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")

    plan_text = Path(args.plan_a).read_text()
    data      = parse_organizer(plan_text)
    dry_run   = args.dry_run or not TOKEN_FILE.exists()

    if dry_run:
        print(f"\n[DRY RUN] Would create organizer doc: {args.title}\n")
        for key, label in zip(SECTION_KEYS, SECTION_LABELS):
            lines = data.get(key, [])
            print(f"--- {label} ---")
            print("\n".join(lines) if lines else "(empty)")
            print()
        print("[dry-run]")
        return

    try:
        docs, drive = build_services()
        title       = find_unique_title(drive, args.folder_id, args.title)
        if title != args.title:
            print(f"[info] Title '{args.title}' already exists — using '{title}'", file=sys.stderr)
        doc_url = create_organizer_doc(docs, drive, args.folder_id, title, data)
    except Exception as e:
        print(f"ERROR creating organizer doc: {e}", file=sys.stderr)
        sys.exit(1)

    print(doc_url)


if __name__ == "__main__":
    main()
