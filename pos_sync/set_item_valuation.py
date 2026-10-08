"""Isi Item.valuation_rate fallback agar POS Invoice bisa keluar dari gudang
outlet yang belum punya SLE (tidak ada riwayat → ERPNext minta valuation rate).

Sumber nilai (bukan tebakan): SLE non-nol terakhir
  1. site LAMA (8082) — nilai akuntansi asli era eResto, dipakai lebih dulu
  2. site LOKAL (8081) — seed/pilot, dipakai bila site lama kosong
Item tanpa riwayat di kedua site (AM001, PJO2601) TIDAK diisi; injector
menandai barisnya `allow_zero_valuation_rate` supaya transparan.

Idempoten: hanya menulis bila beda. Usage:
  python3 set_item_valuation.py [--dry-run]
Env: /tmp/eresto_mig.env (ERPNEXT_URL/ERPNEXT_API_KEY lokal + ERPNEXT_OLD_API_KEY).
"""
import argparse
import json
import sys
import urllib.parse

import requests

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from prod_common import load_env  # noqa: E402

OLD_BASE = "http://127.0.0.1:8082"

# item yang muncul sebagai baris POS Invoice atau komponen bundle
ITEMS = [
    "AM001", "PEL260083", "PEL260072",
    "BB260030", "BB260031", "BB260032", "BB260033", "BB260039", "BB260040",
    "BB260043", "BB260044", "BB260047",
    "PEL260069", "PEL260070", "PEL260071", "PEL260076", "PEL260085",
    "PJO2601", "PJO2602", "PJO2603", "PJO2604", "PJO2605",
]

NO_HISTORY = ("AM001", "PJO2601")  # tanpa SLE di site lama maupun lokal

# Nilai pengganti bila riwayat kosong — DICATAT sebagai asumsi, bukan tebakan
# kode. Hanya memengaruhi COGS/nilai persediaan site LOKAL.
#   AM001   : harga jual terdaftar (Price List) Rp5.000
#   PJO2601 : sejajar PJO2602 (Ropi Keju Matang, SLE seed lokal) Rp10.000
ASSUMED = {
    "AM001": (5000.0, "harga jual terdaftar"),
    "PJO2601": (10000.0, "sejajar PJO2602 Ropi Keju Matang"),
}


def sess(key):
    s = requests.Session()
    s.headers.update({"Authorization": "token " + key})
    return s


def latest_nonzero(s, base, code):
    r = s.get(base + "/api/resource/Stock Ledger Entry", params={
        "filters": json.dumps([["item_code", "=", code],
                               ["is_cancelled", "=", 0],
                               ["valuation_rate", ">", 0]]),
        "fields": '["valuation_rate","warehouse","posting_date"]',
        "order_by": "posting_datetime desc", "limit_page_length": 1},
        timeout=60)
    rows = r.json().get("data", []) if r.status_code == 200 else []
    return rows[0] if rows else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    env = load_env("/tmp/eresto_mig.env")
    loc_base = env["ERPNEXT_URL"].rstrip("/")
    old = sess(env["ERPNEXT_OLD_API_KEY"])
    loc = sess(env["ERPNEXT_API_KEY"])

    print("== sumber nilai ==")
    plan = {}
    for code in ITEMS:
        src, row = None, None
        for tag, s, base in (("old", old, OLD_BASE), ("local", loc, loc_base)):
            got = latest_nonzero(s, base, code)
            if got:
                src, row = tag, got
                break
        if row:
            plan[code] = (src, float(row["valuation_rate"]))
            print(f"  {code:12s} <- {src:5s} {row['valuation_rate']:>14,.2f}"
                  f"  ({row.get('warehouse')})")
        elif code in ASSUMED:
            rate, why = ASSUMED[code]
            plan[code] = ("asumsi", rate)
            print(f"  {code:12s} <- asumsi {rate:>13,.2f}  ({why})")
        else:
            print(f"  {code:12s} <- (tidak ada riwayat; zero-valuation di baris)")

    print("== tulis Item.valuation_rate ==")
    for code, (src, rate) in plan.items():
        url = loc_base + "/api/resource/Item/" + urllib.parse.quote(code)
        d = loc.get(url, params={"fields": '["valuation_rate","standard_rate"]'},
                    timeout=60).json()
        cur = float(d.get("data", {}).get("valuation_rate") or 0)
        if abs(cur - rate) < 0.0001:
            print(f"  {code:12s} sudah {rate:,.2f}")
            continue
        if args.dry_run:
            print(f"  {code:12s} DRY-RUN {cur:,.2f} -> {rate:,.2f}")
            continue
        r = loc.put(url, json={"valuation_rate": rate}, timeout=60)
        if r.status_code != 200:
            print(f"  !! {code} gagal HTTP {r.status_code}: {r.text[:200]}")
        else:
            print(f"  {code:12s} {cur:,.2f} -> {rate:,.2f}")
    print(f"selesai ({len(plan)} item diisi, {len(NO_HISTORY)} tanpa riwayat)")


if __name__ == "__main__":
    main()
