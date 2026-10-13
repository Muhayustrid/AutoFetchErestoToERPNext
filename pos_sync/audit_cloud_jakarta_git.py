#!/usr/bin/env python3
"""pos_sync/audit_cloud_jakarta_git.py — READ-ONLY audit CLOUD.

Menjawab: apa isi `Goods In Transit - JURI` cloud (13 item), siapa yang
mengubah Bin Jakarta/GBJ 10:47-14:05 hari ini, dan bagaimana posisi Jakarta
cloud vs LAMA sekarang. Tidak menulis apa pun.

Pakai:
  .venv/bin/python pos_sync/audit_cloud_jakarta_git.py
  .venv/bin/python pos_sync/audit_cloud_jakarta_git.py --json out.json
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env

COMPANY = "PT. JUARA ROTI INDONESIA"
OLD_BASE = "https://rotiropi.j.frappe.cloud"
GIT = "Goods In Transit - JURI"
JKT = "Gudang Jakarta - JURI"
GBJ = "Gudang Barang Jadi - JURI"
JKT_LAMA = "Gudang Jakarta - ROPI"
GIT_LAMA = "Goods In Transit - ROPI"
GBJ_LAMA = "Gudang Barang Jadi - ROPI"

# 12 item 2 SE in-transit LAMA (qty dokumen -> stok BARU)
KIRIMAN = {
    "PJ260013": 21516, "PJ260012": 16872, "PJ260014": 19968,
    "PJ260011": 1080, "PJ260010": 3000, "PJ260016": 1360,
    "BB260043": 30000, "BB260044": 21000, "BB260045": 2500,
    "PEL260006": 10, "PEL260068": 30, "PEL260077": 7500,
}


def bins(c, wh, items=None):
    f = [["warehouse", "=", wh], ["actual_qty", "!=", 0]]
    if items:
        f.append(["item_code", "in", items])
    st, d = c.get("/api/resource/Bin", {
        "filters": json.dumps(f),
        "fields": json.dumps(["item_code", "actual_qty", "stock_uom",
                              "valuation_rate", "stock_value", "modified"]),
        "limit_page_length": 0})
    return d.get("data", []) if st == 200 else []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    p = load_env("/tmp/eresto_prod.env")
    cloud = Client(p["ERPNEXT_URL"], p["ERPNEXT_API_KEY"], "CLOUD")
    mig = load_env("/tmp/eresto_mig.env")
    old = Client(OLD_BASE, mig["ERPNEXT_OLD_CLOUD_API_KEY"], "LAMA")
    print(f"# CLOUD: {cloud.base}")
    out = {}

    # 1. Isi GIT - JURI cloud
    print(f"\n=== 1. {GIT} (CLOUD) ===")
    git = bins(cloud, GIT)
    for r in git:
        print(f"   {r['item_code']:<12}{r['actual_qty']:>14} {r.get('stock_uom',''):<7}"
              f"@{r.get('valuation_rate')}  modified {r.get('modified')}")
    print(f"   total: {len(git)} item")
    out["git_cloud"] = git

    # 2. Jejak voucher yang menyentuh GIT cloud
    print(f"\n=== 2. SLE {GIT} (CLOUD) ===")
    sle = cloud.list_all(
        "Stock Ledger Entry",
        ["item_code", "posting_date", "posting_time", "actual_qty",
         "qty_after_transaction", "voucher_type", "voucher_no",
         "is_cancelled", "creation"],
        [["warehouse", "=", GIT]],
        order="posting_date asc, posting_time asc, creation asc")
    for r in sle:
        flag = "  C" if r.get("is_cancelled") else ""
        print(f"   {r['posting_date']} {str(r['posting_time'])[:8]:<9}"
              f"{r['item_code']:<12}{r['actual_qty']:>12} -> {r['qty_after_transaction']:>12}"
              f"  {r['voucher_type']:<22}{r['voucher_no']}{flag}")
    print(f"   total SLE: {len(sle)}")
    out["sle_git_cloud"] = sle

    # 3. Jakarta & GBJ cloud vs LAMA
    items = list(KIRIMAN)
    jkt = {r["item_code"]: r for r in bins(cloud, JKT, items)}
    gbj = {r["item_code"]: r for r in bins(cloud, GBJ, items)}
    gitm = {r["item_code"]: r for r in bins(cloud, GIT, items)}
    print(f"\n=== 3. Posisi cloud vs LAMA (12 item kiriman) ===")
    print(f"{'item':<11}{'JKT_CLOUD':>12}{'GBJ_CLOUD':>12}{'GIT_CLOUD':>11}"
          f"{'JKT_LAMA':>11}{'GBJ_LAMA':>11}{'GIT_LAMA':>11}{'kiriman':>10}")
    for code in items:
        def q(c, wh):
            st, d = c.get("/api/resource/Bin", {
                "filters": json.dumps([["item_code", "=", code],
                                       ["warehouse", "=", wh]]),
                "fields": json.dumps(["actual_qty"]), "limit_page_length": 1})
            r = d.get("data", []) if st == 200 else []
            return float(r[0]["actual_qty"]) if r else 0.0
        print(f"{code:<11}{q(cloud, JKT):>12.0f}{q(cloud, GBJ):>12.0f}"
              f"{q(cloud, GIT):>11.0f}{q(old, JKT_LAMA):>11.0f}"
              f"{q(old, GBJ_LAMA):>11.0f}{q(old, GIT_LAMA):>11.0f}"
              f"{KIRIMAN[code]:>10}")
    out["posisi"] = {c: {"jkt_cloud": jkt.get(c, {}).get("actual_qty"),
                         "gbj_cloud": gbj.get(c, {}).get("actual_qty"),
                         "git_cloud": gitm.get(c, {}).get("actual_qty")}
                     for c in items}

    # 4. Dokumen cloud yang menyentuh JKT/GBJ cloud (semua, urut waktu)
    print(f"\n=== 4. Dokumen cloud menyentuh {JKT} & {GBJ} (terbaru dulu) ===")
    for wh in (JKT, GBJ):
        print(f"-- {wh}")
        sle2 = cloud.list_all(
            "Stock Ledger Entry",
            ["item_code", "posting_date", "posting_time", "actual_qty",
             "voucher_type", "voucher_no", "is_cancelled"],
            [["warehouse", "=", wh]],
            order="posting_date desc, posting_time desc, creation desc")
        byv = {}
        for r in sle2:
            byv.setdefault((r["posting_date"], r["voucher_type"],
                            r["voucher_no"]), []).append(r)
        for (d, vt, vn), rs in sorted(byv.items(), reverse=True)[:25]:
            tot = sum(x["actual_qty"] for x in rs)
            print(f"   {d} {vt:<22}{vn:<26}{len(rs):>3} baris Σ{tot:>12,.0f}")
    out["sle_jkt_gbj"] = {}

    if args.json:
        with open(args.json, "w") as f:
            json.dump(out, f, indent=1, default=str)
        print(f"\n# dumped -> {args.json}")


if __name__ == "__main__":
    main()
