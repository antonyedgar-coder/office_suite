"""
Build CA_Office_Suite_Business_Rules_Detailed.docx from the Markdown source.
Uses only the Python standard library (no python-docx required).

Includes Word Table of Contents (update in Word: right-click TOC -> Update field)
and centered page numbers in the footer (Page X of Y).

Run: python docs/build_word_manual.py
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

DOCS = Path(__file__).resolve().parent
SRC = DOCS / "CA_Office_Suite_Business_Rules_Detailed.md"
OUT = DOCS / "CA_Office_Suite_Business_Rules_Detailed.docx"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CP_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC_NS = "http://purl.org/dc/elements/1.1/"
DCTERMS_NS = "http://purl.org/dc/terms/"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
EP_NS = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
VT_NS = "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"


def _esc(text: str) -> str:
    return escape(text, {"'": "&apos;", '"': "&quot;"})


def _run(text: str, *, bold: bool = False, italic: bool = False, size_pt: int = 11) -> str:
    rpr = []
    if bold:
        rpr.append("<w:b/>")
    if italic:
        rpr.append("<w:i/>")
    rpr.append(f'<w:sz w:val="{size_pt * 2}"/>')
    rpr.append(f'<w:szCs w:val="{size_pt * 2}"/>')
    rpr.append('<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/>')
    rpr.append('<w:color w:val="333333"/>')
    rpr_inner = f"<w:rPr>{''.join(rpr)}</w:rPr>" if rpr else ""
    return f"<w:r>{rpr_inner}<w:t xml:space=\"preserve\">{_esc(text)}</w:t></w:r>"


def _runs_formatted(text: str, *, base_size: int = 11) -> str:
    parts = re.split(r"(\*\*[^*]+\*\*)", text)
    out: list[str] = []
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            out.append(_run(part[2:-2], bold=True, size_pt=base_size))
        else:
            out.append(_run(part, size_pt=base_size))
    return "".join(out)


def _p(
    inner: str,
    *,
    style: str | None = None,
    align: str | None = None,
    space_before: int | None = None,
    space_after: int | None = None,
    left_indent: int | None = None,
    page_break_before: bool = False,
) -> str:
    ppr: list[str] = []
    if style:
        ppr.append(f'<w:pStyle w:val="{style}"/>')
    if align:
        ppr.append(f'<w:jc w:val="{align}"/>')
    if space_before is not None:
        ppr.append(f'<w:spacing w:before="{space_before}"/>')
    if space_after is not None:
        ppr.append(f'<w:spacing w:after="{space_after}"/>')
    if left_indent is not None:
        ppr.append(f'<w:ind w:left="{left_indent}"/>')
    if page_break_before:
        ppr.append('<w:pageBreakBefore/>')
    ppr_xml = f"<w:pPr>{''.join(ppr)}</w:pPr>" if ppr else ""
    return f"<w:p>{ppr_xml}{inner}</w:p>"


def _p_text(
    text: str,
    *,
    style: str | None = None,
    align: str | None = None,
    base_size: int = 11,
    **kwargs,
) -> str:
    return _p(_runs_formatted(text, base_size=base_size), style=style, align=align, **kwargs)


def _p_plain(text: str, *, size_pt: int = 11, bold: bool = False, align: str | None = None) -> str:
    return _p(_run(text, bold=bold, size_pt=size_pt), align=align)


def _page_break() -> str:
    return "<w:p><w:r><w:br w:type=\"page\"/></w:r></w:p>"


def _toc_field() -> str:
    return (
        "<w:p>"
        "<w:r>"
        '<w:fldChar w:fldCharType="begin"/>'
        '<w:instrText xml:space="preserve"> TOC \\o "1-3" \\h \\z \\u </w:instrText>'
        '<w:fldChar w:fldCharType="separate"/>'
        "</w:r>"
        f"<w:r>{_run('Right-click here and choose Update Field to refresh the table of contents.', italic=True, size_pt=10)}</w:r>"
        "<w:r>"
        '<w:fldChar w:fldCharType="end"/>'
        "</w:r>"
        "</w:p>"
    )


def _parse_table_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _is_table_separator(line: str) -> bool:
    s = line.strip().replace("|", "").replace(":", "").replace("-", "").strip()
    return not s and "---" in line


def _table_xml(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    ncols = max(len(r) for r in rows)
    grid = "".join(f'<w:gridCol w:w="{(9000 // ncols)}"/>' for _ in range(ncols))
    body_rows: list[str] = []
    for i, row in enumerate(rows):
        cells: list[str] = []
        for j in range(ncols):
            text = row[j] if j < len(row) else ""
            text = re.sub(r"\*\*", "", text)
            runs = _run(text, bold=(i == 0), size_pt=10)
            cells.append(
                "<w:tc>"
                "<w:tcPr><w:tcW w:w=\"0\" w:type=\"auto\"/></w:tcPr>"
                f"<w:p>{runs}</w:p>"
                "</w:tc>"
            )
        body_rows.append(f"<w:tr>{''.join(cells)}</w:tr>")
    return (
        "<w:tbl>"
        "<w:tblPr>"
        '<w:tblW w:w="0" w:type="auto"/>'
        '<w:tblBorders>'
        '<w:top w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:left w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:right w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
        "</w:tblBorders>"
        "</w:tblPr>"
        f"<w:tblGrid>{grid}</w:tblGrid>"
        f"{''.join(body_rows)}"
        "</w:tbl>"
    )


def _page_num_field(instr: str, *, placeholder: str) -> str:
    """PAGE / NUMPAGES field with placeholder text for Word preview."""
    return (
        "<w:r>"
        '<w:fldChar w:fldCharType="begin"/>'
        f'<w:instrText xml:space="preserve"> {instr} </w:instrText>'
        '<w:fldChar w:fldCharType="separate"/>'
        "</w:r>"
        f"<w:r>{_run(placeholder, size_pt=9)}</w:r>"
        "<w:r>"
        '<w:fldChar w:fldCharType="end"/>'
        "</w:r>"
    )


def _footer_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:ftr xmlns:w="{W_NS}">
  <w:p>
    <w:pPr><w:jc w:val="center"/></w:pPr>
    {_run("Page ", size_pt=9)}
    {_page_num_field("PAGE", placeholder="1")}
    {_run(" of ", size_pt=9)}
    {_page_num_field("NUMPAGES", placeholder="1")}
  </w:p>
</w:ftr>"""


