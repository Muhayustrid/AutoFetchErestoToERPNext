#!/usr/bin/env python3
"""pos_sync/endtransit_cloud_jakarta.py — End-transit GIT JURI -> Gudang Jakarta (CLOUD).

Konteks (audit 2026-10-12):
  Dua Stock Entry hasil migrasi 8 Okt SUDAH ada di cloud:
    SE-MTF-261009020 (GBJ -> Goods In Transit - JURI, 6 item dough)
    SE-MTF-261009021 (GBJ -> Goods In Transit - JURI, 6 item BB/PEL)
  `add_to_transit = 0` dan TIDAK ada end-transit pasangan -> barang nyangkut
  di `Goods In Transit - JURI` cloud sejak 8 Okt. Site LAMA pun sama
  (`MAT-STE-2026-09748` / `09752`).

Keputusan user:
  - End-transit di **CLOUD** saja (lokal sudah punya penanganan sendiri).
  - End-transit **12 item** kiriman; `PEL260087` (10.000 Pcs, opening 30 Sep)
    **TIDAK** diikutkan (bukan bagian kiriman 8 Okt).
  - **Gudang Barang Jadi tidak disentuh** (barang sudah keluar dari GBJ).
  - posting 8 Okt 12:00, tanpa transit lagi (langsung ke Gudang Jakarta).

Idempotensi: `remarks = "ERESTO END-TRANSIT KE JAKARTA 8 OKT"` -> cek-dulu-skip.

Pakai:
  .venv/bin/python pos_sync/endtransit_cloud_jakarta.py            # dry-run
  .venv/bin/python pos_sync/endtransit_cloud_jakarta.py --execute
  .venv/bin/python pos_sync/endtransit_cloud_jakarta.py --verify
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env

COMPANY = "PT. JUARA ROTI INDONESIA"
GIT = "Goods In Transit - JURI"
JKT = "Gudang Jakarta - JURI"
POST_DATE, POST_TIME = "2026-10-08", "12:00:00"
REMARK = "ERESTO END-TRANSIT KE JAKARTA 8 OKT"
SRC_DOCS = ["SE-MTF-261009020", "SE-MTF-261009021"]
AUDIT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "audit_logs")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()

    p = load_env("/tmp/eresto_prod.env")
    c = Client(p["ERPNEXT_URL"], p["ERPNEXT_API_KEY"], "CLOUD")
    print(f"# CLOUD: {c.base}")
    print(f"# {GIT} -> {JKT} | posting {POST_DATE} {POST_TIME}")

    # ---------- kumpulkan baris dari sumber (qty = apa yang ada di GIT)
    lines = []
    for name in SRC_DOCS:
        st, d = c.get("/api/resource/Stock Entry/" + name)
        if st != 200:
            raise SystemExit(f"gagal ambil {name}: HTTP {st}")
        doc = d["data"]
        for it in doc.get("items", []):
            lines.append({
                "src": name,
                "item_code": it["item_code"],
                "qty": float(it["qty"]),
                "uom": it.get("uom"),
                "stock_uom": it.get("stock_uom"),
                "conversion_factor": float(it.get("conversion_factor") or 1.0),
                "basic_rate": float(it.get("basic_rate") or 0.0),
            })

    # ---------- cek saldo GIT cloud (harus cukup)
    print(f"\n{'item':<11}{'src':<20}{'qty':>12}{'uom':>6}"
          f"{'saldo_GIT':>12}{'rate':>14}  cek")
    total = 0.0
    for l in lines:
        st, d = c.get("/api/resource/Bin", {
            "filters": json.dumps([["item_code", "=", l["item_code"]],
                                   ["warehouse", "=", GIT]]),
            "fields": json.dumps(["actual_qty"]), "limit_page_length": 1})
        r = d.get("data", []) if st == 200 else []
        saldo = float(r[0]["actual_qty"]) if r else 0.0
        l["saldo_git"] = saldo
        l["cukup"] = saldo >= l["qty"] - 1e-6
        total += l["qty"] * l["basic_rate"]
        print(f"{l['item_code']:<11}{l['src']:<20}{l['qty']:>12.0f}"
              f"{str(l['uom']):>6}{saldo:>12.0f}{l['basic_rate']:>14.4f}"
              f"  {'OK' if l['cukup'] else 'SALDO KURANG!'}")
    kurang = [l["item_code"] for l in lines if not l["cukup"]]
    print(f"   total nilai: Rp {total:,.2f}")
    if kurang:
        print(f"   (catatan) saldo GIT 0 untuk {kurang} — normal bila end-transit "
              f"sudah dijalankan; cek bagian VERIFIKASI untuk hasil akhir.")

    # ---------- idempotensi
    st, d = c.get("/api/resource/Stock Entry", {
        "filters": json.dumps([["company", "=", COMPANY],
                               ["remarks", "=", REMARK]]),
        "fields": json.dumps(["name", "docstatus"]), "limit_page_length": 5})
    ada = d.get("data", []) if st == 200 else []
    print(f"\n# dokumen end-transit sudah ada: {ada if ada else 'BELUM'}")

    if args.verify:
        print("\n== VERIFIKASI GIT vs JAKARTA")
        for l in lines:
            def q(wh):
                s2, d2 = c.get("/api/resource/Bin", {
                    "filters": json.dumps([["item_code", "=", l["item_code"]],
                                           ["warehouse", "=", wh]]),
                    "fields": json.dumps(["actual_qty"]), "limit_page_length": 1})
                r2 = d2.get("data", []) if s2 == 200 else []
                return float(r2[0]["actual_qty"]) if r2 else 0.0
            print(f"   {l['item_code']:<11} GIT={q(GIT):>11.0f}"
                  f"  JKT={q(JKT):>11.0f}")
        st, d = c.get("/api/resource/Bin", {
            "filters": json.dumps([["warehouse", "like", "%JURI%"],
                                   ["actual_qty", "<", 0]]),
            "fields": json.dumps(["item_code", "warehouse", "actual_qty"]),
            "limit_page_length": 0})
        neg = d.get("data", []) if st == 200 else []
        print(f"\n   Bin negatif gudang JURI: {len(neg)}")
        for r in neg[:10]:
            print(f"      {r['item_code']:<12}{r['actual_qty']:>12} {r['warehouse']}")
        return

    if not args.execute:
        print("\n# DRY-RUN — tidak ada yang ditulis. Tambah --execute.")
        return

    if ada:
        print("[SKIP] sudah ada (idempoten)")
        return

    os.makedirs(AUDIT_DIR, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    bpath = os.path.join(AUDIT_DIR, f"backup_endtransit_jakarta_{ts}.json")
    with open(bpath, "w") as f:
        json.dump({"ts": ts, "lines": lines, "src_docs": SRC_DOCS}, f,
                  indent=1, default=str)
    print(f"# backup -> {bpath}")

    payload = {
        "doctype": "Stock Entry",
        "stock_entry_type": "Material Transfer",
        "purpose": "Material Transfer",
        "company": COMPANY,
        "posting_date": POST_DATE,
        "posting_time": POST_TIME,
        "set_posting_time": 1,
        "from_warehouse": GIT,
        "to_warehouse": JKT,
        "remarks": REMARK,
        "items": [{
            "item_code": l["item_code"],
            "qty": l["qty"],
            "uom": l["uom"],
            "stock_uom": l["stock_uom"],
            "conversion_factor": l["conversion_factor"],
            "transfer_qty": l["qty"] * l["conversion_factor"],
            "s_warehouse": GIT,
            "t_warehouse": JKT,
            "basic_rate": l["basic_rate"] or None,
            "set_basic_rate_manually": 1,
            "allow_zero_valuation_rate": 0 if l["basic_rate"] else 1,
        } for l in lines],
    }
    st, d = c.post("Stock Entry", payload)
    if st != 200:
        raise SystemExit(f"[GAGAL] insert: HTTP {st} {str(d)[:400]}")
    name = d["data"]["name"]
    st2, d2 = c.submit("Stock Entry", name)
    if st2 != 200:
        raise SystemExit(f"[GAGAL] submit {name}: HTTP {st2} {str(d2)[:400]}")
    print(f"[OK] {name} submitted ({len(lines)} baris)")
    print("\n# jalankan --verify untuk cek hasil")


if __name__ == "__main__":
    main()
