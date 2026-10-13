#!/usr/bin/env python3
"""Hapus duplikat PO PT. JURI ROTI (draft kembar) di CLOUD BARU.

Keputusan user 2026-10-12 ("duplikat lebih baik dihapus"). Audit isi
(company+supplier+tanggal+item) menemukan 2 duplikat nyata selain yang sudah
dihapus (`PO-JURI-261009011`):
  - `PO126.280926.002` duplikat `PO126.280926.001` (RSUD PADANGAN BOJONEGORO,
    28 Sep, Rp113.000) — dua-duanya draft, simpan 001.
  - `POO53.300926.001` duplikat `POO53.300926.002` (RSUD SETJONEGORO WONOSOBO,
    30 Sep, Rp16.443.020) — simpan 002 (submitted).

Prosedur (KNOWLEDGE §6): BACKUP JSON -> guard docstatus draft & tidak ada
PR/PI -> DELETE -> verifikasi 404 + penjaga tetap ada. Idempoten (rerun SKIP).

CLI:
  python pos_sync/hapus_po_juri_duplikat.py [--execute] [--only PO126.280926.002 ...]

Env: /tmp/eresto_prod.env (ERPNEXT_URL CLOUD, ERPNEXT_API_KEY).
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env  # noqa: E402

# (hapus, pertahankan, catatan)
TARGETS = [
    ("PO126.280926.002", "PO126.280926.001",
     "RSUD PADANGAN BOJONEGORO 28 Sep Rp113.000 (dua-duanya draft)"),
    ("POO53.300926.001", "POO53.300926.002",
     "RSUD SETJONEGORO WONOSOBO 30 Sep Rp16.443.020 (002 submitted)"),
]
AUDIT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "audit_logs")


def same_content(a, b):
    return (a.get("company") == b.get("company")
            and a.get("supplier") == b.get("supplier")
            and safe(a.get("transaction_date")) == safe(b.get("transaction_date"))
            and abs(float(a.get("grand_total") or 0) - float(b.get("grand_total") or 0)) < 1
            and [(i.get("item_code"), round(float(i.get("qty") or 0), 3),
                  round(float(i.get("rate") or 0), 2)) for i in a.get("items", [])]
            == [(i.get("item_code"), round(float(i.get("qty") or 0), 3),
                 round(float(i.get("rate") or 0), 2)) for i in b.get("items", [])])


def safe(v):
    return "" if v is None else str(v)


def process(erp, trash, keep, note, execute):
    print("-" * 84)
    print(f"  HAPUS {trash} (simpan {keep}) — {note}")
    st, body = erp.get(f"/api/resource/Purchase Order/{trash}")
    if st == 404:
        print(f"    [SKIP] {trash} sudah tidak ada (idempoten).")
        return "SKIP"
    if st != 200:
        print(f"    [GAGAL] baca {trash}: HTTP {st}")
        return "FAIL"
    doc = body.get("data", body)
    stk, bodyk = erp.get(f"/api/resource/Purchase Order/{keep}")
    keepd = bodyk.get("data", bodyk) if stk == 200 else {}
    print(f"    {trash}: ds={doc.get('docstatus')} {doc.get('status')} "
          f"Rp{doc.get('grand_total')} owner={doc.get('owner')}")
    print(f"    {keep}: {'ADA ds=' + str(keepd.get('docstatus')) if stk == 200 else 'TIDAK ADA'}"
          f" | identik={same_content(doc, keepd) if keepd else '?'}")

    if doc.get("docstatus") != 0:
        print(f"    [REFUSE] {trash} bukan draft.")
        return "REFUSE"

    troubles = []
    for dt, field in [("Purchase Receipt Item", "purchase_order"),
                      ("Purchase Invoice Item", "purchase_order")]:
        st_c, body_c = erp.get(f"/api/resource/{dt}", params={
            "filters": json.dumps([[field, "=", trash]]),
            "fields": json.dumps(["parent"]), "limit_page_length": 5})
        rows = body_c.get("data", []) if st_c == 200 else []
        if rows:
            troubles.append(f"{dt}:{rows}")
    if troubles:
        print(f"    [REFUSE] masih dirujuk -> {troubles}")
        return "REFUSE"

    if not execute:
        print("    [DRY-RUN] tidak dihapus.")
        return "DRYRUN"

    # backup
    os.makedirs(AUDIT_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(AUDIT_DIR, f"backup_{trash.replace('/', '_')}_{stamp}.json")
    with open(path, "w") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"    Backup: {path}")

    st_d, body_d = erp.delete("Purchase Order", trash)
    print(f"    [{'OK' if st_d in (200, 202, 204) else 'GAGAL'}] DELETE -> HTTP {st_d}")
    if st_d not in (200, 202, 204):
        print(f"      {str(body_d)[:250]}")
        return "FAIL"
    st_v, _ = erp.get(f"/api/resource/Purchase Order/{trash}")
    st_k2, _ = erp.get(f"/api/resource/Purchase Order/{keep}")
    print(f"    Verifikasi: {trash} -> HTTP {st_v} "
          f"({'hilang OK' if st_v == 404 else 'MASIH ADA!'}) | {keep} ada={st_k2 == 200}")
    return "DELETED"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--only", nargs="*", default=None,
                    help="batasi ke dokumen yg dihapus tertentu")
    args = ap.parse_args()

    env = load_env("/tmp/eresto_prod.env")
    url, key = env["ERPNEXT_URL"], env["ERPNEXT_API_KEY"]
    erp = Client(url, key, label="BARU")
    print("=" * 84)
    print("  HAPUS DUPLIKAT PO PT. JURI (draft kembar) — CLOUD BARU")
    print(f"  TARGET SITE: {url}")
    print("=" * 84)

    targets = [t for t in TARGETS if not args.only or t[0] in set(args.only)]
    results = {}
    for trash, keep, note in targets:
        results[trash] = process(erp, trash, keep, note, args.execute)

    print("=" * 84)
    print("  Hasil:", results)
    if not args.execute:
        print("  [DRY-RUN] jalankan dengan --execute untuk eksekusi.")
    print("=" * 84)


if __name__ == "__main__":
    main()
