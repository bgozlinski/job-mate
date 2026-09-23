"""Turning a stored resume into a file its owner can take away (FR-5).

The export converts and nothing more: the "improved" resume is a version the user wrote
themselves from a match's suggestions, stored like any other (FR-2). Nothing here calls
a model, so nothing here can invent a fact the resume does not state.
"""

import functools
import io
import re
from pathlib import Path
from typing import Literal

import docx
from fontTools.ttLib import TTFont
from fpdf import FPDF, XPos, YPos

from app.models.resume import Resume

type ExportFormat = Literal["md", "docx", "pdf"]

MEDIA_TYPES: dict[ExportFormat, str] = {
    "md": "text/markdown; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
"""Control characters XML 1.0 cannot carry; python-docx raises ValueError on them."""

FONT = (
    Path(__file__).resolve().parent.parent / "assets" / "fonts" / "PTSans-Regular.ttf"
)
"""
PT Sans, unmodified, under the OFL (licence alongside). The PDF core fonts are Latin-1
only and cannot draw a Polish letter. Chosen for Polish coverage at a size under the
500 KB large-file hook; subsetting a bigger font would be a modified version, which
its Reserved Font Name forbids distributing under that name.
"""

BODY_SIZE = 11
HEADING_SIZE = 16
LINE_HEIGHT = 6


def filename(resume: Resume, fmt: ExportFormat) -> str:
    """Name the file after the row, never after anything the user typed.

    The role or the original filename would put user text into Content-Disposition,
    where a quote or a newline breaks the header.
    """
    return f"resume-{resume.id}.{fmt}"


def to_markdown(resume: Resume) -> bytes:
    """Render the resume as Markdown: the role as a heading, then the text verbatim.

    Verbatim rather than escaped: it is the owner's own text, which may already use
    Markdown bullets, and escaping would turn those into literal asterisks.
    """
    heading = f"# {resume.target_role.strip()}\n\n" if resume.target_role else ""

    return f"{heading}{resume.content.strip()}\n".encode()


def to_docx(resume: Resume) -> bytes:
    """Render the resume as a Word document, one paragraph per line.

    The role is the heading, and blank lines stay blank paragraphs, so the spacing of
    the original survives. Control characters are dropped before the split, not after:
    splitlines() treats vertical tab, form feed and the separators U+001C-U+001E as
    line breaks, so each would otherwise leave a stray empty paragraph.
    """
    document = docx.Document()

    if resume.target_role:
        document.add_heading(_without_control(resume.target_role.strip()), level=1)

    for line in _without_control(resume.content).strip().splitlines():
        document.add_paragraph(line)

    buffer = io.BytesIO()
    document.save(buffer)

    return buffer.getvalue()


def to_pdf(resume: Resume) -> bytes:
    """Render the resume as a PDF: the role as a heading, the text wrapped to the page.

    Characters the font cannot draw -- emoji, mostly -- are left out rather than
    rendered as blanks, so what is missing is decided here and not by a warning.
    Every cell returns to the left margin: fpdf2 leaves the cursor at the right edge
    by default, where the next line has no width to be drawn in.
    """
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.add_font("body", fname=str(FONT))

    def line(text: str, height: float) -> None:
        pdf.multi_cell(0, height, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    if resume.target_role:
        pdf.set_font("body", size=HEADING_SIZE)
        line(_drawable(resume.target_role.strip()), LINE_HEIGHT * 1.5)
        pdf.ln(LINE_HEIGHT)

    pdf.set_font("body", size=BODY_SIZE)

    for text in _drawable(resume.content).strip().splitlines():
        line(text, LINE_HEIGHT)

    return bytes(pdf.output())


@functools.cache
def _glyphs() -> frozenset[int]:
    """Read, once, the code points the font has a glyph for."""
    return frozenset(TTFont(FONT).getBestCmap())


def _drawable(text: str) -> str:
    """Keep line breaks and whatever the font can draw; drop the rest."""
    glyphs = _glyphs()

    return "".join(
        char for char in _without_control(text) if char == "\n" or ord(char) in glyphs
    )


def _without_control(text: str) -> str:
    """Drop the control characters text extracted from a PDF sometimes carries."""
    return _CONTROL.sub("", text)


RENDERERS = {"md": to_markdown, "docx": to_docx, "pdf": to_pdf}
