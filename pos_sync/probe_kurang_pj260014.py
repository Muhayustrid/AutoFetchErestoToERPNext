#!/usr/bin/env python3
"""pos_sync/probe_kurang_pj260014.py — READ-ONLY.

Menjawab: kenapa saldo `Gudang Barang Jadi - ROPI` (LAMA) untuk PJ260014
hanya 10.908 Pcs pada 10-12 Okt, padahal kiriman in-transit 8 Okt butuh
19.968 Pcs?

Bandingkan trail GBJ LAMA di sekitar 8 Okt, cari dokumen yang menarik
PJ260014 kembali dari GBJ, dan bandingkan dengan site BARU.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env

ITEM = "PJ260014"
GBJ_OLD = "Gudang Barang Jadi - ROPI"
GBJ_NEW = "Gudang Barang Jadi - JURI"


def main():
    mig = load_env("/tmp/eresto_mig.env")
    old = Client("https://rotiropi.j.frappe.cloud",
                 mig["ERPNEXT_OLD_CLOUD_API_KEY"], "LAMA")
    new = Client(mig["ERPNEXT_URL"], mig["ERPNEXT_API_KEY"], "BARU")

    print("== A. Saldo per gudang LAMA vs BARU")
    for label, c, wh in (("LAMA", old, GBJ_OLD), ("BARU", new, GBJ_NEW)):
        st, d = c.get("/api/resource/Bin", {
            "filters": json.dumps([["item_code", "=", ITEM],
                                   ["actual_qty", "!=", 0]]),
            "fields": json.dumps(["warehouse", "actual_qty", "stock_uom"]),
            "limit_page_length": 0})
        print(f"   -- {label}")
        for r in sorted(d.get("data", []), key=lambda x: -x["actual_qty"]):
            print(f"      {r['actual_qty']:>12} {r['stock_uom']:<5} {r['warehouse']}")

    print("\n== B. SLE PJ260014 di Gudang Barang Jadi - ROPI (LAMA), urut waktu")
    sle = old.list_all(
        "Stock Ledger Entry",
        ["posting_date", "posting_time", "actual_qty", "qty_after_transaction",
         "voucher_type", "voucher_no", "incoming_rate", "is_cancelled"],
        [["item_code", "=", ITEM], ["warehouse", "=", GBJ_OLD]],
        order="posting_date asc, posting_time asc, creation asc")
    print(f"   {len(sle)} baris")
    for r in sle:
        flag = "  CANCELLED" if r.get("is_cancelled") else ""
        print(f"   {r['posting_date']} {str(r['posting_time'])[:11]:<12}"
              f"{r['actual_qty']:>11} -> {r['qty_after_transaction']:>11}"
              f"  {r['voucher_type']:<22}{r['voucher_no']}{flag}")

    print("\n== C. SLE PJ260014 di Gudang Barang Jadi - JURI (BARU), urut waktu")
    sle2 = new.list_all(
        "Stock Ledger Entry",
        ["posting_date", "posting_time", "actual_qty", "qty_after_transaction",
         "voucher_type", "voucher_no", "incoming_rate", "is_cancelled"],
        [["item_code", "=", ITEM], ["warehouse", "=", GBJ_NEW]],
        order="posting_date asc, posting_time asc, creation asc")
    print(f"   {len(sle2)} baris")
    for r in sle2:
        flag = "  CANCELLED" if r.get("is_cancelled") else ""
        print(f"   {r['posting_date']} {str(r['posting_time'])[:11]:<12}"
              f"{r['actual_qty']:>11} -> {r['qty_after_transaction']:>11}"
              f"  {r['voucher_type']:<22}{r['voucher_no']}{flag}")

    print(f"\n== D. Semua dokumen LAMA 7-12 Okt yang menyentuh {ITEM} "
          f"(voucher apa saja)")
    for vt in ("Stock Entry", "Delivery Note", "Purchase Receipt",
               "Stock Reconciliation", "Sales Invoice"):
        rows = old.list_all(
            vt,
            ["name", "posting_date", "posting_time", "docstatus", "company",
             "from_warehouse", "to_warehouse"],
            [["name", "in", []], ],
            ) if False else None
    # cara yang benar: cari lewat Stock Ledger Entry di semua gudang, 7-12 Okt
    sle3 = old.list_all(
        "Stock Ledger Entry",
        ["warehouse", "posting_date", "posting_time", "actual_qty",
         "qty_after_transaction", "voucher_type", "voucher_no", "is_cancelled"],
        [["item_code", "=", ITEM],
         ["posting_date", ">=", "2026-10-07"],
         ["posting_date", "<=", "2026-10-13"]],
        order="posting_date asc, posting_time asc")
    for r in sle3:
        flag = "  C" if r.get("is_cancelled") else ""
        print(f"   {r['posting_date']} {str(r['posting_time'])[:11]:<12}"
              f"{r['actual_qty']:>11} -> {r['qty_after_transaction']:>11}"
              f"  {r['voucher_type']:<22}{r['voucher_no']:<26}{r['warehouse']}{flag}")

    print("\n== E. Semua dokumen BARU yang menyentuh PJ260014 (semua gudang)")
    sle4 = new.list_all(
        "Stock Ledger Entry",
        ["warehouse", "posting_date", "posting_time", "actual_qty",
         "voucher_type", "voucher_no", "is_cancelled"],
        [["item_code", "=", ITEM]],
        order="posting_date asc, posting_time asc")
    for r in sle4:
        print(f"   {r['posting_date']} {str(r['posting_time'])[:11]:<12}"
              f"{r['actual_qty']:>11}  {r['voucher_type']:<22}"
              f"{r['voucher_no']:<26}{r['warehouse']}")


if __name__ == "__main__":
    main()
