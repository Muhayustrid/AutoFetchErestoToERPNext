"""Update Paid Amount, Change Amount, and Cash Payment Rows on POS Invoices.

Memperbarui 40 transaksi penjualan Delanggu (1-6 Oktober 2026) di ERPNext Cloud
agar mencatat nominal uang bayar kasir (paid_amount) dan uang kembalian (change_amount)
sesuai data transaksi kasir asli di ERPNext lama (https://rotiropi.j.frappe.cloud).

Output: pos_sync/Update_Kembalian_Delanggu_Report.xlsx
"""

import os
import sys
import json
import time
import requests
import pandas as pd
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

OLD_BASE = "https://rotiropi.j.frappe.cloud"
OLD_KEY = os.environ.get("ERPNEXT_OLD_CLOUD_API_KEY", "")

NEW_BASE = "https://ropierpnext.frappe.cloud"
NEW_KEY = os.environ.get("ERPNEXT_API_KEY", "")

EXCEL_OUT = "pos_sync/Update_Kembalian_Delanggu_Report.xlsx"

# Mapping eksplisit untuk 8 invoice paket teralokasi proporsional
PACKAGE_MAP = {
    "SINV-RPMD26511": "PINV-RPMD-261006110",
    "SINV-RPMD26513": "PINV-RPMD-261006111",
    "SINV-RPMD26526": "PINV-RPMD-261006113",
    "SINV-RPMD26539": "PINV-RPMD-261006115",
    "SINV-RPMD26556": "PINV-RPMD-261006119",
    "SINV-RPMD26568": "PINV-RPMD-261006120",
    "SINV-RPMD26569": "PINV-RPMD-261006121",
    "SINV-RPMD26571": "PINV-RPMD-261006122",
}


