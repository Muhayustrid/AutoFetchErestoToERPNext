"""Seed stok awal 4 bahan untuk kebutuhan SE historis 1-2 Okt (disetujui user).

Satu Material Receipt backdate 2026-09-30 -> Gudang Produksi - JURI,
rate = valuasi historis site lama, remarks = ERESTO-SEED-2026-10-01.
Idempoten via remarks. Setelah seed, migrasi WO+SE bisa jalan berurutan
tanpa negative stock.

Isi seed dihitung oleh analisis shortfall (lihat /tmp/seed_list.json saat
dibuat): BB260017, BB260019, BB260025, BB260055.

Usage: python3 seed_opening.py [--dry-run]
Env: ERPNEXT_URL, ERPNEXT_API_KEY (site BARU).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ERP, eresto_key  # noqa: E402


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


SEED_KEY = eresto_key("SEED-2026-10-01")

SEED_LINES = [
    # (item_code, qty, uom, basic_rate) — rate historis site lama
    ("BB260055", 273740.0, "g", 28.801486528),
    ("BB260017", 43200.0, "g", 69.643733333),
    ("BB260019", 1608.0, "Pcs", 396.0),
    ("BB260025", 1492.4, "g", 53.0),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    env = load_env()
    erp = ERP(env["ERPNEXT_URL"].rstrip("/"), env["ERPNEXT_API_KEY"])
    if erp.find_by_remark("Stock Entry", "remarks", SEED_KEY):
        print(f"seed sudah ada ({SEED_KEY}) -> stop")
        return
    payload = {
        "doctype": "Stock Entry",
        "company": "PT. JUARA ROTI INDONESIA",
        "stock_entry_type": "Material Receipt",
        "posting_date": "2026-09-30",
        "set_posting_time": 1,
        "to_warehouse": "Gudang Produksi - JURI",
        "remarks": SEED_KEY + " (stok awal migrasi site-lama 1-2 Okt)",
        "items": [
            {"item_code": c, "qty": q, "uom": u,
             "t_warehouse": "Gudang Produksi - JURI",
             "basic_rate": r, "valuation_rate": r,
             "expense_account": "5110.020 - Penyesuaian Stock - JURI",
             "cost_center": "Main - JURI"}
            for c, q, u, r in SEED_LINES
        ],
    }
    if args.dry_run:
        print("DRY-RUN seed:", json.dumps(payload)[:300])
        return
    st, d = erp.post("Stock Entry", payload)
    if st != 200:
        print(f"GAGAL POST seed: {st} {json.dumps(d)[:500]}")
        sys.exit(1)
    name = d["data"]["name"]
    st2, d2 = erp.submit("Stock Entry", name)
    if st2 != 200:
        print(f"GAGAL SUBMIT seed {name}: {st2} {json.dumps(d2)[:300]}")
        sys.exit(1)
    print(f"SEED OK: {name}")


if __name__ == "__main__":
    main()
