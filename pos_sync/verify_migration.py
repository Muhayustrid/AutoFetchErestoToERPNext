"""Verifikasi migrasi: bandingkan dokumen lama vs baru + tulis Excel rekap.

Bandingkan per DocType: jumlah dokumen + total qty per item_code
(setelah ITEM_MAP) + total produced_qty WO + total fg_completed_qty SE.
Sumber lama: pos_sync/window/*.json. Sumber baru: REST (filter remarks ERESTO).

Usage: python3 verify_migration.py [--out XLSX]
Env: ERPNEXT_URL, ERPNEXT_API_KEY (site BARU).
"""
import argparse
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ERP, ITEM_MAP, eresto_key  # noqa: E402

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


def load_env(path="/tmp/eresto_mig.env"):
    d = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def style_sheet(ws, money_cols=()):
    ws.freeze_panes = "A2"
    try:
        ws.auto_filter.ref = ws.dimensions
    except Exception:
        pass
    fill = PatternFill("solid", fgColor="D9EAF7")
    for c in ws[1]:
        c.fill, c.font = fill, Font(bold=True)
        c.alignment = Alignment(horizontal="center", vertical="center",
                                wrap_text=True)
    for col in ws.columns:
        w = max(len(str(c.value or "")) for c in col)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(w + 2, 45)


def fetch_new(erp, doctype, remark_field, like="ERESTO %"):
    out, start = [], 0
    while True:
        st, d = erp.get("/api/resource/" + urllib.parse.quote(doctype), {
            "filters": json.dumps([[remark_field, "like", like]]),
            "fields": '["name"]', "limit_page_length": 200,
            "limit_start": start, "order_by": "name"})
        rows = d.get("data", []) if st == 200 else []
        if not rows:
            break
        for r in rows:
            st2, d2 = erp.get("/api/resource/" + urllib.parse.quote(doctype)
                              + "/" + urllib.parse.quote(r["name"]))
            if st2 == 200:
                out.append(d2["data"])
        start += len(rows)
        if len(rows) < 200:
            break
    return out


def qty_by_item(docs, code_fn=lambda it: it["item_code"], qty_fn=lambda it: it.get("qty", 0)):
    tot = {}
    for h in docs:
        for it in h.get("items", []):
            c = ITEM_MAP.get(code_fn(it), code_fn(it))
            tot[c] = tot.get(c, 0) + float(qty_fn(it) or 0)
    return tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="pos_sync/Migrasi_Okt2026.xlsx")
    args = ap.parse_args()
    env = load_env()
    erp = ERP(env["ERPNEXT_URL"].rstrip("/"), env["ERPNEXT_API_KEY"])
    wdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "window")

    checks, fails = [], []
    summary = []
    plan = [
        ("Work_Order", "Work Order", "description", "ERESTO MFG-WO-%"),
        ("Stock_Entry", "Stock Entry", "remarks", "ERESTO MAT-STE-%"),
        ("Purchase_Order", "Purchase Order", "title", "ERESTO %"),
        ("Purchase_Receipt", "Purchase Receipt", "title", "ERESTO %"),
        ("Sales_Order", "Sales Order", "title", "ERESTO %"),
        ("Delivery_Note", "Delivery Note", "title", "ERESTO %"),
    ]
    for fname, dt, rf, like in plan:
        old = json.load(open(os.path.join(wdir, fname + ".json")))
        if fname == "Stock_Entry":
            # gabungkan SE WO-linked + non-WO (keduanya dimigrasi)
            p2 = os.path.join(wdir, "Stock_Entry_NonWO.json")
            if os.path.exists(p2):
                old = old + json.load(open(p2))
        new = fetch_new(erp, dt, rf, like)
        oq, nq = qty_by_item(old), qty_by_item(new)
        key = set(oq) | set(nq)
        diff = {c: round(oq.get(c, 0) - nq.get(c, 0), 3) for c in key
                if abs(oq.get(c, 0) - nq.get(c, 0)) > 0.001}
        ok_count = len(old) == len(new)
        ok_qty = not diff
        summary.append({"doctype": dt, "lama": len(old), "baru": len(new),
                        "hitung_OK": "LOLOS" if ok_count else "GAGAL",
                        "qty_OK": "LOLOS" if ok_qty else "GAGAL"})
        checks.append((f"{dt}: {len(new)}/{len(old)} dokumen", ok_count))
        checks.append((f"{dt}: qty per item sama ({len(diff)} selisih)", ok_qty))
        for c, v in sorted(diff.items()):
            fails.append({"doctype": dt, "item": c, "selisih_lama_minus_baru": v,
                          "lama": oq.get(c, 0), "baru": nq.get(c, 0)})
    # WO produced vs SE manufacture: produced lama mencakup WO In Process
    # (parsial), jadi pembanding sah = manufacture baru vs manufacture lama.
    wold = json.load(open(os.path.join(wdir, "Work_Order.json")))
    sold = json.load(open(os.path.join(wdir, "Stock_Entry.json")))
    snew = fetch_new(erp, "Stock Entry", "remarks", "ERESTO MAT-STE-%")
    op = sum(float(w.get("produced_qty") or 0) for w in wold)
    sold_all = sold
    p2 = os.path.join(wdir, "Stock_Entry_NonWO.json")
    if os.path.exists(p2):
        sold_all = sold + json.load(open(p2))
    sp_old = sum(float(s.get("fg_completed_qty") or 0) for s in sold_all
                 if s.get("stock_entry_type") == "Manufacture"
                 and any(it.get("is_stock_item", 1) for it in s.get("items", [])))
    sp_new = sum(float(s.get("fg_completed_qty") or 0) for s in snew
                 if s.get("stock_entry_type") == "Manufacture")
    checks.append((f"SE manufacture (stock item) baru {sp_new:g} vs lama {sp_old:g} "
                   f"(info: produced lama {op:g}, beda krn WO In Process; "
                   f"13 SE bundel non-stock di-skip sesuai model baru)",
                   abs(sp_new - sp_old) < 0.01))
    summary.append({"doctype": "WO-vs-SE", "lama": op, "baru": sp_new,
                    "hitung_OK": "", "qty_OK": "LOLOS" if abs(sp_new - sp_old) < 0.01 else "GAGAL"})

    print("== hasil verifikasi ==")
    all_ok = True
    for name, ok in checks:
        print(f"  [{'LOLOS' if ok else 'GAGAL'}] {name}")
        all_ok = all_ok and ok
    with pd.ExcelWriter(args.out, engine="openpyxl") as w:
        pd.DataFrame(summary).to_excel(w, sheet_name="Rekap", index=False)
        pd.DataFrame([{"cek": n, "hasil": "LOLOS" if ok else "GAGAL"}
                      for n, ok in checks]).to_excel(
            w, sheet_name="Validation", index=False)
        pd.DataFrame(fails).to_excel(w, sheet_name="Failed", index=False)
        for ws in w.sheets.values():
            style_sheet(ws)
    print(f"  Excel: {args.out}")
    if not all_ok:
        sys.exit(1)
    print("VERIFIKASI OK")


if __name__ == "__main__":
    main()
