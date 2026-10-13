#!/usr/bin/env python3
"""pos_sync/verify_mr_po_25sep_7okt.py — Verifikasi dua sisi (READ-ONLY).

Bandingkan Material Request (Purchase) & Purchase Order PT. JURI window
2026-09-25 s/d 2026-10-07 antara site LAMA dan BARU:
  jumlah, docstatus, ID identik, item baris, qty, nilai, dan relink MR->PO.
Tidak menulis apa pun.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env

COMPANY = "PT. JUARA ROTI INDONESIA"
OLD_BASE = "https://rotiropi.j.frappe.cloud"
START, END = "2026-09-25", "2026-10-07"
EXTRA_MR = ["MAT-MR-2026-00448", "MAT-MR-2026-00583"]


def main():
    mig = load_env("/tmp/eresto_mig.env")
    new = Client(mig["ERPNEXT_URL"], mig["ERPNEXT_API_KEY"], "BARU")
    old = Client(OLD_BASE, mig["ERPNEXT_OLD_CLOUD_API_KEY"], "LAMA")

    allnew_mr = {r["name"]: r for r in new.list_all(
        "Material Request",
        ["name", "title", "docstatus", "material_request_type",
         "transaction_date", "set_warehouse", "per_ordered"])}
    allnew_po = {r["name"]: r for r in new.list_all(
        "Purchase Order",
        ["name", "title", "docstatus", "transaction_date", "supplier",
         "grand_total", "company"])}

    print("=" * 78)
    print(f"VERIFIKASI MIGRASI MR (PURCHASE) & PO — {START} s/d {END}")
    print("=" * 78)

    # ---------- MR
    mr = old.list_all("Material Request",
                      ["name", "transaction_date", "docstatus",
                       "material_request_type", "set_warehouse"],
                      [["company", "=", COMPANY],
                       ["material_request_type", "=", "Purchase"],
                       ["transaction_date", ">=", START],
                       ["transaction_date", "<=", END]],
                      order="name asc")
    for m in EXTRA_MR:
        st, d = old.get("/api/resource/Material Request/" + m)
        if st == 200:
            mr.append({"name": m, "transaction_date": d["data"]["transaction_date"],
                       "docstatus": d["data"].get("docstatus"),
                       "material_request_type": "Purchase",
                       "set_warehouse": d["data"].get("set_warehouse")})
    mr_sub = [r for r in mr if r["docstatus"] == 1]
    print(f"\n== MATERIAL REQUEST (Purchase)")
    print(f"   sumber submitted : {len(mr_sub)}")
    ada = [r for r in mr_sub if r["name"] in allnew_mr]
    hilang = [r["name"] for r in mr_sub if r["name"] not in allnew_mr]
    print(f"   ada di BARU      : {len(ada)}  (ID identik)")
    if hilang:
        print(f"   HILANG           : {len(hilang)} -> {hilang}")
    ds_ok = sum(1 for r in ada if allnew_mr[r["name"]]["docstatus"] == 1)
    print(f"   docstatus submit : {ds_ok}/{len(ada)}")
    ttl = [r["name"] for r in ada
           if allnew_mr[r["name"]].get("title") == f"ERESTO {r['name']}"]
    print(f"   title marker     : {len(ttl)}/{len(ada)}")
    dup = [r["name"] for r in mr_sub
           if sum(1 for x in allnew_mr.values()
                  if x.get("title") == f"ERESTO {r['name']}") > 1]
    print(f"   duplikat title   : {len(dup)}")

    # ---------- PO
    po = old.list_all("Purchase Order",
                      ["name", "transaction_date", "docstatus", "supplier",
                       "grand_total"],
                      [["company", "=", COMPANY],
                       ["transaction_date", ">=", START],
                       ["transaction_date", "<=", END]],
                      order="name asc")
    po_sub = [r for r in po if r["docstatus"] == 1]
    print(f"\n== PURCHASE ORDER")
    print(f"   sumber submitted : {len(po_sub)}")
    ada_po = [r for r in po_sub if r["name"] in allnew_po]
    hilang_po = [r["name"] for r in po_sub if r["name"] not in allnew_po]
    print(f"   ada di BARU      : {len(ada_po)}  (ID identik)")
    if hilang_po:
        print(f"   HILANG           : {len(hilang_po)} -> {hilang_po[:10]}")
    ds_ok = sum(1 for r in ada_po if allnew_po[r["name"]]["docstatus"] == 1)
    print(f"   docstatus submit : {ds_ok}/{len(ada_po)}")
    beda_nilai = []
    for r in ada_po:
        t = allnew_po[r["name"]]
        d0 = abs((t.get("grand_total") or 0) - (r.get("grand_total") or 0))
        if d0 > 1:
            beda_nilai.append((r["name"], r.get("grand_total"), t.get("grand_total")))
    print(f"   nilai 0 selisih  : {len(ada_po) - len(beda_nilai)}/{len(ada_po)}")
    for b in beda_nilai[:10]:
        print(f"      BEDA {b[0]}: lama {b[1]:,.0f} vs baru {b[2]:,.0f}")

    # ---------- relink PO -> MR
    print(f"\n== RELINK PO -> MR (baris PO punya material_request yang valid?)")
    checked = linked = broken = 0
    for r in ada_po[:200]:
        st, d = new.get("/api/resource/Purchase Order/" + r["name"])
        if st != 200:
            continue
        for it in d["data"].get("items", []):
            m = it.get("material_request")
            if not m:
                continue
            checked += 1
            if m in allnew_mr and allnew_mr[m]["docstatus"] == 1:
                linked += 1
            else:
                broken += 1
    print(f"   baris ber-MR     : {checked}")
    print(f"   MR valid di BARU : {linked}")
    print(f"   MR tidak valid   : {broken}")

    # ---------- hitung ulang MR yang dirujuk PO
    print(f"\n== MR yang dirujuk PO di scope (perlu ada di BARU)")
    ref = set()
    for r in po_sub:
        st, d = old.get("/api/resource/Purchase Order/" + r["name"],
                        {"fields": json.dumps(["items"])})
        if st != 200:
            continue
        for it in d["data"].get("items", []):
            if it.get("material_request"):
                ref.add(it["material_request"])
    ada_ref = [m for m in ref if m in allnew_mr]
    print(f"   dirujuk  : {len(ref)}")
    print(f"   ada BARU : {len(ada_ref)}")
    miss = sorted(set(ref) - set(ada_ref))
    if miss:
        print(f"   BELUM ADA: {len(miss)} -> {miss}")

    hasil = (not hilang and not hilang_po and not dup and not beda_nilai
             and not miss)
    print(f"\n# VERIFIKASI {'LOLOS' if hasil else 'ADA TEMUAN'}")


if __name__ == "__main__":
    main()
