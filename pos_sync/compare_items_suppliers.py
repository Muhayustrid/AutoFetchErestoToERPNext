import os
"""Analisis perbandingan master Item dan Supplier antara ERPNext Lama dan Baru."""

import json
import re
import requests

OLD_BASE = "https://rotiropi.j.frappe.cloud"
OLD_KEY = os.environ.get("ERPNEXT_OLD_CLOUD_API_KEY", "")

PROD_BASE = "https://ropierpnext.frappe.cloud"
PROD_KEY = os.environ.get("ERPNEXT_API_KEY", "")

def get_all(base, key, doctype, fields):
    headers = {"Authorization": f"token {key}"}
    items = []
    limit = 500
    start = 0
    while True:
        r = requests.get(
            f"{base}/api/resource/{doctype}",
            headers=headers,
            params={
                "fields": json.dumps(fields),
                "limit_start": start,
                "limit_page_length": limit,
                "order_by": "name asc"
            },
            timeout=60
        )
        data = r.json().get("data", [])
        items.extend(data)
        if len(data) < limit:
            break
        start += limit
    return items

def norm_name(s):
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s

def compare():
    old_items = get_all(OLD_BASE, OLD_KEY, "Item", ["name", "item_name", "item_group", "stock_uom", "is_stock_item", "disabled"])
    prod_items = get_all(PROD_BASE, PROD_KEY, "Item", ["name", "item_name", "item_group", "stock_uom", "is_stock_item", "disabled"])

    old_suppliers = get_all(OLD_BASE, OLD_KEY, "Supplier", ["name", "supplier_name", "supplier_group", "supplier_type", "is_internal_supplier"])
    prod_suppliers = get_all(PROD_BASE, PROD_KEY, "Supplier", ["name", "supplier_name", "supplier_group", "supplier_type", "is_internal_supplier"])

    prod_by_code = {it["name"]: it for it in prod_items}
    prod_by_name = {norm_name(it["item_name"]): it for it in prod_items}

    missing_items = []
    matched_by_both = []
    same_name_diff_code = []
    same_code_diff_name = []

    for it in old_items:
        code = it["name"]
        name_norm = norm_name(it["item_name"])
        
        in_code = code in prod_by_code
        in_name = name_norm in prod_by_name
        
        if in_code and in_name:
            matched_by_both.append(it)
        elif in_name and not in_code:
            target_it = prod_by_name[name_norm]
            same_name_diff_code.append((code, target_it["name"], it["item_name"]))
        elif in_code and not in_name:
            target_it = prod_by_code[code]
            same_code_diff_name.append((code, it["item_name"], target_it["item_name"]))
        else:
            missing_items.append(it)

    print("================ HASIL ANALISIS ITEM ================")
    print(f"Total Item di Old ERPNext: {len(old_items)}")
    print(f"Total Item di New ERPNext: {len(prod_items)}")
    print(f"1. Cocok persis (Kode & Nama sama) : {len(matched_by_both)}")
    print(f"2. Nama sama, tapi Kode beda        : {len(same_name_diff_code)}")
    for old_c, new_c, name in same_name_diff_code:
        print(f"   - Old: {old_c:15s} -> New: {new_c:15s} | Nama: {name}")

    print(f"3. Kode sama, tapi Nama beda        : {len(same_code_diff_name)}")
    for code, old_n, new_n in same_code_diff_name:
        print(f"   - Kode: {code:15s} | Old Name: {old_n:30s} -> New Name: {new_n}")

    print(f"\n4. Benar-benar belum ada (Kode & Nama tidak ada di target): {len(missing_items)}")
    for it in missing_items:
        dis = " [DISABLED]" if it.get("disabled") else ""
        print(f"   - {it['name']:15s} | {it['item_name']:40s} | {it['item_group']:25s} | {it['stock_uom']}{dis}")

    # SUPPLIERS
    prod_sup_by_code = {s["name"].lower(): s for s in prod_suppliers}
    prod_sup_by_name = {norm_name(s.get("supplier_name")): s for s in prod_suppliers}

    missing_suppliers = []
    same_name_diff_code_sup = []
    matched_sup = []

    for s in old_suppliers:
        code = s["name"].lower()
        name_norm = norm_name(s.get("supplier_name"))

        in_code = code in prod_sup_by_code
        in_name = name_norm in prod_sup_by_name

        if in_code or in_name:
            if in_name and not in_code:
                same_name_diff_code_sup.append((s["name"], prod_sup_by_name[name_norm]["name"], s.get("supplier_name")))
            else:
                matched_sup.append(s)
        else:
            missing_suppliers.append(s)

    print("\n================ HASIL ANALISIS SUPPLIER ================")
    print(f"Total Supplier di Old ERPNext: {len(old_suppliers)}")
    print(f"Total Supplier di New ERPNext: {len(prod_suppliers)}")
    print(f"1. Sudah ada (Kode/Nama cocok)    : {len(matched_sup)}")
    print(f"2. Nama sama, Kode beda           : {len(same_name_diff_code_sup)}")
    for old_c, new_c, name in same_name_diff_code_sup:
        print(f"   - Old: {old_c:15s} -> New: {new_c:15s} | Nama: {name}")
    print(f"3. Benar-benar belum ada          : {len(missing_suppliers)}")
    for s in missing_suppliers:
        print(f"   - {s['name']:15s} | {s.get('supplier_name', ''):40s} | Group: {s.get('supplier_group', '')}")

if __name__ == "__main__":
    compare()