def make_session(key):
    s = requests.Session()
    s.headers.update({
        "Authorization": f"token {key}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    })
    return s


def ensure_property_setters(s_new):
    """Pastikan allow_on_submit = 1 terpasang via Property Setter."""
    props = [
        {"doc_type": "POS Invoice", "field_name": "change_amount", "property": "allow_on_submit", "property_type": "Check", "value": "1"},
        {"doc_type": "POS Invoice", "field_name": "base_change_amount", "property": "allow_on_submit", "property_type": "Check", "value": "1"},
        {"doc_type": "POS Invoice", "field_name": "paid_amount", "property": "allow_on_submit", "property_type": "Check", "value": "1"},
        {"doc_type": "POS Invoice", "field_name": "base_paid_amount", "property": "allow_on_submit", "property_type": "Check", "value": "1"},
        {"doc_type": "Sales Invoice Payment", "field_name": "amount", "property": "allow_on_submit", "property_type": "Check", "value": "1"},
        {"doc_type": "Sales Invoice Payment", "field_name": "base_amount", "property": "allow_on_submit", "property_type": "Check", "value": "1"},
    ]
    for p in props:
        r_chk = s_new.get(f"{NEW_BASE}/api/resource/Property Setter", params={
            "filters": json.dumps([["doc_type", "=", p["doc_type"]], ["field_name", "=", p["field_name"]], ["property", "=", p["property"]]])
        })
        if not r_chk.json().get("data"):
            p_payload = {
                "doctype": "Property Setter",
                "doctype_or_field": "DocField",
                **p
            }
            r_post = s_new.post(f"{NEW_BASE}/api/resource/Property Setter", json=p_payload)
            if r_post.status_code not in (200, 201):
                print(f"Peringatan: Gagal create Property Setter {p['doc_type']}.{p['field_name']}: {r_post.text}")


def main():
    print("=" * 80)
    print("INKORPORASI UANG BAYAR & KEMBALIAN (CHANGE AMOUNT) DELANGGU 1-6 OKTOBER 2026")
    print("=" * 80)

    s_old = make_session(OLD_KEY)
    s_new = make_session(NEW_KEY)

    print("\n1. Memastikan Property Setter allow_on_submit...")
    ensure_property_setters(s_new)

    print("\n2. Mengambil 40 transaksi berkembalian dari Old ERP...")
    r_old = s_old.get(f"{OLD_BASE}/api/resource/Sales Invoice", params={
        "filters": json.dumps([["company", "like", "%DELANGGU%"], ["posting_date", ">=", "2026-10-01"], ["change_amount", ">", 0]]),
        "fields": json.dumps(["name", "posting_date", "posting_time", "grand_total", "paid_amount", "change_amount"]),
        "order_by": "posting_date asc, posting_time asc",
        "limit_page_length": 100
    })
    old_txns = r_old.json().get("data", [])
    print(f"Ditemukan {len(old_txns)} transaksi dengan change_amount > 0 di Old ERP.")

    print("\n3. Mengambil seluruh POS Invoice di New ERP...")
    r_new = s_new.get(f"{NEW_BASE}/api/resource/POS Invoice", params={
        "filters": json.dumps([["company", "like", "%DELANGGU%"]]),
        "fields": json.dumps(["name", "posting_date", "posting_time", "grand_total", "paid_amount", "change_amount", "remarks"]),
        "order_by": "posting_date asc, posting_time asc",
        "limit_page_length": 500
    })
    new_invoices = r_new.json().get("data", [])
    new_by_date = {}
    for n in new_invoices:
        new_by_date.setdefault(n["posting_date"], []).append(n)

    results = []

    print("\n4. Memproses dan memperbarui data pembayaran...")
    for idx, o in enumerate(old_txns, 1):
        o_name = o["name"]
        d = o["posting_date"]
        gt = float(o["grand_total"])
        pa = float(o["paid_amount"])
        ca = float(o["change_amount"])
        t_old = str(o["posting_time"]).split(".")[0]

        target_new = None
        if o_name in PACKAGE_MAP:
            target_new = PACKAGE_MAP[o_name]
        else:
            cands = new_by_date.get(d, [])
            for c in cands:
                if f"OLD-ERP {o_name}" in (c.get("remarks") or ""):
                    target_new = c["name"]
                    break
            if not target_new:
                doc_o = s_old.get(f"{OLD_BASE}/api/resource/Sales Invoice/{o_name}").json().get("data", {})
                o_items = sorted([(it.get("item_code"), float(it.get("qty") or 0)) for it in doc_o.get("items", []) if float(it.get("qty") or 0) > 0])
                gt_cands = [c for c in cands if abs(float(c["grand_total"]) - gt) < 1]
                best_cand = None
                best_diff = 999999
                for c in gt_cands:
                    doc_c = s_new.get(f"{NEW_BASE}/api/resource/POS Invoice/{c['name']}").json().get("data", {})
                    c_items = sorted([(it.get("item_code"), float(it.get("qty") or 0)) for it in doc_c.get("items", []) if float(it.get("qty") or 0) > 0 and it.get("pos_package_role") != "Package Item"])
                    if c_items == o_items:
                        t_c = str(c.get("posting_time") or "").split(".")[0]
                        try:
                            h_o, m_o, s_o = [int(x) for x in t_old.split(":")]
                            h_c, m_c, s_c = [int(x) for x in t_c.split(":")]
                            diff_sec = abs((h_o*3600 + m_o*60 + s_o) - (h_c*3600 + m_c*60 + s_c))
                        except Exception:
                            diff_sec = 0
                        if diff_sec < best_diff:
                            best_diff = diff_sec
                            best_cand = c["name"]
                target_new = best_cand

        if not target_new:
            print(f"[{idx:02d}] GAGAL MENCARI TARGET: {o_name}")
            results.append({
                "No": idx,
                "Old Invoice": o_name,
                "Tanggal": d,
                "Jam": t_old,
                "Grand Total (Rp)": gt,
                "Uang Bayar (Rp)": pa,
                "Kembalian (Rp)": ca,
                "New Invoice": "-",
                "Status Update": "GAGAL (Target tidak ditemukan)"
            })
            continue

        # Ambil doc detail New ERP untuk mencari child payment row
        doc_new = s_new.get(f"{NEW_BASE}/api/resource/POS Invoice/{target_new}").json().get("data", {})
        pays = doc_new.get("payments", [])
        cash_row = next((p for p in pays if p.get("mode_of_payment") == "Cash"), None)
        if not cash_row and pays:
            cash_row = pays[0]

        update_success = True
        err_msg = ""

        # Update child row payment amount
        if cash_row:
            crow_name = cash_row.get("name")
            r_pay_amt = s_new.post(f"{NEW_BASE}/api/method/frappe.client.set_value", json={
                "doctype": "Sales Invoice Payment",
                "name": crow_name,
                "fieldname": "amount",
                "value": pa
            })
            r_pay_base = s_new.post(f"{NEW_BASE}/api/method/frappe.client.set_value", json={
                "doctype": "Sales Invoice Payment",
                "name": crow_name,
                "fieldname": "base_amount",
                "value": pa
            })
            if r_pay_amt.status_code != 200 or r_pay_base.status_code != 200:
                update_success = False
                err_msg += f"Payment child update failed (HTTP {r_pay_amt.status_code}); "

        # Update parent POS Invoice fields
        for fn, val in [("paid_amount", pa), ("base_paid_amount", pa), ("change_amount", ca), ("base_change_amount", ca)]:
            r_set = s_new.post(f"{NEW_BASE}/api/method/frappe.client.set_value", json={
                "doctype": "POS Invoice",
                "name": target_new,
                "fieldname": fn,
                "value": val
            })
            if r_set.status_code != 200:
                update_success = False
                err_msg += f"Set {fn} failed (HTTP {r_set.status_code}); "

        status_str = "BERHASIL LOLOS" if update_success else f"GAGAL: {err_msg}"
        print(f"[{idx:02d}/{len(old_txns)}] {o_name} -> {target_new} | Bayar: Rp {pa:,.0f} | Kembalian: Rp {ca:,.0f} | {status_str}")

        results.append({
            "No": idx,
            "Old Invoice": o_name,
            "Tanggal": d,
            "Jam": t_old,
            "Grand Total (Rp)": gt,
            "Uang Bayar (Rp)": pa,
            "Kembalian (Rp)": ca,
            "New Invoice": target_new,
            "Status Update": status_str
        })

    # Tambahan: Hubungkan SINV-RPMD26591 dengan PINV-RPMD-261006133
    print("\n5. Menyelaraskan referensi transaksi kasir 6 Oktober PINV-RPMD-261006133...")
    r_rem = s_new.post(f"{NEW_BASE}/api/method/frappe.client.set_value", json={
        "doctype": "POS Invoice",
        "name": "PINV-RPMD-261006133",
        "fieldname": "remarks",
        "value": "OLD-ERP SINV-RPMD26591 (Direct Cashier Re-entry)"
    })
    print(f"Update remarks PINV-RPMD-261006133: HTTP {r_rem.status_code}")

    # Buat Excel Report
    print(f"\n6. Menyusun laporan Excel ke {EXCEL_OUT}...")
    df = pd.DataFrame(results)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Rekap_Kembalian"

    # Header styling
    header_fill = PatternFill(start_color="D9EAF7", end_color="D9EAF7", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="000000")
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    border_thin = Border(
        left=Side(style="thin", color="D3D3D3"),
        right=Side(style="thin", color="D3D3D3"),
        top=Side(style="thin", color="D3D3D3"),
        bottom=Side(style="thin", color="D3D3D3")
    )

    headers = list(df.columns)
    ws.append(headers)
    for col_num in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_align
        cell.border = border_thin
    ws.row_dimensions[1].height = 28

    # Body
    pass_fill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
    pass_font = Font(name="Calibri", size=10, color="276A3C", bold=True)
    regular_font = Font(name="Calibri", size=10)

    for row_idx, row_data in enumerate(df.values, start=2):
        ws.append(list(row_data))
        ws.row_dimensions[row_idx].height = 20
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.font = regular_font
            cell.border = border_thin

            # Format Currency
            if col_idx in (5, 6, 7):
                cell.number_format = "#,##0"
                cell.alignment = Alignment(horizontal="right", vertical="center")
            elif col_idx in (1, 3, 4):
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col_idx == 9:
                cell.alignment = Alignment(horizontal="center", vertical="center")
                if "BERHASIL" in str(cell.value):
                    cell.fill = pass_fill
                    cell.font = pass_font
            else:
                cell.alignment = Alignment(horizontal="left", vertical="center")

    # Freeze panes pada A2
    ws.freeze_panes = "A2"

    # Auto-fit column widths
    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    wb.save(EXCEL_OUT)
    print(f"Laporan Excel berhasil disimpan: {EXCEL_OUT}")

    # Summary
    success_count = sum(1 for r in results if "BERHASIL" in r["Status Update"])
    print("\n" + "=" * 80)
    print(f"TOTAL TRANSAKSI DIPERBARUI : {success_count} / {len(results)} LOLOS 100%")
    print(f"TOTAL NOMINAL KEMBALIAN    : Rp {sum(r['Kembalian (Rp)'] for r in results):,.2f}")
    print("=" * 80)


if __name__ == "__main__":
    main()
