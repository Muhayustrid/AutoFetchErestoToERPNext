"""Verifikasi injeksi PROD (docs/07): hitung dokumen + paritas stok Bin.

Sumber: /tmp/eresto_mig.env (lokal), /tmp/eresto_prod.env (prod),
dump pos_sync/prod_src/*.json. Output Excel pos_sync/Injeksi_Prod.xlsx.

Usage: python3 prod_verify.py
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import (LOCAL_ENV, PROD_ENV, SRC_DIR, Client,  # noqa: E402
                         jload, load_env)

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

PLAN = [
    ("Work Order", "description", "work_order.json", None),
    ("Purchase Order", "title", "purchase_order.json", None),
    ("Sales Order", "title", "sales_order.json", None),
    ("Purchase Receipt", "title", "purchase_receipt.json", None),
    ("Stock Entry", "remarks", "stock_entry.json", None),
    ("Delivery Note", "title", "delivery_note.json", None),
]
SKIP_TJBK = ("- TJBK",)


def style_sheet(ws):
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
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(
            w + 2, 48)


def fetch_all(client, dt, fields, like=None, like_field=None):
    filters = [[like_field, "like", like]] if like else None
    return client.list_all(dt, fields, filters, order="name asc")


def main():
    le, pe = load_env(LOCAL_ENV), load_env(PROD_ENV)
    lc = Client(le["ERPNEXT_URL"], le["ERPNEXT_API_KEY"], label="local")
    pc = Client(pe["ERPNEXT_URL"], pe["ERPNEXT_API_KEY"], label="prod")

    checks, fails, summary = [], [], []

    # ---------- 1. hitung + qty per doctype ----------
    print("== 1. paritas dokumen ==")
    for dt, fld, fname, _ in PLAN:
        src = jload(fname)
        if dt == "Stock Entry":
            src = [s for s in src
                   if (s.get("remarks") or "").startswith("ERESTO MAT-STE-")]
        prod = fetch_all(pc, dt, ["name", "docstatus", fld], "ERESTO%", fld)
        n_ok = len(src) == len(prod)
        qsrc = sum(len(d.get("items", [])) for d in src)
        qprd = 0
        for r in prod:
            st, d = pc.get("/api/resource/" + dt + "/" + r["name"])
            qprd += len((d.get("data") or {}).get("items", []))
        q_ok = qsrc == qprd
        checks.append((f"{dt}: dokumen {len(prod)}/{len(src)}", n_ok))
        checks.append((f"{dt}: baris item {qprd}/{qsrc}", q_ok))
        summary.append({"doctype": dt, "lama": len(src), "baru": len(prod),
                        "baris_lama": qsrc, "baris_baru": qprd,
                        "hitung_OK": "LOLOS" if n_ok else "GAGAL",
                        "baris_OK": "LOLOS" if q_ok else "GAGAL"})
        # docstatus split
        if dt == "Stock Entry":
            ds_src = Counter(d["docstatus"] for d in src)
        else:
            ds_src = Counter(d["docstatus"] for d in src)
        ds_prd = Counter(r["docstatus"] for r in prod)
        if ds_src != ds_prd:
            checks.append((f"{dt}: docstatus {dict(ds_prd)} vs {dict(ds_src)}",
                           False))
            fails.append({"cek": "docstatus", "doctype": dt,
                          "lama": dict(ds_src), "baru": dict(ds_prd)})
        else:
            checks.append((f"{dt}: docstatus sama {dict(ds_prd)}", True))

    # ---------- 2. WO parse ----------
    print("== 2. Work Order ==")
    wsrc = {w["name"]: w for w in jload("work_order.json")}
    wprd = fetch_all(pc, "Work Order", ["name", "description", "status",
                                        "produced_qty", "docstatus"],
                     "ERESTO MFG-WO-%", "description")
    ok_pair = len(wsrc) == len(wprd)
    checks.append((f"WO pasangan {len(wprd)}/{len(wsrc)}", ok_pair))
    s_prod = Counter(x["status"] for x in wprd)
    s_src = Counter(w["status"] for w in wsrc.values())
    checks.append((f"WO status {dict(s_prod)} vs {dict(s_src)}",
                   s_prod == s_src))
    prod_total = sum(float(x.get("produced_qty") or 0) for x in wprd)
    src_total = sum(float(w.get("produced_qty") or 0) for w in wsrc.values())
    checks.append((f"WO produced_qty {prod_total:g} vs {src_total:g}",
                   abs(prod_total - src_total) < 0.01))
    summary.append({"doctype": "WO-produced", "lama": round(src_total, 2),
                    "baru": round(prod_total, 2)})

    # ---------- 3. Bin parity ----------
    print("== 3. paritas Bin ==")
    lbins = {}
    for b in lc.list_all("Bin", ["item_code", "warehouse", "actual_qty"]):
        lbins[(b["item_code"], b["warehouse"])] = float(b.get("actual_qty")
                                                        or 0)
    pbins = {}
    for b in pc.list_all("Bin", ["item_code", "warehouse", "actual_qty"]):
        pbins[(b["item_code"], b["warehouse"])] = float(b.get("actual_qty")
                                                        or 0)
    keys = set(lbins) | set(pbins)
    diffs, tj = [], 0
    for k in sorted(keys):
        item, wh = k
        if any(wh.endswith(s) for s in SKIP_TJBK):
            if abs(pbins.get(k, 0)) > 0.001:
                differs = True
            tj += 1
            continue
        lq, pq = lbins.get(k, 0.0), pbins.get(k, 0.0)
        if abs(lq - pq) > 0.001:
            diffs.append({"item": item, "warehouse": wh, "lokal": round(lq, 3),
                          "prod": round(pq, 3)})
    # bin yang tidak ada di prod sama sekali tapi ada di lokal -> harus 0
    n_pairs = len([k for k in keys if not any(k[1].endswith(s)
                                              for s in SKIP_TJBK)])
    checks.append((f"Bin: {n_pairs} pasangan, {len(diffs)} selisih",
                   len(diffs) == 0))
    checks.append((f"Bin TJBK (data uji lokal) dikecualikan: {tj} pasangan",
                   True))
    for d in diffs[:200]:
        fails.append({"cek": "bin", **d})
    # total qty per warehouse (gambaran besar)
    lwh, pwh = {}, {}
    for (i, w), q in lbins.items():
        if any(w.endswith(s) for s in SKIP_TJBK):
            continue
        lwh[w] = lwh.get(w, 0) + q
    for (i, w), q in pbins.items():
        pwh[w] = pwh.get(w, 0) + q
    for w in sorted(set(lwh) | set(pwh)):
        summary.append({"doctype": "Bin " + w, "lama": round(lwh.get(w, 0), 2),
                        "baru": round(pwh.get(w, 0), 2),
                        "hitung_OK": "LOLOS" if abs(lwh.get(w, 0)
                                                    - pwh.get(w, 0)) < 1
                        else "CEK"})

    # ---------- 4. stok akhir per item (semua warehouse nonton) ----------
    print("== 4. rekap ==")
    all_ok = True
    for name, ok in checks:
        print(f"  [{'LOLOS' if ok else 'GAGAL'}] {name}")
        all_ok = all_ok and ok

    with pd.ExcelWriter("pos_sync/Injeksi_Prod.xlsx",
                        engine="openpyxl") as w:
        pd.DataFrame(summary).to_excel(w, sheet_name="Rekap", index=False)
        pd.DataFrame([{"cek": n, "hasil": "LOLOS" if ok else "GAGAL"}
                      for n, ok in checks]).to_excel(
            w, sheet_name="Validation", index=False)
        pd.DataFrame(fails).to_excel(w, sheet_name="Failed", index=False)
        for ws in w.sheets.values():
            style_sheet(ws)
    print("  Excel: pos_sync/Injeksi_Prod.xlsx")
    if not all_ok:
        sys.exit(1)
    print("VERIFIKASI OK")


if __name__ == "__main__":
    main()
