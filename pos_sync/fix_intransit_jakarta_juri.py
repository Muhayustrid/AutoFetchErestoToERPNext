#!/usr/bin/env python3
"""pos_sync/fix_intransit_jakarta_juri.py — Lunasi 2 SE in-transit LAMA ke Gudang Jakarta (BARU).

Latar (keputusan user 2026-10-12):
  Dua Stock Entry Material Transfer di site LAMA
    - MAT-STE-2026-09748 : Gudang Barang Jadi - ROPI -> Goods In Transit - ROPI
                           6 baris dough/krim (PJ260010..016)
    - MAT-STE-2026-09752 : Gudang Barang Jadi - ROPI -> Goods In Transit - ROPI
                           6 baris bahan baku & kemasan (BB/PEL)
  keduanya `add_to_transit = 1` dan TIDAK PERNAH di-end-transit; barangnya
  menggantung di Goods In Transit - ROPI (Rp 88,2 juta). Site BARU tidak punya
  satu pun jejaknya.

Keputusan user:
  - scope: **site BARU saja** (site LAMA tidak disentuh).
  - target: **langsung `Gudang Jakarta - JURI`** (tanpa transit; barang
    dianggap sudah receipt).
  - qty: **persis mengikuti site LAMA**, dikonversi ke UOM stok site BARU.
  - gudang asal: **`Gudang Barang Jadi - JURI`** (sesuai asal dokumen LAMA).
  - harga: **harga bawaan site BARU** (basic_rate diambil dari saldo Bin
    gudang asal di site BARU, bukan dari dokumen LAMA).

Bentuk: 1 Stock Entry `Material Transfer` per dokumen sumber, item item_code +
qty = dokumen LAMA, s_warehouse = GBJ, t_warehouse = Gudang Jakarta - JURI.

Keamanan:
  - **dry-run default** (`--execute` untuk jalan).
  - idempoten: kunci `remarks = "ERESTO <nama-dokumen-lama>"` -> cek-dulu-skip.
  - backup JSON sebelum tulis (`audit_logs/backup_intransit_jakarta_<ts>.json`).
  - guard: submit ditolak kalau uom dokumen LAMA tidak ada di master BARU.
  - `allow_negative_stock` TIDAK pernah dinyalakan (kebijakan AGENTS).
  - `--only <nama-lama>` untuk uji satu dokumen.

Pakai:
  .venv/bin/python pos_sync/fix_intransit_jakarta_juri.py            # dry-run
  .venv/bin/python pos_sync/fix_intransit_jakarta_juri.py --only MAT-STE-2026-09748 --execute
  .venv/bin/python pos_sync/fix_intransit_jakarta_juri.py --execute  # dua-duanya
  .venv/bin/python pos_sync/fix_intransit_jakarta_juri.py --verify
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env

COMPANY = "PT. JUARA ROTI INDONESIA"
OLD_BASE = "https://rotiropi.j.frappe.cloud"
SRC_WH_OLD = "Gudang Barang Jadi - ROPI"
SRC_WH_NEW = "Gudang Barang Jadi - JURI"
TGT_WH_NEW = "Gudang Jakarta - JURI"
MARKER = "ERESTO {}"
DOCS = ["MAT-STE-2026-09748", "MAT-STE-2026-09752"]
AUDIT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "audit_logs")


# ---------------------------------------------------------------- helpers
def read_old_doc(old, name):
    st, d = old.get("/api/resource/Stock Entry/" + name)
    if st != 200:
        raise SystemExit(f"LAMA: gagal ambil {name} (HTTP {st}) {str(d)[:200]}")
    return d["data"]


def item_master(new, code):
    """{uom: conversion_factor}, stock_uom — dari master site BARU."""
    st, d = new.get("/api/resource/Item/" + code)
    if st != 200:
        raise SystemExit(f"BARU: item {code} tidak ada (HTTP {st})")
    it = d["data"]
    cf = {u["uom"]: float(u["conversion_factor"]) for u in (it.get("uoms") or [])}
    cf[it["stock_uom"]] = 1.0
    return cf, it["stock_uom"]


def gbj_saldo(new, code):
    """Saldo + valuation rate gudang asal di BARU (harga bawaan site BARU)."""
    st, d = new.get("/api/resource/Bin", {
        "filters": json.dumps([["item_code", "=", code],
                               ["warehouse", "=", SRC_WH_NEW]]),
        "fields": json.dumps(["actual_qty", "valuation_rate", "stock_value",
                              "stock_uom"]),
        "limit_page_length": 1})
    rows = d.get("data", []) if st == 200 else []
    if not rows:
        return 0.0, 0.0
    r = rows[0]
    return float(r.get("actual_qty") or 0.0), float(r.get("valuation_rate") or 0.0)


def build_lines(new, old_doc):
    """Baris tujuan: item_code + qty dalam UOM dokumen LAMA (dikonversi ke UOM stok BARU)."""
    out = []
    for it in old_doc.get("items", []):
        code = it["item_code"]
        cf, stock_uom = item_master(new, code)
        old_uom = it.get("uom") or it.get("stock_uom")
        if old_uom not in cf:
            raise SystemExit(
                f"BARU: UOM '{old_uom}' tidak ada di master item {code} "
                f"(yang ada: {sorted(cf)}). Jangan menebak — hentikan.")
        qty = float(it["qty"])
        factor = cf[old_uom]
        qty_stock = qty * factor
        saldo, rate = gbj_saldo(new, code)
        out.append({
            "src_line": it.get("name"),
            "item_code": code,
            "item_name": it.get("item_name"),
            "old_uom": old_uom,
            "old_qty": qty,
            "conversion_factor": factor,
            "stock_uom": stock_uom,
            "qty": qty_stock,             # dalam UOM stok BARU
            "uom": stock_uom,
            "rate_baru": rate,            # harga bawaan site BARU
            "saldo_gbj": saldo,
            "cukup": saldo >= qty_stock,
        })
    return out


def existing(new, old_name):
    st, d = new.get("/api/resource/Stock Entry", {
        "filters": json.dumps([["company", "=", COMPANY],
                               ["remarks", "=", MARKER.format(old_name)]]),
        "fields": json.dumps(["name", "docstatus", "posting_date", "posting_time"]),
        "limit_page_length": 5})
    return d.get("data", []) if st == 200 else []


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="benar-benar tulis")
    ap.add_argument("--only", default="", help="batasi ke 1 dokumen LAMA")
    ap.add_argument("--verify", action="store_true", help="hanya laporkan status")
    args = ap.parse_args()

    mig = load_env("/tmp/eresto_mig.env")
    new = Client(mig["ERPNEXT_URL"], mig["ERPNEXT_API_KEY"], "BARU")
    old = Client(OLD_BASE, mig["ERPNEXT_OLD_CLOUD_API_KEY"], "LAMA")

    docs = [d for d in DOCS if not args.only or d == args.only]
    if not docs:
        raise SystemExit(f"--only {args.only} tidak dikenal (pilihan: {DOCS})")

    print(f"# BARU : {new.base}")
    print(f"# LAMA : {OLD_BASE}  (read-only)")
    print(f"# {SRC_WH_NEW} -> {TGT_WH_NEW}")
    print(f"# mode : {'VERIFY' if args.verify else ('EXECUTE' if args.execute else 'DRY-RUN')}")

    plan = {}
    for name in docs:
        old_doc = read_old_doc(old, name)
        lines = build_lines(new, old_doc)
        plan[name] = {
            "posting_date": old_doc["posting_date"],
            "posting_time": old_doc["posting_time"],
            "lines": lines,
        }

        print(f"\n== {name}  (LAMA {old_doc.get('posting_date')} "
              f"{old_doc.get('posting_time')}, docstatus {old_doc.get('docstatus')})")
        have = existing(new, name)
        print(f"   di BARU: {len(have)} dokumen ber-marker '{MARKER.format(name)}'"
              f" -> {[h['name'] for h in have] if have else 'BELUM ADA'}")
        print(f"   {'item':<11}{'LAMA':>10}{'uom':>6}{'x cf':>7}{'= stok BARU':>13}"
              f"{'uom':>6}{'saldo GBJ':>12}{'rate BARU':>13}  cek")
        for l in lines:
            print(f"   {l['item_code']:<11}{l['old_qty']:>10}{l['old_uom']:>6}"
                  f"{l['conversion_factor']:>7}{l['qty']:>13}{l['stock_uom']:>6}"
                  f"{l['saldo_gbj']:>12}{l['rate_baru']:>13.4f}"
                  f"  {'OK' if l['cukup'] else 'SALDO KURANG!'}")
        kurang = [l["item_code"] for l in lines if not l["cukup"]]
        if kurang:
            print(f"   !! SALDO GBJ KURANG untuk: {kurang} (submit akan "
                  f"ditolak NegativeStockError; allow_negative_stock=0)")

    if args.verify:
        print("\n# verify selesai (read-only)")
        return

    if not args.execute:
        print("\n# DRY-RUN — tidak ada yang ditulis. Tambahkan --execute untuk jalan.")
        return

    os.makedirs(AUDIT_DIR, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    bpath = os.path.join(AUDIT_DIR, f"backup_intransit_jakarta_{ts}.json")

    # backup: dokumen BARU yang akan dibuat + saldo pra
    backup = {"ts": ts, "target_warehouse": TGT_WH_NEW, "src_warehouse": SRC_WH_NEW,
              "docs": {}}
    for name in docs:
        backup["docs"][name] = {
            "old_doc": read_old_doc(old, name),
            "existing_in_new": existing(new, name),
            "pra_bin_gbj": {l["item_code"]: {"qty": l["saldo_gbj"],
                                             "rate": l["rate_baru"]}
                            for l in plan[name]["lines"]},
        }
    with open(bpath, "w") as f:
        json.dump(backup, f, indent=1, default=str)
    print(f"\n# backup -> {bpath}")

    ok = skip = fail = 0
    for name in docs:
        if existing(new, name):
            print(f"[SKIP] {name}: sudah ada di BARU (idempoten)")
            skip += 1
            continue

        p = plan[name]
        payload = {
            "doctype": "Stock Entry",
            "stock_entry_type": "Material Transfer",
            "purpose": "Material Transfer",
            "company": COMPANY,
            "posting_date": p["posting_date"],
            "posting_time": p["posting_time"],
            "set_posting_time": 1,
            "from_warehouse": SRC_WH_NEW,
            "to_warehouse": TGT_WH_NEW,
            "remarks": MARKER.format(name),
            "items": [{
                "item_code": l["item_code"],
                "qty": l["qty"],
                "uom": l["uom"],
                "stock_uom": l["stock_uom"],
                "conversion_factor": 1.0,
                "transfer_qty": l["qty"],
                "s_warehouse": SRC_WH_NEW,
                "t_warehouse": TGT_WH_NEW,
                "basic_rate": l["rate_baru"] or None,
                "set_basic_rate_manually": 1,
                "allow_zero_valuation_rate": 0 if l["rate_baru"] else 1,
            } for l in p["lines"]],
        }

        st, res = new.post("Stock Entry", payload)
        if st != 200:
            print(f"[GAGAL] insert {name}: HTTP {st} {str(res)[:300]}")
            fail += 1
            continue
        new_name = res["data"]["name"]
        st2, res2 = new.submit("Stock Entry", new_name)
        if st2 != 200:
            print(f"[GAGAL] submit {new_name} ({name}): HTTP {st2} {str(res2)[:300]}")
            fail += 1
            continue
        print(f"[OK] {name} -> {new_name} submitted "
              f"({len(p['lines'])} baris)")
        ok += 1

    print(f"\n=== SELESAI: {ok} sukses, {skip} dilewati, {fail} gagal ===")


if __name__ == "__main__":
    main()
