#!/usr/bin/env python3
"""pos_sync/cek_skenario_balik_gbj.py — READ-ONLY.

Menjawab pertanyaan user: "misal dari goodintransit dibalikin ke gudang
barang jadi apakah tetap minus?"

Dua skenario:
  A. "Balik dari transit": asumsi barang BARU masuk GIT dulu (sebanyak
     kiriman LAMA), lalu dipindah GIT -> GBJ. Uji: apakah GBJ tetap minus?
     (Jawab: tidak minus, karena GIT = +kiriman.)
  B. Realistis: kalau barang dipindah dari GBJ -> GIT -> JKT berurutan,
     kebutuhan GBJ = 2x kiriman -> GBJ minus jauh.

Cek juga: apakah ada stok di GIT - JURI di BARU (target 'dibalikin').
Read-only; tidak menulis apa pun.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env

GBJ = "Gudang Barang Jadi - JURI"
GIT = "Goods In Transit - JURI"
JKT = "Gudang Jakarta - JURI"
COMPANY = "PT. JUARA ROTI INDONESIA"

# item: qty kiriman (stok BARU) per dokumen
KIRIMAN = {
    "MAT-STE-2026-09748": {
        "PJ260013": 21516, "PJ260012": 16872, "PJ260014": 19968,
        "PJ260011": 1080, "PJ260010": 3000, "PJ260016": 1360,
    },
    "MAT-STE-2026-09752": {
        "BB260043": 30000, "BB260044": 21000, "BB260045": 2500,
        "PEL260006": 10, "PEL260068": 30, "PEL260077": 7500,
    },
}


def bin_qty(c, wh, item):
    st, d = c.get("/api/resource/Bin", {
        "filters": json.dumps([["item_code", "=", item],
                               ["warehouse", "=", wh]]),
        "fields": json.dumps(["actual_qty"]), "limit_page_length": 1})
    rows = d.get("data", []) if st == 200 else []
    return float(rows[0]["actual_qty"]) if rows else 0.0


def sum_bin_wh(c, wh, item):
    return bin_qty(c, wh, item)


def main():
    mig = load_env("/tmp/eresto_mig.env")
    new = Client(mig["ERPNEXT_URL"], mig["ERPNEXT_API_KEY"], "BARU")
    old = Client("https://rotiropi.j.frappe.cloud",
                 mig["ERPNEXT_OLD_CLOUD_API_KEY"], "LAMA")

    print(f"# BARU {new.base}")
    for name, items in KIRIMAN.items():
        print(f"\n===== skenario dari {name} =====")
        print(f"{'item':<11}{'GBJ_now':>11}{'GIT_now':>10}{'JKT_now':>10}"
              f"{'kiriman':>10}"
              f"{'A:GBJ+GIT':>11}{'B:GBJ-2x':>11}")
        for it, q in items.items():
            gbj = bin_qty(new, GBJ, it)
            git = bin_qty(new, GIT, it)
            jkt = bin_qty(new, JKT, it)
            # Skenario A: masuk GIT dulu (+q), lalu GIT -> GBJ (+q). GBJ = asal
            # Skenario B: GBJ -q (ke GIT) lalu -q lagi (GIT->JKT) = GBJ - 2q
            print(f"{it:<11}{gbj:>11.0f}{git:>10.0f}{jkt:>10.0f}{q:>10.0f}"
                  f"{(gbj + git):>11.0f}{(gbj - 2*q):>11.0f}")

    print("\n# Skenario 'balik dari transit' (A): barang diasumsikan SUDAH di GIT")
    print("#   GBJ akhir = GBJ_now + q  (GIT punya q, dipindah ke GBJ)  -> cek minus")
    print("# Skenario 'lewat transit' (B): GBJ -> GIT -> JKT, GBJ keluar 2x q")
    print("#\n# Catatan: di BARU, GIT - JURI = 0 untuk semua item (sudah diaudit),")
    print("# jadi skenario A hanya masuk akal kalau barang GIT diisi dulu.")
    print("\n# Pembanding LAMA: saldo Goods In Transit - ROPI (= yang menggantung)")
    for name, items in KIRIMAN.items():
        print(f"  -- {name}")
        for it, q in items.items():
            git_old = bin_qty(old, "Goods In Transit - ROPI", it)
            gbj_old = bin_qty(old, "Gudang Barang Jadi - ROPI", it)
            print(f"     {it:<11} GIT_LAMA={git_old:>10.0f}  GBJ_LAMA={gbj_old:>10.0f}")


if __name__ == "__main__":
    main()
