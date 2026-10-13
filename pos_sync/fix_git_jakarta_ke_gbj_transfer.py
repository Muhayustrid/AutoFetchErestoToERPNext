#!/usr/bin/env python3
"""pos_sync/fix_git_jakarta_ke_gbj_transfer.py — Perbaikan stok Goods In Transit JURI.

Latar & keputusan user (2026-10-12):
  Stok yang "nangkring" di Goods In Transit site LAMA (12 item dari 2 SE
  Material Transfer 8 Okt: MAT-STE-2026-09748 & MAT-STE-2026-09752) itu
  sebenarnya alokasi/transferan dari Gudang Barang Jadi. Keputusan user:
  di site BARU, alokasi itu "dibalikin" ke Gudang Barang Jadi lalu dikirim
  LANGSUNG ke Gudang Jakarta (tanpa transit), dengan kejadian 8-9 Okt.

  Site BARU tidak punya objek GIT maupun transferannya (ledger GBJ/Jakarta
  bahkan berhenti 2-5 Okt), jadi bentuknya:
    1. Stock Reconciliation (purpose "Stock Reconciliation", akun
       5110.020 - Penyesuaian Stock) di `Gudang Barang Jadi - JURI`,
       posting 2026-10-08 09:00, qty ABSOLUT = saldo saat itu + qty kiriman,
       untuk 12 item. -> setara "transferan 8 Okt dikembalikan ke GBJ".
    2. Stock Entry Material Transfer `Gudang Barang Jadi - JURI` ->
       `Gudang Jakarta - JURI`, posting 2026-10-08 12:00, qty = qty kiriman.
  Hasil: GBJ netral (naik lalu keluar), Jakarta +kiriman, GIT tetap 0,
  TIDAK ada minus (allow_negative_stock tetap 0).

Idempotensi:
  - RECO   : kunci marker `remark = "ERESTO-GBJ-ALOKASI-8OKT"`.
  - Transfer: kunci `remarks = "ERESTO ALOKASI 8 OKT -> JAKARTA"`.

Pakai:
  .venv/bin/python pos_sync/fix_git_jakarta_ke_gbj_transfer.py --plan
  .venv/bin/python pos_sync/fix_git_jakarta_ke_gbj_transfer.py --reco  --execute
  .venv/bin/python pos_sync/fix_git_jakarta_ke_gbj_transfer.py --transfer --execute
  .venv/bin/python pos_sync/fix_git_jakarta_ke_gbj_transfer.py --verify
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
GBJ = "Gudang Barang Jadi - JURI"
JKT = "Gudang Jakarta - JURI"
GIT = "Goods In Transit - JURI"
ADJ_ACCOUNT = "5110.020 - Penyesuaian Stock - JURI"
RECO_DATE, RECO_TIME = "2026-10-08", "09:00:00"
TRF_DATE, TRF_TIME = "2026-10-08", "12:00:00"
RECO_REMARK = "ERESTO-GBJ-ALOKASI-8OKT"
TRF_REMARK = "ERESTO ALOKASI 8 OKT -> JAKARTA"
DOCS = ["MAT-STE-2026-09748", "MAT-STE-2026-09752"]
AUDIT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "audit_logs")


# ------------------------------------------------------------------ data
def load_kiriman(new, old):
    """12 baris kiriman: item, qty dalam UOM stok BARU, uom, qty dokumen LAMA."""
    out = []
    for name in DOCS:
        st, d = old.get("/api/resource/Stock Entry/" + name)
        if st != 200:
            raise SystemExit(f"LAMA: {name} HTTP {st}")
        for it in d["data"].get("items", []):
            code = it["item_code"]
            st2, d2 = new.get("/api/resource/Item/" + code)
            if st2 != 200:
                raise SystemExit(f"BARU: item {code} tidak ada (HTTP {st2})")
            master = d2["data"]
            cf = {u["uom"]: float(u["conversion_factor"])
                  for u in (master.get("uoms") or [])}
            cf[master["stock_uom"]] = 1.0
            old_uom = it.get("uom") or it.get("stock_uom")
            factor = cf.get(old_uom) or cf.get(str(old_uom).lower())
            if factor is None:
                raise SystemExit(f"{code}: UOM '{old_uom}' tidak ada di BARU "
                                 f"{sorted(cf)} — jangan menebak")
            out.append({
                "src_doc": name,
                "item_code": code,
                "old_uom": old_uom,
                "old_qty": float(it["qty"]),
                "factor": factor,
                "qty": float(it["qty"]) * factor,   # qty stok BARU
                "stock_uom": master["stock_uom"],
            })
    return out


def bin_now(new, wh, code):
    st, d = new.get("/api/resource/Bin", {
        "filters": json.dumps([["item_code", "=", code], ["warehouse", "=", wh]]),
        "fields": json.dumps(["actual_qty", "valuation_rate"]),
        "limit_page_length": 1})
    rows = d.get("data", []) if st == 200 else []
    return (float(rows[0]["actual_qty"]), float(rows[0].get("valuation_rate") or 0)
            ) if rows else (0.0, 0.0)


def find_reco(new):
    st, d = new.get("/api/resource/Stock Reconciliation", {
        "filters": json.dumps([["company", "=", COMPANY],
                               ["remark", "=", RECO_REMARK]]),
        "fields": json.dumps(["name", "docstatus", "posting_date", "posting_time"]),
        "limit_page_length": 5})
    return d.get("data", []) if st == 200 else []


def find_trf(new):
    st, d = new.get("/api/resource/Stock Entry", {
        "filters": json.dumps([["company", "=", COMPANY],
                               ["remarks", "=", TRF_REMARK]]),
        "fields": json.dumps(["name", "docstatus"]),
        "limit_page_length": 5})
    return d.get("data", []) if st == 200 else []


# ------------------------------------------------------------------ plan
def build_plan(new, old):
    kiriman = load_kiriman(new, old)
    plan = []
    for k in kiriman:
        saldo, rate = bin_now(new, GBJ, k["item_code"])
        plan.append(dict(k, saldo_gbj=saldo, rate=rate,
                         reco_qty=saldo + k["qty"],          # qty ABSOLUT RECO
                         kurang=k["qty"] - saldo))
    return plan


def show(plan, title):
    print(f"\n== {title}")
    print(f"{'item':<11}{'asal_dok':>10}{'qty_LAMA':>10}{'uom':>6}{'= stok':>10}"
          f"{'uom':>5}{'saldo_GBJ':>11}{'RECO_set':>11}{'rate':>12}"
          f"{'nilai':>15}{'cek':>7}")
    for p in plan:
        cek = "OK" if p["reco_qty"] >= p["qty"] else "??"
        print(f"{p['item_code']:<11}{p['src_doc'][-5:]:>10}{p['old_qty']:>10.0f}"
              f"{p['old_uom']:>6}{p['qty']:>10.0f}{p['stock_uom']:>5}"
              f"{p['saldo_gbj']:>11.0f}{p['reco_qty']:>11.0f}{p['rate']:>12.4f}"
              f"{p['qty'] * p['rate']:>15.2f}{cek:>7}")
    tot = sum(p["qty"] * p["rate"] for p in plan)
    print(f"   total nilai kiriman: Rp {tot:,.2f}")


# ------------------------------------------------------------------ exec
def do_reco(new, plan):
    have = find_reco(new)
    if have:
        print(f"[SKIP] RECO sudah ada: {[h['name'] for h in have]}")
        return 0, 0

    payload = {
        "doctype": "Stock Reconciliation",
        "company": COMPANY,
        "purpose": "Stock Reconciliation",
        "posting_date": RECO_DATE,
        "posting_time": RECO_TIME,
        "set_posting_time": 1,
        "expense_account": ADJ_ACCOUNT,
        "cost_center": "Main - JURI",
        "remark": RECO_REMARK,
        "items": [{
            "item_code": p["item_code"],
            "warehouse": GBJ,
            "qty": p["reco_qty"],                  # ABSOLUT
            "uom": p["stock_uom"],
            "stock_uom": p["stock_uom"],
            "conversion_factor": 1.0,
            "valuation_rate": p["rate"] or None,
        } for p in plan],
    }
    st, res = new.post("Stock Reconciliation", payload)
    if st != 200:
        print(f"[GAGAL] insert RECO: HTTP {st} {str(res)[:400]}")
        return 0, 1
    name = res["data"]["name"]
    st2, res2 = new.submit("Stock Reconciliation", name)
    if st2 != 200:
        print(f"[GAGAL] submit RECO {name}: HTTP {st2} {str(res2)[:400]}")
        return 0, 1
    print(f"[OK] RECO {name} submitted ({len(plan)} baris, posting "
          f"{RECO_DATE} {RECO_TIME})")
    return 1, 0


def do_trf(new, plan):
    have = find_trf(new)
    if have:
        print(f"[SKIP] transfer sudah ada: {[h['name'] for h in have]}")
        return 0, 0

    payload = {
        "doctype": "Stock Entry",
        "stock_entry_type": "Material Transfer",
        "purpose": "Material Transfer",
        "company": COMPANY,
        "posting_date": TRF_DATE,
        "posting_time": TRF_TIME,
        "set_posting_time": 1,
        "from_warehouse": GBJ,
        "to_warehouse": JKT,
        "remarks": TRF_REMARK,
        "items": [{
            "item_code": p["item_code"],
            "qty": p["qty"],                       # dalam UOM stok
            "uom": p["stock_uom"],
            "stock_uom": p["stock_uom"],
            "conversion_factor": 1.0,
            "transfer_qty": p["qty"],
            "s_warehouse": GBJ,
            "t_warehouse": JKT,
            "basic_rate": p["rate"] or None,
            "set_basic_rate_manually": 1,
            "allow_zero_valuation_rate": 0 if p["rate"] else 1,
        } for p in plan],
    }
    st, res = new.post("Stock Entry", payload)
    if st != 200:
        print(f"[GAGAL] insert transfer: HTTP {st} {str(res)[:400]}")
        return 0, 1
    name = res["data"]["name"]
    st2, res2 = new.submit("Stock Entry", name)
    if st2 != 200:
        print(f"[GAGAL] submit transfer {name}: HTTP {st2} {str(res2)[:400]}")
        return 0, 1
    print(f"[OK] transfer {name} submitted ({len(plan)} baris, posting "
          f"{TRF_DATE} {TRF_TIME})")
    return 1, 0


def do_verify(new, plan):
    print("\n== VERIFIKASI")
    ok = True
    for p in plan:
        gbj, _ = bin_now(new, GBJ, p["item_code"])
        jkt, _ = bin_now(new, JKT, p["item_code"])
        git, _ = bin_now(new, GIT, p["item_code"])
        flag = "OK" if gbj >= 0 and git == 0 else "PERIKSA"
        if git != 0:
            ok = False
        print(f"   {p['item_code']:<11} GBJ={gbj:>11.0f}  JKT={jkt:>11.0f}"
              f"  GIT={git:>8.0f}  {flag}")
    # cek Bin negatif gudang JURI saja (company PT. JURI)
    st, d = new.get("/api/resource/Bin", {
        "filters": json.dumps([["actual_qty", "<", 0],
                               ["warehouse", "like", "%JURI%"]]),
        "fields": json.dumps(["warehouse", "item_code", "actual_qty"]),
        "limit_page_length": 0})
    neg = d.get("data", []) if st == 200 else []
    print(f"\n   Bin negatif gudang JURI: {len(neg)}")
    for r in neg[:20]:
        print(f"      {r['item_code']:<12}{r['actual_qty']:>12} {r['warehouse']}")
    st, d = new.get("/api/method/frappe.client.get_value",
                    {"doctype": "Stock Settings",
                     "fieldname": "allow_negative_stock"})
    if st == 200:
        print(f"   allow_negative_stock = {d.get('message')}")
    return ok and not neg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="tampilkan rencana saja")
    ap.add_argument("--reco", action="store_true", help="buat+submit RECO GBJ")
    ap.add_argument("--transfer", action="store_true", help="buat+submit transfer")
    ap.add_argument("--verify", action="store_true", help="verifikasi hasil")
    ap.add_argument("--execute", action="store_true", help="benar-benar tulis")
    args = ap.parse_args()

    mig = load_env("/tmp/eresto_mig.env")
    new = Client(mig["ERPNEXT_URL"], mig["ERPNEXT_API_KEY"], "BARU")
    old = Client(OLD_BASE, mig["ERPNEXT_OLD_CLOUD_API_KEY"], "LAMA")

    print(f"# BARU: {new.base} | LAMA (read-only): {OLD_BASE}")
    plan = build_plan(new, old)
    show(plan, "RENCANA: RECO GBJ (absolut = saldo + kiriman) -> Transfer GBJ ke Jakarta")

    if args.verify:
        ok = do_verify(new, plan)
        print(f"\n# VERIFY {'LOLOS' if ok else 'ADA TEMUAN'}")
        return

    if not (args.reco or args.transfer):
        if not args.plan:
            print("\n# (dry-run) pilih --reco atau --transfer; tambah --execute "
                  "untuk menulis.")
        return

    if not args.execute:
        print("\n# DRY-RUN — tidak ada yang ditulis. Tambah --execute.")
        return

    os.makedirs(AUDIT_DIR, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    bpath = os.path.join(AUDIT_DIR, f"backup_git_jakarta_fix_{ts}.json")
    with open(bpath, "w") as f:
        json.dump({"ts": ts, "plan": plan,
                   "pra_bin_gbj": {p["item_code"]: p["saldo_gbj"] for p in plan},
                   "reco_existing": find_reco(new),
                   "trf_existing": find_trf(new)}, f, indent=1, default=str)
    print(f"# backup -> {bpath}")

    ok = fail = 0
    if args.reco:
        o, f_ = do_reco(new, plan)
        ok += o
        fail += f_
    if args.transfer:
        o, f_ = do_trf(new, plan)
        ok += o
        fail += f_
    print(f"\n=== SELESAI: {ok} sukses, {fail} gagal ===")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
