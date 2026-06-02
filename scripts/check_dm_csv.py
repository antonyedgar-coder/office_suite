"""One-off: validate director mapping CSV. Run from real-app: python scripts/check_dm_csv.py <path>"""
import os
import sys
from collections import Counter
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ca_suite.settings")

def main():
    import django
    django.setup()
    from masters.director_mapping_import import (
        attach_client_master_validation,
        parse_director_mappings_csv,
        validate_director_mapping_import_active_uniqueness_in_file,
    )

    path = Path(sys.argv[1])
    raw = path.read_bytes()
    rows, file_errors = parse_director_mappings_csv(raw)
    if file_errors:
        print("FILE:", file_errors)
        return
    attach_client_master_validation(rows)
    validate_director_mapping_import_active_uniqueness_in_file(rows)
    bad = [r for r in rows if r.errors]
    same_id = sum(
        1
        for r in rows
        if (r.data.get("director_client_id") or "").upper()
        == (r.data.get("company_client_id") or "").upper()
    )
    ctr = Counter(e for r in bad for e in r.errors)
    print(f"total={len(rows)} bad={len(bad)} ok={len(rows)-len(bad)} same_director_company_id={same_id}")
    for msg, n in ctr.most_common(15):
        print(f"  {n:4d}  {msg}")
    for r in bad[:5]:
        print(f"  row {r.row_num}: {r.errors}")


if __name__ == "__main__":
    main()
