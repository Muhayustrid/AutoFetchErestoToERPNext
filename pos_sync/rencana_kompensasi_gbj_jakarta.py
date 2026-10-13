#!/usr/bin/env python3
"""pos_sync/rencana_kompensasi_gbj_jakarta.py — READ-ONLY (dry-run).

Rencana (keputusan user 2026-10-12):
  1. Kompensasi masuk ke `Gudang Barang Jadi - JURI`: 12 item dari 2 SE
     in-transit LAMA (`MAT-STE-2026-09748` + `MAT-STE-2026-09752`),
     qty persis dokumen LAMA dikonversi ke UOM stok BARU.
     -> Material Receipt (akun penyesuaian 5110.020 - Penyesuaian Stock).
  2. Material Transfer `Gudang Barang Jadi - JURI` -> `Gudang Jakarta - JURI`,
     qty sama, langsung tanpa transit.

Script ini hanya menghitung & menampilkan, TIDAK menulis apa pun.
Semua angka diambil dari site BARU (read-only) + dokumen LAMA (read-only).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env

COMPANY = "PT. JUARA ROTI INDONESIA"
OLD_BASE = "https://rotiropi.j.frappe.cloud"
GBJ = "Gudang Barang Jadi - JURI"
JKT = "Gudang Jakarta - JURI"
DOCS = ["MAT-STE-2026-09748", "MAT-STE-2026-09752"]


def item_uom(new, code):
    st, d = new.get("/api/resource/Item/" + code)
    if st != 200:
        raise SystemExit(f"item {code} tidak ada di BARU (HTTP {st})")
    it = d["data"]
    cf = {u["uom"]: float(u["conversion_factor"]) for u in (it.get("uoms") or [])}
    cf[it["stock_uom"]] = 1.0
    return cf, it["stock_uom"]


def bin_of(c, wh, code):
    st, d = c.get("/api/resource/Bin", {
        "filters": json.dumps([["item_code", "=", code], ["warehouse", "=", wh]]),
        "fields": json.dumps(["actual_qty", "valuation_rate"]),
        "limit_page_length": 1})
    rows = d.get("data", []) if st == 200 else []
    return (float(rows[0]["actual_qty"]), float(rows[0].get("valuation_rate") or 0)
            ) if rows else (0.0, 0.0)


def main():
    mig = load_env("/tmp/eresto_mig.env")
    new = Client(mig["ERPNEXT_URL"], mig["ERPNEXT_API_KEY"], "BARU")
    old = Client(OLD_BASE, mig["ERPNEXT_OLD_CLOUD_API_KEY"], "LAMA")

    print("# site BARU:", new.base, "| site LAMA (read-only):", OLD_BASE)
    print("# GBJ =", GBJ, "-> JKT =", JKT)

    tot_kiriman_nilai = 0.0
    print(f"\n{'item':<11}{'dok':>7}{'qty_LAMA':>10}{'uom':>6}{'x cf':>7}"
          f"{'= stok':>10}{'uom':>5}{'GBJ_now':>10}{'rate':>13}"
          f"{'nilai':>16}{'GBJ+sisa':>10}")
    for name in DOCS:
        st, d = old.get("/api/resource/Stock Entry/" + name)
        if st != 200:
            raise SystemExit(f"LAMA {name} HTTP {st}")
        for it in d["data"].get("items", []):
            code, q = it["item_code"], float(it["qty"])
            old_uom = it.get("uom") or it.get("stock_uom")
            cf, stock_uom = item_uom(new, code)
            factor = cf.get(old_uom) or cf.get(old_uom.lower())
            if factor is None:
                raise SystemExit(f"{code}: UOM '{old_uom}' tak ada di BARU {sorted(cf)}")
            qty = q * factor
            gbj, rate = bin_of(new, GBJ, code)
            nilai = qty * rate
            tot_kiriman_nilai += nilai
            print(f"{code:<11}{name[-5:]:>7}{q:>10.0f}{old_uom:>6}{factor:>7.0f}"
                  f"{qty:>10.0f}{stock_uom:>5}{gbj:>10.0f}{rate:>13.4f}"
                  f"{nilai:>16.2f}{gbj:>10.0f}")

    print(f"\n# total nilai kiriman (rate BARU): Rp {tot_kiriman_nilai:,.2f}")
    print("\n# CATATAN: kolom 'GBJ+sisa' = saldo GBJ sekarang (tanpa kompensasi).")
    print("#   GBJ akan naik +qty oleh kompensasi, lalu keluar -qty oleh transfer,")
    print("#   jadi saldo GBJ akhir = saldo sekarang (netral). TIDAK ada minus.")
    print("#   Cek: transfer hanya butuh qty, dan setelah kompensasi GBJ >= qty.")


if __name__ == "__main__":
    main()
