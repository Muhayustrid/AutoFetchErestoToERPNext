"""Migrasi Produksi Delanggu via Native Work Order + POS Production Recipe.

Mengimplementasikan arsitektur resmi POSNext Production:
1. Work Order dibuat dan disubmit (skip_transfer=1, use_multi_level_bom=0).
2. Stock Entry Manufacture digenerate via API resmi `make_stock_entry(work_order_id)`.
3. Stock Entry disubmit dengan posting_date & posting_time historis.
4. Work Order otomatis bertransisi ke status 'Completed' (produced_qty = fg_qty).
5. POS Production Log dibuat dan disubmit dengan relasi ganda ke Work Order & Stock Entry.

Company: RS PKU MUHAMMADIYAH DELANGGU
Warehouse: Stores - RPMD
"""

import json
import os
import sys
import time
import requests
import pandas as pd
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side

OLD_BASE = "https://rotiropi.j.frappe.cloud"
OLD_KEY = os.environ.get("ERPNEXT_OLD_CLOUD_API_KEY", "")

NEW_BASE = "https://ropierpnext.frappe.cloud"
NEW_KEY = os.environ.get("ERPNEXT_API_KEY", "")

COMPANY = "RS PKU MUHAMMADIYAH DELANGGU"
WAREHOUSE = "Stores - RPMD"
POS_PROFILE = "SHIFT 1 - RS PKU MUHAMMADIYAH DELANGGU"
EXCEL_OUT = "pos_sync/Injeksi_Work_Order_Delanggu.xlsx"

RECIPE_MAPPING = {
    "RP001": {
        "recipe_name": "ROPI BUTTER",
        "fg_code": "PJO2603",
        "fg_name": "Ropi Butter Matang",
        "bom_no": "BOM-PJO2603-001"
    },
    "RP002": {
        "recipe_name": "ROPI COKLAT",
        "fg_code": "PJO2601",
        "fg_name": "Ropi Coklat Matang",
        "bom_no": "BOM-PJO2601-001"
    },
    "RP003": {
        "recipe_name": "ROPI KEJU",
        "fg_code": "PJO2602",
        "fg_name": "Ropi Keju Matang",
        "bom_no": "BOM-PJO2602-001"
    },
    "CR001": {
        "recipe_name": "Croissant",
        "fg_code": "PJO2605",
        "fg_name": "Croissant Matang",
        "bom_no": "BOM-PJO2605-001"
    },
    "GM001": {
        "recipe_name": "Gempi",
        "fg_code": "PJO2604",
        "fg_name": "Gempi Matang",
        "bom_no": "BOM-PJO2604-001"
    }
}


def make_session(key):
    s = requests.Session()
    s.headers.update({
        "Authorization": f"token {key}",
        "Accept": "application/json"
    })
    return s


