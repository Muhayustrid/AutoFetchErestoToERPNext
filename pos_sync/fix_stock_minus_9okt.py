#!/usr/bin/env python3
"""pos_sync/fix_stock_minus_9okt.py — bereskan minus Telur Cair + kunci stock non-negatif.

Konteks (temuan 2026-10-09):
  BB260055 Telur Cair @ Gudang Produksi - JURI = -19.982,8 g. Fisik: telur utuh
  (BB260027) sudah dipecah produksi tetapi Repack-nya tidak dicatat (repack
  tercatat 86.442,2 g; konsumsi MTFM 141.380 g). Stok BB260027 tersedia.
  Fix = catat repack yang kurang: BB260027 -23.155 g -> BB260055 +19.982,8 g
  (yield 86,32% sama dgn SE-RPK-261009004: 100.000->86.300).
  Posting 16:20 (sebelum MTFM 16:31 yang menjadikan minus) supaya seluruh
  riwayat non-negatif.

  --lock: setelah 0 bin negatif se-sistem -> Stock Settings.allow_negative_stock=0
  PERMANEN (kebijakan user: sistem harus menolak stock minus) + smoke test
  (submit SE minus harus DITOLAK; draft dibersihkan).

DEFAULT DRY-RUN. Jalankan: python pos_sync/fix_stock_minus_9okt.py --execute [--lock]
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env

JURI = "PT. JUARA ROTI INDONESIA"
ITEM_OUT, ITEM_IN = "BB260027", "BB260055"   # Telur Utuh -> Telur Cair
WH = "Gudang Produksi - JURI"
REMARK = "Repack penyelesaian telur 9 Okt (fisik sudah dipecah, repack belum dicatat)"


def bin_qty(c, item, wh):
    rows = c.list_all("Bin", ["actual_qty"],
                      filters=[["item_code", "=", item], ["warehouse", "=", wh]])
    return float(rows[0]["actual_qty"]) if rows else 0.0


def find_reco_draft(c, remark):
    st, d = c.get("/api/resource/Stock Entry", {
        "filters": json.dumps([["docstatus", "=", 0], ["remarks", "=", remark]]),
        "fields": json.dumps(["name"]), "limit_page_length": 1})
    return (d.get("data") or [None])[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--lock", action="store_true",
                    help="kunci allow_negative_stock=0 setelah minus bersih")
    args = ap.parse_args()

    prod = load_env("/tmp/eresto_prod.env")
    c = Client(prod["ERPNEXT_URL"], prod["ERPNEXT_API_KEY"], "BARU")

    qty055 = bin_qty(c, ITEM_IN, WH)
    qty027 = bin_qty(c, ITEM_OUT, WH)
    deficit = round(-qty055, 3) if qty055 < 0 else 0.0
    print("== PREFLIGHT ==")
    print(f"  {ITEM_OUT} (Telur Utuh) @ {WH}: {qty027} g")
    print(f"  {ITEM_IN} (Telur Cair) @ {WH}: {qty055} g -> deficit={deficit}")
    if deficit <= 0:
        print("  [SKIP] tidak ada minus.")
    else:
        yield_ = 0.863  # konsisten SE-RPK-261009004 (100.000->86.300)
        src_qty = round(deficit / yield_, 3)
        print(f"  rencana: {ITEM_OUT} -{src_qty} g -> {ITEM_IN} +{deficit} g")
        if qty027 < src_qty:
            raise SystemExit(f"STOP: stok {ITEM_OUT} tidak cukup ({qty027} < {src_qty})")
        if not args.execute:
            print("\n[DRY-RUN] Jalankan ulang dengan --execute.")
            return
        else:
            draft = find_reco_draft(c, REMARK)
            if draft:
                name = draft["name"]
                print(f"  [draft] reuse {name}")
            else:
                payload = {
                    "doctype": "Stock Entry",
                    "stock_entry_type": "Repack",
                    "purpose": "Repack",
                    "company": JURI,
                    "posting_date": "2026-10-09",
                    "posting_time": "16:20:00",
                    "set_posting_time": 1,
                    "remarks": REMARK,
                    "items": [
                        {"item_code": ITEM_OUT, "qty": src_qty, "uom": "g",
                         "s_warehouse": WH, "t_warehouse": None,
                         "conversion_factor": 1.0, "basic_rate": 24.8},
                        {"item_code": ITEM_IN, "qty": deficit, "uom": "g",
                         "s_warehouse": None, "t_warehouse": WH,
                         "is_finished_item": 1,
                         "conversion_factor": 1.0},
                    ],
                }
                st, d = c.post("Stock Entry", payload)
                if st not in (200, 201):
                    raise SystemExit(f"GAGAL buat SE: HTTP {st} {str(d)[:400]}")
                name = d["data"]["name"]
                print(f"  [OK] SE {name} dibuat")
            st, d = c.submit("Stock Entry", name)
            print(f"  [{'OK' if st == 200 else 'FAIL'}] submit {name}: HTTP {st} "
                  f"{'' if st == 200 else str(d)[:300]}")
            if st != 200:
                raise SystemExit("STOP: submit SE gagal")

    # ---------- verifikasi minus ----------
    print("\n== VERIFIKASI MINUS ==")
    ok = False
    for attempt in range(18):
        st, d = c.get("/api/method/frappe.client.get_count", {
            "doctype": "Bin", "filters": json.dumps([["actual_qty", "<", 0]])})
        neg = d.get("message", "?")
        if neg == 0:
            ok = True
            break
        print(f"  [{attempt+1}] bin negatif sisa: {neg}")
        time.sleep(5)
    print(f"  [{'LOLOS' if ok else 'GAGAL'}] 0 bin negatif se-sistem")
    if not ok:
        rows = c.list_all("Bin", ["item_code", "warehouse", "actual_qty"],
                          filters=[["actual_qty", "<", 0]])
        print(f"  sisa: {rows}")

    qty055_after = bin_qty(c, ITEM_IN, WH)
    print(f"  {ITEM_IN} @ {WH} sekarang: {qty055_after} g")

    # ---------- lock ----------
    if args.lock:
        if not ok:
            raise SystemExit("STOP: masih ada minus, tidak dikunci")
        print("\n== LOCK allow_negative_stock=0 ==")
        if not args.execute:
            print("  [DRY-RUN] lock dilewati (--execute belum dipakai).")
        else:
            st, _ = c.put("Stock Settings", "Stock Settings",
                          {"allow_negative_stock": 0})
            print(f"  [{'OK' if st == 200 else 'FAIL'}] set allow_negative_stock=0 (HTTP {st})")
            # smoke test: SE minus harus DITOLAK
            smoke = {
                "doctype": "Stock Entry",
                "stock_entry_type": "Material Transfer",
                "purpose": "Material Transfer",
                "company": JURI,
                "items": [{"item_code": ITEM_IN, "qty": 1.0, "uom": "g",
                           "s_warehouse": "Gudang Bahan Baku - JURI",
                           "t_warehouse": "Gudang Produksi - JURI",
                           "conversion_factor": 1.0}],
            }
            st, d = c.post("Stock Entry", smoke)
            if st != 200:
                print(f"  [INFO] smoke SE tidak bisa dibuat (HTTP {st}) — skip; "
                      f"cek manual bila perlu")
            else:
                sname = d["data"]["name"]
                st2, d2 = c.submit("Stock Entry", sname)
                rejected = st2 != 200
                print(f"  [{'LOLOS' if rejected else 'GAGAL'}] smoke submit minus "
                      f"{'DITOLAK' if rejected else 'LOLOS (bahaya!)'} (HTTP {st2})")
                # draft apa pun hasil smoke dibersihkan
                st3, d3 = c.get(f"/api/resource/Stock Entry/{sname}")
                if st3 == 200 and d3["data"]["docstatus"] == 0:
                    c.req("DELETE", f"/api/resource/Stock Entry/{sname}")
                    print(f"  [OK] draft smoke {sname} dihapus")

    # ---------- laporan ----------
    try:
        import pandas as pd
        st, d = c.get("/api/method/frappe.client.get_value", {
            "doctype": "Stock Settings", "fieldname": "allow_negative_stock"})
        flag = (d.get("message") or {}).get("allow_negative_stock", "?")
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "Laporan_Fix_Stock_Minus_9Okt.xlsx")
        with pd.ExcelWriter(out, engine="openpyxl") as xw:
            pd.DataFrame([{"item": ITEM_IN, "warehouse": WH,
                           "before": qty055, "deficit_fixed": deficit,
                           "after": qty055_after,
                           "negative_stock_flag": flag,
                           "status": "LOLOS" if ok else "PERIKSA"}]).to_excel(
                xw, sheet_name="Ringkasan", index=False)
        print(f"  [OK] Laporan -> {out}")
    except Exception as e:  # noqa: BLE001
        print(f"  [WARN] excel: {e}")


if __name__ == "__main__":
    main()
