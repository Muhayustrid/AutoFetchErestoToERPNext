"""Dump sumber dari site LOKAL + meta dari PROD ke pos_sync/prod_src/.

Sumber = state final site lokal (erp.localhost:8081) — dokumen hasil migrasi
site lama yang siap disalin ke production. Idempoten (cukup dijalankan ulang).

Usage: python3 prod_dump.py
"""
import json
import os
import urllib.parse

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import LOCAL_ENV, PROD_ENV, SRC_DIR, Client, fetch_meta, load_env  # noqa: E402

DOCS = [
    # (file, doctype, field marker, like)
    ("work_order.json", "Work Order", "description", "ERESTO %"),
    ("stock_entry.json", "Stock Entry", "remarks", "ERESTO %"),
    ("purchase_order.json", "Purchase Order", "title", "ERESTO %"),
    ("purchase_receipt.json", "Purchase Receipt", "title", "ERESTO %"),
    ("sales_order.json", "Sales Order", "title", "ERESTO %"),
    ("delivery_note.json", "Delivery Note", "title", "ERESTO %"),
]

COMPANIES_MISSING = [
    "RSU San Medica (FRC)", "Bangka Tengah (FRC)", "Plaza Haji alQosbah (FRC)",
    "RS Medina Garut (FRC)", "Jambi Sarulangun (FRC)", "Sungai Penuh (FRC)",
    "Mitra Swalayan Gombong (FRC)", "RSUP Palembang",
]
ITEMS_MISSING = ["BB260057", "BB260058", "BB260059", "BB260060", "BB260061",
                 "BB260062", "PEL260072", "PEL260097"]
SUPPLIERS_MISSING = [
    "Toko Santi", "Shopee - Duster Joe", "Shopee - Lionelplastik",
    "Shopee - Tokorak.ID", "Shopee - Smartcom LTD", "Shopee - Neo Geo Shop",
    "Shopee - Mikadoshop", "Shopee - Ledaohome", "Shopee - 123 Packaging",
]
CUSTOMER_EXTRA_CODES = ["CUST-260210", "CUST-260211", "CUST-260203"]
CUSTOMER_EXTRA_NAMES = COMPANIES_MISSING + ["RSI FATIMAH BANYUWANGI",
                                            "Harapan Indah (FRC)"]

PROD_META_DOCTYPES = [
    # parent
    "Company", "Customer", "Supplier", "Item", "BOM", "Work Order",
    "Stock Entry", "Purchase Order", "Purchase Receipt", "Sales Order",
    "Delivery Note", "Stock Reconciliation", "Fiscal Year",
    "Mode of Payment", "Warehouse",
    # child
    "Item Default", "UOM Conversion Detail", "BOM Item", "BOM Operation",
    "Work Order Item", "Work Order Operation", "Stock Entry Detail",
    "Purchase Order Item", "Purchase Receipt Item", "Sales Order Item",
    "Delivery Note Item", "Stock Reconciliation Item",
    "Mode of Payment Account", "Fiscal Year Company",
]


def full(client, doctype, name):
    st, d = client.get("/api/resource/" + urllib.parse.quote(doctype)
                       + "/" + urllib.parse.quote(name))
    if st != 200:
        print(f"  !! GET {doctype} {name} HTTP {st}")
        return None
    return d["data"]


