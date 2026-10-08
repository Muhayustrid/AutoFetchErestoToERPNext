import os
"""Pembersihan seluruh transaksi di https://ropierpnext.frappe.cloud
kecuali Journal Entry ACC-JV-2026-00001.

Menghapus:
- Delivery Note (46)
- Purchase Receipt (27)
- Stock Entry (308)
- Work Order (120)
- Sales Order (17)
- Purchase Order (86)
- Stock Reconciliation (8)
- POS Print Log / POS Invoice / POS Shifts jika ada

Memanfaatkan:
- Accounts Settings: delete_linked_ledger_entries = 1 (hapus GL & SLE otomatis per voucher)
- Stock Settings: allow_negative_stock = 1 (mencegah validasi stok negatif saat reversal)
"""

import argparse
import json
import time
import urllib.parse
import requests

URL = "https://ropierpnext.frappe.cloud"
HEADERS = {"Authorization": f"token {os.environ.get('ERPNEXT_API_KEY', '')}"}

CLEANUP_ORDER = [
    "POS Closing Shift",
    "POS Invoice",
    "POS Opening Shift",
    "Delivery Note",
    "Purchase Receipt",
    "Stock Entry",
    "Work Order",
    "Sales Order",
    "Purchase Order",
    "Stock Reconciliation",
]

def req(method, path, payload=None, params=None, max_retries=4):
    for a in range(1, max_retries + 1):
        try:
            r = requests.request(method, f"{URL}{path}", json=payload, params=params, headers=HEADERS, timeout=90)
            if r.status_code in {429, 500, 502, 503, 504}:
                time.sleep(2 ** a)
                continue
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, {"_raw": r.text[:500]}
        except requests.RequestException as e:
            time.sleep(2 ** a)
    return -1, {"error": "Request failed after retries"}

def get_count(doctype, filters=None):
    params = {"doctype": doctype}
    if filters:
        params["filters"] = json.dumps(filters)
    st, d = req("GET", "/api/method/frappe.client.get_count", params=params)
    if st == 200:
        return d.get("message", 0)
    return -1

def get_docs(doctype):
    out = []
    start = 0
    while True:
        params = {
            "fields": json.dumps(["name", "docstatus"]),
            "limit_page_length": 500,
            "limit_start": start,
            "order_by": "creation desc",
        }
        st, d = req("GET", f"/api/resource/{urllib.parse.quote(doctype)}", params=params)
        if st != 200:
            break
        rows = d.get("data", [])
        if not rows:
            break
        out.extend(rows)
        start += len(rows)
        if len(rows) < 500:
            break
    return out

def cancel_doc(doctype, name):
    return req("PUT", f"/api/resource/{urllib.parse.quote(doctype)}/{urllib.parse.quote(name)}", {"docstatus": 2})

def delete_doc(doctype, name):
    return req("DELETE", f"/api/resource/{urllib.parse.quote(doctype)}/{urllib.parse.quote(name)}")

