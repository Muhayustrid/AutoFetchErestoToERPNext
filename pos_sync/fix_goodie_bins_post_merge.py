#!/usr/bin/env python3
"""pos_sync/fix_goodie_bins_post_merge.py — koreksi Bin PEL260072 pasca-merge PG001.

Masalah: merge item (rename_doc merge=1) menggabungkan 2 stream SLE, tetapi 2
Stock Reconciliation *absolute* (opening PG001 vs opening PEL260072) saling
menimpa saat repost -> 2 gudang meleset:
  GBJ  : harusnya 18052+25165=43217 -> jadi 16492
  RPMD : harusnya -2+73=71          -> jadi -2
(TRNG 75, Jakarta 6194, Mini 40 sudah benar.)

Fix: 1 Stock Reconciliation korektif (absolute) di posting hari ini utk
gudang yang meleset, nilai = target (jumlah saldo pra-merge dari backup
audit_logs/backup_merge_goodie_*.json). Rate GBJ = gabungan nilai pra-merge
(1369.34 & 1368) = 1368.78; RPMD = 1900.

DEFAULT DRY-RUN. Jalankan: python pos_sync/fix_goodie_bins_post_merge.py --execute
"""
import argparse
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env

ITEM = "PEL260072"
JURI = "PT. JUARA ROTI INDONESIA"
RATES = {
    "Gudang Barang Jadi - JURI": 1368.78,  # blended (25165*1369.34 + 18052*1368)/43217
    "Stores - RPMD": 1900.0,
}


def latest_backup():
    pat = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                       "audit_logs", "backup_merge_goodie_*.json")
    files = sorted(glob.glob(pat))
    if not files:
        raise SystemExit("STOP: backup merge tidak ditemukan")
    return files[-1]


