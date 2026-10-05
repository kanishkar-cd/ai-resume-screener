"""Layout-aware text reconstruction for text-based PDF pages.

PyMuPDF's plain block order interleaves multi-column resumes and keeps every
visual line wrap as a hard line break. Downstream extraction is line-oriented,
so this module rebuilds reading order from line geometry:

1. two-column pages are detected from a vertical gutter and read column by column;
2. fragments sharing a baseline (e.g. a title and its right-aligned dates) become one row;
3. visually wrapped lines are re-joined into a single logical line;
4. bullet glyphs (including Symbol-font private-use bullets) are normalized to "• ".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import median
from typing import Any

BULLET_GLYPHS = frozenset(
    "•●▪■◦○➢➤►▶▸✓✔❖◆◇∙⁃"  # common Unicode bullets
    "\uf0b7\uf0a7\uf076\uf0d8\uf0fc\uf0a8\uf06e\uf0e0\uf0f0\uf09f"  # Symbol/Wingdings private-use bullets
)
_ASCII_BULLET = re.compile(r"^[-*–]\s+")
_DATE_ONLY = re.compile(
    r"^\(?\s*(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*,?\s*)?(?:19|20)\d{2}"
    r"(?:\s*(?:-|–|—|to)\s*(?:(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*,?\s*)?(?:19|20)\d{2}|present|current|now|till\s+date))?\s*\)?$",
    re.I,
)
_SENTENCE_END = (".", "!", "?", ":", ";")
_LABEL_LINE = re.compile(r"^[A-Z][\w&/+.()' -]{0,30}:\s")  # "Tools: ...", "Tech Stack: ..."
_CONTACT_START = re.compile(r"^(?:\S+@\S+|https?://|www\.|\S+\.(?:com|in|io|dev|me|org|net)\b)", re.I)
_CONTINUES = (",", "&", "/", "+", "(", " and", " or", " with", " of", " for", " to", " in", " the")


@dataclass
class _Line:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    size: float
    first_bold: bool
    last_bold: bool

    @property
    def height(self) -> float:
        return max(self.y1 - self.y0, 1.0)

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class _Row:
    parts: list[_Line] = field(default_factory=list)

    @property
    def x0(self) -> float:
        return min(p.x0 for p in self.parts)

    @property
    def x1(self) -> float:
        return max(p.x1 for p in self.parts)

    @property
    def y0(self) -> float:
        return min(p.y0 for p in self.parts)

    @property
    def y1(self) -> float:
        return max(p.y1 for p in self.parts)

    @property
    def content_parts(self) -> list[_Line]:
        """Fragments in reading order, ignoring a bullet glyph rendered as its own fragment."""
        ordered = sorted(self.parts, key=lambda p: p.x0)
        if len(ordered) > 1 and len(ordered[0].text) == 1 and ordered[0].text in BULLET_GLYPHS:
            return ordered[1:]
        return ordered

    @property
    def size(self) -> float:
        return self.content_parts[0].size

    def text(self) -> str:
        ordered = sorted(self.parts, key=lambda p: p.x0)
        out = ordered[0].text
        for prev, cur in zip(ordered, ordered[1:]):
            gap = cur.x0 - prev.x1
            # A wide horizontal gap separates logically distinct fields (title vs. dates).
            out += ("  " if gap > max(prev.size, 6.0) * 1.2 else " ") + cur.text
        return out


def _span_is_bold(span: dict[str, Any]) -> bool:
    return bool(span.get("flags", 0) & 16) or "bold" in str(span.get("font", "")).lower()


def _collect_lines(page_dict: dict[str, Any]) -> list[_Line]:
    lines: list[_Line] = []
    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for raw in block.get("lines", []):
            direction = raw.get("dir", (1, 0))
            if abs(direction[0] - 1) > 0.05:  # skip rotated / vertical text
                continue
            all_spans = raw.get("spans", [])
            # Whitespace-only spans carry the word spacing in some PDFs: keep them for text,
            # but use only visible spans for geometry and styling.
            spans = [s for s in all_spans if s.get("text", "").strip()]
            if not spans:
                continue
            text = ""
            prev_x1: float | None = None
            for span in all_spans:
                piece = re.sub(r"[\r\xa0]", " ", span.get("text", ""))
                if not piece.strip():
                    if text and not text.endswith(" "):
                        text += " "
                    continue
                if prev_x1 is not None:
                    gap = span["bbox"][0] - prev_x1
                    size = max(float(span.get("size", 10.0)), 6.0)
                    if gap > size * 1.2:
                        text = text.rstrip() + "  "
                    elif gap > size * 0.15 and not text.endswith(" ") and not piece.startswith(" "):
                        text += " "  # words positioned apart without an encoded space
                text += piece
                prev_x1 = span["bbox"][2]
            text = re.sub(r"[ \t]{3,}", "  ", text).strip()
            if not text:
                continue
            x0 = min(s["bbox"][0] for s in spans)
            x1 = max(s["bbox"][2] for s in spans)
            y0 = min(s["bbox"][1] for s in spans)
            y1 = max(s["bbox"][3] for s in spans)
            dominant = max(spans, key=lambda s: len(s["text"].strip()))
            lines.append(_Line(
                x0, y0, x1, y1, text, round(float(dominant.get("size", 10.0)), 1),
                _span_is_bold(spans[0]), _span_is_bold(spans[-1]),
            ))
    return lines


def _find_gutter(lines: list[_Line], page_width: float) -> float | None:
    """Return the x position of a two-column gutter, or None for single-column pages."""
    if len(lines) < 12:
        return None
    total_chars = sum(len(line.text) for line in lines)
    best: tuple[int, float] | None = None
    x = page_width * 0.25
    while x <= page_width * 0.75:
        crossing = sum(1 for line in lines if line.x0 < x - 1 and line.x1 > x + 1)
        if best is None or crossing < best[0] or (crossing == best[0] and abs(x - page_width / 2) < abs(best[1] - page_width / 2)):
            best = (crossing, x)
        x += 2.0
    if best is None:
        return None
    crossing, gutter = best
    if crossing > max(2, int(len(lines) * 0.06)):
        return None
    left = [line for line in lines if line.x1 <= gutter + 1]
    right = [line for line in lines if line.x0 >= gutter - 1]
    left_chars = sum(len(line.text) for line in left)
    right_chars = sum(len(line.text) for line in right)
    # Both sides must carry real content; a strip of right-aligned dates is not a column.
    if min(left_chars, right_chars) < total_chars * 0.2 or min(len(left), len(right)) < 5:
        return None
    if median(len(line.text) for line in right) < 12 or median(len(line.text) for line in left) < 12:
        return None
    return gutter


def _reading_order(lines: list[_Line], page_width: float) -> list[list[_Line]]:
    """Split a page into ordered regions; each region is read top-to-bottom."""
    lines = sorted(lines, key=lambda line: (line.y0, line.x0))
    gutter = _find_gutter(lines, page_width)
    if gutter is None:
        return [lines]
    regions: list[list[_Line]] = []
    left: list[_Line] = []
    right: list[_Line] = []

    def flush() -> None:
        columns = [column for column in (left, right) if column]
        if len(columns) == 2:
            line_height = median(line.height for line in left + right)
            # Sidebar layouts often put the name/contact block at the top of the right column.
            if right[0].y0 < left[0].y0 - 2 * line_height:
                columns.reverse()
        regions.extend(list(column) for column in columns)
        left.clear()
        right.clear()

    for line in lines:
        if line.x0 < gutter - 1 and line.x1 > gutter + 1:
            flush()  # full-width line (name banner, spanning heading) closes the column band
            regions.append([line])
        elif line.x1 <= gutter + 1:
            left.append(line)
        else:
            right.append(line)
    flush()
    return regions


def _group_rows(lines: list[_Line]) -> list[_Row]:
    rows: list[_Row] = []
    for line in sorted(lines, key=lambda line: (line.cy, line.x0)):
        if rows:
            row = rows[-1]
            overlap = min(row.y1, line.y1) - max(row.y0, line.y0)
            sizes = (line.size, row.parts[-1].size)
            # A large name banner beside a small contact line is not one logical row.
            similar_size = max(sizes) <= 1.5 * max(min(sizes), 1.0)
            if similar_size and overlap >= 0.5 * min(line.height, row.y1 - row.y0 or 1.0):
                row.parts.append(line)
                continue
        rows.append(_Row([line]))
    return rows


def _normalize_bullet(text: str) -> tuple[str, bool]:
    stripped = text.lstrip()
    if stripped and stripped[0] in BULLET_GLYPHS:
        body = stripped[1:].lstrip(" \t" + "".join(BULLET_GLYPHS))
        return ("• " + body if body else "•"), True
    if _ASCII_BULLET.match(stripped):
        return "• " + _ASCII_BULLET.sub("", stripped, count=1), True
    return stripped, False


def _rows_to_lines(rows: list[_Row]) -> list[str]:
    if not rows:
        return []
    right_edges = sorted(row.x1 for row in rows)
    col_right = right_edges[int(len(right_edges) * 0.95)] if len(right_edges) > 3 else right_edges[-1]
    col_left = min(row.x0 for row in rows)
    width = max(col_right - col_left, 1.0)

    out: list[str] = []
    prev: _Row | None = None
    para_x0 = 0.0
    pending_bullet = False
    for row in rows:
        text, is_bullet = _normalize_bullet(row.text())
        if text == "•":
            pending_bullet = True  # glyph rendered as its own line; attach to next row
            prev = None
            continue
        if pending_bullet and not is_bullet:
            text, is_bullet = "• " + text, True
        pending_bullet = False

        joinable = (
            prev is not None
            and out
            and not is_bullet
            # A multi-fragment row (title + right-aligned dates) only continues into a line that
            # sits under its last fragment, i.e. the wrapped value cell of a "Label  values" table.
            and (len(prev.content_parts) == 1 or abs(row.x0 - prev.content_parts[-1].x0) <= 3)
            and len(row.content_parts) == 1
            and abs(prev.size - row.size) < 0.6
            and prev.content_parts[-1].last_bold == row.content_parts[0].first_bold
            and (row.y0 - prev.y1) < 0.75 * prev.content_parts[-1].height
            and row.x0 >= para_x0 - 2
            and not _DATE_ONLY.match(text)
            and not out[-1].rstrip().endswith(":")
            and not _LABEL_LINE.match(text)
        )
        if joinable:
            last_text = out[-1].rstrip()
            # A finished sentence followed by a capitalised line is kept separate: merging two
            # list items is worse than leaving one paragraph split (sections regroup lines anyway).
            reached_margin = prev.x1 >= col_right - max(0.12 * width, 3 * prev.size) and not (
                last_text.endswith((".", "!", "?")) and text[:1].isupper()
            )
            soft_continuation = (
                (text[:1].islower() and not last_text.endswith(_SENTENCE_END) and not _CONTACT_START.match(text))
                or last_text.endswith(_CONTINUES)
            )
            joinable = reached_margin or soft_continuation
        if joinable:
            last = out[-1]
            if last.endswith("-") and not last.endswith(" -"):
                out[-1] = last + text  # keep compound hyphen ("fine-" + "tuning")
            else:
                out[-1] = last.rstrip() + " " + text
        else:
            out.append(text)
            para_x0 = row.x0
        prev = row
    return out


def reflow_plain_text(text: str) -> str:
    """Re-join visually wrapped lines in text without geometry (OCR output).

    A line continues the previous one when the previous line ran close to the
    longest line width without ending a sentence, or when it starts in lower case.
    """
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    if len(lines) < 3:
        return "\n".join(lines)
    lengths = sorted(len(line) for line in lines)
    full_width = lengths[int(len(lengths) * 0.9)]
    out: list[str] = []
    for line in lines:
        text_line, is_bullet = _normalize_bullet(line)
        if out and not is_bullet:
            prev = out[-1]
            heading = text_line.isupper() and len(text_line.split()) <= 5
            wrapped = len(prev) >= 0.75 * full_width and not prev.endswith(_SENTENCE_END)
            lower_start = (
                text_line[:1].islower() and not prev.endswith(_SENTENCE_END) and not _CONTACT_START.match(text_line)
            )
            if (wrapped or lower_start) and not heading and not _DATE_ONLY.match(text_line) and not _LABEL_LINE.match(text_line):
                out[-1] = (prev + text_line) if prev.endswith("-") and not prev.endswith(" -") else f"{prev} {text_line}"
                continue
        out.append(text_line)
    return "\n".join(out)


def page_text(page: Any) -> str:
    """Return reading-ordered, reflowed text for a single PyMuPDF page."""
    page_dict = page.get_text("dict")
    lines = _collect_lines(page_dict)
    if not lines:
        return ""
    output: list[str] = []
    for region in _reading_order(lines, float(page.rect.width)):
        output.extend(_rows_to_lines(_group_rows(region)))
    return "\n".join(output)
