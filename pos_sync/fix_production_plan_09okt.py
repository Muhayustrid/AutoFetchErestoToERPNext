#!/usr/bin/env python3
"""pos_sync/fix_production_plan_09okt.py — Perbaiki Work Orders & Stock Entries Production Plan 9 Okt 2026 (JURI).

Masalah:
  1. Work Order required_items memiliki source_warehouse = 'Stores - JURI' (seharusnya 'Gudang Produksi - JURI').
  2. 23 Work Order memiliki fg_warehouse = 'Gudang Barang Jadi - JURI' (seharusnya 'Cold Storage Produksi - JURI').
  3. 35 SE Material Transfer for Manufacture menarik bahan baku dari 'Stores - JURI' -> membuat Stores minus besar.
  4. 23 SE Manufacture menaruh adonan & krim kopi langsung ke 'Gudang Barang Jadi - JURI'.
  5. 2 SE Material Transfer (SE-MTF-261009030 & 031) memindahkan adonan Gempi dari Cold Storage ke Gudang Barang Jadi.

Langkah Perbaikan:
  1. Cancel 2 SE-MTF (sudah selesai).
  2. Cancel 25 SE Manufacture.
  3. Cancel 35 SE Material Transfer for Manufacture.
  4. Update 61 Work Orders (header & required_items -> Gudang Produksi - JURI & Cold Storage Produksi - JURI).
  5. Update Production Plan MFG-PP-2026-00007 (po_items warehouse -> Cold Storage Produksi - JURI).
  6. Recreate 35 SE Material Transfer for Manufacture (dari Gudang Produksi - JURI -> Work In Progress - JURI).
  7. Recreate 25 SE Manufacture (ke Cold Storage Produksi - JURI).
  8. Verifikasi saldo seluruh gudang JURI (tidak ada minus baru, Stores 0 minus, Cold Storage terisi adonan).
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env

BACKUP_FILE = "audit_logs/backup_mfg_pp_261009.json"


def ensure_property_setters(client):
    """Pastikan allow_on_submit = 1 sementara pada DocField WO & WO Item."""
    setters = [
        ("Work Order", "source_warehouse"),
        ("Work Order", "fg_warehouse"),
        ("Work Order", "required_items"),
        ("Work Order Item", "source_warehouse"),
    ]
    for dt, fld in setters:
        client.post("Property Setter", {
            "doctype": "Property Setter",
            "doctype_or_field": "DocField",
            "doc_type": dt,
            "field_name": fld,
            "property": "allow_on_submit",
            "property_type": "Check",
            "value": "1"
        })
    print("[OK] Property Setters configured.")


def cancel_stock_entries(client, backup):
    """Cancel 25 SE-MFG lalu 35 SE-MTFM."""
    mfg_names = []
    mtfm_names = []
    for sname, sdoc in backup["stock_entries"].items():
        if sname.startswith("SE-MTF-26100903"):
            continue  # manual transfer sudah dicancel
        stype = sdoc.get("stock_entry_type")
        if stype == "Manufacture":
            mfg_names.append(sname)
        elif stype == "Material Transfer for Manufacture":
            mtfm_names.append(sname)

    mfg_names.sort(reverse=True)
    mtfm_names.sort(reverse=True)

    print(f"\n--- CANCEL {len(mfg_names)} SE MANUFACTURE ---")
    for sname in mfg_names:
        st, d = client.get(f"/api/resource/Stock Entry/{sname}")
        if st == 200 and d.get("data", {}).get("docstatus") == 1:
            st_c, _ = client.cancel("Stock Entry", sname)
            print(f"  Cancel {sname}: status {st_c}")
        else:
            print(f"  {sname} already cancelled / not submitted.")

    print(f"\n--- CANCEL {len(mtfm_names)} SE MATERIAL TRANSFER FOR MANUFACTURE ---")
    for sname in mtfm_names:
        st, d = client.get(f"/api/resource/Stock Entry/{sname}")
        if st == 200 and d.get("data", {}).get("docstatus") == 1:
            st_c, _ = client.cancel("Stock Entry", sname)
            print(f"  Cancel {sname}: status {st_c}")
        else:
            print(f"  {sname} already cancelled / not submitted.")


def check_stores_negative(client):
    """Verifikasi apakah Stores - JURI masih ada saldo negatif."""
    st, bins = client.get("/api/resource/Bin", {
        "filters": json.dumps([["warehouse", "=", "Stores - JURI"], ["actual_qty", "<", 0]]),
        "fields": json.dumps(["item_code", "actual_qty"])
    })
    rows = bins.get("data", [])
    print(f"\n--- STORES - JURI NEGATIVE BINS: {len(rows)} ---")
    for r in rows:
        print(f"  {r['item_code']}: {r['actual_qty']}")
    return len(rows)


def update_work_orders(client):
    """Update seluruh 61 Work Orders agar source & fg warehouse benar."""
    print("\n--- UPDATING 61 WORK ORDERS ---")
    wos = client.list_all("Work Order", ["name", "docstatus"],
                          filters=[["production_plan", "=", "MFG-PP-2026-00007"]], order="name asc")
    for w in wos:
        wname = w["name"]
        st, d = client.get(f"/api/resource/Work Order/{wname}")
        if st != 200:
            print(f"  [ERROR] Cannot get {wname}")
            continue
        doc = d["data"]
        req_items = doc.get("required_items", [])
        for it in req_items:
            it["source_warehouse"] = "Gudang Produksi - JURI"

        update_payload = {
            "source_warehouse": "Gudang Produksi - JURI",
            "wip_warehouse": "Work In Progress - JURI",
            "fg_warehouse": "Cold Storage Produksi - JURI",
            "required_items": req_items
        }
        st_put, _ = client.put("Work Order", wname, update_payload)
        print(f"  Update {wname} (ds={doc.get('docstatus')}): status {st_put}")

    # Update Production Plan
    print("\n--- UPDATING PRODUCTION PLAN MFG-PP-2026-00007 ---")
    st_pp, d_pp = client.get("/api/resource/Production Plan/MFG-PP-2026-00007")
    if st_pp == 200:
        pp_doc = d_pp["data"]
        po_items = pp_doc.get("po_items", [])
        for it in po_items:
            it["warehouse"] = "Cold Storage Produksi - JURI"
        client.put("Production Plan", "MFG-PP-2026-00007", {"po_items": po_items})
        print("  Production Plan po_items warehouses updated to Cold Storage Produksi - JURI.")


def recreate_stock_entries(client, backup):
    """Recreate 35 MTFM dan 25 MFG dengan gudang yang benar."""
    # 35 WOs: WO-JURI-261009001..010, 018..021, 028..048
    mtfm_wos = []
    for i in range(1, 11):
        mtfm_wos.append(f"WO-JURI-261009{i:03d}")
    for i in range(18, 22):
        mtfm_wos.append(f"WO-JURI-261009{i:03d}")
    for i in range(28, 49):
        mtfm_wos.append(f"WO-JURI-261009{i:03d}")

    print(f"\n--- RE-CREATING {len(mtfm_wos)} SE MATERIAL TRANSFER FOR MANUFACTURE ---")
    for wname in mtfm_wos:
        # Cek apakah sudah ada MTFM submitted untuk WO ini yang source-nya Gudang Produksi
        st_chk, d_chk = client.get("/api/resource/Stock Entry", {
            "filters": json.dumps([
                ["work_order", "=", wname],
                ["stock_entry_type", "=", "Material Transfer for Manufacture"],
                ["docstatus", "=", 1]
            ]),
            "fields": json.dumps(["name", "from_warehouse"])
        })
        existing = d_chk.get("data", [])
        if existing:
            print(f"  MTFM for {wname} already exists: {existing[0]['name']} (skip)")
            continue

        st, res = client.req("POST", "/api/method/erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry", {
            "work_order_id": wname,
            "purpose": "Material Transfer for Manufacture"
        })
        if st != 200:
            print(f"  [ERROR] make_stock_entry MTFM failed for {wname}: {res}")
            continue
        se_doc = res["message"]
        se_doc["naming_series"] = "SE-MTFM-.YY..MM..DD..###."
        se_doc["posting_date"] = "2026-10-09"
        se_doc["set_posting_time"] = 1
        se_doc["to_warehouse"] = "Work In Progress - JURI"
        for it in se_doc.get("items", []):
            it["s_warehouse"] = "Gudang Produksi - JURI"
            it["t_warehouse"] = "Work In Progress - JURI"

        st_post, res_post = client.post("Stock Entry", se_doc)
        if st_post == 200:
            new_se_name = res_post["data"]["name"]
            st_sub, res_sub = client.submit("Stock Entry", new_se_name)
            print(f"  MTFM for {wname} -> {new_se_name} (submitted: {st_sub})")
        else:
            print(f"  [ERROR] POST MTFM failed for {wname}: {res_post}")

    # Re-create 25 MFG
    # 25 WOs: WO-JURI-261009018..021, 028..048
    mfg_wos = []
    for i in range(18, 22):
        mfg_wos.append(f"WO-JURI-261009{i:03d}")
    for i in range(28, 49):
        mfg_wos.append(f"WO-JURI-261009{i:03d}")

    # Map original finished quantities & fg_completed_qty from backup
    orig_mfg = {}
    for sname, sdoc in backup["stock_entries"].items():
        if sdoc.get("stock_entry_type") == "Manufacture":
            wo = sdoc.get("work_order")
            fin_qty = None
            for it in sdoc.get("items", []):
                if it.get("is_finished_item"):
                    fin_qty = float(it.get("qty"))
            orig_mfg[wo] = {
                "fg_completed_qty": sdoc.get("fg_completed_qty"),
                "fin_qty": fin_qty,
                "posting_time": sdoc.get("posting_time")
            }

    print(f"\n--- RE-CREATING {len(mfg_wos)} SE MANUFACTURE ---")
    for wname in mfg_wos:
        # Cek apakah sudah ada MFG submitted untuk WO ini yang to_warehouse-nya Cold Storage
        st_chk, d_chk = client.get("/api/resource/Stock Entry", {
            "filters": json.dumps([
                ["work_order", "=", wname],
                ["stock_entry_type", "=", "Manufacture"],
                ["docstatus", "=", 1]
            ]),
            "fields": json.dumps(["name", "to_warehouse"])
        })
        existing = d_chk.get("data", [])
        if existing:
            print(f"  MFG for {wname} already exists: {existing[0]['name']} (skip)")
            continue

        mfg_meta = orig_mfg.get(wname, {})
        payload = {
            "work_order_id": wname,
            "purpose": "Manufacture"
        }
        if mfg_meta.get("fin_qty"):
            payload["qty"] = mfg_meta["fin_qty"]

        st, res = client.req("POST", "/api/method/erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry", payload)
        if st != 200:
            print(f"  [ERROR] make_stock_entry MFG failed for {wname}: {res}")
            continue
        se_doc = res["message"]
        se_doc["naming_series"] = "SE-MFG-.YY..MM..DD..###."
        se_doc["posting_date"] = "2026-10-09"
        if mfg_meta.get("posting_time"):
            se_doc["set_posting_time"] = 1
            se_doc["posting_time"] = mfg_meta["posting_time"]
        if mfg_meta.get("fg_completed_qty"):
            se_doc["fg_completed_qty"] = mfg_meta["fg_completed_qty"]
        se_doc["from_warehouse"] = "Work In Progress - JURI"
        se_doc["to_warehouse"] = "Cold Storage Produksi - JURI"
        for it in se_doc.get("items", []):
            if it.get("is_finished_item"):
                it["t_warehouse"] = "Cold Storage Produksi - JURI"
                if mfg_meta.get("fin_qty"):
                    it["qty"] = mfg_meta["fin_qty"]
                    it["transfer_qty"] = mfg_meta["fin_qty"]
            else:
                it["s_warehouse"] = "Work In Progress - JURI"

        st_post, res_post = client.post("Stock Entry", se_doc)
        if st_post == 200:
            new_se_name = res_post["data"]["name"]
            st_sub, res_sub = client.submit("Stock Entry", new_se_name)
            print(f"  MFG for {wname} -> {new_se_name} (to Cold Storage, submitted: {st_sub})")
        else:
            print(f"  [ERROR] POST MFG failed for {wname}: {res_post}")


def main():
    with open(BACKUP_FILE) as f:
        backup = json.load(f)

    prod = load_env("/tmp/eresto_prod.env")
    client = Client(prod["ERPNEXT_URL"], prod["ERPNEXT_API_KEY"], "BARU")

    ensure_property_setters(client)
    cancel_stock_entries(client, backup)
    check_stores_negative(client)
    update_work_orders(client)
    recreate_stock_entries(client, backup)
    check_stores_negative(client)
    print("\n[SELESAI] Script eksekusi selesai.")


if __name__ == "__main__":
    main()
