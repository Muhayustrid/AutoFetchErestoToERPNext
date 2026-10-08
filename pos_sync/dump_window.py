"""Dump baca-saja dokumen jendela 1-2 Okt 2026 dari site LAMA via REST.

Usage: python3 dump_window.py [--out DIR]
Butuh ERPNEXT_OLD_API_KEY di env. Tidak menulis apa pun ke site mana pun.
Keluar: JSON per DocType + child items di DIR (default pos_sync/window/).
"""
import argparse
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ERP, NEW_BASE, OLD_BASE  # noqa: E402

WINDOW = ("2026-10-01", "2026-10-02")

# doctype: (filter tanggal, field tanggal, child doctype, parentfield)
PLAN = {
    "Work Order": ("creation", ["Work Order Item", "Work Order Operation"]),
    "Purchase Order": ("transaction_date", ["Purchase Order Item"]),
    "Purchase Receipt": ("posting_date", ["Purchase Receipt Item"]),
    "Sales Order": ("transaction_date", ["Sales Order Item"]),
    "Delivery Note": ("posting_date", ["Delivery Note Item"]),
    "Stock Entry": ("posting_date", ["Stock Entry Detail"]),
}


def dump(erp, doctype, datefield, children, outdir, extra_filters=None):
    names, start = [], 0
    while True:
        filters = [[datefield, ">=", WINDOW[0]], [datefield, "<=", WINDOW[1] + " 23:59:59"]]
        if extra_filters:
            filters += extra_filters
        st, d = erp.get("/api/resource/" + urllib.parse.quote(doctype), {
            "filters": json.dumps(filters),
            "fields": '["name"]', "limit_page_length": 200,
            "limit_start": start, "order_by": "name"})
        if st != 200:
            print(f"ERROR list {doctype}: {d}")
            sys.exit(1)
        rows = d.get("data", [])
        if not rows:
            break
        names += [r["name"] for r in rows]
        start += len(rows)
        if len(rows) < 200:
            break
    docs = []
    for n in names:
        st, d = erp.get("/api/resource/" + urllib.parse.quote(doctype)
                        + "/" + urllib.parse.quote(n))
        if st != 200:
            print(f"ERROR get {doctype} {n}: {str(d)[:200]}")
            sys.exit(1)
        docs.append(d["data"])
    path = os.path.join(outdir, doctype.replace(" ", "_") + ".json")
    with open(path, "w") as f:
        json.dump(docs, f, default=str, indent=1)
    print(f"  {doctype}: {len(docs)} dokumen -> {path}")
    return docs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="pos_sync/window")
    args = ap.parse_args()
    key = os.environ.get("ERPNEXT_OLD_API_KEY", "")
    if not key:
        print("ERROR: ERPNEXT_OLD_API_KEY kosong di env")
        sys.exit(1)
    os.makedirs(args.out, exist_ok=True)
    erp = ERP(OLD_BASE, key)
    st, _ = erp.get("/api/method/frappe.auth.get_logged_user")
    if st != 200:
        print(f"ERROR: API key site lama ditolak HTTP {st}")
        sys.exit(1)
    print("== dump window 1-2 Okt 2026 dari site lama ==")
    wo = dump(erp, "Work Order", "creation", None, args.out)
    wo_names = [w["name"] for w in wo]
    dump(erp, "Purchase Order", "transaction_date", None, args.out)
    dump(erp, "Purchase Receipt", "posting_date", None, args.out)
    dump(erp, "Sales Order", "transaction_date", None, args.out)
    dump(erp, "Delivery Note", "posting_date", None, args.out)
    # SE hanya yang terkait WO jendela
    se_all, start = [], 0
    print("  Stock Entry: filter work_order dalam jendela...")
    while True:
        st, d = erp.get("/api/resource/Stock Entry", {
            "filters": json.dumps([["work_order", "in", wo_names]]),
            "fields": '["name"]', "limit_page_length": 200,
            "limit_start": start, "order_by": "name"})
        if st != 200:
            print(f"ERROR list Stock Entry: {d}")
            sys.exit(1)
        rows = d.get("data", [])
        if not rows:
            break
        se_all += [r["name"] for r in rows]
        start += len(rows)
        if len(rows) < 200:
            break
    docs = []
    for n in se_all:
        st, d = erp.get("/api/resource/Stock Entry/" + urllib.parse.quote(n))
        if st != 200:
            print(f"ERROR get Stock Entry {n}")
            sys.exit(1)
        docs.append(d["data"])
    path = os.path.join(args.out, "Stock_Entry.json")
    with open(path, "w") as f:
        json.dump(docs, f, default=str, indent=1)
    print(f"  Stock Entry: {len(docs)} dokumen -> {path}")
    print("DUMP OK")


if __name__ == "__main__":
    main()