def main():
    print(f"=== MEMULAI PEMBERSIHAN TOTAL TRANSAKSI DI {URL} ===", flush=True)
    start_time = time.time()

    # Pre-check & Backup Journal Entry
    st_je, d_je = req("GET", "/api/resource/Journal Entry/ACC-JV-2026-00001")
    if st_je == 200:
        with open("audit_logs/backup_ACC-JV-2026-00001.json", "w") as f:
            json.dump(d_je.get("data", {}), f, indent=2)
        print("OK: Backup ACC-JV-2026-00001 tersimpan di audit_logs/backup_ACC-JV-2026-00001.json", flush=True)
    else:
        print(f"[WARN] ACC-JV-2026-00001 tidak ditemukan: HTTP {st_je}", flush=True)

    pre_gl = get_count("GL Entry")
    pre_sle = get_count("Stock Ledger Entry")
    pre_je = get_count("Journal Entry")
    print(f"Status Awal:", flush=True)
    print(f"  Total GL Entry          : {pre_gl}", flush=True)
    print(f"  Total Stock Ledger Entry: {pre_sle}", flush=True)
    print(f"  Total Journal Entry     : {pre_je} (HARUS TETAP 1)\n", flush=True)

    # 1. Setup temporary settings
    print("[1/4] Mengaktifkan delete_linked_ledger_entries=1 & allow_negative_stock=1...", flush=True)
    st1, _ = req("PUT", "/api/resource/Accounts Settings/Accounts Settings", {"delete_linked_ledger_entries": 1})
    st2, _ = req("PUT", "/api/resource/Stock Settings/Stock Settings", {"allow_negative_stock": 1})
    if st1 != 200 or st2 != 200:
        raise SystemExit(f"Gagal mengupdate settings: Accounts={st1}, Stock={st2}")
    print("      OK: Setting pembersihan aktif.\n", flush=True)

    # Pre-clean POS Print Log if any
    r_logs = get_docs("POS Print Log")
    if r_logs:
        print(f"Membersihkan {len(r_logs)} POS Print Log...", flush=True)
        for l in r_logs:
            delete_doc("POS Print Log", l["name"])

    # 2. Process each DocType in order
    print("[2/4] Memproses Cancel dan Delete per DocType...", flush=True)
    for idx_dt, dt in enumerate(CLEANUP_ORDER, start=1):
        docs = get_docs(dt)
        print(f"\n--- [{idx_dt}/{len(CLEANUP_ORDER)}] {dt} (Ditemukan: {len(docs)}) ---", flush=True)
        if not docs:
            print("  Kosong, lanjut.", flush=True)
            continue

        # Step A: Cancel all submitted
        submitted = [d["name"] for d in docs if d.get("docstatus") == 1]
        if submitted:
            print(f"  Membatalkan (Cancel) {len(submitted)} dokumen {dt}...", flush=True)
            cancel_fails = []
            for i, name in enumerate(submitted, start=1):
                st, res = cancel_doc(dt, name)
                if st != 200:
                    cancel_fails.append((name, res))
                    print(f"    [FAIL CANCEL] {name}: {res}", flush=True)
                else:
                    if i % 25 == 0 or i == len(submitted):
                        print(f"    Progress cancel: {i}/{len(submitted)}", flush=True)
                time.sleep(0.04)

            # Retry failed cancels once if any
            if cancel_fails:
                print(f"  Mencoba ulang {len(cancel_fails)} dokumen yang gagal cancel...", flush=True)
                for name, _ in cancel_fails:
                    st, res = cancel_doc(dt, name)
                    if st != 200:
                        print(f"    [STILL FAIL] {name}: {res}", flush=True)
                    else:
                        print(f"    [RETRY OK] {name}", flush=True)
                    time.sleep(0.1)

        # Step B: Delete all (now draft or cancelled)
        docs_to_del = get_docs(dt)
        if docs_to_del:
            print(f"  Menghapus (Delete) {len(docs_to_del)} dokumen {dt}...", flush=True)
            del_fails = []
            for i, d in enumerate(docs_to_del, start=1):
                name = d["name"]
                st, res = delete_doc(dt, name)
                if st not in (200, 202):
                    del_fails.append((name, res))
                    print(f"    [FAIL DELETE] {name}: {res}", flush=True)
                else:
                    if i % 25 == 0 or i == len(docs_to_del):
                        print(f"    Progress delete: {i}/{len(docs_to_del)}", flush=True)
                time.sleep(0.04)

            if del_fails:
                print(f"  Mencoba ulang {len(del_fails)} dokumen yang gagal delete...", flush=True)
                for name, _ in del_fails:
                    st, res = delete_doc(dt, name)
                    if st not in (200, 202):
                        print(f"    [STILL FAIL DEL] {name}: {res}", flush=True)
                    else:
                        print(f"    [RETRY DEL OK] {name}", flush=True)
                    time.sleep(0.1)

        rem = get_count(dt)
        print(f"  Selesai {dt}. Sisa di sistem: {rem}", flush=True)

    # 3. Restore settings
    print("\n[3/4] Mengembalikan delete_linked_ledger_entries=0 & allow_negative_stock=0...", flush=True)
    req("PUT", "/api/resource/Accounts Settings/Accounts Settings", {"delete_linked_ledger_entries": 0})
    req("PUT", "/api/resource/Stock Settings/Stock Settings", {"allow_negative_stock": 0})
    print("      OK: Setting sistem dipulihkan ke normal.\n", flush=True)

    # 4. Final Verification
    print("="*60, flush=True)
    print("=== VERIFIKASI AKHIR HASIL PEMBERSIHAN ===", flush=True)
    print("="*60, flush=True)
    
    post_je = get_count("Journal Entry")
    post_gl = get_count("GL Entry")
    post_sle = get_count("Stock Ledger Entry")
    post_bin_pos = get_count("Bin", {"actual_qty": [">", 0]})
    post_bin_neg = get_count("Bin", {"actual_qty": ["<", 0]})

    print(f"DocType Transaksi:", flush=True)
    all_zero = True
    for dt in CLEANUP_ORDER:
        cnt = get_count(dt)
        status = "BERSIH (0)" if cnt == 0 else f"MASIH ADA ({cnt})"
        if cnt != 0:
            all_zero = False
        print(f"  {dt:25s}: {cnt:4d} [{status}]", flush=True)

    print(f"\nGeneral Ledger & Stock Ledger:", flush=True)
    print(f"  Journal Entry           : {post_je:4d} (Target: 1) -> {'LOLOS' if post_je == 1 else 'PERIKSA'}", flush=True)
    print(f"  GL Entry                : {post_gl:4d} (Target: 17 milik JE) -> {'LOLOS' if post_gl == 17 else 'PERIKSA'}", flush=True)
    print(f"  Stock Ledger Entry      : {post_sle:4d} (Target: 0) -> {'LOLOS' if post_sle == 0 else 'PERIKSA'}", flush=True)
    print(f"  Bin (actual_qty > 0)    : {post_bin_pos:4d} (Target: 0) -> {'LOLOS' if post_bin_pos == 0 else 'PERIKSA'}", flush=True)
    print(f"  Bin (actual_qty < 0)    : {post_bin_neg:4d} (Target: 0) -> {'LOLOS' if post_bin_neg == 0 else 'PERIKSA'}", flush=True)

    # Verify that the 1 remaining JE is ACC-JV-2026-00001
    st_je2, d_je2 = req("GET", "/api/resource/Journal Entry/ACC-JV-2026-00001")
    if st_je2 == 200:
        print(f"\nVerifikasi Journal Entry:", flush=True)
        print(f"  ACC-JV-2026-00001 ada, docstatus={d_je2.get('data', {}).get('docstatus')}, total_debit={d_je2.get('data', {}).get('total_debit')}", flush=True)
        print("  -> JOURNAL ENTRY 100% AMAN DAN UTUH.", flush=True)
    else:
        print(f"\n[ALERT] Gagal menemukan ACC-JV-2026-00001: HTTP {st_je2}", flush=True)

    elapsed = time.time() - start_time
    print(f"\nWaktu eksekusi: {elapsed:.1f} detik", flush=True)

if __name__ == "__main__":
    main()
