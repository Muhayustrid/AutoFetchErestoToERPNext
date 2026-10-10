#!/usr/bin/env python3
"""pos_sync/merge_goodie_bag_items.py — gabung Item PG001 'Goodie Bag 6 Roti' -> PEL260072 'Goodie Bag'.

Konteks (keputusan user 2026-10-09):
  Satu barang fisik punya DUA kode: PG001 (legacy, 18.052 pcs di GBJ) dan
  PEL260072 (kanonik, dipakai 43+ DN/SO & 90+ PO). POS Package
  'Paket Goodiebag 6 ROPI' salah memasang komponen PG001, dan mapping lama
  reinject_package_invoices.py memakai PKG01->PG001 -> PG001 minus di RPMD.

Aksi: pakai fitur native Frappe `rename_doc(merge=1)`:
  - semua referensi (SLE, POS Invoice Item, Stock Entry Detail,
    Stock Reconciliation Item, POS Package Item, Item Price, Repost Item
    Valuation) dipindah PG001 -> PEL260072;
  - Bin PG001 dihapus, Bin PEL260072 direpost ulang per gudang (net gabungan);
  - Item PG001 dihapus otomatis (masuk Deleted Document).

DEFAULT = DRY-RUN (preflight saja). Eksekusi: --execute
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env

OLD, NEW = "PG001", "PEL260072"
PROPS = ["stock_uom", "is_stock_item", "has_serial_no", "has_batch_no"]
POS_INVOICES = ["PINV-RPMD-261006107", "PINV-RPMD-261006109",
                "PINV-RPMD-261008019", "PINV-RPMD-261008023"]


def q(s):
    return urllib.parse.quote(s)


def get_doc(c, dt, name):
    st, d = c.get(f"/api/resource/{q(dt)}/{q(name)}")
    return (d.get("data") if st == 200 else None), st


def bins_of(c, item):
    rows = c.list_all("Bin", ["warehouse", "actual_qty"],
                      filters=[["item_code", "=", item]])
    return {r["warehouse"]: float(r["actual_qty"]) for r in rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    prod = load_env("/tmp/eresto_prod.env")
    c = Client(prod["ERPNEXT_URL"], prod["ERPNEXT_API_KEY"], "BARU")

    print("== PREFLIGHT ==")
    old, st_o = get_doc(c, "Item", OLD)
    new, st_n = get_doc(c, "Item", NEW)
    if st_o != 200:
        print(f"  [SKIP] Item {OLD} tidak ada (HTTP {st_o}) — sudah pernah di-merge?")
        verify(c)
        return
    if st_n != 200:
        raise SystemExit(f"STOP: target {NEW} tidak ada (HTTP {st_n})")

    for f in PROPS:
        a, b = old.get(f), new.get(f)
        ok = str(a) == str(b)
        print(f"  [{ 'OK' if ok else 'BEDA'}] {f}: {OLD}={a} vs {NEW}={b}")
        if not ok:
            raise SystemExit("STOP: properti item beda — merge native akan menolak.")

    for code in (OLD, NEW):
        b = c.find("Product Bundle", "new_item_code", code,
                   fields=("name", "disabled"))
        active = [x for x in b if not x.get("disabled")]
        if active:
            raise SystemExit(f"STOP: {code} punya Product Bundle aktif: {active}")
    print("  [OK] tidak ada Product Bundle aktif utk kedua item")

    # guard native: PG001 & PEL260072 tidak boleh se-RECO (same warehouse, submitted)
    reco_hits = c.list_all("Stock Reconciliation Item",
                           ["parent", "warehouse"],
                           filters=[["item_code", "=", NEW]])
    reco_new = {(r["parent"], r["warehouse"]) for r in reco_hits}
    reco_hits = c.list_all("Stock Reconciliation Item",
                           ["parent", "warehouse"],
                           filters=[["item_code", "=", OLD]])
    reco_old = {(r["parent"], r["warehouse"]) for r in reco_hits}
    clash = reco_new & reco_old
    print(f"  [{'WARN' if clash else 'OK'}] RECO bentrok (submitted same wh): {clash or '-'}")
    if clash:
        raise SystemExit("STOP: ada RECO submitted memuat kedua item (guard merge).")

    bin_old, bin_new = bins_of(c, OLD), bins_of(c, NEW)
    print(f"  Bin {OLD}: {bin_old}")
    print(f"  Bin {NEW}: {bin_new}")
    expected = {}
    for wh in set(bin_old) | set(bin_new):
        expected[wh] = round(bin_old.get(wh, 0.0) + bin_new.get(wh, 0.0), 3)
    print(f"  Ekspektasi Bin gabungan: {expected}")

    if not args.execute:
        print("\n[DRY-RUN] Jalankan ulang dengan --execute untuk merge.")
        return

    # ---------- backup ----------
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                         "audit_logs", f"backup_merge_goodie_{stamp}.json")
    os.makedirs(os.path.dirname(bpath), exist_ok=True)
    backup = {"old_item": old, "new_item": new, "bins_old": bin_old, "bins_new": bin_new}
    backup["sle"] = c.list_all("Stock Ledger Entry",
                               ["name", "posting_date", "posting_time", "warehouse",
                                "actual_qty", "qty_after_transaction", "voucher_type",
                                "voucher_no"],
                               filters=[["item_code", "=", OLD]])
    backup["pos_invoices"] = {}
    for pinv in POS_INVOICES:
        doc, _ = get_doc(c, "POS Invoice", pinv)
        backup["pos_invoices"][pinv] = doc
    pkg = c.list_all("POS Package", ["name", "package_name"])
    backup["pos_package"] = {}
    for p in pkg:
        doc, _ = get_doc(c, "POS Package", p["name"])
        backup["pos_package"][p["name"]] = doc
    with open(bpath, "w") as f:
        json.dump(backup, f, indent=2, default=str)
    print(f"\n[OK] Backup -> {os.path.abspath(bpath)}")

    # ---------- merge (form-encoded; rename_doc wajib form) ----------
    r = c.s.post(c.base + "/api/method/frappe.client.rename_doc",
                 data={"doctype": "Item", "old_name": OLD,
                       "new_name": NEW, "merge": 1}, timeout=300)
    print(f"[MERGE] rename_doc merge: HTTP {r.status_code}")
    if r.status_code != 200:
        raise SystemExit(f"GAGAL merge: {r.text[:500]}")
    print(f"  message={r.json().get('message')}")

    # ---------- poll repost ----------
    print("\n== POLL Repost Item Valuation ==")
    for attempt in range(30):
        rows = c.list_all("Repost Item Valuation",
                          ["name", "status", "item_code"],
                          filters=[["item_code", "=", NEW],
                                   ["status", "in", ["Queued", "In Progress"]]])
        if not rows:
            print("  [OK] tidak ada repost pending")
            break
        print(f"  [{attempt+1}] {len(rows)} pending...")
        time.sleep(10)
    else:
        print("  [WARN] repost masih pending setelah polling — cek nanti")

    verify(c, bin_before=expected)


def verify(c, bin_before=None):
    print("\n== VERIFIKASI ==")
    _, st = get_doc(c, "Item", OLD)
    print(f"  [{'LOLOS' if st == 404 else 'GAGAL'}] Item {OLD} terhapus (HTTP {st})")

    pkg_rows = c.list_all("POS Package Item", ["parent", "item_code", "qty"],
                          filters=[["item_code", "=", OLD]])
    print(f"  [{'LOLOS' if not pkg_rows else 'GAGAL'}] POS Package Item sisa {OLD}: {pkg_rows or 0}")
    pkg_new = c.list_all("POS Package Item", ["parent", "item_code"],
                         filters=[["item_code", "=", NEW]])
    print(f"  [{'LOLOS' if pkg_new else 'INFO'}] POS Package Item pakai {NEW}: "
          f"{[(r['parent'], r['item_code']) for r in pkg_new]}")

    inv_ref = []
    for pinv in POS_INVOICES:
        doc, stp = get_doc(c, "POS Invoice", pinv)
        if stp != 200:
            inv_ref.append((pinv, f"HTTP{stp}")); continue
        codes = sorted({it["item_code"] for it in doc.get("items", [])
                        if it["item_code"] in (OLD, NEW)})
        inv_ref.append((pinv, codes))
    bad = [x for x in inv_ref if OLD in x[1]]
    print(f"  [{'LOLOS' if not bad else 'GAGAL'}] POS Invoice rows: {inv_ref}")

    bins = bins_of(c, NEW)
    print(f"  Bin {NEW}: {dict(sorted(bins.items()))}")
    if bin_before:
        ok = all(abs(bins.get(wh, 0.0) - v) < 0.01 for wh, v in bin_before.items())
        print(f"  [{'LOLOS' if ok else 'WARN'}] Bin gabungan sesuai ekspektasi: {bin_before}")

    st, d = c.get("/api/method/frappe.client.get_count", {
        "doctype": "Bin", "filters": json.dumps([["actual_qty", "<", 0]])})
    print(f"  [INFO] Bin negatif se-sistem: {d.get('message', '?')}")

    # laporan excel
    try:
        import pandas as pd
        rows = [{"warehouse": wh, "qty": qty} for wh, qty in sorted(bins.items())]
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "Laporan_Merge_Goodie_Bag.xlsx")
        with pd.ExcelWriter(out, engine="openpyxl") as xw:
            pd.DataFrame(rows).to_excel(xw, sheet_name="Bin_Gabungan", index=False)
            pd.DataFrame([{"pos_invoice": p, "item_codes": ",".join(c_) if isinstance(c_, list) else c_}
                          for p, c_ in inv_ref]).to_excel(xw, sheet_name="POS_Invoice_Ref", index=False)
        print(f"  [OK] Laporan -> {out}")
    except Exception as e:  # noqa: BLE001
        print(f"  [WARN] excel: {e}")


if __name__ == "__main__":
    main()
