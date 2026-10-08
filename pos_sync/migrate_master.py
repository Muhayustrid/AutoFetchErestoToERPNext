"""Tahap master: buat yang hilang di site BARU sebelum migrasi dokumen.

- Item: PEL260072 (Goodie Bag), PEL260097 (Balon Ropi Orange) — detail dari site lama.
- Supplier: Toko Santi + 7 akun Shopee (nama persis site lama).
- Customer: RSI FATIMAH BANYUWANGI (CUST260044 lama).
- BOM: BOM-PJ260016-001 (Krim Kopi, resep dari site lama).

Idempoten: cek ada dulu per kode/nama. Jebakan naming series BB26-.### :
buat dulu lalu rename (pola create_stok_items.py) bila kode tertimpa.

Usage: python3 migrate_master.py [--dry-run]
Env: ERPNEXT_URL, ERPNEXT_API_KEY (site BARU).
"""
import argparse
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ERP  # noqa: E402


def load_env(path="/tmp/eresto_mig.env"):
    d = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


NEW_ITEMS = [
    {"item_code": "PEL260072", "item_name": "Goodie Bag",
     "item_group": "Perlengkapan", "stock_uom": "Pcs"},
    {"item_code": "PEL260097", "item_name": "Balon Ropi Warna Orange(100pcs)",
     "item_group": "Perlengkapan", "stock_uom": "Pcs"},
]

NEW_SUPPLIERS = [
    "Toko Santi", "Shopee - Duster Joe", "Shopee - Lionelplastik",
    "Shopee - Tokorak.ID", "Shopee - Smartcom LTD", "Shopee - Neo Geo Shop",
    "Shopee - Mikadoshop", "Shopee - Ledaohome", "Shopee - 123 Packaging",
]

NEW_CUSTOMERS = ["RSI FATIMAH BANYUWANGI"]

# Resep BOM-PJ260016-001 dari site lama (qty per 25 Pcs Krim Kopi).
KRIM_KOPI_ITEMS = [
    ("BB260029", 5000.0, "g"), ("BB260011", 3875.0, "g"),
    ("BB260022", 2500.0, "g"), ("BB260015", 3500.0, "g"),
    ("BB260016", 600.0, "g"), ("BB260019", 26.0, "Pcs"),
    ("BB260002", 52.0, "Pcs"),
]


def ensure_item(erp, spec, dry):
    code = spec["item_code"]
    st, d = erp.get("/api/resource/Item/" + urllib.parse.quote(code))
    if st == 200:
        print(f"  item {code}: sudah ada")
        return d["data"]["name"]
    if dry:
        print(f"  item {code}: DRY-RUN buat")
        return code
    st, d = erp.post("Item", {"doctype": "Item", **spec,
                              "is_stock_item": 1, "include_item_in_manufacturing": 1})
    if st != 200:
        print(f"  !! item {code} gagal: {json.dumps(d)[:300]}")
        return None
    name = d["data"]["name"]
    if name != code:  # naming series menimpa kode -> rename (form-encoded)
        st2, d2 = erp.rename("Item", name, code)
        if st2 != 200 or (d2.get("message") or "") != code:
            print(f"  !! rename {name}->{code} gagal: {json.dumps(d2)[:200]}")
            return None
        print(f"  item {code}: dibuat + rename dari {name}")
        return code
    print(f"  item {code}: dibuat")
    return code


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    env = load_env()
    erp = ERP(env["ERPNEXT_URL"].rstrip("/"), env["ERPNEXT_API_KEY"])

    print("== item ==")
    for spec in NEW_ITEMS:
        ensure_item(erp, spec, args.dry_run)

    print("== supplier ==")
    for s in NEW_SUPPLIERS:
        st, d = erp.get("/api/resource/Supplier/" + urllib.parse.quote(s))
        if st == 200:
            print(f"  supplier {s}: sudah ada")
            continue
        if args.dry_run:
            print(f"  supplier {s}: DRY-RUN buat")
            continue
        st, d = erp.post("Supplier", {"doctype": "Supplier",
                                      "supplier_name": s,
                                      "supplier_group": "All Supplier Groups",
                                      "supplier_type": "Company"})
        print(f"  supplier {s}: {'dibuat' if st == 200 else 'GAGAL ' + json.dumps(d)[:200]}")

    print("== customer ==")
    for c in NEW_CUSTOMERS:
        st, d = erp.get("/api/resource/Customer", {
            "filters": json.dumps([["customer_name", "=", c]]),
            "fields": '["name"]', "limit_page_length": 2})
        rows = d.get("data", []) if st == 200 else []
        if rows:
            print(f"  customer {c}: sudah ada ({rows[0]['name']})")
            continue
        if args.dry_run:
            print(f"  customer {c}: DRY-RUN buat")
            continue
        st, d = erp.post("Customer", {"doctype": "Customer",
                                      "customer_name": c,
                                      "customer_group": "Outlet Reguler",
                                      "territory": "All Territories",
                                      "customer_type": "Company"})
        print(f"  customer {c}: {'dibuat' if st == 200 else 'GAGAL ' + json.dumps(d)[:200]}")

    print("== BOM Krim Kopi ==")
    st, d = erp.get("/api/resource/BOM/BOM-PJ260016-001")
    if st == 200:
        print("  BOM-PJ260016-001: sudah ada")
    elif args.dry_run:
        print("  BOM-PJ260016-001: DRY-RUN buat")
    else:
        st, d = erp.post("BOM", {
            "doctype": "BOM", "item": "PJ260016", "quantity": 25,
            "company": "PT. JUARA ROTI INDONESIA", "is_active": 1,
            "is_default": 1,
            "items": [{"item_code": c, "qty": q, "uom": u} for c, q, u in KRIM_KOPI_ITEMS],
            "remarks": "ERESTO BOM-PJ260016-001 (resep site lama)",
        })
        print(f"  BOM-PJ260016-001: {'dibuat' if st == 200 else 'GAGAL ' + json.dumps(d)[:500]}")
    print("MASTER OK")


if __name__ == "__main__":
    main()
