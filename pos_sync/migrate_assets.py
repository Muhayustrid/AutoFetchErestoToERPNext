import os
"""Migrasi master Asset dari ERPNext Lama ke ERPNext Baru Cloud."""

import json
import requests

OLD_BASE = "https://rotiropi.j.frappe.cloud"
OLD_KEY = os.environ.get("ERPNEXT_OLD_CLOUD_API_KEY", "")

PROD_BASE = "https://ropierpnext.frappe.cloud"
PROD_KEY = os.environ.get("ERPNEXT_API_KEY", "")

DROP_KEYS = {"name", "owner", "creation", "modified", "modified_by", "docstatus", "idx", "status"}


def run_migration():
    s_old = requests.Session()
    s_old.headers.update({"Authorization": f"token {OLD_KEY}"})

    s_prod = requests.Session()
    s_prod.headers.update({"Authorization": f"token {PROD_KEY}"})

    r = s_old.get(f"{OLD_BASE}/api/resource/Asset", params={"limit_page_length": 100, "order_by": "name asc"})
    assert r.status_code == 200, f"Gagal get Asset list: {r.text}"
    asset_list = r.json().get("data", [])

    print(f"Total Asset dari Old ERPNext: {len(asset_list)}")
    migrated, skipped = [], []

    for a in asset_list:
        target_name = a["name"]
        st = s_prod.get(f"{PROD_BASE}/api/resource/Asset/{target_name}").status_code
        if st == 200:
            skipped.append(target_name)
            continue

        doc = s_old.get(f"{OLD_BASE}/api/resource/Asset/{target_name}").json().get("data", {})
        payload = {k: v for k, v in doc.items() if k not in DROP_KEYS and not k.startswith("_")}

        r_post = s_prod.post(f"{PROD_BASE}/api/resource/Asset", json=payload)
        assert r_post.status_code == 200, f"Gagal create {target_name}: {r_post.text}"

        assigned = r_post.json().get("data", {}).get("name")
        if assigned != target_name:
            r_ren = s_prod.post(
                f"{PROD_BASE}/api/method/frappe.client.rename_doc",
                data={"doctype": "Asset", "old_name": assigned, "new_name": target_name, "merge": 0},
            )
            assert r_ren.status_code == 200, f"Gagal rename {assigned} -> {target_name}: {r_ren.text}"

        migrated.append(target_name)
        print(f"  [+] Migrated Asset: {target_name} ({doc.get('asset_name')})")

    print(f"\nSelesai: {len(migrated)} dimigrasikan, {len(skipped)} sudah ada.")

    # Verifikasi akhir
    r_check = s_prod.get(f"{PROD_BASE}/api/resource/Asset", params={"limit_page_length": 100})
    prod_assets = r_check.json().get("data", [])
    print(f"Total Asset aktif di Cloud Baru: {len(prod_assets)} / {len(asset_list)}")
    assert len(prod_assets) == len(asset_list), f"Asset count mismatch: {len(prod_assets)} != {len(asset_list)}"
    print("Verifikasi 42/42 LOLOS!")


if __name__ == "__main__":
    run_migration()
