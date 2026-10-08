import os
"""Migrasi item yang benar-benar belum ada dari ERPNext Lama ke ERPNext Baru Cloud.

Menjamin:
- Tidak membuat duplikat untuk item yang sudah ada dengan nama/arti sama meskipun beda kode.
- Menggunakan rename_doc untuk mengatasi penimpaan naming series otomatis di ERPNext target.
- Idempoten: cek keberadaan kode & nama sebelum create.
"""

import requests
import json
import urllib.parse

PROD_BASE = "https://ropierpnext.frappe.cloud"
PROD_KEY = os.environ.get("ERPNEXT_API_KEY", "")

OLD_BASE = "https://rotiropi.j.frappe.cloud"
OLD_KEY = os.environ.get("ERPNEXT_OLD_CLOUD_API_KEY", "")

ITEMS_TO_MIGRATE = [
    {
        "item_code": "PEL260007",
        "item_name": "Balon Ropi Warna Kuning (100pcs)",
        "item_group": "Perlengkapan",
        "stock_uom": "Pcs",
        "is_stock_item": 1,
    },
    {
        "item_code": "PEL260096",
        "item_name": "Balon Ropi Warna Putih(100pcs)",
        "item_group": "Perlengkapan",
        "stock_uom": "Pcs",
        "is_stock_item": 1,
    },
    {
        "item_code": "PEL260098",
        "item_name": "Balon Ropi Warna Pink (100pcs)",
        "item_group": "Perlengkapan",
        "stock_uom": "Pcs",
        "is_stock_item": 1,
    },
    {
        "item_code": "BHP260014",
        "item_name": "Hair Nett",
        "item_group": "Barang Habis Pakai",
        "stock_uom": "Pack",
        "is_stock_item": 1,
    },
    {
        "item_code": "ATK260048",
        "item_name": "Stiker Label 103",
        "item_group": "ATK",
        "stock_uom": "Pcs",
        "is_stock_item": 1,
    },
]

def migrate_items():
    s = requests.Session()
    s.headers.update({"Authorization": f"token {PROD_KEY}"})

    print("=== MIGRASI MASTER ITEM KE ERPNEXT BARU CLOUD ===")
    results = []
    for item in ITEMS_TO_MIGRATE:
        code = item["item_code"]
        name = item["item_name"]

        # 1. Cek by code
        r = s.get(f"{PROD_BASE}/api/resource/Item/{urllib.parse.quote(code)}")
        if r.status_code == 200:
            print(f"[SKIP] Item code {code} sudah ada di target.")
            results.append({"code": code, "status": "ALREADY_EXISTS"})
            continue

        # 2. Cek by name
        r_name = s.get(f"{PROD_BASE}/api/resource/Item", params={
            "filters": json.dumps([["item_name", "=", name]]),
            "fields": json.dumps(["name", "item_name"])
        })
        if r_name.status_code == 200 and r_name.json().get("data"):
            existing = r_name.json()["data"][0]
            print(f"[SKIP] Item dengan nama '{name}' sudah ada dengan kode {existing['name']}.")
            results.append({"code": code, "status": f"NAME_EXISTS ({existing['name']})"})
            continue

        # 3. Create
        payload = {
            "doctype": "Item",
            "item_code": code,
            "item_name": name,
            "item_group": item["item_group"],
            "stock_uom": item["stock_uom"],
            "is_stock_item": item.get("is_stock_item", 1),
        }
        r_post = s.post(f"{PROD_BASE}/api/resource/Item", json=payload)
        if r_post.status_code != 200:
            print(f"[FAIL] Gagal create {code}: {r_post.text}")
            results.append({"code": code, "status": "FAILED", "err": r_post.text})
            continue

        temp_name = r_post.json().get("data", {}).get("name")
        final_name = temp_name
        if temp_name != code:
            r_ren = s.post(f"{PROD_BASE}/api/method/frappe.client.rename_doc", data={
                "doctype": "Item",
                "old_name": temp_name,
                "new_name": code,
                "merge": 0
            })
            if r_ren.status_code == 200:
                final_name = code
                print(f"[OK] Created & renamed: {temp_name} -> {final_name}")
            else:
                print(f"[WARN] Rename {temp_name} -> {code} gagal: {r_ren.text}")
        else:
            print(f"[OK] Created: {final_name}")

        results.append({"code": final_name, "name": name, "status": "CREATED"})

    return results

if __name__ == "__main__":
    res = migrate_items()
    print("\nHasil Migrasi:")
    for r in res:
        print(" ", r)
