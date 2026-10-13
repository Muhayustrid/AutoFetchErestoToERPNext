#!/usr/bin/env python3
"""pos_sync/audit_goodintransit_juri.py — AUDIT READ-ONLY stok Goods In Transit - JURI.

Latar: user melaporkan stok di `Goods In Transit - JURI` (site BARU
ropierpnext.frappe.cloud) berasal dari 2 Stock Entry Material Transfer site
LAMA (`MAT-STE-2026-09748` barang jadi/dough + `MAT-STE-2026-09752` bahan
baku & kemasan) yang BELUM di-endtransit, dengan target gudang Jakarta.

Script ini TIDAK menulis apa pun (hanya GET). Output: cetak + JSON dump
supaya bisa dipakai menyusun rencana perbaikan.

Pakai: .venv/bin/python pos_sync/audit_goodintransit_juri.py [--json out.json]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env

COMPANY = "PT. JUARA ROTI INDONESIA"
GIT = "Goods In Transit - JURI"
DEST = "Gudang Jakarta - JURI"

SE_FIELDS = ["name", "stock_entry_type", "purpose", "posting_date",
             "posting_time", "docstatus", "from_warehouse", "to_warehouse",
             "remarks", "add_to_transit", "total_amount", "company"]


def se_list(c, extra_filters, fields=SE_FIELDS, order="posting_date asc, name asc"):
    st, d = c.get("/api/resource/Stock Entry", {
        "filters": json.dumps([["company", "=", COMPANY]] + extra_filters),
        "fields": json.dumps(fields),
        "limit_page_length": 0,
        "order_by": order,
    })
    if st != 200:
        raise SystemExit(f"gagal list SE: HTTP {st} {str(d)[:300]}")
    return d.get("data", [])


def se_detail(c, name):
    st, d = c.get("/api/resource/Stock Entry/" + name)
    if st != 200:
        raise SystemExit(f"gagal get {name}: HTTP {st}")
    return d["data"]


def bin_rows(c, warehouse, item_code=None):
    f = [["warehouse", "=", warehouse], ["actual_qty", "!=", 0]]
    if item_code:
        f.append(["item_code", "=", item_code])
    st, d = c.get("/api/resource/Bin", {
        "filters": json.dumps(f),
        "fields": json.dumps(["item_code", "warehouse", "actual_qty",
                              "ordered_qty", "valuation_rate", "stock_value",
                              "stock_uom"]),
        "limit_page_length": 0,
    })
    if st != 200:
        raise SystemExit(f"gagal list Bin {warehouse}: HTTP {st} {str(d)[:200]}")
    return d.get("data", [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    env = load_env("/tmp/eresto_mig.env")
    c = Client(env["ERPNEXT_URL"], env["ERPNEXT_API_KEY"], "BARU")
    print(f"# site BARU: {c.base}")

    out = {}

    # 1. Jejak dokumen sumber di site BARU (cari di remarks & name)
    print("\n== 1. Jejak MAT-STE-2026-09748 / 09752 di BARU")
    traces = []
    for old in ("MAT-STE-2026-09748", "MAT-STE-2026-09752"):
        rows = se_list(c, [["remarks", "like", f"%{old}%"]])
        if not rows:
            rows = c.list_all("Stock Entry",
                              ["name", "posting_date", "posting_time",
                               "docstatus", "from_warehouse", "to_warehouse",
                               "remarks", "stock_entry_type"],
                              [["name", "=", old]])
        print(f"  {old}: {len(rows)} dokumen")
        for r in rows:
            print("   ", r["name"], "|", r.get("stock_entry_type"), "|",
                  r.get("posting_date"), r.get("posting_time"), "| ds",
                  r.get("docstatus"), "|", r.get("from_warehouse"), "->",
                  r.get("to_warehouse"))
            print("      remarks:", (r.get("remarks") or "")[:150])
        traces.append({"old": old, "docs": rows})
    out["traces"] = traces

    # 2. Semua SE aktif yang menaruh barang ke Goods In Transit - JURI
    print(f"\n== 2. SE aktif (docstatus != 2) dengan to_warehouse = {GIT}")
    into_git = se_list(c, [["docstatus", "!=", 2], ["to_warehouse", "=", GIT]])
    for r in into_git:
        print("   ", r["name"], "|", r.get("stock_entry_type"), "|",
              r.get("posting_date"), r.get("posting_time"), "| ds",
              r.get("docstatus"), "| add_to_transit", r.get("add_to_transit"),
              "|", r.get("from_warehouse"))
        print("      remarks:", (r.get("remarks") or "")[:150])
    out["into_git"] = into_git

    # 2b. baris yang gudangnya == GIT (from atau to) walau header beda
    print(f"\n== 2b. Temuan lewat Stock Entry Detail (warehouse = {GIT})")
    st, d = c.get("/api/resource/Stock Entry Detail", {
        "filters": json.dumps([["warehouse", "=", GIT],
                               ["docstatus", "!=", 2]]),
        "fields": json.dumps(["name", "parent", "item_code", "qty", "s_warehouse",
                              "t_warehouse", "basic_rate", "amount",
                              "docstatus"]),
        "limit_page_length": 0,
    })
    detail_rows = d.get("data", []) if st == 200 else []
    parents = {}
    for r in detail_rows:
        parents.setdefault(r["parent"], []).append(r)
    print(f"   {len(detail_rows)} baris di {len(parents)} dokumen")
    for p in sorted(parents):
        print("   ", p, f"({len(parents[p])} baris)")
    out["detail_git"] = detail_rows

    # 3. Combo transfer yang mendarat di GIT
    print("\n== 3. Kombinasi asal -> GIT")
    combos = {}
    for r in into_git:
        combos.setdefault((r.get("from_warehouse"), r.get("stock_entry_type")),
                          []).append(r["name"])
    for (src, typ), names in combos.items():
        print(f"   {src} -> {GIT} | {typ} | {len(names)} dok")
    out["combos"] = {f"{k[0]}|{k[1]}": v for k, v in combos.items()}

    # 4. Bin di GIT + bin di tujuan (Gudang Jakarta - JURI)
    print(f"\n== 4. Bin {GIT}")
    bins_git = bin_rows(c, GIT)
    for r in bins_git:
        print(f"   {r['item_code']:<12} {r['actual_qty']:>14} {r.get('stock_uom','')}"
              f"  @{r.get('valuation_rate')}  = {r.get('stock_value')}")
    print(f"   total item: {len(bins_git)}")
    out["bins_git"] = bins_git

    print(f"\n== 4b. Bin {DEST} (target)")
    bins_dest = bin_rows(c, DEST)
    for r in bins_dest:
        print(f"   {r['item_code']:<12} {r['actual_qty']:>14} {r.get('stock_uom','')}"
              f"  @{r.get('valuation_rate')}  = {r.get('stock_value')}")
    print(f"   total item: {len(bins_dest)}")
    out["bins_dest"] = bins_dest

    # 5. SLE di GIT (siapa saja yang menyentuh)
    print(f"\n== 5. Stock Ledger Entry warehouse {GIT} (20 terakhir)")
    sle = c.list_all("Stock Ledger Entry",
                     ["name", "item_code", "posting_date", "posting_time",
                      "actual_qty", "qty_after_transaction", "voucher_type",
                      "voucher_no", "is_cancelled", "warehouse"],
                     [["warehouse", "=", GIT]],
                     order="posting_date asc, posting_time asc, creation asc")
    for r in sle:
        print(f"   {r['posting_date']} {r['posting_time']} {r['item_code']:<12}"
              f" {r['actual_qty']:>12} -> {r['qty_after_transaction']:>12}"
              f"  {r['voucher_type']} {r['voucher_no']}"
              f"{'  CANCELLED' if r.get('is_cancelled') else ''}")
    out["sle_git"] = sle

    if args.json:
        with open(args.json, "w") as f:
            json.dump(out, f, indent=1, default=str)
        print(f"\n# dumped -> {args.json}")


if __name__ == "__main__":
    main()
