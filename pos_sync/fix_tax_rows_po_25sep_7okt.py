#!/usr/bin/env python3
"""pos_sync/fix_tax_rows_po_25sep_7okt.py — Tambahkan baris pajak ke PO hasil migrasi.

Konteks: 27 PO yang dimigrasi dari site LAMA memakai template 'Purchase Tax -
ROPI' (PPN 11% DI ATAS net total). Saat migrasi, `taxes = []` dikirim kosong,
jadi grand_total di BARU = net (kurang 11%). Script ini menambahkan baris pajak
agar grand_total = LAMA persis.

Aturan (KNOWLEDGE §6.8): update setelah submit -> Property Setter
`allow_on_submit=1` sementara + set_value, lalu pulihkan ke 0.

Pakai:
  .venv/bin/python pos_sync/fix_tax_rows_po_25sep_7okt.py           # dry-run
  .venv/bin/python pos_sync/fix_tax_rows_po_25sep_7okt.py --execute
  .venv/bin/python pos_sync/fix_tax_rows_po_25sep_7okt.py --verify
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env

COMPANY = "PT. JUARA ROTI INDONESIA"
OLD_BASE = "https://rotiropi.j.frappe.cloud"
START, END = "2026-09-25", "2026-10-07"
TAX_TEMPLATE = "Purchase Tax - JURI"
PPN_ACCOUNT = "1152.001 - PPN Masukan - JURI"
COST_CENTER = "Main - JURI"
AUDIT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "audit_logs")


def tax_added(po_new):
    """True kalau PO di BARU sudah punya baris pajak."""
    return any(abs(float(t.get("tax_amount") or 0)) > 0
               for t in (po_new.get("taxes") or []))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    mig = load_env("/tmp/eresto_mig.env")
    new = Client(mig["ERPNEXT_URL"], mig["ERPNEXT_API_KEY"], "BARU")
    old = Client(OLD_BASE, mig["ERPNEXT_OLD_CLOUD_API_KEY"], "LAMA")

    mode = "EXECUTE" if args.execute else ("VERIFY" if args.verify else "DRY-RUN")
    print(f"# mode={mode} | BARU={new.base} | LAMA(read-only)={OLD_BASE}")

    # PO sumber yang pakai template pajak 'di atas net'
    po_rows = old.list_all(
        "Purchase Order",
        ["name", "transaction_date", "docstatus", "taxes_and_charges",
         "grand_total", "net_total"],
        [["company", "=", COMPANY],
         ["transaction_date", ">=", START],
         ["transaction_date", "<=", END],
         ["docstatus", "=", 1]],
        order="transaction_date asc, name asc")
    targets = [r for r in po_rows
               if r.get("taxes_and_charges") == "Purchase Tax - ROPI"]
    print(f"# PO sumber ber-template 'Purchase Tax - ROPI': {len(targets)}")

    plan, done, skip = [], [], []
    for r in targets:
        name = r["name"]
        if args.only and name != args.only:
            continue
        # cari di BARU: by ID identik, atau by title 'ERESTO <id-lama>'
        st, d = new.get("/api/resource/Purchase Order/" + name)
        tgt_name = name
        if st != 200:
            st2, d2 = new.get("/api/resource/Purchase Order", {
                "filters": json.dumps([["title", "=", f"ERESTO {name}"]]),
                "fields": json.dumps(["name"]), "limit_page_length": 1})
            rows = d2.get("data", []) if st2 == 200 else []
            if not rows:
                skip.append((name, "BELUM ADA di BARU"))
                continue
            tgt_name = rows[0]["name"]
            st, d = new.get("/api/resource/Purchase Order/" + tgt_name)
        b = d["data"]
        if tax_added(b):
            done.append(tgt_name)
            continue
        # basis pajak: net_total BARU (agar konsisten walau ada pembulatan).
        # Untuk dokumen submitted, net_total harus sama dengan LAMA.
        net_baru = float(b.get("net_total") or 0)
        if b.get("docstatus") == 1 and abs(net_baru - float(r.get("net_total") or 0)) > 1:
            skip.append((tgt_name, "net_total beda (submitted, bukan kasus 'di atas net')"))
            continue
        if b.get("docstatus") == 0 and abs(net_baru - float(r.get("net_total") or 0)) > 100:
            skip.append((tgt_name, f"net_total beda {net_baru:,.2f} (draft)"))
            continue
        plan.append({"name": tgt_name, "lama_id": name,
                     "net_lama": net_baru,
                     "grand_lama": float(r.get("grand_total") or 0),
                     "grand_baru": float(b.get("grand_total") or 0)})

    print(f"\n# sudah ada baris pajak : {len(done)}")
    print(f"# perlu ditambahkan      : {len(plan)}")
    print(f"# dilewati               : {len(skip)}")
    for n, why in skip:
        print(f"     - {n}: {why}")
    print(f"\n{'PO':<20}{'net':>16}{'grand lama':>16}{'grand baru':>16}{'PPN 11%':>15}")
    for p in plan:
        print(f"{p['name']:<20}{p['net_lama']:>16,.0f}{p['grand_lama']:>16,.0f}"
              f"{p['grand_baru']:>16,.0f}{p['net_lama']*0.11:>15,.0f}")

    if args.verify or not args.execute:
        if not args.execute:
            print("\n# DRY-RUN — tidak ada yang ditulis. Tambah --execute.")
        return

    os.makedirs(AUDIT_DIR, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    bpath = os.path.join(AUDIT_DIR, f"backup_tax_rows_po_{ts}.json")
    with open(bpath, "w") as f:
        json.dump({"ts": ts, "plan": plan}, f, indent=1, default=str)
    print(f"\n# backup -> {bpath}")

    # Property Setter sementara: allow_on_submit untuk field terkait pajak
    setters = []
    for spec in (
        {"doctype_or_field": "DocField", "field_name": "taxes"},
        {"doctype_or_field": "DocField", "field_name": "total_taxes_and_charges"},
        {"doctype_or_field": "DocField", "field_name": "grand_total"},
        {"doctype_or_field": "DocField", "field_name": "rounded_total"},
        {"doctype_or_field": "DocField", "field_name": "base_grand_total"},
        {"doctype_or_field": "DocField", "field_name": "base_rounded_total"},
        {"doctype_or_field": "DocField", "field_name": "in_words"},
        {"doctype_or_field": "DocField", "field_name": "taxes_and_charges"},
    ):
        payload = {"doctype": "Property Setter", "doc_type": "Purchase Order",
                   "property": "allow_on_submit", "property_type": "Check",
                   "value": "1"}
        payload.update(spec)
        st, d = new.post("Property Setter", payload)
        nm = d.get("data", {}).get("name") if st == 200 else None
        if nm:
            setters.append(nm)
        print(f"# setter {spec['field_name']}: {st} {nm}")

    ok = fail = 0
    try:
        for p in plan:
            payload = {
                "taxes_and_charges": TAX_TEMPLATE,
                "taxes": [{
                    "charge_type": "On Net Total",
                    "account_head": PPN_ACCOUNT,
                    "description": "PPN Masukan @ 11.0",
                    "rate": 11.0,
                    "cost_center": COST_CENTER,
                    "category": "Total",
                    "add_deduct_tax": "Add",
                    # hitung sendiri: PUT tidak memicu recalc pajak di v16
                    "tax_amount": round(p["net_lama"] * 0.11, 2),
                    "total": round(p["net_lama"] * 1.11, 2),
                    "base_tax_amount": round(p["net_lama"] * 0.11, 2),
                    "base_total": round(p["net_lama"] * 1.11, 2),
                    "net_amount": p["net_lama"],
                    "base_net_amount": p["net_lama"],
                }],
                "total_taxes_and_charges": round(p["net_lama"] * 0.11, 2),
                "grand_total": round(p["net_lama"] * 1.11, 2),
                "base_grand_total": round(p["net_lama"] * 1.11, 2),
                "rounded_total": round(p["net_lama"] * 1.11, 2),
                "base_rounded_total": round(p["net_lama"] * 1.11, 2),
                "in_words": None,
            }
            st, d = new.put("Purchase Order", p["name"], payload)
            if st != 200:
                print(f"  [FAIL] {p['name']}: HTTP {st} {str(d)[:180]}")
                fail += 1
                continue
            b = d["data"]
            ok += 1
            print(f"  [OK] {p['name']:<20} grand={b.get('grand_total'):>16,.2f} "
                  f"(target {p['grand_lama']:,.2f})")
    finally:
        for s in setters:
            st, d = new.delete("Property Setter", s)
            print(f"# setter dihapus: {s} -> {st}")

    print(f"\n=== SELESAI: {ok} sukses, {fail} gagal ===")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
