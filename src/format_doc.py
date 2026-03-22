"""
format_doc.py — Parses lesson plan text into Google Docs API batchUpdate requests.

Handles:
  - Heading hierarchy (doc title, section headers, time block headers)
  - Color-coded [EN] / [ES] / [MX] sections (blue / green / orange)
  - Bold role labels (Teacher:, Students:, Discussion prompts:)
  - Italic teacher script paragraphs
  - Bold quality-check lines ([✓])
  - Bullet indentation
"""

import re

# ── Colors ───────────────────────────────────────────────────────────────────

def _rgb(hex_str):
    h = hex_str.lstrip("#")
    return {
        "red":   int(h[0:2], 16) / 255,
        "green": int(h[2:4], 16) / 255,
        "blue":  int(h[4:6], 16) / 255,
    }

COLORS = {
    "en":      _rgb("1565c0"),  # blue
    "es":      _rgb("2e7d32"),  # green
    "mx":      _rgb("e65100"),  # orange
    "time":    _rgb("0d47a1"),  # dark blue for block headers
    "check":   _rgb("1b5e20"),  # dark green for ✓ items
    "misc":    _rgb("4a148c"),  # purple for misconception labels
}

# ── Line classifier ───────────────────────────────────────────────────────────

def _classify(line):
    s = line.strip()
    if not s:
        return "empty"
    if re.match(r"^[=━]{10,}$", s):
        return "main_sep"
    if re.match(r"^[─\-]{10,}$", s):
        return "sub_sep"
    if re.match(r"^LESSON \d+ OF \d+$", s):
        return "doc_title"
    if re.match(r"^\d+\. [A-Z][A-Z\s/&().,\-]+$", s):
        return "section_h2"
    if re.match(r"^BLOCK \d+", s) and ("—" in s or "minutes" in s.lower()):
        return "block_h3"
    if re.match(r"^\[EN\]", s):
        return "en"
    if re.match(r"^\[ES\]", s):
        return "es"
    if re.match(r"^\[MX\]", s):
        return "mx"
    if re.match(r"^(Teacher|Students?|Discussion prompts?)\s*:?\s*$", s, re.IGNORECASE):
        return "role_label"
    if re.match(r"^\[✓\]", s):
        return "check"
    if re.match(r"^\s*(Misconception \d+|REAL-WORLD CONNECTION|QUALITY CHECK|ANTICIPATED MISCONCEPTIONS)", s, re.IGNORECASE):
        return "subhead"
    if re.match(r"^(\s{2,})[-•]\s", line):
        return "bullet"
    return "normal"

# ── Markup cleanup ────────────────────────────────────────────────────────────

def _clean(line):
    """Strip **bold** markers from display text (we apply bold programmatically)."""
    return re.sub(r"\*\*(.+?)\*\*", r"\1", line.rstrip())

# ── Segment model ─────────────────────────────────────────────────────────────

class Seg:
    """One paragraph of text with attached formatting."""
    __slots__ = ("text", "para_style", "bold", "italic", "color", "indent_pt")

    def __init__(self, text, para_style="NORMAL_TEXT", bold=False,
                 italic=False, color=None, indent_pt=None):
        self.text       = text
        self.para_style = para_style
        self.bold       = bold
        self.italic     = italic
        self.color      = color
        self.indent_pt  = indent_pt

# ── Parser ────────────────────────────────────────────────────────────────────

