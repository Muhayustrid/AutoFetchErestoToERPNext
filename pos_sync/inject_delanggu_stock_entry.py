"""Migrasi Stock Entry Produksi Delanggu dari Site Lama ke Site Baru.

Sumber: https://rotiropi.j.frappe.cloud
Target: https://ropierpnext.frappe.cloud
Company: RS PKU MUHAMMADIYAH DELANGGU
Warehouse: Stores - RPMD

Aturan Sesuai Instruksi User:
1. Resep mengikuti POS Production Recipe / BOM baru di website target (bukan resep lama).
2. Produksi menghasilkan Roti Matang (PJO*), BUKAN produk jual (RP*/CR*/GM*).
3. Produksi TIDAK mengonsumsi kemasan/paper bag (PEL260076) atau box gempi (PEL260069),
   karena kemasan otomatis terpotong saat penjualan POS Invoice (Product Bundle).
4. Ruang lingkup: 20 entri Manufacture pada periode aktif 1-5 Oktober 2026.
   (Bulan September telah dikunci lewat Stock Reconciliation 30 Sep 18:00 RECO-RPMD-261005001).
5. Idempoten via marker remarks `MIG-RPMD-<OLD_SE_NAME>`, aman di-rerun.
6. Menghasilkan laporan Excel verifikasi di pos_sync/Injeksi_Stock_Entry_Delanggu.xlsx.
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
EXCEL_OUT = "pos_sync/Injeksi_Stock_Entry_Delanggu.xlsx"

# Pemetaan dari produk lama ke resep & item matang baru
RECIPE_MAPPING = {
    "RP001": {
        "recipe_name": "ROPI BUTTER",
        "fg_code": "PJO2603",
        "fg_name": "Ropi Butter Matang",
        "bom_no": "BOM-PJO2603-001",
        "materials": [
            {"item_code": "PJ260012", "item_name": "Dough Ropi Butter", "ratio": 1.0, "uom": "Pcs"},
            {"item_code": "PJ260016", "item_name": "Krim Kopi", "ratio": 0.04, "uom": "Pcs"}
        ]
    },
    "RP002": {
        "recipe_name": "ROPI COKLAT",
        "fg_code": "PJO2601",
        "fg_name": "Ropi Coklat Matang",
        "bom_no": "BOM-PJO2601-001",
        "materials": [
            {"item_code": "PJ260013", "item_name": "Dough Ropi Coklat", "ratio": 1.0, "uom": "Pcs"},
            {"item_code": "PJ260016", "item_name": "Krim Kopi", "ratio": 0.04, "uom": "Pcs"}
        ]
    },
    "RP003": {
        "recipe_name": "ROPI KEJU",
        "fg_code": "PJO2602",
        "fg_name": "Ropi Keju Matang",
        "bom_no": "BOM-PJO2602-001",
        "materials": [
            {"item_code": "PJ260014", "item_name": "Dough Ropi Keju", "ratio": 1.0, "uom": "Pcs"},
            {"item_code": "PJ260016", "item_name": "Krim Kopi", "ratio": 0.04, "uom": "Pcs"}
        ]
    },
    "CR001": {
        "recipe_name": "Croissant",
        "fg_code": "PJO2605",
        "fg_name": "Croissant Matang",
        "bom_no": "BOM-PJO2605-001",
        "materials": [
            {"item_code": "PJ260010", "item_name": "Dough Croissant", "ratio": 1.0, "uom": "Pcs"},
            {"item_code": "BB260038", "item_name": "Gula Cair Sachet", "ratio": 0.3, "uom": "Sachet"},
            {"item_code": "BB260046", "item_name": "Olesan Pastry", "ratio": 3.0, "uom": "g"}
        ]
    },
    "GM001": {
        "recipe_name": "Gempi",
        "fg_code": "PJO2604",
        "fg_name": "Gempi Matang",
        "bom_no": "BOM-PJO2604-001",
        "materials": [
            {"item_code": "PJ260011", "item_name": "Dough Gempi", "ratio": 1.0, "uom": "Pcs"},
            {"item_code": "PEL260077", "item_name": "Plastik Alas Gempi", "ratio": 1.0, "uom": "Pcs"}
        ]
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
    print("=" * 70)
    print("MIGRASI STOCK ENTRY PRODUKSI DELANGGU (eResto/Old Site -> New Site)")
    print("=" * 70)

    s_old = make_session(OLD_KEY)
    s_new = make_session(NEW_KEY)

    # 1. Tarik daftar Stock Entry dari site lama per Oktober 2026
    r_list = s_old.get(f"{OLD_BASE}/api/resource/Stock Entry", params={
        "filters": f'[["company", "like", "%DELANGGU%"], ["posting_date", ">=", "2026-10-01"]]',
        "fields": '["name", "purpose", "posting_date", "posting_time"]',
        "order_by": "posting_date asc, posting_time asc",
        "limit_page_length": 100
    }, timeout=30)
    if r_list.status_code != 200:
        print(f"FATAL: Gagal mengambil daftar Stock Entry dari site lama: HTTP {r_list.status_code}")
        sys.exit(1)

    old_entries = r_list.json().get("data", [])
    print(f"Ditemukan {len(old_entries)} Stock Entry periode 1-5 Okt 2026 di site lama.")

    # 2. Cek Stock Entry yang sudah ada di site baru (idempotency check)
    r_existing = s_new.get(f"{NEW_BASE}/api/resource/Stock Entry", params={
        "filters": f'[["company", "=", "{COMPANY}"], ["docstatus", "!=", 2]]',
        "fields": '["name", "remarks", "docstatus"]',
        "limit_page_length": 500
    }, timeout=30)
    existing_map = {}
    if r_existing.status_code == 200:
        for ex in r_existing.json().get("data", []):
            rem = ex.get("remarks") or ""
            if "MIG-RPMD-" in rem:
                key = rem.split("|")[0].strip()
                existing_map[key] = ex.get("name")
    print(f"Stock Entry existing dengan marker MIG-RPMD: {len(existing_map)} dokumen.\n")

    results = []

    for idx, se_meta in enumerate(old_entries, 1):
        old_name = se_meta["name"]
        posting_date = se_meta["posting_date"]
        posting_time = se_meta["posting_time"]
        if "." in posting_time:
            clean_time = posting_time.split(".")[0]
        else:
            clean_time = posting_time

        marker_key = f"MIG-RPMD-{old_name}"

        # Ambil detail lengkap dari site lama
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

        recipe_spec = RECIPE_MAPPING.get(old_fg_code)
        if not recipe_spec:
            print(f"[{idx}/{len(old_entries)}] ERROR {old_name}: SKU {old_fg_code} tidak ada di RECIPE_MAPPING!")
            continue

        recipe_name = recipe_spec["recipe_name"]
        new_fg_code = recipe_spec["fg_code"]
        new_fg_name = recipe_spec["fg_name"]
        bom_no = recipe_spec["bom_no"]

        remarks = f"{marker_key} | POS Production: {recipe_name}"

        # Periksa apakah sudah ada
        if marker_key in existing_map:
            new_se_name = existing_map[marker_key]
            print(f"[{idx}/{len(old_entries)}] [ADA] {old_name} -> {new_se_name} ({recipe_name} {fg_qty} Pcs)")
            results.append({
                "No": idx,
                "Old SE Name": old_name,
                "Posting Date": posting_date,
                "Posting Time": clean_time,
                "Old FG Code": old_fg_code,
                "New FG Code": new_fg_code,
                "New FG Name": new_fg_name,
                "Qty (Pcs)": fg_qty,
                "Recipe Name": recipe_name,
                "BOM No": bom_no,
                "New SE Name": new_se_name,
                "Status": "ADA (Skipped)"
            })
            continue

        # Bangun item bahan baku sesuai resep baru (tanpa kemasan)
        new_items_payload = []
        materials_snapshot = []
        for mat in recipe_spec["materials"]:
            needed_qty = round(mat["ratio"] * fg_qty, 4)
            new_items_payload.append({
                "item_code": mat["item_code"],
                "qty": needed_qty,
                "s_warehouse": WAREHOUSE,
                "uom": mat["uom"],
                "stock_uom": mat["uom"],
                "conversion_factor": 1.0,
                "is_finished_item": 0
            })
            materials_snapshot.append({
                "item_code": mat["item_code"],
                "qty": needed_qty
            })

        # Baris Finished Good (roti matang PJO*)
        new_items_payload.append({
            "item_code": new_fg_code,
            "qty": fg_qty,
            "t_warehouse": WAREHOUSE,
            "uom": "Pcs",
            "stock_uom": "Pcs",
            "conversion_factor": 1.0,
            "is_finished_item": 1
        })

        se_payload = {
            "doctype": "Stock Entry",
            "stock_entry_type": "Manufacture",
            "purpose": "Manufacture",
            "company": COMPANY,
            "set_posting_time": 1,
            "posting_date": posting_date,
            "posting_time": clean_time,
            "bom_no": bom_no,
            "fg_completed_qty": fg_qty,
            "remarks": remarks,
            "docstatus": 1,
            "items": new_items_payload
        }

        r_create = s_new.post(f"{NEW_BASE}/api/resource/Stock Entry", json=se_payload, timeout=60)
        if r_create.status_code not in (200, 201):
            print(f"[{idx}/{len(old_entries)}] GAGAL inject {old_name}: HTTP {r_create.status_code} {r_create.text[:300]}")
            results.append({
                "No": idx,
                "Old SE Name": old_name,
                "Posting Date": posting_date,
                "Posting Time": clean_time,
                "Old FG Code": old_fg_code,
                "New FG Code": new_fg_code,
                "New FG Name": new_fg_name,
                "Qty (Pcs)": fg_qty,
                "Recipe Name": recipe_name,
                "BOM No": bom_no,
                "New SE Name": "-",
                "Status": f"GAGAL: {r_create.text[:100]}"
            })
            continue

        se_resp = r_create.json().get("data", {})
        new_se_name = se_resp.get("name")
        existing_map[marker_key] = new_se_name

        # Buat juga POS Production Log untuk pencatatan riwayat POS Next
        log_payload = {
            "doctype": "POS Production Log",
            "recipe": recipe_name,
            "production_item": new_fg_code,
            "qty": fg_qty,
            "items_used": json.dumps(materials_snapshot),
            "stock_entry": new_se_name,
            "pos_profile": POS_PROFILE,
            "company": COMPANY,
            "docstatus": 1
        }
        r_log = s_new.post(f"{NEW_BASE}/api/resource/POS Production Log", json=log_payload, timeout=30)
        log_name = r_log.json().get("data", {}).get("name") if r_log.status_code in (200, 201) else "-"

        print(f"[{idx}/{len(old_entries)}] [OK] {old_name} -> {new_se_name} ({recipe_name} {fg_qty} Pcs) | Log: {log_name}")
        results.append({
            "No": idx,
            "Old SE Name": old_name,
            "Posting Date": posting_date,
            "Posting Time": clean_time,
            "Old FG Code": old_fg_code,
            "New FG Code": new_fg_code,
            "New FG Name": new_fg_name,
            "Qty (Pcs)": fg_qty,
            "Recipe Name": recipe_name,
            "BOM No": bom_no,
            "New SE Name": new_se_name,
            "Status": "SUBMITTED (LOLOS)"
        })
        time.sleep(0.05)

    # 3. Buat Excel Report
    os.makedirs("pos_sync", exist_ok=True)
    df = pd.DataFrame(results)

    # Rekap per jenis produk
    rekap_fg = df.groupby(["New FG Code", "New FG Name", "Recipe Name"]).agg(
        Total_Qty=("Qty (Pcs)", "sum"),
        Total_Batch=("Old SE Name", "count")
    ).reset_index()

    with pd.ExcelWriter(EXCEL_OUT, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Stock_Entry_Delanggu", index=False)
        rekap_fg.to_excel(writer, sheet_name="Rekap_Produk", index=False)

    # Styling
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
                if str(cell.value) in ("SUBMITTED (LOLOS)", "ADA (Skipped)"):
                    cell.fill = pass_fill
                    cell.font = Font(name="Calibri", size=10, bold=True, color="375623")
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    wb.save(EXCEL_OUT)
    print("\n" + "=" * 70)
    print(f"Laporan Excel berhasil disimpan: {EXCEL_OUT}")
    print(f"Total Stock Entry Diproses : {len(results)}")
    print(f"Total Submitted (Lolos)    : {sum(1 for r in results if 'SUBMITTED' in r['Status'])}")
    print(f"Total Existing (Ada)       : {sum(1 for r in results if 'ADA' in r['Status'])}")
    print("=" * 70)


if __name__ == "__main__":
    main()