def main():
    os.makedirs(SRC_DIR, exist_ok=True)
    le, pe = load_env(LOCAL_ENV), load_env(PROD_ENV)
    lc = Client(le["ERPNEXT_URL"], le["ERPNEXT_API_KEY"], label="local")
    pc = Client(pe["ERPNEXT_URL"], pe["ERPNEXT_API_KEY"], label="prod")

    # 1. meta site prod
    meta = fetch_meta(pc, PROD_META_DOCTYPES)
    json.dump(meta, open(os.path.join(SRC_DIR, "prod_meta.json"), "w"),
              indent=1)
    print(f"meta prod: {len(meta)} doctype")

    # 2. dokumen
    all_docs = {}
    for fname, dt, fld, like in DOCS:
        lst = lc.list_all(dt, ["name"], [[fld, "like", like]], order="name asc")
        docs = []
        for r in lst:
            doc = full(lc, dt, r["name"])
            if doc:
                docs.append(doc)
        json.dump(docs, open(os.path.join(SRC_DIR, fname), "w"),
                  indent=1, default=str)
        all_docs[dt] = docs
        print(f"{dt}: {len(docs)} dokumen -> {fname}")

    recos = lc.list_all("Stock Reconciliation", ["name"], order="name asc")
    recos_full = [full(lc, "Stock Reconciliation", r["name"]) for r in recos]
    recos_full = [r for r in recos_full if r]
    json.dump(recos_full, open(os.path.join(SRC_DIR,
              "stock_reconciliation.json"), "w"), indent=1, default=str)
    print(f"Stock Reconciliation: {len(recos_full)}")

    # 3. bin + sle
    for fname, dt, flds in (
            ("bin.json", "Bin", ["item_code", "warehouse", "actual_qty",
                                 "valuation_rate"]),
            ("sle.json", "Stock Ledger Entry",
             ["item_code", "warehouse", "actual_qty", "voucher_type",
              "voucher_no", "posting_date", "posting_time"])):
        rows = lc.list_all(dt, flds)
        json.dump(rows, open(os.path.join(SRC_DIR, fname), "w"), default=str)
        print(f"{dt}: {len(rows)} baris -> {fname}")

    # 4. master yang belum ada di prod
    for fname, dt, names in (
            ("companies_missing.json", "Company", COMPANIES_MISSING),
            ("items_missing.json", "Item", ITEMS_MISSING),
            ("suppliers_missing.json", "Supplier", SUPPLIERS_MISSING),
            ("bom_krim_kopi.json", "BOM", ["BOM-PJ260016-001"])):
        docs = [full(lc, dt, n) for n in names]
        docs = [d for d in docs if d]
        json.dump(docs, open(os.path.join(SRC_DIR, fname), "w"),
                  indent=1, default=str)
        print(f"{dt}: {len(docs)}/{len(names)} -> {fname}")

    # 5. customer: dari dokumen + daftar tambahan
    codes, names = set(), set()
    for dt in ("Sales Order", "Delivery Note"):
        for doc in all_docs[dt]:
            if doc.get("customer"):
                codes.add(doc["customer"])
            if doc.get("customer_name"):
                names.add(doc["customer_name"])
    codes |= set(CUSTOMER_EXTRA_CODES)
    names |= set(CUSTOMER_EXTRA_NAMES)
    for nm in names:
        rows = lc.list_all("Customer", ["name"],
                           [["customer_name", "=", nm]])
        for r in rows:
            codes.add(r["name"])
    cust_docs = []
    for cod in sorted(codes):
        doc = full(lc, "Customer", cod)
        if doc:
            cust_docs.append(doc)
    json.dump(cust_docs, open(os.path.join(SRC_DIR, "customers.json"), "w"),
              indent=1, default=str)
    print(f"Customer: {len(cust_docs)} dari {len(codes)} kode "
          f"({len(names)} nama) -> customers.json")

    # 6. supplier: daftar lengkap dari lokal (untuk nama) + full yang hilang
    sup_all = lc.list_all("Supplier", ["name", "supplier_name"])
    json.dump(sup_all, open(os.path.join(SRC_DIR, "suppliers_all_local.json"),
                            "w"), default=str)
    print(f"Supplier lokal: {len(sup_all)} -> suppliers_all_local.json")

    # 7. MoP lokal (baris akun per company utk 8 baru)
    mops = []
    for m in ("Cash", "QRIS", "Debit Card", "Credit Card"):
        doc = full(lc, "Mode of Payment", m)
        if doc:
            mops.append(doc)
    json.dump(mops, open(os.path.join(SRC_DIR, "mop_local.json"), "w"),
              indent=1, default=str)
    print(f"Mode of Payment: {len(mops)} -> mop_local.json")

    # 8. ringkasan status dokumen
    summary = {}
    for dt in all_docs:
        from collections import Counter
        summary[dt] = dict(Counter(d.get("docstatus") for d in all_docs[dt]))
    json.dump(summary, open(os.path.join(SRC_DIR, "summary.json"), "w"),
              indent=1)
    print("summary docstatus:", json.dumps(summary))
    print("DUMP OK")


if __name__ == "__main__":
    main()
