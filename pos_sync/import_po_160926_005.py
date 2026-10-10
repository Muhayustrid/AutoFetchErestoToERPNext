#!/usr/bin/env python3
"""Import PO-160926-005 dari ERPNext Lama (rotiropi.j.frappe.cloud) ke ERPNext Baru (ropierpnext.frappe.cloud).

Spesifikasi:
- PO Name: PO-160926-005
- Sumber: https://rotiropi.j.frappe.cloud
- Target: https://ropierpnext.frappe.cloud
- Company: PT. JUARA ROTI INDONESIA
- Supplier: SUP260168 -> CV Mitra Sukses Sejati
- Item: BB260044 (Olesan Dark Choco (1 kg)), Qty: 150 kg, Rate: 57,081
- Warehouse: Gudang Barang Jadi - ROPI -> Gudang Barang Jadi - JURI
- Tax: Purchase Tax - ROPI -> Purchase Tax - JURI (PPN 11% On Net Total)
- Net Total: Rp 8,562,150
- Tax Total: Rp 941,836.50
- Grand Total: Rp 9,503,986.50
- Docstatus: 1 (Submitted)
"""

import json
import os
import sys
import requests


def load_env(filepath):
    env_vars = {}
    if os.path.exists(filepath):
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip().strip('"').strip("'")
    return env_vars