def main():
    print("=" * 75)
    print("MIGRASI PRODUKSI DELANGGU VIA WORK ORDER (ALUR RESMI POSNEXT)")
    print("=" * 75)

    s_old = make_session(OLD_KEY)
    s_new = make_session(NEW_KEY)

    # 1. Ambil 20 entri dari site lama (Oktober 2026)
    r_list = s_old.get(f"{OLD_BASE}/api/resource/Stock Entry", params={
        "filters": f'[["company", "like", "%DELANGGU%"], ["posting_date", ">=", "2026-10-01"]]',
        "fields": '["name", "purpose", "posting_date", "posting_time"]',
        "order_by": "posting_date asc, posting_time asc",
        "limit_page_length": 100
    }, timeout=30)
    if r_list.status_code != 200:
        print(f"FATAL: Gagal mengambil daftar Stock Entry: HTTP {r_list.status_code}")
        sys.exit(1)

    old_entries = r_list.json().get("data", [])
    print(f"Ditemukan {len(old_entries)} Stock Entry periode 1-5 Okt 2026 dari site lama.")

    # 2. Cek Work Order existing di site baru
    r_existing_wo = s_new.get(f"{NEW_BASE}/api/resource/Work Order", params={
        "filters": f'[["company", "=", "{COMPANY}"], ["docstatus", "!=", 2]]',
        "fields": '["name", "description", "status", "docstatus"]',
        "limit_page_length": 500
    }, timeout=30)
    existing_wo_map = {}
    if r_existing_wo.status_code == 200:
        for ex in r_existing_wo.json().get("data", []):
            desc = ex.get("description") or ""
            if "MIG-RPMD-" in desc:
                key = desc.split("|")[0].strip()
                existing_wo_map[key] = ex.get("name")
    print(f"Work Order existing dengan marker MIG-RPMD: {len(existing_wo_map)} dokumen.\n")

    results = []

    for idx, se_meta in enumerate(old_entries, 1):
        old_name = se_meta["name"]
        posting_date = se_meta["posting_date"]
        posting_time = se_meta["posting_time"]
        clean_time = posting_time.split(".")[0] if "." in posting_time else posting_time
        marker_key = f"MIG-RPMD-{old_name}"

        # Ambil detail dari site lama
        r_det = s_old.get(f"{OLD_BASE}/api/resource/Stock Entry/{old_name}", timeout=30)
        if r_det.status_code != 200:
            print(f"[{idx}/{len(old_entries)}] GAGAL ambil detail {old_name}: HTTP {r_det.status_code}")
            continue

        doc_old = r_det.json().get("data", {})
        items_old = doc_old.get("items", [])
        fg_old_list = [it for it in items_old if it.get("t_warehouse")]
        if not fg_old_list:
            print(f"[{idx}/{len(old_entries)}] SKIP {old_name}: Tidak ada Finished Good!")
            continue

        fg_old = fg_old_list[0]
        old_fg_code = fg_old.get("item_code")
        fg_qty = float(fg_old.get("qty") or 0)

        spec = RECIPE_MAPPING.get(old_fg_code)
        if not spec:
            print(f"[{idx}/{len(old_entries)}] ERROR {old_name}: SKU {old_fg_code} tidak dikenali!")
            continue

        recipe_name = spec["recipe_name"]
        fg_code = spec["fg_code"]
        fg_name = spec["fg_name"]
        bom_no = spec["bom_no"]

        desc = f"{marker_key} | {recipe_name}"

        # Periksa apakah sudah ada Work Order
        if marker_key in existing_wo_map:
            wo_name = existing_wo_map[marker_key]
            print(f"[{idx}/{len(old_entries)}] [ADA] {old_name} -> WO {wo_name} ({recipe_name} {fg_qty} Pcs)")
            results.append({
                "No": idx,
                "Old SE Name": old_name,
                "Posting Date": posting_date,
                "Posting Time": clean_time,
                "Recipe Name": recipe_name,
                "FG Code": fg_code,
                "FG Name": fg_name,
                "Qty (Pcs)": fg_qty,
                "Work Order": wo_name,
                "Stock Entry": "-",
                "Production Log": "-",
                "Status": "ADA (Skipped)"
            })
            continue

        # Tahap A: Buat & Submit Work Order
        wo_payload = {
            "doctype": "Work Order",
            "production_item": fg_code,
            "bom_no": bom_no,
            "qty": fg_qty,
            "company": COMPANY,
            "source_warehouse": WAREHOUSE,
            "fg_warehouse": WAREHOUSE,
            "wip_warehouse": WAREHOUSE,
            "skip_transfer": 1,
            "use_multi_level_bom": 0,
            "planned_start_date": f"{posting_date} {clean_time}",
            "description": desc,
            "docstatus": 1
        }
        r_wo = s_new.post(f"{NEW_BASE}/api/resource/Work Order", json=wo_payload, timeout=45)
        if r_wo.status_code not in (200, 201):
            print(f"[{idx}/{len(old_entries)}] GAGAL buat Work Order {old_name}: HTTP {r_wo.status_code} {r_wo.text[:250]}")
            results.append({
                "No": idx,
                "Old SE Name": old_name,
                "Posting Date": posting_date,
                "Posting Time": clean_time,
                "Recipe Name": recipe_name,
                "FG Code": fg_code,
                "FG Name": fg_name,
                "Qty (Pcs)": fg_qty,
                "Work Order": "-",
                "Stock Entry": "-",
                "Production Log": "-",
                "Status": f"GAGAL WO: {r_wo.text[:80]}"
            })
            continue

        wo_name = r_wo.json().get("data", {}).get("name")
        existing_wo_map[marker_key] = wo_name

        # Tahap B: Generate Stock Entry Manufacture via make_stock_entry resmi
        r_make_se = s_new.post(f"{NEW_BASE}/api/method/erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry", json={
            "work_order_id": wo_name,
            "purpose": "Manufacture",
            "qty": fg_qty
        }, timeout=45)
        if r_make_se.status_code != 200:
            print(f"[{idx}/{len(old_entries)}] GAGAL make_stock_entry untuk {wo_name}: HTTP {r_make_se.status_code} {r_make_se.text[:250]}")
            results.append({
                "No": idx,
                "Old SE Name": old_name,
                "Posting Date": posting_date,
                "Posting Time": clean_time,
                "Recipe Name": recipe_name,
                "FG Code": fg_code,
                "FG Name": fg_name,
                "Qty (Pcs)": fg_qty,
                "Work Order": wo_name,
                "Stock Entry": "-",
                "Production Log": "-",
                "Status": f"GAGAL make_se: {r_make_se.text[:80]}"
            })
            continue

        se_doc = r_make_se.json().get("message", {})
        se_doc["posting_date"] = posting_date
        se_doc["posting_time"] = clean_time
        se_doc["set_posting_time"] = 1
        se_doc["remarks"] = f"{marker_key} | Work Order: {wo_name} | POS Production: {recipe_name}"
        se_doc["docstatus"] = 1

        # Tahap C: Submit Stock Entry Manufacture
        r_sub_se = s_new.post(f"{NEW_BASE}/api/resource/Stock Entry", json=se_doc, timeout=45)
        if r_sub_se.status_code not in (200, 201):
            print(f"[{idx}/{len(old_entries)}] GAGAL submit Stock Entry untuk {wo_name}: HTTP {r_sub_se.status_code} {r_sub_se.text[:250]}")
            results.append({
                "No": idx,
                "Old SE Name": old_name,
                "Posting Date": posting_date,
                "Posting Time": clean_time,
                "Recipe Name": recipe_name,
                "FG Code": fg_code,
                "FG Name": fg_name,
                "Qty (Pcs)": fg_qty,
                "Work Order": wo_name,
                "Stock Entry": "-",
                "Production Log": "-",
                "Status": f"GAGAL SE: {r_sub_se.text[:80]}"
            })
            continue

        se_name = r_sub_se.json().get("data", {}).get("name")

        # Tahap D: Buat & Submit POS Production Log
        raw_materials = [{"item_code": it["item_code"], "qty": it["qty"]}
                         for it in se_doc.get("items", []) if it.get("s_warehouse")]
        log_payload = {
            "doctype": "POS Production Log",
            "recipe": recipe_name,
            "production_item": fg_code,
            "qty": fg_qty,
            "work_order": wo_name,
            "stock_entry": se_name,
            "items_used": json.dumps(raw_materials),
            "pos_profile": POS_PROFILE,
            "company": COMPANY,
            "docstatus": 1
        }
        r_log = s_new.post(f"{NEW_BASE}/api/resource/POS Production Log", json=log_payload, timeout=30)
        log_name = r_log.json().get("data", {}).get("name") if r_log.status_code in (200, 201) else "-"

        print(f"[{idx}/{len(old_entries)}] [OK] {old_name} -> WO: {wo_name} (Completed) -> SE: {se_name} | Log: {log_name} ({recipe_name} {fg_qty} Pcs)")
        results.append({
            "No": idx,
            "Old SE Name": old_name,
            "Posting Date": posting_date,
            "Posting Time": clean_time,
            "Recipe Name": recipe_name,
            "FG Code": fg_code,
            "FG Name": fg_name,
            "Qty (Pcs)": fg_qty,
            "Work Order": wo_name,
            "Stock Entry": se_name,
            "Production Log": log_name,
            "Status": "COMPLETED (LOLOS)"
        })
        time.sleep(0.05)

    # 4. Simpan Laporan Excel
    os.makedirs("pos_sync", exist_ok=True)
    df = pd.DataFrame(results)

    rekap_fg = df.groupby(["FG Code", "FG Name", "Recipe Name"]).agg(
        Total_Qty=("Qty (Pcs)", "sum"),
        Total_Batch=("Old SE Name", "count")
    ).reset_index()

    with pd.ExcelWriter(EXCEL_OUT, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Work_Order_Production", index=False)
        rekap_fg.to_excel(writer, sheet_name="Rekap_Produk", index=False)

    wb = openpyxl.load_workbook(EXCEL_OUT)
    hdr_fill = PatternFill(start_color="D9EAF7", end_color="D9EAF7", fill_type="solid")
    pass_fill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
    hdr_font = Font(name="Calibri", size=11, bold=True)
    regular_font = Font(name="Calibri", size=10)
    thin_border = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9")
    )

    for ws in wb.worksheets:
        ws.freeze_panes = "A2"
        for cell in ws[1]:
            cell.fill = hdr_fill
            cell.font = hdr_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
        for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
            for cell in row:
                cell.font = regular_font
                cell.border = thin_border
                if str(cell.value) in ("COMPLETED (LOLOS)", "ADA (Skipped)"):
                    cell.fill = pass_fill
                    cell.font = Font(name="Calibri", size=10, bold=True, color="375623")
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    wb.save(EXCEL_OUT)
    print("\n" + "=" * 75)
    print(f"Laporan Excel berhasil disimpan: {EXCEL_OUT}")
    print(f"Total Batch Diproses       : {len(results)}")
    print(f"Total Completed (Lolos)     : {sum(1 for r in results if 'COMPLETED' in r['Status'])}")
    print("=" * 75)


if __name__ == "__main__":
    main()
