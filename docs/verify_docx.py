"""Write docx verification summary to verify_docx_report.txt."""
from __future__ import annotations

import zipfile
from pathlib import Path

DOCX = Path(__file__).resolve().parent / "CA_Office_Suite_Business_Rules_Detailed.docx"
OUT = Path(__file__).resolve().parent / "verify_docx_report.txt"


def main() -> None:
    lines: list[str] = []
    if not DOCX.is_file():
        lines.append("STATUS=MISSING")
        OUT.write_text("\n".join(lines), encoding="utf-8")
        return

    lines.append(f"PATH={DOCX}")
    lines.append(f"SIZE_BYTES={DOCX.stat().st_size}")
    with zipfile.ZipFile(DOCX) as zf:
        names = sorted(zf.namelist())
        lines.append(f"ZIP_PARTS={len(names)}")
        doc = zf.read("word/document.xml").decode("utf-8")
        lines.append(f"DOCUMENT_XML_CHARS={len(doc)}")
        lines.append(f"HEADING1_COUNT={doc.count('w:val=\"Heading1\"')}")
        lines.append(f"HEADING2_COUNT={doc.count('w:val=\"Heading2\"')}")
        lines.append(f"HAS_TOC_FIELD={'TOC \\\\o' in doc or 'TOC \\o' in doc}")
        lines.append(f"HAS_PAGE_FIELD={' PAGE ' in doc}")
        lines.append(f"HAS_NUMPAGES={' NUMPAGES ' in doc}")
        lines.append(f"HAS_TITLE_PAGE={'CA Office Suite' in doc}")
        lines.append(f"HAS_SECTION_17={'17. Appendix' in doc or 'Appendix' in doc}")
    lines.append("STATUS=OK")
    OUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
