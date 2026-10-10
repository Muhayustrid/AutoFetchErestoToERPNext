#!/usr/bin/env python3
"""pos_sync/migrate_mtfm_7_8_okt.py — Migrasi SE Material Transfer for Manufacture 7 & 8 Okt ke site baru.

Menyuplai pasokan bahan baku riil dari Gudang Produksi - JURI ke Work In Progress - JURI,
sehingga konsumsi SE Manufacture 7 & 8 Okt memiliki pasokan yang seimbang dan tidak
menyebabkan saldo minus di WIP.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env

def run():
    prod = load_env("/tmp/eresto_prod.env")
    mig = load_env("/tmp/eresto_mig.env")
    new = Client(prod["ERPNEXT_URL"], prod["ERPNEXT_API_KEY"], "BARU")
    old = Client("https://rotiropi.j.frappe.cloud", mig["ERPNEXT_OLD_CLOUD_API_KEY"], "LAMA")

    st, ses = old.get("/api/resource/Stock Entry", {
        "filters": json.dumps([
            ["company", "=", "PT. JUARA ROTI INDONESIA"],
            ["posting_date", "in", ["2026-10-07", "2026-10-08"]],
            ["purpose", "=", "Material Transfer for Manufacture"],
            ["docstatus", "=", 1]
        ]),
        "fields": json.dumps(["name", "work_order", "posting_date", "posting_time"]),
        "order_by": "posting_date asc, posting_time asc",
        "limit_page_length": 500
    })
    rows = ses.get("data", [])
    print(f"Total MTFM di LAMA (7-8 Okt): {len(rows)}")

    success, skipped, failed = 0, 0, 0
    for idx, r in enumerate(rows, 1):
        old_name = r["name"]
        wo_name = r["work_order"]
        post_date = r["posting_date"]
        post_time = r["posting_time"]

        # 1. Check existing on BARU
        st_chk, existing = new.get("/api/resource/Stock Entry", {
            "filters": json.dumps([
                ["remarks", "like", f"%{old_name}%"],
                ["docstatus", "=", 1]
            ]),
            "fields": json.dumps(["name"])
        })
        if existing.get("data"):
            print(f"[{idx}/{len(rows)}] {old_name} -> {existing['data'][0]['name']} (already exists, skip)")
            skipped += 1
            continue

        # 2. Make Stock Entry from WO
        st_make, res_make = new.req("POST", "/api/method/erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry", {
            "work_order_id": wo_name,
            "purpose": "Material Transfer for Manufacture"
        })
        if st_make != 200:
            print(f"[{idx}/{len(rows)}] [ERROR] make_stock_entry failed for {wo_name} ({old_name}): {res_make}")
            failed += 1
            continue

        se_doc = res_make["message"]
        se_doc["naming_series"] = "SE-MTFM-.YY..MM..DD..###."
        se_doc["company"] = "PT. JUARA ROTI INDONESIA"
        se_doc["posting_date"] = post_date
        se_doc["posting_time"] = post_time
        se_doc["set_posting_time"] = 1
        se_doc["remarks"] = f"ERESTO {old_name} | Migrasi Site Lama"
        se_doc["to_warehouse"] = "Work In Progress - JURI"
        for it in se_doc.get("items", []):
            it["s_warehouse"] = "Gudang Produksi - JURI"
            it["t_warehouse"] = "Work In Progress - JURI"

        # 3. Post and submit
        st_post, res_post = new.post("Stock Entry", se_doc)
        if st_post == 200:
            new_name = res_post["data"]["name"]
            st_sub, res_sub = new.submit("Stock Entry", new_name)
            if st_sub == 200:
                print(f"[{idx}/{len(rows)}] {old_name} -> {new_name} for {wo_name} (submitted)")
                success += 1
            else:
                print(f"[{idx}/{len(rows)}] [ERROR] Submit {new_name} failed: {res_sub}")
                failed += 1
        else:
            print(f"[{idx}/{len(rows)}] [ERROR] POST {old_name} failed: {res_post}")
            failed += 1

    print(f"\n[SELESAI] Sukses: {success}, Skipped: {skipped}, Gagal: {failed}")

if __name__ == "__main__":
    run()
