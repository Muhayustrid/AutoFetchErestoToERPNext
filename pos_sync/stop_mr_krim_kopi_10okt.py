#!/usr/bin/env python3
"""pos_sync/stop_mr_krim_kopi_10okt.py — Stop MR manual Krim Kopi yang menahan pool.

Konteks (2026-10-10): handover WO Krim Kopi (PJ260016) ditolak "Qty melebihi
lot tersedia: diminta 26, tersedia -3482". Pool Cold Storage = 869, tetapi
_pool_reserved_now menjumlah 4 MR migrasi berstatus Transferred tanpa SE
(fix kode di production_app) + MREQ-MTR-26-0190 (Pending, 869 Pcs, dibuat
manual 9 Okt, tanpa Work Order). Keputusan user: Stop MR-0190.

DEFAULT DRY-RUN. Jalankan: python pos_sync/stop_mr_krim_kopi_10okt.py --execute
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env

MR = "MREQ-MTR-26-0190"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    prod = load_env("/tmp/eresto_prod.env")
    c = Client(prod["ERPNEXT_URL"], prod["ERPNEXT_API_KEY"], "BARU")

    st, d = c.get(f"/api/resource/Material Request/{MR}")
    if st != 200:
        sys.exit(f"GAGAL baca {MR}: {st}")
    doc = d["data"]
    print(f"{MR}: docstatus={doc['docstatus']} status={doc['status']}",
          [(i["item_code"], i["qty"], i.get("custom_work_order")) for i in doc["items"]])
    if doc["status"] == "Stopped":
        print("SKIP_EXISTS: sudah Stopped")
        return
    if doc["docstatus"] != 1 or doc["status"] != "Pending":
        sys.exit("BATAL: status tidak terduga, cek manual")
    if not args.execute:
        print("DRY-RUN: akan di-Stop. Tambah --execute.")
        return

    st, d = c.req("POST", "/api/method/erpnext.stock.doctype.material_request."
                  "material_request.update_status", {"name": MR, "status": "Stopped"})
    print("update_status:", st, "OK" if st == 200 else d.get("exception", d))
    st, d = c.get(f"/api/resource/Material Request/{MR}")
    print("VERIFIKASI status:", d["data"]["status"],
          "LOLOS" if d["data"]["status"] == "Stopped" else "GAGAL")


if __name__ == "__main__":
    main()
