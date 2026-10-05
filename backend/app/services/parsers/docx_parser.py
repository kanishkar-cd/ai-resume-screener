from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.schemas.parsed_document import ParserEngine
from app.services.parsers.base import ParseOutput


def _is_list_paragraph(paragraph: Paragraph) -> bool:
    p_pr = paragraph._p.pPr
    if p_pr is not None and p_pr.numPr is not None:
        return True
    style_name = (paragraph.style.name if paragraph.style is not None else "") or ""
    return style_name.lower().startswith("list")


def _paragraph_lines(paragraph: Paragraph) -> list[str]:
    text = paragraph.text.strip()
    if not text:
        return []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if _is_list_paragraph(paragraph):
        # Word list items carry no bullet glyph in their text; mark them like PDF bullets.
        lines[0] = "• " + lines[0].lstrip("•●▪-* ")
    return lines


def _table_lines(table: Table) -> list[str]:
    lines: list[str] = []
    for row in table.rows:
        cells: list[str] = []
        for cell in row.cells:
            cell_text = "\n".join(
                line for paragraph in cell.paragraphs for line in _paragraph_lines(paragraph)
            ).strip()
            if cell_text and cell_text not in cells:  # merged cells repeat their text
                cells.append(cell_text)
        if not cells:
            continue
        if all("\n" not in cell for cell in cells):
            lines.append(" | ".join(cells))
        else:
            # Layout tables (whole resume sections inside cells): keep each cell's lines.
            for cell in cells:
                lines.extend(cell.splitlines())
    return lines


def parse_docx(path: Path) -> ParseOutput:
    document = Document(str(path))
    text_parts: list[str] = []

    # Many templates place the candidate name/contact block in the page header.
    for section in document.sections[:1]:
        for paragraph in section.header.paragraphs:
            text_parts.extend(_paragraph_lines(paragraph))

    # Walk the body in document order so tables stay where they appear.
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            text_parts.extend(_paragraph_lines(Paragraph(child, document)))
        elif child.tag == qn("w:tbl"):
            text_parts.extend(_table_lines(Table(child, document)))

    raw_text = "\n".join(text_parts).strip()
    return ParseOutput(
        raw_text=raw_text,
        page_count=None,
        parser_engine=ParserEngine.PYTHON_DOCX,
    )
