#!/usr/bin/env python3
"""pos_sync/cek_ketersediaan_gbj_jakarta.py — READ-ONLY.

Cek apakah `Gudang Barang Jadi - JURI` (BARU) punya stok 12 item kiriman
in-transit LAMA (MAT-STE-2026-09748/09752), dan bandingkan dengan saldo
`Gudang Jakarta - JURI`. Juga tampilkan rekap saldo di semua gudang JURI
untuk item-item itu, supaya kelihatan kalau stoknya ada di gudang lain.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env

COMPANY = "PT. JUARA ROTI INDONESIA"
GBJ = "Gudang Barang Jadi - JURI"
JKT = "Gudang Jakarta - JURI"

# (item, qty dalam UOM dokumen LAMA, uom dokumen LAMA)
LINES = [
    ("MAT-STE-2026-09748", [
        ("PJ260013", 1793.0, "Pack"),
        ("PJ260012", 1406.0, "Pack"),
        ("PJ260014", 1664.0, "Pack"),
        ("PJ260011", 360.0, "Pack"),
        ("PJ260010", 500.0, "Pack"),
        ("PJ260016", 1360.0, "Pcs"),
    ]),
    ("MAT-STE-2026-09752", [
        ("BB260043", 30.0, "Kg"),
        ("BB260044", 21.0, "Kg"),
        ("BB260045", 10.0, "Pcs"),
        ("PEL260006", 10.0, "Pcs"),
        ("PEL260068", 30.0, "Pcs"),
        ("PEL260077", 7500.0, "Pcs"),
    ]),
]


def main():
    mig = load_env("/tmp/eresto_mig.env")
    new = Client(mig["ERPNEXT_URL"], mig["ERPNEXT_API_KEY"], "BARU")

    conv, stock_uom = {}, {}
    codes = [c for _, lines in LINES for c, _, _ in lines]
    for code in codes:
        st, d = new.get("/api/resource/Item/" + code)
        if st != 200:
            raise SystemExit(f"item {code} HTTP {st}")
        it = d["data"]
        stock_uom[code] = it["stock_uom"]
        conv[code] = {u["uom"]: u["conversion_factor"] for u in (it.get("uoms") or [])}
        conv[code][it["stock_uom"]] = 1.0

    # saldo semua gudang JURI untuk item-item ini
    def chunked(lst, n=20):
        for i in range(0, len(lst), n):
            yield lst[i:i + n]

    bal = {}
    for ch in chunked(codes):
        st, d = new.get("/api/resource/Bin", {
            "filters": json.dumps([["item_code", "in", ch], ["actual_qty", "!=", 0]]),
            "fields": json.dumps(["item_code", "warehouse", "actual_qty",
                                  "stock_uom", "valuation_rate"]),
            "limit_page_length": 0})
        for r in d.get("data", []):
            bal.setdefault(r["item_code"], {})[r["warehouse"]] = r

    print(f"{'item':<11}{'dokumen':>9}{'qty_dok':>10}{'uom':>6}"
          f"{'-> Pcs/g':>11}{'GBJ':>11}{'JKT':>11}{'ColdSt':>11}{'other':>11}")
    for doc, lines in LINES:
        for code, q, uom in lines:
            cf = conv[code].get(uom)
            qty_base = q * cf if cf else None
            b = bal.get(code, {})
            gbj = b.get("Gudang Barang Jadi - JURI", {}).get("actual_qty", 0)
            jkt = b.get("Gudang Jakarta - JURI", {}).get("actual_qty", 0)
            cs = b.get("Cold Storage Produksi - JURI", {}).get("actual_qty", 0)
            others = sum(v["actual_qty"] for k, v in b.items()
                         if k not in ("Gudang Barang Jadi - JURI",
                                      "Gudang Jakarta - JURI",
                                      "Cold Storage Produksi - JURI"))
            print(f"{code:<11}{doc[-5:]:>9}{q:>10}{uom:>6}"
                  f"{(qty_base if qty_base is not None else '?'):>11}"
                  f"{gbj:>11}{jkt:>11}{cs:>11}{others:>11}")

    print("\n== Detail per gudang (hanya yang ber-saldo)")
    for code in codes:
        b = bal.get(code, {})
        if not b:
            print(f"   {code:<11} (tidak ada saldo di gudang mana pun)")
            continue
        print(f"   {code}:")
        for wh, r in sorted(b.items(), key=lambda x: -x[1]["actual_qty"]):
            print(f"       {r['actual_qty']:>14} {r.get('stock_uom',''):<7} {wh}"
                  f"  @{r.get('valuation_rate')}")

    print(f"\n== UOM master (BARU)")
    for code in codes:
        print(f"   {code:<11} stock_uom={stock_uom[code]:<8} "
              f"konversi={ {k: v for k, v in conv[code].items()} }")


if __name__ == "__main__":
    main()
