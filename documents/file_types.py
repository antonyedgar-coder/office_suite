"""Allowed upload file types for document type templates."""

from __future__ import annotations

# Each choice maps to one or more lowercase extensions (no dots).
DOCUMENT_FILE_TYPE_CHOICES: list[tuple[str, str]] = [
    ("pdf", "PDF"),
    ("jpeg", "JPEG"),
    ("jpg", "JPG"),
    ("png", "PNG"),
    ("word", "Word"),
    ("xlsm", "XLSM"),
    ("csv", "CSV"),
    ("xlsx", "XLSX"),
    ("ppt", "PowerPoint"),
    ("zip", "ZIP"),
    ("rar", "RAR"),
]

EXTENSIONS_BY_FILE_TYPE: dict[str, tuple[str, ...]] = {
    "pdf": ("pdf",),
    "jpeg": ("jpeg",),
    "jpg": ("jpg",),
    "png": ("png",),
    "word": ("doc", "docx"),
    "xlsm": ("xlsm",),
    "csv": ("csv",),
    "xlsx": ("xlsx", "xls"),  # legacy .xls uploads grouped with Excel
    "ppt": ("ppt", "pptx"),
    "zip": ("zip",),
    "rar": ("rar",),
}

_LABEL_BY_EXTENSION: dict[str, str] = {}
for _key, _label in DOCUMENT_FILE_TYPE_CHOICES:
    for _ext in EXTENSIONS_BY_FILE_TYPE[_key]:
        _LABEL_BY_EXTENSION.setdefault(_ext, _label)


def all_known_extensions() -> set[str]:
    out: set[str] = set()
    for exts in EXTENSIONS_BY_FILE_TYPE.values():
        out.update(exts)
    return out


def extensions_from_file_type_choices(choice_keys: list[str] | set[str]) -> str:
    """Comma-separated extension string for DocumentTypeTemplate.allowed_extensions."""
    exts: set[str] = set()
    for key in choice_keys:
        exts.update(EXTENSIONS_BY_FILE_TYPE.get(key, ()))
    if not exts:
        return "pdf"
    return ",".join(sorted(exts))


def file_type_choices_from_extensions(extensions_csv: str) -> list[str]:
    """Map stored extensions to selected file-type choice keys."""
    allowed = {
        p.strip().lower().lstrip(".")
        for p in (extensions_csv or "").split(",")
        if p.strip()
    }
    selected: list[str] = []
    for key, exts in EXTENSIONS_BY_FILE_TYPE.items():
        if any(ext in allowed for ext in exts):
            selected.append(key)
    return selected


def format_extension_labels(extensions: set[str] | list[str]) -> str:
    """Human-readable labels for list views (e.g. PDF, Word, XLSX)."""
    ext_set = {e.strip().lower().lstrip(".") for e in extensions if e}
    if not ext_set:
        return "—"
    labels: list[str] = []
    seen: set[str] = set()
    for key, label in DOCUMENT_FILE_TYPE_CHOICES:
        group = EXTENSIONS_BY_FILE_TYPE[key]
        if any(ext in ext_set for ext in group):
            if label not in seen:
                labels.append(label)
                seen.add(label)
    for ext in sorted(ext_set):
        if ext not in {e for g in EXTENSIONS_BY_FILE_TYPE.values() for e in g}:
            labels.append(ext.upper())
    return ", ".join(labels) if labels else "—"