def parse_lesson(text):
    """
    Convert lesson plan plain text into a list of Seg objects.
    Tracks [EN]/[ES]/[MX] context and teacher-script blocks.
    """
    segments = []
    current_color = None   # "en" | "es" | "mx" | None
    in_teacher   = False   # True while we're inside a Teacher: block

    for line in text.split("\n"):
        ltype = _classify(line)
        clean = _clean(line)

        # Structural boundaries reset color/script tracking
        if ltype in ("section_h2", "block_h3", "main_sep", "sub_sep"):
            current_color = None
            in_teacher    = False

        # ── Skip separator lines (use heading spacing instead) ──
        if ltype in ("main_sep", "sub_sep"):
            segments.append(Seg("\n"))
            continue

        if ltype == "empty":
            segments.append(Seg("\n"))
            in_teacher = False  # blank line ends teacher script
            continue

        # ── Structural headings ──
        if ltype == "doc_title":
            segments.append(Seg(clean + "\n", para_style="TITLE", bold=True))
            continue

        if ltype == "section_h2":
            segments.append(Seg(clean + "\n", para_style="HEADING_2", bold=True))
            continue

        if ltype == "block_h3":
            segments.append(Seg(clean + "\n", para_style="HEADING_3",
                                bold=True, color=COLORS["time"]))
            continue

        if ltype == "subhead":
            color = COLORS.get(current_color)
            segments.append(Seg(clean + "\n", para_style="HEADING_4",
                                bold=True, italic=True, color=color))
            continue

        # ── Language section markers ──
        if ltype in ("en", "es", "mx"):
            current_color = ltype
            in_teacher    = False
            segments.append(Seg(clean + "\n", bold=True, color=COLORS[ltype]))
            continue

        # ── Role labels ──
        if ltype == "role_label":
            in_teacher = "teacher" in line.strip().lower()
            color = COLORS.get(current_color)
            segments.append(Seg(clean + "\n", bold=True, color=color))
            continue

        # ── Quality-check items ──
        if ltype == "check":
            segments.append(Seg(clean + "\n", bold=True, color=COLORS["check"]))
            continue

        # ── Bullet points ──
        if ltype == "bullet":
            color  = COLORS.get(current_color)
            italic = in_teacher and current_color is None
            segments.append(Seg(clean + "\n", italic=italic,
                                color=color, indent_pt=28))
            continue

        # ── Normal body text ──
        color  = COLORS.get(current_color)
        # Only italicise teacher script in the EN (uncolored) context;
        # ES/MX teacher script is already distinguished by color.
        italic = in_teacher and current_color is None
        segments.append(Seg(clean + "\n", italic=italic, color=color))

    return segments

# ── Request builders ──────────────────────────────────────────────────────────

def _loc(index, tab_id=None):
    loc = {"index": index}
    if tab_id:
        loc["tabId"] = tab_id
    return loc

def _rng(start, end, tab_id=None):
    r = {"startIndex": start, "endIndex": end}
    if tab_id:
        r["tabId"] = tab_id
    return r

def segments_to_requests(segments, tab_id=None, insert_at=1):
    """
    Convert a list of Seg objects into two lists of Docs API requests:
      insert_reqs  — a single insertText with all content
      format_reqs  — updateTextStyle / updateParagraphStyle calls

    Caller should execute insert_reqs first, then format_reqs, so that
    indices remain valid.
    """
    full_text = "".join(s.text for s in segments)

    insert_reqs = [{
        "insertText": {
            "location": _loc(insert_at, tab_id),
            "text": full_text,
        }
    }]

    format_reqs = []
    cursor = insert_at

    for seg in segments:
        end = cursor + len(seg.text)

        # Paragraph style
        if seg.para_style and seg.para_style != "NORMAL_TEXT":
            format_reqs.append({
                "updateParagraphStyle": {
                    "range": _rng(cursor, end, tab_id),
                    "paragraphStyle": {"namedStyleType": seg.para_style},
                    "fields": "namedStyleType",
                }
            })

        # Indentation
        if seg.indent_pt:
            format_reqs.append({
                "updateParagraphStyle": {
                    "range": _rng(cursor, end, tab_id),
                    "paragraphStyle": {
                        "indentStart": {"magnitude": seg.indent_pt, "unit": "PT"}
                    },
                    "fields": "indentStart",
                }
            })

        # Text style
        text_style = {}
        fields     = []
        if seg.bold:
            text_style["bold"]   = True
            fields.append("bold")
        if seg.italic:
            text_style["italic"] = True
            fields.append("italic")
        if seg.color:
            text_style["foregroundColor"] = {
                "color": {"rgbColor": seg.color}
            }
            fields.append("foregroundColor")

        if text_style:
            format_reqs.append({
                "updateTextStyle": {
                    "range": _rng(cursor, end, tab_id),
                    "textStyle": text_style,
                    "fields": ",".join(fields),
                }
            })

        cursor = end

    return insert_reqs, format_reqs