def _styles_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W_NS}">
  <w:docDefaults>
    <w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:rPrDefault>
    <w:pPrDefault><w:pPr><w:spacing w:after="160" w:line="259" w:lineRule="auto"/></w:pPr></w:pPrDefault>
  </w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="240"/></w:pPr><w:rPr><w:sz w:val="56"/><w:b/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:sz w:val="32"/><w:b/><w:color w:val="2F5496"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="160" w:after="80"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:sz w:val="26"/><w:b/><w:color w:val="2F5496"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:uiPriority w:val="9"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="120" w:after="60"/><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:sz w:val="22"/><w:b/><w:color w:val="2F5496"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="720"/></w:pPr></w:style>
</w:styles>"""


def _document_xml(body: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{W_NS}" xmlns:r="{R_NS}">
  <w:body>
    {body}
    <w:sectPr>
      <w:footerReference w:type="default" r:id="rIdFooter"/>
      <w:pgSz w:w="12240" w:h="15840"/>
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720"/>
    </w:sectPr>
  </w:body>
</w:document>"""


def _content_types_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="{CT_NS}">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""


def _rels_root_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{REL_NS}">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""


def _document_rels_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{REL_NS}">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
  <Relationship Id="rIdFooter" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
</Relationships>"""


def _core_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="{CP_NS}" xmlns:dc="{DC_NS}" xmlns:dcterms="{DCTERMS_NS}" xmlns:xsi="{XSI_NS}">
  <dc:title>CA Office Suite — Detailed Business Rules</dc:title>
  <dc:creator>CA Office Suite</dc:creator>
  <cp:lastModifiedBy>build_word_manual.py</cp:lastModifiedBy>
</cp:coreProperties>"""


