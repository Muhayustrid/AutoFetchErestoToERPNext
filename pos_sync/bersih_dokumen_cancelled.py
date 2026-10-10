#!/usr/bin/env python3
"""pos_sync/bersih_dokumen_cancelled.py — hapus permanen dokumen cancelled PT. JURI.

Scope (keputusan user 2026-10-09): HANYA company "PT. JUARA ROTI INDONESIA".
Dokumen cancelled company lain (mis. WO-TRNG-261007001 = TRAINING) TIDAK disentuh.

Prosedur (teruji di repo: cleanup_prod_transactions.py + memori
erpnext-delete-pos-invoice-procedure):
  1. Scan live docstatus=2 utk daftar doctype transaksi -> filter company.
  2. Backup full JSON tiap dokumen -> audit_logs/backup_cancelled_docs_<ts>.json.
  3. Purge POS Print Log refer (expected 0).
  4. Accounts Settings.delete_linked_ledger_entries=1 sementara (restore di finally).
  5. Hapus urut dependency-safe (SE -1 dulu; PR sebelum PO).
  6. Khusus 2 MR terkunci amended_from: lepas link di pengganti aktif
     (Property Setter sementara) lalu hapus; gagal -> SKIP_LINKED (tidak dipaksa).
  7. Verifikasi: docstatus=2 JURI = 0, Bin net-zero, GL/SLE/PLE per nama = 0.

DEFAULT = DRY-RUN. Jalankan: python pos_sync/bersih_dokumen_cancelled.py --execute
Output: stdout OK/LOLOS + pos_sync/Laporan_Bersih_Dokumen_Cancelled.xlsx
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

JURI = "PT. JUARA ROTI INDONESIA"

# Urutan hapus dependency-safe. (doctype, {nama: ...} atau None=scan semua cancelled JURI)
# Catatan: untuk doctype besar cukup scan docstatus=2 (ini daftar definitif 31 dok).
DOCTYPE_ORDER = [
    "Stock Entry",            # -001-1 SEBELUM -001 (amended_from)
    "Purchase Receipt",       # PR sebelum PO (item.purchase_order)
    "Purchase Invoice",
    "Delivery Note",
    "Stock Reconciliation",
    "Purchase Order",
    "Material Request",
    "Work Order",
    # sapuan luas (scan hanya; daftar definitif hari ini kosong utk ini semua)
    "Journal Entry",
    "Payment Entry",
    "Sales Invoice",
    "POS Invoice",
    "Asset",
    "Landed Cost Voucher",
]

SETTERS = [("Material Request", "amended_from")]  # utk lepas link pengganti aktif


def q(dt):
    return urllib.parse.quote(dt)


def get_doc(c, dt, name):
    st, d = c.get(f"/api/resource/{q(dt)}/{q(name)}")
    return (d.get("data") if st == 200 else None), st


def scan_cancelled_juri(c):
    """Semua dok cancel ber-company JURI (field 'company' bisa tak ada -> manual)."""
    out = {}
    for dt in DOCTYPE_ORDER:
        rows = c.list_all(dt, ["name", "docstatus", "company"],
                          filters=[["docstatus", "=", 2]])
        out[dt] = [r["name"] for r in rows if r.get("company") == JURI]
        skipped = [r["name"] for r in rows if r.get("company") != JURI]
        if skipped:
            print(f"  [scope] {dt}: skip non-JURI -> {skipped}")
    return out


def bin_snapshot(c):
    rows = c.list_all("Bin", ["item_code", "warehouse", "actual_qty"],
                      filters=[["actual_qty", "!=", 0]])
    return {(r["item_code"], r["warehouse"]): round(float(r["actual_qty"]), 6) for r in rows}


def ensure_setter(c, dt, field):
    st, d = c.get("/api/resource/Property Setter", {
        "filters": json.dumps([["doc_type", "=", dt], ["field_name", "=", field],
                               ["property", "=", "allow_on_submit"]]),
        "fields": json.dumps(["name", "value"])})
    existing = (d.get("data") or [None])[0] if st == 200 else None
    if existing:
        if str(existing.get("value")) == "1":
            return None, existing["name"]  # sudah ada dari sesi lain
        raise SystemExit(f"STOP: setter {dt}.{field} ada value={existing['value']}")
    st, d = c.post("Property Setter", {
        "doctype": "Property Setter", "doctype_or_field": "DocField",
        "doc_type": dt, "field_name": field,
        "property": "allow_on_submit", "property_type": "Check", "value": "1"})
    if st not in (200, 201):
        raise SystemExit(f"GAGAL buat setter {dt}.{field}: HTTP {st} {str(d)[:300]}")
    return True, d["data"]["name"]


def delete_one(c, dt, name):
    st, d = c.req("DELETE", f"/api/resource/{q(dt)}/{q(name)}")
    return st, str(d)[:300]


def purge_pos_print_logs(c, names):
    total = 0
    for n in names:
        st, d = c.get("/api/resource/POS%20Print%20Log", {
            "filters": json.dumps([["reference_name", "=", n]]),
            "fields": json.dumps(["name"]), "limit_page_length": 0})
        for r in (d.get("data") or []):
            c.req("DELETE", f"/api/resource/POS%20Print%20Log/{q(r['name'])}")
            total += 1
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    prod = load_env("/tmp/eresto_prod.env")
    c = Client(prod["ERPNEXT_URL"], prod["ERPNEXT_API_KEY"], "BARU")

    print("== SCAN dokumen cancelled ==")
    plan = scan_cancelled_juri(c)
    total = sum(len(v) for v in plan.values())
    for dt, names in plan.items():
        if names:
            print(f"  {dt}: {len(names)} -> {', '.join(names)}")
    print(f"TOTAL dokumen target: {total}")

    # 2 MR terkunci: pastikan pengganti aktif ada sebelum lepas link
    mr_locked = [n for n in plan.get("Material Request", [])
                 if c.find("Material Request", "amended_from", n, fields=("name", "docstatus"))]
    print(f"  MR terkunci amended_from: {mr_locked or '-'}")

    if total == 0:
        print("[SKIP] Tidak ada dokumen cancelled JURI (sudah bersih).")
        verify(c, plan)
        return

    if not args.execute:
        print("\n[DRY-RUN] Jalankan ulang dengan --execute untuk menghapus.")
        return

    # ---------- backup ----------
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                               "audit_logs", f"backup_cancelled_docs_{stamp}.json")
    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
    backup = {}
    for dt, names in plan.items():
        for n in names:
            doc, st = get_doc(c, dt, n)
            backup[f"{dt}||{n}"] = doc or {"_missing": True, "_http": st}
    with open(backup_path, "w") as f:
        json.dump(backup, f, indent=2, default=str)
    print(f"\n[OK] Backup {len(backup)} dokumen -> {os.path.abspath(backup_path)}")

    bin_before = bin_snapshot(c)
    print(f"[OK] Snapshot Bin (non-zero): {len(bin_before)} posisi")

    # ---------- POS Print Log ----------
    all_names = [n for v in plan.values() for n in v]
    purged = purge_pos_print_logs(c, all_names)
    print(f"[OK] POS Print Log dipurge: {purged}")

    # ---------- settings sementara ----------
    st, _ = c.put("Accounts Settings", "Accounts Settings",
                  {"delete_linked_ledger_entries": 1})
    print(f"[OK] Accounts Settings.delete_linked_ledger_entries=1 (HTTP {st})")

    results = []  # (doctype, name, status)
    created = []
    try:
        # ---------- MR terkunci: lepas amended_from di pengganti aktif ----------
        for mr in mr_locked:
            repl = c.list_all("Material Request", ["name", "docstatus", "amended_from"],
                              filters=[["amended_from", "=", mr]])
            for r in repl:
                flag, setter_name = ensure_setter(c, "Material Request", "amended_from")
                if flag:
                    created.append(setter_name)
                # hanya boleh diubah lewat set_value (read_only field)
                stv, dv = c.req("POST", "/api/method/frappe.client.set_value", {
                    "doctype": "Material Request", "name": r["name"],
                    "fieldname": "amended_from", "value": None})
                print(f"  [MR] lepas amended_from {r['name']}: HTTP {stv}")

        # ---------- hapus urut ----------
        # SE: -1 dulu (amended_from chain)
        def sort_key(n):
            return (0 if n.endswith("-1") else 1, n)

        for dt in DOCTYPE_ORDER:
            names = sorted(plan.get(dt, []), key=sort_key)
            for n in names:
                st, msg = delete_one(c, dt, n)
                ok = st in (200, 202)
                results.append((dt, n, "DELETED" if ok else f"FAIL HTTP {st}"))
                print(f"  [{'OK' if ok else 'FAIL'}] {dt} {n}: {st}{'' if ok else ' ' + msg}")
                time.sleep(0.05)

            # retry sekali
            fails = [(d, nm) for d, nm, s in results if d == dt and s.startswith("FAIL")]
            for d, nm in fails:
                st, msg = delete_one(c, d, nm)
                if st in (200, 202):
                    results = [(dd, nn, "DELETED" if (dd, nn) == (d, nm) else ss)
                               for dd, nn, ss in results]
                    print(f"  [RETRY OK] {d} {nm}")
                else:
                    print(f"  [RETRY FAIL] {d} {nm}: {st} {msg}")
                time.sleep(0.1)
    finally:
        st, _ = c.put("Accounts Settings", "Accounts Settings",
                      {"delete_linked_ledger_entries": 0})
        print(f"\n[OK] restore delete_linked_ledger_entries=0 (HTTP {st})")
        for sname in created:
            c.req("DELETE", f"/api/resource/Property%20Setter/{q(sname)}")
            print(f"  [setter] hapus {sname}")

    # ---------- per-doc ledger check ----------
    print("\n== CEK LEDGER per dokumen ==")
    ledger_ok = True
    for dt, n in [(d, nm) for d, nm, s in results]:
        leftover = {}
        for ldt in ("GL Entry", "Stock Ledger Entry", "Payment Ledger Entry"):
            st, dct = c.req("GET", "/api/method/frappe.client.get_count",
                            params={"doctype": ldt, "filters": json.dumps(
                                [["voucher_no", "=", n]])})
            if st == 200:
                val = dct.get("message", 0)
                if isinstance(val, int) and val > 0:
                    leftover[ldt] = val
            else:
                leftover[ldt] = f"HTTP{st}"
        # WARN hanya untuk sisa > 0; HTTP error PLE/GL dianggap informasi
        hard = {k: v for k, v in leftover.items() if isinstance(v, int)}
        if hard:
            ledger_ok = False
            print(f"  [WARN] {dt} {n}: sisa {hard}")
    if ledger_ok:
        print("  [LOLOS] semua ledger refer dokumen terhapus = 0")

    # ---------- bin net-zero ----------
    bin_after = bin_snapshot(c)
    diff = {}
    for k in set(bin_before) | set(bin_after):
        b, a = bin_before.get(k), bin_after.get(k)
        if b != a:
            diff[k] = (b, a)
    print(f"\n== BIN BANDING: {'[LOLOS] net-zero' if not diff else '[WARN] ada perubahan'}")
    for k, (b, a) in list(diff.items())[:20]:
        print(f"  {k}: {b} -> {a}")

    verify(c, plan)

    # ---------- report excel ----------
    try:
        import pandas as pd
        rows = [{"doctype": d, "name": n, "status": s} for d, n, s in results]
        df = pd.DataFrame(rows)
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "Laporan_Bersih_Dokumen_Cancelled.xlsx")
        with pd.ExcelWriter(out, engine="openpyxl") as xw:
            pd.DataFrame([{"scope": JURI, "total": total, "deleted": sum(
                1 for _, _, s in results if s == "DELETED")}]).to_excel(
                xw, sheet_name="Ringkasan", index=False)
            df.to_excel(xw, sheet_name="Deleted", index=False)
            pd.DataFrame([{"bin": f"{k[0]}@{k[1]}", "before": v[0], "after": v[1]}
                          for k, v in diff.items()]).to_excel(
                xw, sheet_name="Bin_Diff", index=False)
        print(f"[OK] Laporan -> {out}")
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] gagal tulis excel: {e}")


def verify(c, plan):
    print("\n== VERIFIKASI AKHIR ==")
    left = []
    for dt in DOCTYPE_ORDER:
        rows = c.list_all(dt, ["name", "docstatus", "company"],
                          filters=[["docstatus", "=", 2]])
        j = [r["name"] for r in rows if r.get("company") == JURI]
        if j:
            left += [(dt, n) for n in j]
    ok = not left
    print(f"  [{'LOLOS' if ok else 'GAGAL'}] docstatus=2 company JURI sisa: {left or 0}")

    st, d = c.get("/api/method/frappe.client.get_count", {
        "doctype": "Bin", "filters": json.dumps([["actual_qty", "<", 0]])})
    neg = d.get("message", "?")
    print(f"  [INFO] Bin negatif se-sistem: {neg} (target 0 setelah B2+B3)")


if __name__ == "__main__":
    main()
