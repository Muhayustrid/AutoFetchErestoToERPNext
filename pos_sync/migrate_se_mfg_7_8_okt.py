#!/usr/bin/env python3
"""pos_sync/migrate_se_mfg_7_8_okt.py — Migrasi SE Manufacture 7 & 8 Okt ke site baru.

Memasukkan pasokan riil produksi adonan dari WIP ke Cold Storage Produksi - JURI,
sehingga Serah Terima yang sudah ada tidak menyebabkan stok minus, dan saldo
Cold Storage per 30 Sep 23:59:59 murni 0 tanpa perlu angka fiktif.
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
            ["purpose", "=", "Manufacture"],
            ["docstatus", "=", 1]
        ]),
        "fields": json.dumps(["name", "work_order", "posting_date", "posting_time"]),
        "order_by": "posting_date asc, posting_time asc",
        "limit_page_length": 500
    })
    rows = ses.get("data", [])
    print(f"Total SE Manufacture di LAMA (7-8 Okt): {len(rows)}")

    # Cache BOMs
    bom_cache = {}

    success, skipped, failed = 0, 0, 0
    for idx, r in enumerate(rows, 1):
        old_name = r["name"]
        wo_name = r["work_order"]

        # Check existing
        st_chk, existing = new.get("/api/resource/Stock Entry", {
            "filters": json.dumps([["remarks", "like", f"%{old_name}%"]]),
            "fields": json.dumps(["name", "docstatus"])
        })
        if existing.get("data"):
            skipped += 1
            continue

        st_old, se_old = old.get("/api/resource/Stock Entry/" + old_name)
        if st_old != 200:
            print(f"[{idx}/{len(rows)}] Gagal ambil {old_name} dari LAMA: {st_old}")
            failed += 1
            continue
        old_doc = se_old["data"]

        if wo_name not in bom_cache:
            st_wo, wo_doc = new.get("/api/resource/Work Order/" + wo_name)
            if st_wo != 200:
                print(f"[{idx}/{len(rows)}] WO {wo_name} tidak ditemukan di BARU: {st_wo}")
                failed += 1
                continue
            bom_cache[wo_name] = wo_doc["data"].get("bom_no")
        bom_no = bom_cache[wo_name]

        payload = {
            "doctype": "Stock Entry",
            "stock_entry_type": "Manufacture",
            "purpose": "Manufacture",
            "company": "PT. JUARA ROTI INDONESIA",
            "work_order": wo_name,
            "from_bom": 1,
            "bom_no": bom_no,
            "fg_completed_qty": float(old_doc.get("fg_completed_qty") or 0.0),
            "posting_date": old_doc["posting_date"],
            "posting_time": old_doc["posting_time"],
            "set_posting_time": 1,
            "from_warehouse": "Work In Progress - JURI",
            "to_warehouse": "Cold Storage Produksi - JURI",
            "remarks": f"ERESTO {old_name} | Migrasi Site Lama",
            "items": []
        }

        for it in old_doc.get("items", []):
            s_wh = "Work In Progress - JURI" if it.get("s_warehouse") else None
            t_wh = "Cold Storage Produksi - JURI" if it.get("t_warehouse") else None
            payload["items"].append({
                "item_code": it["item_code"],
                "qty": float(it["qty"]),
                "uom": it.get("uom"),
                "stock_uom": it.get("stock_uom"),
                "conversion_factor": float(it.get("conversion_factor") or 1.0),
                "transfer_qty": float(it.get("transfer_qty") or it["qty"]),
                "s_warehouse": s_wh,
                "t_warehouse": t_wh,
                "is_finished_item": it.get("is_finished_item"),
                "basic_rate": float(it.get("basic_rate") or 0.0),
                "set_basic_rate_manually": 1,
                "allow_zero_valuation_rate": 1
            })

        st_post, res_post = new.post("Stock Entry", payload)
        if st_post != 200:
            print(f"[{idx}/{len(rows)}] Gagal insert {old_name}: {res_post}")
            failed += 1
            continue

        new_name = res_post["data"]["name"]
        st_sub, res_sub = new.submit("Stock Entry", new_name)
        if st_sub != 200:
            print(f"[{idx}/{len(rows)}] Gagal submit {new_name} ({old_name}): {res_sub}")
            failed += 1
            continue

        success += 1
        if idx % 10 == 0 or idx == len(rows):
            print(f"[{idx}/{len(rows)}] Progress: {success} sukses, {skipped} dilewati, {failed} gagal")

    print(f"\n=== SELESAI: {success} sukses, {skipped} dilewati, {failed} gagal ===")

if __name__ == "__main__":
    run()
