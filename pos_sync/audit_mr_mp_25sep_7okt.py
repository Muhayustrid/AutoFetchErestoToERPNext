#!/usr/bin/env python3
"""pos_sync/audit_mr_mp_25sep_7okt.py — READ-ONLY (v2).

Audit Material Request & Purchase Order ("Material Purchase") PT. JUARA ROTI
INDONESIA window 2026-09-25 s/d 2026-10-07 di site LAMA, dibandingkan dengan
site BARU. Fokus: tipe Purchase saja (yang nyambung ke PO/pembelian).

Tidak menulis apa pun.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env

COMPANY = "PT. JUARA ROTI INDONESIA"
OLD_BASE = "https://rotiropi.j.frappe.cloud"
START, END = "2026-09-25", "2026-10-07"
MR_FIELDS = ["name", "transaction_date", "material_request_type", "docstatus",
             "status", "company", "title", "per_ordered", "per_received",
             "set_warehouse", "custom_is_form_order"]
PO_FIELDS = ["name", "transaction_date", "supplier", "docstatus", "status",
             "grand_total", "title", "company"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    ap.add_argument("--all-types", action="store_true",
                    help="ikutkan MR tipe selain Purchase")
    args = ap.parse_args()

    mig = load_env("/tmp/eresto_mig.env")
    new = Client(mig["ERPNEXT_URL"], mig["ERPNEXT_API_KEY"], "BARU")
    old = Client(OLD_BASE, mig["ERPNEXT_OLD_CLOUD_API_KEY"], "LAMA")

    print(f"# BARU: {new.base} | LAMA: {OLD_BASE}")
    print(f"# window: {START} s/d {END} | company: {COMPANY}")

    out = {}

    # ---- 1. Material Request di LAMA
    flt = [["company", "=", COMPANY],
           ["transaction_date", ">=", START],
           ["transaction_date", "<=", END]]
    mr = old.list_all("Material Request", MR_FIELDS, flt,
                      order="transaction_date asc, name asc")
    if not args.all_types:
        mr_pur = [r for r in mr if r.get("material_request_type") == "Purchase"]
    else:
        mr_pur = mr
    print(f"\n== LAMA Material Request {START}..{END}: {len(mr)} total")
    by_type = {}
    for r in mr:
        t = r.get("material_request_type") or "(kosong)"
        by_type.setdefault(t, []).append(r)
    for t, rows in sorted(by_type.items()):
        ds = {}
        for r in rows:
            ds[r.get("docstatus")] = ds.get(r.get("docstatus"), 0) + 1
        print(f"   -- {t}: {len(rows)} dok | docstatus {ds}")
    out["mr_lama_all"] = mr
    out["mr_lama_purchase"] = mr_pur

    # ---- 2. Purchase Order di LAMA
    po = old.list_all("Purchase Order", PO_FIELDS,
                      [["company", "=", COMPANY],
                       ["transaction_date", ">=", START],
                       ["transaction_date", "<=", END]],
                      order="transaction_date asc, name asc")
    ds = {}
    for r in po:
        ds[r.get("docstatus")] = ds.get(r.get("docstatus"), 0) + 1
    tot = sum(r.get("grand_total") or 0 for r in po)
    print(f"\n== LAMA Purchase Order {START}..{END}: {len(po)} | docstatus {ds}")
    print(f"   total grand_total: Rp {tot:,.2f}")
    out["po_lama"] = po

    # ---- 3. Bandingkan dengan BARU
    print("\n== BARU: status dokumen (by name & title 'ERESTO <name>')")
    new_mr = {r["name"]: r for r in
              new.list_all("Material Request", ["name", "title", "docstatus",
                                                "material_request_type"])}
    new_mr_title = {r.get("title"): r for r in new_mr.values() if r.get("title")}
    new_po = {r["name"]: r for r in
              new.list_all("Purchase Order", ["name", "title", "docstatus",
                                              "grand_total"])}
    new_po_title = {r.get("title"): r for r in new_po.values() if r.get("title")}

    mr_by_name = [r["name"] for r in mr_pur if r["name"] in new_mr]
    mr_by_title = [r["name"] for r in mr_pur
                   if f"ERESTO {r['name']}" in new_mr_title]
    po_by_name = [r["name"] for r in po if r["name"] in new_po]
    po_by_title = [r["name"] for r in po if f"ERESTO {r['name']}" in new_po_title]
    print(f"   MR Purchase: {len(mr_pur)} | sudah ada by-name {len(mr_by_name)}"
          f" | by-title {len(mr_by_title)}")
    print(f"   PO          : {len(po)} | sudah ada by-name {len(po_by_name)}"
          f" | by-title {len(po_by_title)}")
    out["mr_baru_name"] = mr_by_name
    out["mr_baru_title"] = mr_by_title
    out["po_baru_name"] = po_by_name
    out["po_baru_title"] = po_by_title

    # ---- 4. Rincian MR Purchase
    print(f"\n== Rincian {len(mr_pur)} MR tipe Purchase (LAMA)")
    ds = {}
    for r in mr_pur:
        ds[r.get("docstatus")] = ds.get(r.get("docstatus"), 0) + 1
    print(f"   docstatus: {ds}")
    wh = {}
    for r in mr_pur:
        wh[r.get("set_warehouse")] = wh.get(r.get("set_warehouse"), 0) + 1
    print(f"   set_warehouse: {wh}")
    fo = {}
    for r in mr_pur:
        fo[r.get("custom_is_form_order")] = fo.get(r.get("custom_is_form_order"), 0) + 1
    print(f"   custom_is_form_order: {fo}")
    print("\n   daftar:")
    for r in mr_pur:
        ada = "ADA" if (r["name"] in new_mr or f"ERESTO {r['name']}" in new_mr_title) else "-"
        print(f"      {r['name']:<26}{r['transaction_date']}  ds={r['docstatus']}"
              f"  {str(r.get('set_warehouse') or ''):<32}{ada}")

    # ---- 5. Relasi PO -> MR (untuk relink nanti)
    print("\n== Relasi PO di scope -> MR (baris PO)")
    rel = {}
    for p in po:
        st, d = old.get("/api/resource/Purchase Order/" + p["name"],
                        {"fields": json.dumps(["items"])})
        if st != 200:
            continue
        for it in d["data"].get("items", []):
            m = it.get("material_request")
            if m:
                rel.setdefault(m, []).append(p["name"])
    print(f"   {len(rel)} MR dirujuk oleh PO di scope")
    out["po_to_mr"] = {k: sorted(set(v)) for k, v in rel.items()}
    # MR yang dirujuk tapi di luar scope
    luar = sorted(set(rel) - {r["name"] for r in mr_pur})
    print(f"   !! {len(luar)} MR dirujuk PO tapi TIDAK masuk scope MR Purchase:")
    for m in luar[:40]:
        st, d = old.get("/api/resource/Material Request/" + m)
        if st == 200:
            doc = d["data"]
            print(f"      {m:<26}{doc.get('transaction_date')}  "
                  f"type={doc.get('material_request_type')}  ds={doc.get('docstatus')}")
    out["mr_luar_scope"] = luar

    if args.json:
        with open(args.json, "w") as f:
            json.dump(out, f, indent=1, default=str)
        print(f"\n# dumped -> {args.json}")


if __name__ == "__main__":
    main()