def main():
    mig_env = load_env("/tmp/eresto_mig.env")
    prod_env = load_env("/tmp/eresto_prod.env")

    old_base = "https://rotiropi.j.frappe.cloud"
    old_key = os.environ.get("ERPNEXT_OLD_CLOUD_API_KEY") or mig_env.get("ERPNEXT_OLD_CLOUD_API_KEY")

    target_base = os.environ.get("ERPNEXT_URL") or prod_env.get("ERPNEXT_URL", "https://ropierpnext.frappe.cloud")
    target_key = os.environ.get("ERPNEXT_API_KEY") or prod_env.get("ERPNEXT_API_KEY")

    if not old_key:
        print("ERROR: Kredensial ERPNext Lama (ERPNEXT_OLD_CLOUD_API_KEY) tidak ditemukan!")
        sys.exit(1)
    if not target_key:
        print("ERROR: Kredensial ERPNext Baru (ERPNEXT_API_KEY) tidak ditemukan!")
        sys.exit(1)

    s_old = requests.Session()
    s_old.headers.update({"Authorization": f"token {old_key}"})

    s_target = requests.Session()
    s_target.headers.update({"Authorization": f"token {target_key}"})

    po_name = "PO-160926-005"
    print("=" * 70)
    print(f"IMPORT {po_name} DARI SITUS LAMA KE SITUS BARU")
    print(f"Sumber: {old_base}")
    print(f"Target: {target_base}")
    print("=" * 70)

    # 1. Cek apakah sudah ada di target
    print(f"\n[1/5] Memeriksa keberadaan {po_name} di situs target...")
    r_check = s_target.get(f"{target_base}/api/resource/Purchase Order/{po_name}")
    if r_check.status_code == 200:
        ex = r_check.json().get("data", {})
        print(f"  [!] {po_name} SUDAH ADA di target:")
        print(f"      - Docstatus: {ex.get('docstatus')}")
        print(f"      - Status: {ex.get('status')}")
        print(f"      - Grand Total: Rp {ex.get('grand_total'):,.2f}")
        print(f"      - Supplier: {ex.get('supplier')}")
        return

    # 2. Ambil data asli dari situs lama
    print(f"\n[2/5] Menarik data asli {po_name} dari situs lama...")
    r_src = s_old.get(f"{old_base}/api/resource/Purchase Order/{po_name}")
    if r_src.status_code != 200:
        print(f"  [ERROR] Gagal mengambil {po_name} dari situs lama ({r_src.status_code}): {r_src.text[:200]}")
        sys.exit(1)

    old_doc = r_src.json().get("data", {})
    print(f"  [OK] Data sumber berhasil diambil:")
    print(f"      - Tanggal: {old_doc.get('transaction_date')}")
    print(f"      - Supplier Asli: {old_doc.get('supplier')} ({old_doc.get('supplier_name')})")
    print(f"      - Item count: {len(old_doc.get('items', []))}")
    print(f"      - Net Total: Rp {old_doc.get('net_total'):,.2f}")
    print(f"      - Tax Total: Rp {old_doc.get('total_taxes_and_charges'):,.2f}")
    print(f"      - Grand Total: Rp {old_doc.get('grand_total'):,.2f}")

    # 3. Siapkan payload untuk situs baru
    print(f"\n[3/5] Menyiapkan payload untuk target...")
    target_supplier = "CV Mitra Sukses Sejati"
    target_wh = "Gudang Barang Jadi - JURI"
    target_company = "PT. JUARA ROTI INDONESIA"

    items_payload = []
    for it in old_doc.get("items", []):
        old_uom = it.get("uom", "")
        new_uom = "kg" if old_uom.lower() == "kg" else old_uom

        items_payload.append({
            "item_code": it.get("item_code"),
            "qty": it.get("qty"),
            "uom": new_uom,
            "stock_uom": it.get("stock_uom", "g"),
            "conversion_factor": it.get("conversion_factor", 1000.0),
            "rate": it.get("rate"),
            "warehouse": target_wh,
            "expense_account": "4210.000 - HPP Pembelian - JURI",
            "cost_center": "Main - JURI",
            "schedule_date": it.get("schedule_date") or old_doc.get("schedule_date") or old_doc.get("transaction_date"),
        })

    taxes_payload = []
    for t in old_doc.get("taxes", []):
        taxes_payload.append({
            "category": t.get("category", "Total"),
            "add_deduct_tax": t.get("add_deduct_tax", "Add"),
            "charge_type": t.get("charge_type", "On Net Total"),
            "account_head": "1152.001 - PPN Masukan - JURI",
            "description": "PPN Masukan @ 11.0 - JURI",
            "rate": t.get("rate", 11.0),
            "cost_center": "Main - JURI",
            "tax_amount": t.get("tax_amount"),
            "tax_amount_after_discount_amount": t.get("tax_amount_after_discount_amount") or t.get("tax_amount"),
            "total": t.get("total"),
        })

    payload = {
        "doctype": "Purchase Order",
        "company": target_company,
        "supplier": target_supplier,
        "transaction_date": old_doc.get("transaction_date"),
        "schedule_date": old_doc.get("schedule_date"),
        "set_warehouse": target_wh,
        "currency": "IDR",
        "buying_price_list": "Standard Buying",
        "taxes_and_charges": "Purchase Tax - JURI",
        "title": f"ERESTO {po_name}",
        "remarks": f"Migrasi Site Lama | Ref: {po_name}",
        "items": items_payload,
        "taxes": taxes_payload,
    }

    # 4. Pastikan allow_rename aktif
    s_target.post(
        f"{target_base}/api/resource/Property Setter",
        json={
            "doctype": "Property Setter",
            "doctype_or_field": "DocType",
            "doc_type": "Purchase Order",
            "property": "allow_rename",
            "property_type": "Check",
            "value": "1",
        },
    )

    # 5. POST Draft PO ke target
    print(f"\n[4/5] Mengirim draft Purchase Order ke situs baru...")
    r_post = s_target.post(f"{target_base}/api/resource/Purchase Order", json=payload)
    if r_post.status_code != 200:
        print(f"  [ERROR] POST gagal ({r_post.status_code}): {r_post.text[:400]}")
        sys.exit(1)

    temp_doc = r_post.json().get("data", {})
    temp_name = temp_doc.get("name")
    print(f"  [OK] Draft PO berhasil dibuat dengan nama sementara: {temp_name}")

    # 6. Rename ke PO-160926-005
    print(f"  [>] Melakukan rename {temp_name} -> {po_name}...")
    r_rename = s_target.post(
        f"{target_base}/api/method/frappe.client.rename_doc",
        data={"doctype": "Purchase Order", "old_name": temp_name, "new_name": po_name, "merge": 0},
    )
    if r_rename.status_code == 200:
        final_name = po_name
        print(f"  [OK] Berhasil rename ke {final_name}")
    else:
        print(f"  [WARN] Rename gagal ({r_rename.status_code}): {r_rename.text[:200]}")
        final_name = temp_name

    # 7. Submit Dokumen jika status lama docstatus == 1
    if old_doc.get("docstatus") == 1:
        print(f"\n[5/5] Melakukan submit Purchase Order {final_name}...")
        r_sub = s_target.put(f"{target_base}/api/resource/Purchase Order/{final_name}", json={"docstatus": 1})
        if r_sub.status_code == 200:
            sub_doc = r_sub.json().get("data", {})
            print(f"  [OK] PO {final_name} BERHASIL DI-SUBMIT!")
            print(f"       - Status: {sub_doc.get('status')}")
            print(f"       - Net Total: Rp {sub_doc.get('net_total'):,.2f}")
            print(f"       - Total Taxes: Rp {sub_doc.get('total_taxes_and_charges'):,.2f}")
            print(f"       - Grand Total: Rp {sub_doc.get('grand_total'):,.2f}")
            print(f"       - Items: {len(sub_doc.get('items', []))} baris")
        else:
            print(f"  [ERROR] Submit gagal ({r_sub.status_code}): {r_sub.text[:400]}")
            sys.exit(1)
    else:
        print(f"\n[5/5] Status dokumen sumber adalah draft (docstatus={old_doc.get('docstatus')}), tetap draft.")

    print("\n" + "=" * 70)
    print("PROSES IMPORT SELESAI DENGAN SUKSES!")
    print("=" * 70)


if __name__ == "__main__":
    main()