def bins_of(c, item):
    rows = c.list_all("Bin", ["warehouse", "actual_qty"],
                      filters=[["item_code", "=", item]])
    return {r["warehouse"]: float(r["actual_qty"]) for r in rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--backup", default=None)
    args = ap.parse_args()

    prod = load_env("/tmp/eresto_prod.env")
    c = Client(prod["ERPNEXT_URL"], prod["ERPNEXT_API_KEY"], "BARU")

    bpath = args.backup or latest_backup()
    with open(bpath) as f:
        backup = json.load(f)
    old_bins, new_bins = backup["bins_old"], backup["bins_new"]
    targets = {}
    for wh in set(old_bins) | set(new_bins):
        targets[wh] = round(float(old_bins.get(wh, 0.0)) + float(new_bins.get(wh, 0.0)), 3)
    print(f"== SOURCE: {os.path.basename(bpath)} ==")
    print(f"  target gabungan: { {k: v for k, v in targets.items() if v} }")

    current = bins_of(c, ITEM)
    diffs = {}
    for wh, tgt in targets.items():
        cur = round(current.get(wh, 0.0), 3)
        if abs(cur - tgt) > 0.001:
            diffs[wh] = (cur, tgt)
    print(f"  sekarang: { {k: v for k, v in current.items() if v} }")
    print(f"  DIFF: {diffs or 'TIDAK ADA (semua sudah benar)'}")

    if not diffs:
        print("[SKIP] Semua Bin sudah sesuai target.")
        return
    if not args.execute:
        print("\n[DRY-RUN] Jalankan ulang dengan --execute.")
        return

    items = [{"item_code": ITEM, "warehouse": wh, "qty": tgt,
              "valuation_rate": RATES.get(wh)}
             for wh, (cur, tgt) in diffs.items()]
    if any(it["valuation_rate"] is None for it in items):
        raise SystemExit("STOP: rate utk salah satu gudang belum didefinisikan")

    # RECO per company (warehouse validation: wh harus milik company RECO)
    import urllib.parse
    wh_company = {}
    for it in items:
        st, d = c.get("/api/resource/Warehouse/" + urllib.parse.quote(it["warehouse"]))
        if st != 200:
            raise SystemExit(f"GAGAL ambil Warehouse {it['warehouse']}: HTTP {st}")
        wh_company[it["warehouse"]] = d["data"]["company"]
    groups = {}
    for it in items:
        groups.setdefault(wh_company[it["warehouse"]], []).append(it)

    recos = []
    REMARK = "Koreksi pasca-merge Goodie Bag PG001->PEL260072 (RECO absolute saling timpa)"
    for company, rows in groups.items():
        # reuse draft yang sudah ada (idempoten; mis. sisa kegagalan sebelumnya)
        st, d = c.get("/api/resource/Stock Reconciliation", {
            "filters": json.dumps([["company", "=", company],
                                   ["docstatus", "=", 0],
                                   ["remarks", "=", REMARK]]),
            "fields": json.dumps(["name"]), "limit_page_length": 1})
        existing = (d.get("data") or [None])[0]
        if existing:
            name = existing["name"]
            print(f"  [draft] reuse {name} ({company})")
            st, d = c.put("Stock Reconciliation", name, {
                "purpose": "Stock Reconciliation", "items": rows})
            if st != 200:
                raise SystemExit(f"GAGAL lengkapi draft {name}: HTTP {st} {str(d)[:300]}")
        else:
            payload = {
                "doctype": "Stock Reconciliation",
                "company": company,
                "purpose": "Stock Reconciliation",
                "posting_date": "2026-10-09",
                "posting_time": "19:45:00",
                "set_posting_time": 1,
                "remarks": REMARK,
                "items": rows,
            }
            st, d = c.post("Stock Reconciliation", payload)
            if st not in (200, 201):
                raise SystemExit(f"GAGAL buat RECO {company}: HTTP {st} {str(d)[:400]}")
            name = d["data"]["name"]
        st, d = c.submit("Stock Reconciliation", name)
        print(f"[{'OK' if st == 200 else 'FAIL'}] RECO {name} ({company}) rows={rows}: submit HTTP {st}")
        if st != 200:
            raise SystemExit(f"STOP: submit RECO {name} gagal: {str(d)[:300]}")
        recos.append(name)

    # ---------- verifikasi ----------
    print("\n== VERIFIKASI ==")
    ok = False
    for attempt in range(12):
        time.sleep(5)
        cur = bins_of(c, ITEM)
        left = {wh: (round(cur.get(wh, 0.0), 3), tgt) for wh, (_, tgt) in diffs.items()
                if abs(round(cur.get(wh, 0.0), 3) - tgt) > 0.001}
        if not left:
            ok = True
            break
        print(f"  [{attempt+1}] belum sinkron: {left}")
    print(f"  [{'LOLOS' if ok else 'GAGAL'}] Bin = target")
    cur = bins_of(c, ITEM)
    print(f"  Bin {ITEM}: { {k: v for k, v in cur.items() if v} }")

    st, d = c.get("/api/method/frappe.client.get_count", {
        "doctype": "Bin", "filters": json.dumps([["actual_qty", "<", 0]])})
    print(f"  [INFO] Bin negatif se-sistem: {d.get('message', '?')}")

    # ---------- laporan ----------
    try:
        import pandas as pd
        rows = [{"warehouse": wh, "before": cur_, "target": tgt, "delta": tgt - cur_}
                for wh, (cur_, tgt) in diffs.items()]
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "Laporan_Fix_Goodie_Bins.xlsx")
        with pd.ExcelWriter(out, engine="openpyxl") as xw:
            pd.DataFrame([{"reco": ", ".join(recos), "posting": "2026-10-09 19:45",
                           "status": "LOLOS" if ok else "PERIKSA"}]).to_excel(
                xw, sheet_name="Ringkasan", index=False)
            pd.DataFrame(rows).to_excel(xw, sheet_name="Koreksi", index=False)
            pd.DataFrame([{"warehouse": k, "qty": v} for k, v in cur.items() if v]).to_excel(
                xw, sheet_name="Bin_Akhir", index=False)
        print(f"  [OK] Laporan -> {out}")
    except Exception as e:  # noqa: BLE001
        print(f"  [WARN] excel: {e}")


if __name__ == "__main__":
    main()
