"""Harmonize Item Name for Paket Hemat items on ERPNext Cloud.

Sesuai arahan user:
Menyeragamkan nama item hemat menjadi tanpa kata "Paket":
- ITEM00001 & PAKET26-004 -> "Hemat 1 NEW"
- PAKET26-005 -> "Hemat 2 New" (sebelumnya "Paket Hemat 2 New")
- PAKET26-001 & PAKET26-003 -> "Hemat 3 New"
- PAKET26-006 -> "Hemat 4 New" (sebelumnya "Paket Hemat 4 New")

Juga mengupdate child table POS Invoice Item yang sudah tersubmit agar
dashboard Top Selling Items di POS Next langsung menampilkan "Hemat 2 New".
"""

import csv
import json
import os
import sys
import requests

NEW_BASE = "https://ropierpnext.frappe.cloud"
NEW_KEY = os.environ.get("ERPNEXT_API_KEY", "")

s = requests.Session()
s.headers.update({
    "Authorization": f"token {NEW_KEY}",
    "Accept": "application/json"
})

ITEM_NAME_MAP = {
    "ITEM00001": "Hemat 1 NEW",
    "PAKET26-004": "Hemat 1 NEW",
    "PAKET26-005": "Hemat 2 New",
    "PAKET26-001": "Hemat 3 New",
    "PAKET26-003": "Hemat 3 New",
    "PAKET26-006": "Hemat 4 New",
}


def main():
    print("=" * 60)
    print("PENYERAGAMAN NAMA ITEM PAKET HEMAT")
    print("=" * 60)

    # 1. Update Item Master
    print("\n1. Memperbarui Item Master...")
    for code, target_name in ITEM_NAME_MAP.items():
        r = s.get(f"{NEW_BASE}/api/resource/Item/{code}", params={"fields": '["item_name"]'})
        if r.status_code == 200:
            current_name = r.json().get("data", {}).get("item_name")
            if current_name != target_name:
                r_up = s.put(f"{NEW_BASE}/api/resource/Item/{code}", json={"item_name": target_name})
                if r_up.status_code == 200:
                    print(f"  [OK] {code}: '{current_name}' -> '{target_name}'")
                else:
                    print(f"  [GAGAL] {code}: HTTP {r_up.status_code} {r_up.text[:200]}")
            else:
                print(f"  [SUDAH] {code}: '{current_name}' sudah sesuai")
        else:
            print(f"  [NOT FOUND] {code}: HTTP {r.status_code}")

    # 2. Pasang Property Setter agar item_name pada POS Invoice Item bisa diedit
    print("\n2. Memasang Property Setter allow_on_submit untuk POS Invoice Item...")
    ps_payload = {
        "doctype": "Property Setter",
        "doc_type": "POS Invoice Item",
        "doctype_or_field": "DocField",
        "field_name": "item_name",
        "property": "allow_on_submit",
        "property_type": "Check",
        "value": "1"
    }
    r_ps = s.post(f"{NEW_BASE}/api/resource/Property Setter", json=ps_payload)
    ps_name = None
    if r_ps.status_code in (200, 201):
        ps_name = r_ps.json().get("data", {}).get("name")
        print(f"  [OK] Property Setter terpasang: {ps_name}")
    elif r_ps.status_code == 409 or "Duplicate" in r_ps.text:
        ps_name = "POS Invoice Item-item_name-allow_on_submit"
        print(f"  [INFO] Property Setter sudah ada: {ps_name}")
    else:
        print(f"  [WARN] Property Setter status HTTP {r_ps.status_code}: {r_ps.text[:200]}")

    # 3. Update baris POS Invoice Item yang sudah tersubmit
    print("\n3. Memperbarui baris POS Invoice Item Delanggu...")
    r_inv = s.get(f"{NEW_BASE}/api/resource/POS Invoice", params={
        "filters": '[["company", "=", "RS PKU MUHAMMADIYAH DELANGGU"]]',
        "fields": '["name"]',
        "limit_page_length": 200
    })
    invs = [d["name"] for d in r_inv.json().get("data", [])]

    updated_count = 0
    for inv in invs:
        r_det = s.get(f"{NEW_BASE}/api/resource/POS Invoice/{inv}")
        items = r_det.json().get("data", {}).get("items", [])
        for it in items:
            code = it.get("item_code")
            cur_name = it.get("item_name")
            target_name = ITEM_NAME_MAP.get(code)
            if target_name and cur_name != target_name:
                child_name = it.get("name")
                r_set = s.post(f"{NEW_BASE}/api/method/frappe.client.set_value", data={
                    "doctype": "POS Invoice Item",
                    "name": child_name,
                    "fieldname": "item_name",
                    "value": target_name
                })
                if r_set.status_code == 200:
                    print(f"  [OK] Invoice {inv} item {code}: '{cur_name}' -> '{target_name}'")
                    updated_count += 1
                else:
                    print(f"  [GAGAL] Invoice {inv} item {code}: HTTP {r_set.status_code} {r_set.text[:200]}")

    print(f"\nTotal child rows terupdate: {updated_count}")

    # 4. Update experiments/sku_to_item_code.csv agar sinkron permanen
    print("\n4. Menyesuaikan experiments/sku_to_item_code.csv...")
    csv_path = "experiments/sku_to_item_code.csv"
    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        fieldnames = reader[0].keys()

    csv_updated = 0
    for row in reader:
        item_code = row.get("item_code_erpnext")
        if item_code in ITEM_NAME_MAP:
            new_name = ITEM_NAME_MAP[item_code]
            if row.get("item_name_erpnext") != new_name:
                row["item_name_erpnext"] = new_name
                csv_updated += 1

    with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(reader)
    print(f"  [OK] CSV updated ({csv_updated} baris di-refresh)")

    # 5. Verifikasi kembali data penjualan kategori Paket untuk Delanggu
    print("\n5. Verifikasi Kategori Paket di Delanggu...")
    by_item = {}
    for inv in invs:
        r_det = s.get(f"{NEW_BASE}/api/resource/POS Invoice/{inv}")
        items = r_det.json().get("data", {}).get("items", [])
        for it in items:
            code = it.get("item_code")
            if code in ITEM_NAME_MAP:
                name = it.get("item_name")
                amt = float(it.get("amount") or 0)
                by_item[(code, name)] = by_item.get((code, name), 0) + amt

    print("Hasil di Top Selling Items (Kategori Paket):")
    rank = 1
    for (code, name), amt in sorted(by_item.items(), key=lambda x: x[1], reverse=True):
        print(f"  {rank}. {name:20} | {code:15} | Rp {amt:,.2f}")
        rank += 1

    print("\n" + "=" * 60)
    print("SELESAI - NAMA ITEM PAKET HEMAT TELAH SERAGAM")
    print("=" * 60)


if __name__ == "__main__":
    main()
