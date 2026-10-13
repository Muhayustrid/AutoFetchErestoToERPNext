#!/usr/bin/env python3
"""pos_sync/audit_gtj_landing.py — READ-ONLY.

Menjawab: apakah isi MAT-STE-2026-09748 / 09752 (site LAMA, in-transit ke
Gudang Jakarta) SUDAH mendarat di site BARU? Kalau belum, berapa selisihnya?

Cara: bandingkan saldo `Gudang Jakarta - JURI` (BARU) terhadap snapshot
`Gudang Jakarta - ROPI` (LAMA, 30 Sep) + pergerakan sesudahnya, lalu cari
jejak voucher yang menyentuh item-item kandidat di Jakarta (BARU).

Tidak menulis apa pun.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env

COMPANY = "PT. JUARA ROTI INDONESIA"
GIT_NEW = "Goods In Transit - JURI"
JKT_NEW = "Gudang Jakarta - JURI"
JKT_OLD = "Gudang Jakarta - ROPI"

# 12 baris dari 2 SE in-transit LAMA (qty dalam UOM asli dokumen)
ITEMS_9748 = [("PJ260013", 21516), ("PJ260012", 16872), ("PJ260014", 19968),
              ("PJ260011", 1080), ("PJ260010", 3000), ("PJ260016", 1360)]
ITEMS_9752 = [("BB260043", 30000), ("BB260044", 21000), ("BB260045", 2500),
              ("PEL260006", 10), ("PEL260068", 30), ("PEL260077", 7500)]

ALL_ITEMS = [i for i, _ in ITEMS_9748 + ITEMS_9752]


def bins(c, wh, items=None):
    f = [["warehouse", "=", wh], ["actual_qty", "!=", 0]]
    if items:
        f.append(["item_code", "in", items])
    st, d = c.get("/api/resource/Bin", {
        "filters": json.dumps(f),
        "fields": json.dumps(["item_code", "actual_qty", "stock_uom",
                              "valuation_rate", "stock_value"]),
        "limit_page_length": 0})
    if st != 200:
        raise SystemExit(f"gagal Bin {wh}: HTTP {st} {str(d)[:200]}")
    return {r["item_code"]: r for r in d.get("data", [])}


def main():
    mig = load_env("/tmp/eresto_mig.env")
    new = Client(mig["ERPNEXT_URL"], mig["ERPNEXT_API_KEY"], "BARU")
    old = Client("https://rotiropi.j.frappe.cloud",
                 mig["ERPNEXT_OLD_CLOUD_API_KEY"], "LAMA")

    # chunk item_code supaya query aman (limit request-line)
    def chunked(lst, n=20):
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    bins_jkt_new, bins_jkt_old, bins_git_new = {}, {}, {}
    for ch in chunked(ALL_ITEMS):
        bins_jkt_new.update(bins(new, JKT_NEW, ch))
        bins_jkt_old.update(bins(old, JKT_OLD, ch))
        bins_git_new.update(bins(new, GIT_NEW, ch))

    print("== Saldo per item (BARU Jakarta | LAMA Jakarta | BARU GIT) vs kiriman in-transit")
    print(f"{'item':<12}{'kiriman':>12}{'JKT_BARU':>12}{'JKT_LAMA':>12}{'GIT_BARU':>10}"
          f"{'uom':>8}{'rate_BARU':>14}")
    for label, rows in (("09748", ITEMS_9748), ("09752", ITEMS_9752)):
        print(f"-- dari MAT-STE-2026-{label}")
        for code, q in rows:
            b = bins_jkt_new.get(code, {})
            o = bins_jkt_old.get(code, {})
            g = bins_git_new.get(code, {})
            print(f"{code:<12}{q:>12}{b.get('actual_qty', 0):>12}"
                  f"{o.get('actual_qty', 0):>12}{g.get('actual_qty', 0):>10}"
                  f"{str(b.get('stock_uom', '')):>8}"
                  f"{str(b.get('valuation_rate', '')):>14}")

    # Jejak siapa yang mengisi Jakarta BARU untuk item kandidat
    print("\n== SLE di Gudang Jakarta - JURI (BARU) untuk item kandidat")
    for ch in chunked(ALL_ITEMS):
        sle = new.list_all(
            "Stock Ledger Entry",
            ["item_code", "posting_date", "posting_time", "actual_qty",
             "qty_after_transaction", "voucher_type", "voucher_no",
             "incoming_rate", "is_cancelled"],
            [["warehouse", "=", JKT_NEW], ["item_code", "in", ch]],
            order="item_code asc, posting_date asc, posting_time asc, creation asc")
        for r in sle:
            flag = " C" if r.get("is_cancelled") else ""
            print(f"   {r['item_code']:<12}{r['posting_date']} {str(r['posting_time'])[:8]}"
                  f"{r['actual_qty']:>12} -> {r['qty_after_transaction']:>12}"
                  f"  {r['voucher_type']} {r['voucher_no']}{flag}")

    # UOM di site BARU untuk dough
    print("\n== UOM & konversi item dough di BARU")
    for code in ("PJ260010", "PJ260011", "PJ260012", "PJ260013", "PJ260014",
                 "PJ260016", "BB260043", "BB260044", "BB260045"):
        st, d = new.get("/api/resource/Item/" + code)
        if st != 200:
            print(f"   {code}: HTTP {st}")
            continue
        it = d["data"]
        print(f"   {code:<12} stock_uom={it.get('stock_uom'):<8}"
              f" is_stock={it.get('is_stock_item')}"
              f" has_batch={it.get('has_batch_no')}"
              f" has_serial={it.get('has_serial_no')}")
        for u in it.get("uoms") or []:
            if u.get("uom") != it.get("stock_uom"):
                print(f"        uom alt: {u.get('uom')} cf={u.get('conversion_factor')}")

    # Kebijakan transit: cek Stock Settings & apakah ada MTF end-transit di BARU
    print("\n== Stock Settings BARU")
    st, d = new.get("/api/resource/Stock Settings")
    if st == 200:
        s = d["data"]
        print("   allow_negative_stock:", s.get("allow_negative_stock"))
        print("   enable_perpetual_inventory? (company level)")


if __name__ == "__main__":
    main()
