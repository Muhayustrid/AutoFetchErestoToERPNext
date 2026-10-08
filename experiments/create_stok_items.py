"""Buat 6 item baru di ERPNext lokal: bubuk outlet tanpa padanan.

Keputusan user 2026-10-04: Bubuk Hepi Drink (Moccacino/Cappucino/Kopi
Karamel/Chocolate), Kopi Hitam @6gr (20 Sachet), dan Susu Bubuk
Campuran Minuman (1 kg) DIBUAT BARU di master.
Pola master: sachet -> UOM Sachet (spt BB260034/38), curah -> g
(spt BB260041). Idempoten: skip bila item_code sudah ada.
Env: ERPNEXT_URL, ERPNEXT_API_KEY.
"""
import os
import sys
import urllib.parse

import requests

ENV_PATH = "/tmp/eresto_mig.env"


def load_env(path):
    d = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


ENV = load_env(ENV_PATH)
BASE = ENV["ERPNEXT_URL"].rstrip("/")
S = requests.Session()
S.headers.update({"Authorization": "token " + ENV["ERPNEXT_API_KEY"]})

NEW_ITEMS = [
    {"item_code": "BB260057", "item_name": "Bubuk Hepi Drink Moccacino (30 g)",
     "stock_uom": "Sachet", "sku_eresto": "BB0308"},
    {"item_code": "BB260058", "item_name": "Bubuk Hepi Drink Cappucino (30 g)",
     "stock_uom": "Sachet", "sku_eresto": "BB0309"},
    {"item_code": "BB260059", "item_name": "Bubuk Hepi Drink Kopi Karamel (30 g)",
     "stock_uom": "Sachet", "sku_eresto": "BB0310"},
    {"item_code": "BB260060", "item_name": "Bubuk Hepi Drink Chocolate",
     "stock_uom": "Sachet", "sku_eresto": "BB0311"},
    {"item_code": "BB260061", "item_name": "Kopi Hitam @6gr (Isi 20 Sachet)",
     "stock_uom": "Pcs", "sku_eresto": "BB0322"},
    {"item_code": "BB260062", "item_name": "Susu Bubuk untuk Campuran Minuman (1 kg)",
     "stock_uom": "g", "sku_eresto": "BB0145"},
]
ITEM_GROUP = "Bahan Baku"


def main():
    created, skipped = [], []
    for spec in NEW_ITEMS:
        code = spec["item_code"]
        st = S.get(f"{BASE}/api/resource/Item/{urllib.parse.quote(code)}",
                   timeout=60).status_code
        if st == 200:
            skipped.append(code)
            print(f"  skip {code} (sudah ada)")
            continue
        payload = {
            "doctype": "Item",
            "item_code": code,
            "item_name": spec["item_name"],
            "item_group": ITEM_GROUP,
            "stock_uom": spec["stock_uom"],
            "is_stock_item": 1,
        }
        r = S.post(f"{BASE}/api/resource/Item", json=payload, timeout=90)
        if r.status_code != 200:
            print(f"  GAGAL {code}: HTTP {r.status_code} {r.text[:500]}")
            sys.exit(1)
        assigned = r.json().get("data", {}).get("name")
        if assigned and assigned != code:
            # Item punya naming series BB26-.### yang menimpa item_code;
            # rename agar kode tetap konsisten dgn konvensi master.
            rr = S.post(f"{BASE}/api/method/frappe.client.rename_doc",
                        data={"doctype": "Item", "old_name": assigned,
                              "new_name": code, "merge": 0}, timeout=90)
            if rr.status_code != 200 or rr.json().get("message") != code:
                print(f"  GAGAL rename {assigned} -> {code}: "
                      f"HTTP {rr.status_code} {rr.text[:300]}")
                sys.exit(1)
            print(f"  #{assigned} di-rename -> {code}")
        created.append((code, spec["item_name"], spec["stock_uom"]))
        print(f"  buat {code}: {spec['item_name']} ({spec['stock_uom']})")
    print(f"\nDibuat: {len(created)} | Skip: {len(skipped)}")
    for c in created:
        print("  ", c)


if __name__ == "__main__":
    main()
