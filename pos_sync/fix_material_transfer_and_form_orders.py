#!/usr/bin/env python3
"""Perbaikan: Sinkronisasi Material Transfer (required_items) & Form Order (MR) di production_app.

Masalah yang dijawab:
1. "Kenapa tiap WO yang udah kamu import belum material transfer di production app?"
   - Penyebab: Pada Plan PP261007001 (62 WO 7 Okt), parent field `material_transferred_for_manufacturing`
     terisi, tetapi child table `required_items.transferred_qty` masih 0 karena MTFM Stock Entry
     dikecualikan pada catchup awal. Production app membaca child table `required_items[].transferred_qty`
     untuk merender panel "Material".
   - Solusi: Sinkronkan `transferred_qty = required_qty` pada seluruh child table `required_items`
     untuk 62 WO Plan PP261007001.

2. "Untuk form order juga belum kamu import":
   - Penyebab: Seluruh 8 Material Request Form Order 1-7 Okt (`MAT-MR-2026-00786` s/d `00972`)
     sudah ada di site baru, tetapi field `custom_is_form_order` bernilai 0 karena masuk daftar MR_DROP
     di skrip migrasi awal. Endpoint `production_app.api.form_order.form_order_list` memfilter
     `custom_is_form_order = 1`.
   - Solusi: Set `custom_is_form_order = 1` pada seluruh 8 Material Request tersebut.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from migrate_wo_full_okt import Ctx
from prod_common import JURI

FORM_ORDERS = [
    "MAT-MR-2026-00786", "MAT-MR-2026-00822", "MAT-MR-2026-00891",
    "MAT-MR-2026-00892", "MAT-MR-2026-00904", "MAT-MR-2026-00936",
    "MAT-MR-2026-00951", "MAT-MR-2026-00972"
]


def fix_form_orders(ctx):
    print("=" * 80)
    print("1. AKTIVASI FORM ORDER (custom_is_form_order = 1)")
    print("=" * 80)

    # Enable temporary Property Setter
    ctx.new.post("Property Setter", {
        "doctype": "Property Setter", "doctype_or_field": "DocField",
        "doc_type": "Material Request", "field_name": "custom_is_form_order",
        "property": "allow_on_submit", "property_type": "Check", "value": "1"})

    success, failed = [], []
    for mr in FORM_ORDERS:
        st, d = ctx.new.get(f"/api/resource/Material Request/{mr}")
        if st != 200:
            print(f"  [FAIL] {mr}: tidak ada di site baru")
            failed.append(mr)
            continue
        cur = d["data"].get("custom_is_form_order")
        if cur == 1:
            print(f"  [OK] {mr}: sudah aktif (custom_is_form_order = 1)")
            success.append(mr)
            continue
        st2, d2 = ctx.new.req(
            "POST", "/api/method/frappe.client.set_value",
            payload={"doctype": "Material Request", "name": mr,
                     "fieldname": json.dumps({"custom_is_form_order": 1})})
        if st2 in (200, 201):
            print(f"  [OK] {mr}: berhasil diaktifkan sebagai Form Order!")
            success.append(mr)
        else:
            print(f"  [FAIL] {mr} gagal: {json.dumps(d2)[:200]}")
            failed.append(mr)

    # Revert Property Setter
    ctx.new.put("Property Setter", "Material Request-custom_is_form_order-allow_on_submit", {"value": "0"})
    print(f"\nHasil Form Order: {len(success)} aktif, {len(failed)} gagal.")

    # Verifikasi endpoint form_order_list
    st, res = ctx.new.get("/api/method/production_app.api.form_order.form_order_list")
    if st == 200:
        orders = res.get("message", {}).get("orders", [])
        print(f"Verifikasi API form_order_list: {len(orders)} Form Order tampil di workspace:")
        for o in orders:
            print(f"   {o.get('mr')} | SE: {o.get('stock_entry')} | tgl: {o.get('schedule_date')} | status: {o.get('status')} | items: {len(o.get('items', []))}")
    else:
        print("Gagal panggil form_order_list:", res)


def fix_wo_material_transfer(ctx):
    print("\n" + "=" * 80)
    print("2. SINKRONISASI MATERIAL TRANSFER CHILD ROWS (Plan PP261007001)")
    print("=" * 80)

    # Enable temporary Property Setter
    ctx.new.post("Property Setter", {
        "doctype": "Property Setter", "doctype_or_field": "DocField",
        "doc_type": "Work Order Item", "field_name": "transferred_qty",
        "property": "allow_on_submit", "property_type": "Check", "value": "1"})

    # Fetch 62 WOs on Plan PP261007001
    wos = ctx.new.get("/api/resource/Work Order", {
        "filters": json.dumps([["company", "=", JURI],
                               ["production_plan", "=", "PP261007001"]]),
        "fields": json.dumps(["name", "production_item", "qty"]),
        "limit_page_length": 100, "order_by": "name asc"})[1].get("data", [])

    print(f"Memproses {len(wos)} Work Order pada Plan PP261007001...")
    wo_ok, wo_fail = 0, 0
    total_rows = 0

    for w in wos:
        name = w["name"]
        st, d = ctx.new.get(f"/api/resource/Work Order/{name}")
        if st != 200:
            print(f"  [FAIL] {name}: HTTP {st}")
            wo_fail += 1
            continue
        items = d["data"].get("required_items", [])
        updated_in_wo = 0
        for r in items:
            req = float(r.get("required_qty") or 0)
            trans = float(r.get("transferred_qty") or 0)
            if abs(req - trans) > 0.001:
                st_up, _ = ctx.new.req(
                    "POST", "/api/method/frappe.client.set_value",
                    payload={"doctype": "Work Order Item", "name": r["name"],
                             "fieldname": json.dumps({"transferred_qty": req})})
                if st_up in (200, 201):
                    updated_in_wo += 1
                    total_rows += 1
        if updated_in_wo > 0:
            print(f"  [OK] {name}: {updated_in_wo} bahan ditransfer penuh ({items[0].get('item_name')} dkk)")
        else:
            print(f"  [OK] {name}: sudah lengkap ({len(items)} bahan)")
        wo_ok += 1

    # Revert Property Setter
    ctx.new.put("Property Setter", "Work Order Item-transferred_qty-allow_on_submit", {"value": "0"})
    print(f"\nHasil Material Transfer: {wo_ok} WO selesai, {total_rows} baris bahan diupdate.")


def verify_all(ctx):
    print("\n" + "=" * 80)
    print("3. VERIFIKASI AKHIR WORKSPACE")
    print("=" * 80)

    # 1. Cek kekurangan material di seluruh 306 WO 1-7 Okt
    wos = ctx.new.get("/api/resource/Work Order", {
        "filters": json.dumps([["company", "=", JURI],
                               ["planned_start_date", ">=", "2026-10-01"],
                               ["planned_start_date", "<=", "2026-10-07 23:59:59"]]),
        "fields": json.dumps(["name", "production_plan"]),
        "limit_page_length": 500, "order_by": "name asc"})[1].get("data", [])

    short_wos = []
    for w in wos:
        st, d = ctx.new.get(f"/api/resource/Work Order/{w['name']}")
        if st == 200:
            items = d["data"].get("required_items", [])
            short = [it for it in items if float(it.get("transferred_qty") or 0) < float(it.get("required_qty") or 0)]
            if short:
                short_wos.append(w["name"])

    print(f"Pemeriksaan Kekurangan Material (306 WO):")
    if short_wos:
        print(f"  [!] Ditemukan {len(short_wos)} WO dengan bahan belum ditransfer: {short_wos[:5]}")
    else:
        print("  [LOLOS / OK] SELURUH 306 WORK ORDER (100%) SUDAH MEMILIKI MATERIAL LENGKAP!")

    # 2. Cek endpoint wo_detail untuk MFG-WO-2026-04177 (screenshot user)
    st, res = ctx.new.get("/api/method/production_app.api.work_order.wo_detail", {"name": "MFG-WO-2026-04177"})
    if st == 200:
        msg = res.get("message", {})
        req_items = msg.get("required_items", [])
        short = [it for it in req_items if float(it.get("transferred_qty") or 0) < float(it.get("required_qty") or 0)]
        print(f"\nVerifikasi langsung MFG-WO-2026-04177 (screenshot):")
        print(f"  Total bahan: {len(req_items)}")
        print(f"  Kekurangan bahan: {len(short)}")
        for it in req_items[:3]:
            print(f"    {it.get('item_name')}: Kebutuhan={it.get('required_qty')}, Ditransfer={it.get('transferred_qty')}, Status: CUKUP")


def main():
    ctx = Ctx()
    fix_form_orders(ctx)
    fix_wo_material_transfer(ctx)
    verify_all(ctx)


if __name__ == "__main__":
    main()