def _app_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="{EP_NS}" xmlns:vt="{VT_NS}">
  <Application>Microsoft Office Word</Application>
</Properties>"""


def _build_body_paragraphs(lines: list[str]) -> list[str]:
    parts: list[str] = []
    table_buffer: list[list[str]] = []
    in_table = False
    body_started = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not body_started:
            if stripped.startswith("## 1."):
                body_started = True
            else:
                i += 1
                continue

        if stripped.startswith("|") and not _is_table_separator(stripped):
            if not in_table:
                in_table = True
                table_buffer = []
            table_buffer.append(_parse_table_row(stripped))
            i += 1
            continue
        if in_table:
            if _is_table_separator(stripped) or not stripped.startswith("|"):
                parts.append(_table_xml(table_buffer))
                parts.append(_p(""))
                table_buffer = []
                in_table = False
            if _is_table_separator(stripped):
                i += 1
                continue
            if in_table:
                i += 1
                continue

        if stripped == "---":
            i += 1
            continue

        if stripped.startswith("# ") and not stripped.startswith("## "):
            i += 1
            continue

        if stripped.startswith("## "):
            title = stripped[3:].strip()
            parts.append(_p(_run(title, bold=True, size_pt=16), style="Heading1", space_before=240, space_after=120))
            i += 1
            continue

        if stripped.startswith("### "):
            title = stripped[4:].strip()
            parts.append(_p(_run(title, bold=True, size_pt=13), style="Heading2", space_before=160, space_after=80))
            i += 1
            continue

        if stripped.startswith("> "):
            parts.append(_p_text(stripped[2:].strip(), left_indent=504))
            i += 1
            continue

        if stripped.startswith("- "):
            parts.append(
                _p(
                    _runs_formatted(stripped[2:].strip()),
                    style="ListParagraph",
                )
            )
            i += 1
            continue

        if re.match(r"^\d+\.\s", stripped):
            text = re.sub(r"^\d+\.\s+", "", stripped)
            parts.append(_p_text(text, style="ListParagraph"))
            i += 1
            continue

        if stripped == "*End of detailed manual*":
            i += 1
            continue

        if stripped:
            parts.append(_p_text(stripped))

        i += 1

    if table_buffer:
        parts.append(_table_xml(table_buffer))
    return parts


def build() -> None:
    text = SRC.read_text(encoding="utf-8")
    lines = text.splitlines()

    body_parts: list[str] = []

    # Title page
    body_parts.append(_p_plain("CA Office Suite", size_pt=28, bold=True, align="center"))
    body_parts.append(
        _p_plain("Detailed Business Rules & Logic Manual", size_pt=18, align="center")
    )
    body_parts.append(_p(""))
    body_parts.append(
        _p_text("For employee training and administration", base_size=12, align="center")
    )
    body_parts.append(_page_break())

    # Table of contents
    body_parts.append(_p(_run("Table of Contents", bold=True, size_pt=14), style="Title"))
    body_parts.append(_p(""))
    body_parts.append(_toc_field())
    body_parts.append(
        _p_text(
            "Tip: In Microsoft Word, right-click the table of contents and select "
            "Update Field → Update entire table.",
            base_size=9,
        )
    )
    body_parts.append(_page_break())

    body_parts.extend(_build_body_paragraphs(lines))

    body_xml = "".join(body_parts)
    document_xml = _document_xml(body_xml)

    with zipfile.ZipFile(OUT, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _content_types_xml())
        zf.writestr("_rels/.rels", _rels_root_xml())
        zf.writestr("word/document.xml", document_xml)
        zf.writestr("word/_rels/document.xml.rels", _document_rels_xml())
        zf.writestr("word/styles.xml", _styles_xml())
        zf.writestr("word/footer1.xml", _footer_xml())
        zf.writestr("docProps/core.xml", _core_xml())
        zf.writestr("docProps/app.xml", _app_xml())

    size = OUT.stat().st_size
    (DOCS / "build_docx_size.txt").write_text(str(size), encoding="utf-8")
    print(f"Created: {OUT} ({size:,} bytes)")


if __name__ == "__main__":
    build()
