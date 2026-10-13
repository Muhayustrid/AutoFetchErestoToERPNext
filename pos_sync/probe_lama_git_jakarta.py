#!/usr/bin/env python3
"""pos_sync/probe_lama_git_jakarta.py — AUDIT READ-ONLY site LAMA (ROPI).

Cek: (a) 2 SE Material Transfer in-transit MAT-STE-2026-09748/09752,
(b) seluruh dokumen yang menyentuh 'Goods In Transit - ROPI',
(c) saldo 'Gudang Jakarta - ROPI' sebagai pembanding target.
Tidak menulis apa pun.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env

COMPANY = "PT. JUARA ROTI INDONESIA"
GIT_LAMA = "Goods In Transit - ROPI"
JKT_LAMA = "Gudang Jakarta - ROPI"

SE_FIELDS = ["name", "stock_entry_type", "purpose", "posting_date",
             "posting_time", "docstatus", "from_warehouse", "to_warehouse",
             "remarks", "add_to_transit", "total_amount", "company",
             "per_transferred", "total_outgoing_value"]


def se_list(c, extra, fields=SE_FIELDS, order="posting_date asc, name asc"):
    st, d = c.get("/api/resource/Stock Entry", {
        "filters": json.dumps([["company", "=", COMPANY]] + extra),
        "fields": json.dumps(fields), "limit_page_length": 0, "order_by": order})
    if st != 200:
        raise SystemExit(f"gagal list SE: HTTP {st} {str(d)[:300]}")
    return d.get("data", [])


def bins(c, wh):
    st, d = c.get("/api/resource/Bin", {
        "filters": json.dumps([["warehouse", "=", wh], ["actual_qty", "!=", 0]]),
        "fields": json.dumps(["item_code", "actual_qty", "stock_uom",
                              "valuation_rate", "stock_value"]),
        "limit_page_length": 0})
    if st != 200:
        raise SystemExit(f"gagal Bin {wh}: HTTP {st} {str(d)[:200]}")
    return d.get("data", [])


def main():
    mig = load_env("/tmp/eresto_mig.env")
    old = Client("https://rotiropi.j.frappe.cloud",
                 mig["ERPNEXT_OLD_CLOUD_API_KEY"], "LAMA")
    print("# site LAMA: https://rotiropi.j.frappe.cloud")

    print("\n== A. SE in-transit MAT-STE-2026-09748 / 09752 (LAMA)")
    for old_name in ("MAT-STE-2026-09748", "MAT-STE-2026-09752"):
        st, d = old.get("/api/resource/Stock Entry/" + old_name)
        if st != 200:
            print(f"  {old_name}: HTTP {st} {str(d)[:200]}")
            continue
        r = d["data"]
        print(f"  {r['name']} | {r.get('stock_entry_type')} | "
              f"{r.get('posting_date')} {r.get('posting_time')} | ds {r.get('docstatus')}")
        print(f"     {r.get('from_warehouse')} -> {r.get('to_warehouse')}"
              f" | add_to_transit={r.get('add_to_transit')}"
              f" | total_outgoing={r.get('total_outgoing_value')}")
        print(f"     remarks: {(r.get('remarks') or '')[:160]}")
        print(f"     items: {len(r.get('items') or [])}")
        for it in (r.get("items") or [])[:100]:
            print(f"       {it.get('item_code'):<12} {it.get('qty'):>12} "
                  f"{it.get('uom','')} @{it.get('basic_rate')} "
                  f"| tgt={it.get('t_warehouse')}")

    print(f"\n== B. Semua SE menyentuh {GIT_LAMA} (LAMA, aktif)")
    rows = se_list(old, [["docstatus", "!=", 2]])
    touched = []
    for r in rows:
        if r.get("to_warehouse") == GIT_LAMA or r.get("from_warehouse") == GIT_LAMA:
            touched.append(r)
    for r in touched:
        print(f"   {r['name']} | {r.get('stock_entry_type')} | {r.get('posting_date')}"
              f" {r.get('posting_time')} | ds {r.get('docstatus')}"
              f" | add_to_transit={r.get('add_to_transit')}")
        print(f"      {r.get('from_warehouse')} -> {r.get('to_warehouse')}")
        print(f"      remarks: {(r.get('remarks') or '')[:140]}")
    print(f"   total: {len(touched)}")

    print(f"\n== C. Bin {GIT_LAMA} (LAMA)")
    b = bins(old, GIT_LAMA)
    for r in b:
        print(f"   {r['item_code']:<12} {r['actual_qty']:>14} {r.get('stock_uom','')}"
              f"  @{r.get('valuation_rate')} = {r.get('stock_value')}")
    print(f"   total item: {len(b)}")

    print(f"\n== D. Bin {JKT_LAMA} (LAMA) — pembanding")
    b2 = bins(old, JKT_LAMA)
    for r in b2:
        print(f"   {r['item_code']:<12} {r['actual_qty']:>14} {r.get('stock_uom','')}"
              f"  @{r.get('valuation_rate')} = {r.get('stock_value')}")
    print(f"   total item: {len(b2)}")

    print(f"\n== E. SLE {GIT_LAMA} (LAMA)")
    sle = old.list_all("Stock Ledger Entry",
                       ["item_code", "posting_date", "posting_time", "actual_qty",
                        "qty_after_transaction", "voucher_type", "voucher_no",
                        "is_cancelled"],
                       [["warehouse", "=", GIT_LAMA]],
                       order="posting_date asc, posting_time asc, creation asc")
    for r in sle:
        print(f"   {r['posting_date']} {r['posting_time']} {r['item_code']:<12}"
              f" {r['actual_qty']:>12} -> {r['qty_after_transaction']:>12}"
              f"  {r['voucher_type']} {r['voucher_no']}"
              f"{'  C' if r.get('is_cancelled') else ''}")
    print(f"   total SLE: {len(sle)}")


if __name__ == "__main__":
    main()
