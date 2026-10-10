#!/usr/bin/env python3
"""pos_sync/restore_sr7_zeroouts.py — pemulih zero-out SR7 yang tak bisa
di-recreate tanpa allow_negative_stock (validasi anchor v16).

Latar: RECO-JURI-261009030 (zero-out GBJ BB260019 -108 & BB260046 -2750
per 2026-10-09 12:58:28) dibatalkan saat konsolidasi SR7; recreate-nya
ditolak `NegativeStockError` (anchor: saldo sebelumnya negatif). Karena
flag minus DILARANG dinyalakan tanpa izin user, efeknya dipulihkan lewat
**Stock Entry Material Receipt** dengan qty & rate persis (bin → 0 lagi,
GL sama-sama ke `5110.020 - Penyesuaian Stock - JURI`).

DEFAULT DRY-RUN. Jalankan: python pos_sync/restore_sr7_zeroouts.py --execute
Idempotent via marker remarks "KONSOLIDASI ADJ 5110 SUBST 030".
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env  # noqa: E402

JURI = "PT. JUARA ROTI INDONESIA"
ACC_ADJ = "5110.020 - Penyesuaian Stock - JURI"
CC = "Main - JURI"
MARK = "KONSOLIDASI ADJ 5110 SUBST 030"
POST_DATE = "2026-10-09"
POST_TIME = "12:58:28"

# (item, warehouse, qty, basic_rate) — rate dari GL asli 030:
#   BB260019: 42.718,32 / 108   = 395,54
#   BB260046: 103.910,49 / 2750 = 37,7856327...
ROWS = [
    ("BB260019", "Gudang Barang Jadi - JURI", 108.0, 395.54),
    ("BB260046", "Gudang Barang Jadi - JURI", 2750.0, 37.785631567),
]


def neg_bins(c):
    st, d = c.get("/api/method/frappe.client.get_count", {
        "doctype": "Bin",
        "filters": '{"actual_qty": ["<", 0]}'})
    return d.get("message")


def bins_of(c):
    out = {}
    for it, wh, _q, _r in ROWS:
        st, d = c.get("/api/resource/Bin", {
            "filters": '[["item_code","=","%s"],["warehouse","=","%s"]]' % (it, wh),
            "fields": '["actual_qty","valuation_rate","stock_value"]'})
        out[(it, wh)] = (d.get("data") or [None])[0] if st == 200 else None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    prod = load_env("/tmp/eresto_prod.env")
    c = Client(prod["ERPNEXT_URL"], prod["ERPNEXT_API_KEY"], "BARU")

    print("== kondisi awal ==")
    print("  Bin negatif se-sistem:", neg_bins(c))
    for k, v in bins_of(c).items():
        print("  %s @ %s: %s" % (k[0], k[1], v))

    st, d = c.get("/api/resource/Stock Entry", {
        "filters": '[["company","=","%s"],["remarks","=","%s"]]' % (JURI, MARK),
        "fields": '["name","docstatus"]', "limit_page_length": 1})
    existing = (d.get("data") or [None])[0] if st == 200 else None
    if existing:
        print("[SKIP] sudah ada: %s (docstatus %s)"
              % (existing["name"], existing["docstatus"]))
        return

    if not args.execute:
        print("\n[DRY-RUN] jalankan --execute utk memulihkan (SE Material "
              "Receipt @%s %s, expense %s)." % (POST_DATE, POST_TIME, ACC_ADJ))
        return

    items = []
    for it, wh, q, r in ROWS:
        items.append({
            "item_code": it, "t_warehouse": wh, "qty": q,
            "basic_rate": r, "expense_account": ACC_ADJ, "cost_center": CC})
    payload = {
        "doctype": "Stock Entry", "purpose": "Material Receipt",
        "stock_entry_type": "Material Receipt",
        "company": JURI, "set_posting_time": 1,
        "posting_date": POST_DATE, "posting_time": POST_TIME,
        "remarks": MARK, "items": items, "docstatus": 1}
    stn, dn = c.post("Stock Entry", payload)
    print("CREATE:", stn)
    if stn not in (200, 201):
        print(str(dn)[:500])
        raise SystemExit("GAGAL restore")
    name = dn["data"]["name"]
    print("name:", name)
    time.sleep(4)
    print("== kondisi akhir ==")
    print("  Bin negatif se-sistem:", neg_bins(c))
    for k, v in bins_of(c).items():
        print("  %s @ %s: %s" % (k[0], k[1], v))
    print("OK")


if __name__ == "__main__":
    main()
