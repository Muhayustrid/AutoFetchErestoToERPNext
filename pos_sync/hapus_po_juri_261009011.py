#!/usr/bin/env python3
"""Hapus duplikat PO `PO-JURI-261009011` (Draft) di CLOUD BARU.

Konteks (keputusan user 2026-10-12: "duplikat lebih baik dihapus"):
- `PO-JURI-261009011` = duplikat `PO-JURI-261009012` (Submitted) — supplier,
  tanggal, item, qty, rate, gudang IDENTIK. Dibuat 44 detik beruntun
  (14:36:53 vs 14:37:37) oleh akun purchasing `abicidfg@gmail.com`.
- 011 masih **Draft** (docstatus 0), belum ada PR/PI/GL/SLE → aman dihapus.
- 012 (Submitted, To Receive and Bill) DIPERTAHANKAN.

Prosedur (destruktif — mengikuti KNOWLEDGE §6):
  1. BACKUP JSON dokumen penuh (audit_logs/).
  2. Guard: docstatus harus 0 (draft) — selain itu REFUSE.
  3. Guard: tidak ada Purchase Receipt Item / Purchase Invoice Item yang
     merujuk dokumen ini.
  4. DELETE /api/resource/Purchase Order/<name>.
  5. Verifikasi: GET 404 + tidak muncul di list.
Idempoten: rerun = dokumen sudah tidak ada -> SKIP.

CLI:
  python pos_sync/hapus_po_juri_261009011.py [--execute]

Env: /tmp/eresto_prod.env (ERPNEXT_URL CLOUD, ERPNEXT_API_KEY).
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env  # noqa: E402

TARGET_PO = "PO-JURI-261009011"
KEEP_PO = "PO-JURI-261009012"
AUDIT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "audit_logs")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--execute", action="store_true", help="jalankan (default dry-run)")
    args = ap.parse_args()

    env = load_env("/tmp/eresto_prod.env")
    url, key = env["ERPNEXT_URL"], env["ERPNEXT_API_KEY"]
    erp = Client(url, key, label="BARU")
    print("=" * 84)
    print(f"  HAPUS DUPLIKAT {TARGET_PO} (amankan {KEEP_PO})")
    print(f"  TARGET SITE: {url}")
    print("=" * 84)

    # --- baca dokumen ---
    st, body = erp.get(f"/api/resource/Purchase Order/{TARGET_PO}")
    if st == 404:
        print(f"  [SKIP] {TARGET_PO} sudah tidak ada (idempoten).")
        return
    if st != 200:
        raise SystemExit(f"  GAGAL baca {TARGET_PO}: HTTP {st} {str(body)[:200]}")
    doc = body.get("data", body)
    print(f"  {TARGET_PO}: ds={doc.get('docstatus')} status={doc.get('status')} "
          f"supplier={doc.get('supplier')} Rp{doc.get('grand_total')} "
          f"owner={doc.get('owner')}")

    # --- guard 1: draft ---
    if doc.get("docstatus") != 0:
        raise SystemExit(f"  REFUSE: {TARGET_PO} bukan draft (ds={doc.get('docstatus')}) — "
                         "jangan hapus dokumen yang sudah submit.")

    # --- guard 2: tidak ada rantai turunan ---
    troubles = []
    for dt, field in [("Purchase Receipt Item", "purchase_order"),
                      ("Purchase Invoice Item", "purchase_order")]:
        st_c, body_c = erp.get(f"/api/resource/{dt}", params={
            "filters": json.dumps([[field, "=", TARGET_PO]]),
            "fields": json.dumps(["parent", "item_code"]), "limit_page_length": 5})
        rows = body_c.get("data", []) if st_c == 200 else []
        if rows:
            troubles.append(f"{dt}: {rows}")
    if troubles:
        raise SystemExit(f"  REFUSE: masih dirujuk -> {troubles}")

    # --- banding cepat dgn dokumen yang dipertahankan ---
    st_k, body_k = erp.get(f"/api/resource/Purchase Order/{KEEP_PO}")
    if st_k == 200:
        keep = body_k.get("data", body_k)
        same = (keep.get("supplier") == doc.get("supplier")
                and abs(float(keep.get("grand_total") or 0) - float(doc.get("grand_total") or 0)) < 1
                and [(i.get("item_code"), i.get("qty"), i.get("rate"))
                     for i in keep.get("items", [])]
                == [(i.get("item_code"), i.get("qty"), i.get("rate"))
                    for i in doc.get("items", [])])
        print(f"  {KEEP_PO}: ds={keep.get('docstatus')} identik-dengan-{TARGET_PO}={same}")

    print(f"\n  Rencana: HAPUS {TARGET_PO} (draft duplikat).")
    if not args.execute:
        print("  [DRY-RUN] jalankan dengan --execute untuk eksekusi.")
        return

    # --- backup ---
    os.makedirs(AUDIT_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(AUDIT_DIR, f"backup_{TARGET_PO.replace('/', '_')}_{stamp}.json")
    with open(path, "w") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"  Backup: {path}")

    # --- hapus ---
    st_d, body_d = erp.delete("Purchase Order", TARGET_PO)
    if st_d not in (200, 202, 204):
        raise SystemExit(f"  GAGAL hapus: HTTP {st_d} {str(body_d)[:300]}")
    print(f"  [OK] DELETE {TARGET_PO} -> HTTP {st_d}")

    # --- verifikasi ---
    st_v, _ = erp.get(f"/api/resource/Purchase Order/{TARGET_PO}")
    print(f"  Verifikasi: GET {TARGET_PO} -> HTTP {st_v} "
          f"({'OK hilang' if st_v == 404 else 'MASIH ADA!'})")
    st_k2, body_k2 = erp.get(f"/api/resource/Purchase Order/{KEEP_PO}")
    print(f"  {KEEP_PO} tetap ada: {st_k2 == 200} "
          f"(ds={(body_k2.get('data') or {}).get('docstatus') if st_k2 == 200 else '-'})")
    print("=" * 84)


if __name__ == "__main__":
    main()
