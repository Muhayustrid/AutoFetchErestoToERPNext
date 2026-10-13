#!/usr/bin/env python3
"""pos_sync/audit_gbj_dough_7okt.py — READ-ONLY.

Audit 6 item dough/krim (PJ260010..016) di `Gudang Barang Jadi` LAMA vs BARU.

Titik acuan: 2026-10-08 12:00:00 (saat MAT-STE-2026-09748 keluar dari GBJ
LAMA). Bandingkan saldo GBJ di titik itu (LAMA) dengan saldo GBJ BARU
sekarang, lalu cari voucher yang menjelaskan selisihnya.

Tidak menulis apa pun.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env

ITEMS = ["PJ260010", "PJ260011", "PJ260012", "PJ260013",
         "PJ260014", "PJ260016"]
# qty yang diminta 2 SE in-transit, dalam Pcs (hasil konversi UOM dokumen)
KIRIMAN = {"PJ260010": 3000, "PJ260011": 1080, "PJ260012": 16872,
           "PJ260013": 21516, "PJ260014": 19968, "PJ260016": 1360}
GBJ_OLD = "Gudang Barang Jadi - ROPI"
GBJ_NEW = "Gudang Barang Jadi - JURI"
CUTOFF = "2026-10-08 12:00:00"
CUTOFF_D = "2026-10-08"
CUTOFF_T = "12:00:00"


def saldo_saat(c, wh, item, cutoff_d, cutoff_t):
    """qty_after_transaction baris SLE terakhir <= cutoff."""
    sle = c.list_all(
        "Stock Ledger Entry",
        ["posting_date", "posting_time", "qty_after_transaction"],
        [["item_code", "=", item], ["warehouse", "=", wh],
         ["posting_date", "<=", cutoff_d]],
        order="posting_date desc, posting_time desc, creation desc")
    for r in sle:
        if r["posting_date"] < cutoff_d or str(r["posting_time"]) <= cutoff_t:
            return float(r["qty_after_transaction"])
    return 0.0


def saldo_now(c, wh, item):
    st, d = c.get("/api/resource/Bin", {
        "filters": json.dumps([["item_code", "=", item],
                               ["warehouse", "=", wh]]),
        "fields": json.dumps(["actual_qty", "valuation_rate"]),
        "limit_page_length": 1})
    rows = d.get("data", []) if st == 200 else []
    return (float(rows[0]["actual_qty"]), float(rows[0].get("valuation_rate") or 0)
            ) if rows else (0.0, 0.0)


def main():
    mig = load_env("/tmp/eresto_mig.env")
    old = Client("https://rotiropi.j.frappe.cloud",
                 mig["ERPNEXT_OLD_CLOUD_API_KEY"], "LAMA")
    new = Client(mig["ERPNEXT_URL"], mig["ERPNEXT_API_KEY"], "BARU")

    print(f"# GBJ LAMA={GBJ_OLD}  GBJ BARU={GBJ_NEW}  cutoff={CUTOFF}")
    print(f"\n{'item':<11}{'GBJ_LAMA@12:00':>16}{'GBJ_BARU_now':>14}"
          f"{'selisih':>10}{'kiriman':>10}{'cukup?':>9}")
    rows = []
    for it in ITEMS:
        lama = saldo_saat(old, GBJ_OLD, it, CUTOFF_D, CUTOFF_T)
        baru, rate = saldo_now(new, GBJ_NEW, it)
        selisih = baru - lama
        cukup = "OK" if baru >= KIRIMAN[it] else f"KURANG {KIRIMAN[it]-baru:.0f}"
        rows.append((it, lama, baru, selisih, rate, cukup))
        print(f"{it:<11}{lama:>16.0f}{baru:>14.0f}{selisih:>10.0f}"
              f"{KIRIMAN[it]:>10}{cukup:>9}")

    print("\n# detail: dokumen yang menyentuh GBJ BARU (barang masuk/keluar)")
    for it, *_ in rows:
        sle = new.list_all(
            "Stock Ledger Entry",
            ["posting_date", "posting_time", "actual_qty",
             "qty_after_transaction", "voucher_type", "voucher_no",
             "incoming_rate", "is_cancelled"],
            [["item_code", "=", it], ["warehouse", "=", GBJ_NEW]],
            order="posting_date asc, posting_time asc, creation asc")
        print(f"\n== {it} ({len(sle)} baris GBJ BARU)")
        for r in sle:
            flag = "  C" if r.get("is_cancelled") else ""
            print(f"   {r['posting_date']} {str(r['posting_time'])[:11]:<12}"
                  f"{r['actual_qty']:>10} -> {r['qty_after_transaction']:>10}"
                  f"  {r['voucher_type']:<22}{r['voucher_no']:<24}"
                  f"@{r.get('incoming_rate')}{flag}")

    print("\n# voucher penyuplai ke GBJ LAMA 8 Okt (Manufacture pemulihan)")
    for it, *_ in rows:
        sle = old.list_all(
            "Stock Ledger Entry",
            ["posting_date", "posting_time", "actual_qty",
             "qty_after_transaction", "voucher_type", "voucher_no", "warehouse"],
            [["item_code", "=", it],
             ["posting_date", "in", ["2026-10-08", "2026-10-09"]],
             ["warehouse", "=", GBJ_OLD]],
            order="posting_date asc, posting_time asc")
        masuk = [r for r in sle if r["actual_qty"] > 0]
        keluar = [r for r in sle if r["actual_qty"] < 0]
        print(f"   {it:<11} masuk {len(masuk):>2} dok (+{sum(r['actual_qty'] for r in masuk):>8.0f})"
              f"  keluar {len(keluar):>2} dok ({sum(r['actual_qty'] for r in keluar):>8.0f})")


if __name__ == "__main__":
    main()
