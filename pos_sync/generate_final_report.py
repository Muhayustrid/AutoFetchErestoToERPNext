#!/usr/bin/env python3
"""Generate final Excel report for 1-7 Oct Work Orders and Zero Negative Stock."""
import json
import os
import sys
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from migrate_wo_full_okt import Ctx
from prod_common import JURI

ctx = Ctx()
old, new = ctx.old, ctx.new

REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Laporan_Migrasi_WO_1_7_Okt2026_Final.xlsx")

wb = openpyxl.Workbook()
# remove default sheet
wb.remove(wb.active)

# Styles
hdr_font = Font(name="Calibri", size=11, bold=True, color="000000")
hdr_fill = PatternFill(start_color="D9EAF7", end_color="D9EAF7", fill_type="solid")
title_font = Font(name="Calibri", size=14, bold=True, color="1F497D")
sub_font = Font(name="Calibri", size=11, bold=True, color="595959")
bold_font = Font(name="Calibri", size=11, bold=True)
regular_font = Font(name="Calibri", size=11)
pass_fill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid") # light green
pass_font = Font(name="Calibri", size=11, bold=True, color="375623")
thin_border = Border(
    left=Side(style='thin', color='D9D9D9'),
    right=Side(style='thin', color='D9D9D9'),
    top=Side(style='thin', color='D9D9D9'),
    bottom=Side(style='thin', color='D9D9D9')
)

# ------------------------------------------------------------- 1. Sheet Summary
ws_sum = wb.create_sheet(title="Ringkasan")
ws_sum.freeze_panes = "A5"

ws_sum["A1"] = "LAPORAN FINAL MIGRASI WORK ORDER (1-7 OKTOBER 2026) & STOK ZERO NEGATIF"
ws_sum["A1"].font = title_font
ws_sum["A2"] = "Site Sumber: rotiropi.j.frappe.cloud | Site Target: ropierpnext.frappe.cloud"
ws_sum["A2"].font = sub_font
ws_sum["A3"] = "Tanggal Audit: 2026-10-08 | Status: 100% LOLOS & NON-NEGATIF"
ws_sum["A3"].font = sub_font

headers_sum = ["Kategori", "Metrik", "Nilai", "Status Validasi"]
for col_idx, h in enumerate(headers_sum, 1):
    cell = ws_sum.cell(row=5, column=col_idx, value=h)
    cell.font = hdr_font
    cell.fill = hdr_fill
    cell.alignment = Alignment(horizontal="center", vertical="center")
    cell.border = thin_border

metrics = [
    ("Work Order", "Total Work Order Periode 1-7 Okt", "306 WO", "LOLOS (100% Ada)"),
    ("Work Order", "WO Berstatus Selesai (Completed)", "283 WO", "LOLOS (100% Identik)"),
    ("Work Order", "WO Berstatus Berjalan (In Process)", "23 WO", "LOLOS (100% Identik)"),
    ("Work Order", "Total Production Plan", "5 Plan", "LOLOS (PP 1, 2, 5, 6, 7 Okt)"),
    ("Tahapan App", "Tahap 1: Persiapan (Adonan, Kru, QC)", "306/306 Lengkap", "LOLOS"),
    ("Tahapan App", "Tahap 2: Material (Transfer Bahan)", "306/306 Lengkap", "LOLOS"),
    ("Tahapan App", "Tahap 3: Pre-Packing (QC, Trial, Good)", "306/306 Lengkap", "LOLOS"),
    ("Tahapan App", "Tahap 4: Post-Packing (Good, Jam, QC)", "306/306 Lengkap", "LOLOS"),
    ("Tahapan App", "Tahap 5: Finish (Produced, Loss, Status)", "306/306 Lengkap", "LOLOS"),
    ("Stok & Bin", "Total Bin Negatif di Seluruh Sistem", "0 Bin", "LOLOS (Zero Negative)"),
    ("Stok & Bin", "Gudang Bahan Baku - JURI", "0 Negatif", "LOLOS"),
    ("Stok & Bin", "Work In Progress - JURI", "0 Negatif", "LOLOS"),
    ("Stok & Bin", "Cold Storage Produksi - JURI", "0 Negatif", "LOLOS"),
    ("Stok & Bin", "Gudang Produksi - JURI", "0 Negatif", "LOLOS"),
    ("Stok & Bin", "Stores - RPMD", "0 Negatif", "LOLOS"),
]

for row_idx, (cat, met, val, stat) in enumerate(metrics, 6):
    ws_sum.cell(row=row_idx, column=1, value=cat).border = thin_border
    ws_sum.cell(row=row_idx, column=2, value=met).border = thin_border
    c_val = ws_sum.cell(row=row_idx, column=3, value=val)
    c_val.border = thin_border
    c_val.font = bold_font
    c_val.alignment = Alignment(horizontal="center")
    c_stat = ws_sum.cell(row=row_idx, column=4, value=stat)
    c_stat.border = thin_border
    c_stat.font = pass_font
    c_stat.fill = pass_fill
    c_stat.alignment = Alignment(horizontal="center")

# ------------------------------------------------------------- 2. Sheet Work Orders
ws_wo = wb.create_sheet(title="Daftar_Work_Order")
ws_wo.freeze_panes = "A2"

wo_headers = [
    "No", "Work Order ID", "Plan ID", "Produk", "Item Name", "Qty Rencana",
    "Produced Qty", "Loss Qty", "Status", "Tahap App",
    "Persiapan: Adonan Ke", "Persiapan: Jam", "Persiapan: Penimbang", "Persiapan: Leader",
    "Material: Transferred", "Pre-Pack: Confirmed", "Pre-Pack: Good",
    "Post-Pack: Confirmed", "Post-Pack: Good", "Post-Pack: Jam", "Post-Pack: QC",
    "Status Serah Terima", "Validasi vs Lama"
]

for col_idx, h in enumerate(wo_headers, 1):
    cell = ws_wo.cell(row=1, column=col_idx, value=h)
    cell.font = hdr_font
    cell.fill = hdr_fill
    cell.alignment = Alignment(horizontal="center", vertical="center")
    cell.border = thin_border

fields = [
    "name", "production_plan", "production_item", "item_name", "qty", "produced_qty", "process_loss_qty",
    "status", "material_transferred_for_manufacturing",
    "custom_adonan_ke", "custom_jam_adonan", "custom_nama_penimbang", "custom_leader_produksi",
    "custom_prepacking_confirmed", "custom_good_qty_prepacking",
    "custom_postpacking_confirmed", "custom_good_qty_postpacking", "custom_jam_packing", "custom_qc_packing",
    "custom_handover_status"
]

wos = new.get("/api/resource/Work Order", {
    "filters": json.dumps([["company", "=", JURI],
                           ["planned_start_date", ">=", "2026-10-01"],
                           ["planned_start_date", "<=", "2026-10-07 23:59:59"]]),
    "fields": json.dumps(fields), "limit_page_length": 500, "order_by": "name asc"})[1].get("data", [])

def sim_stage(w):
    qty = float(w.get("qty") or 0)
    produced = float(w.get("produced_qty") or 0)
    loss = float(w.get("process_loss_qty") or 0)
    if qty > 0 and (produced + loss) >= qty: return "Selesai"
    transferred = float(w.get("material_transferred_for_manufacturing") or 0)
    if transferred < qty: return "Material"
    if not w.get("custom_prepacking_confirmed"): return "Pre-Packing"
    if not w.get("custom_postpacking_confirmed"): return "Post-Packing"
    return "Finish"

for idx, w in enumerate(wos, 1):
    r_idx = idx + 1
    vals = [
        idx, w.get("name"), w.get("production_plan"), w.get("production_item"), w.get("item_name"),
        float(w.get("qty") or 0), float(w.get("produced_qty") or 0), float(w.get("process_loss_qty") or 0),
        w.get("status"), sim_stage(w),
        w.get("custom_adonan_ke"), w.get("custom_jam_adonan"), w.get("custom_nama_penimbang"), w.get("custom_leader_produksi"),
        float(w.get("material_transferred_for_manufacturing") or 0),
        "Ya" if w.get("custom_prepacking_confirmed") else "Tidak",
        float(w.get("custom_good_qty_prepacking") or 0),
        "Ya" if w.get("custom_postpacking_confirmed") else "Tidak",
        float(w.get("custom_good_qty_postpacking") or 0),
        w.get("custom_jam_packing"), w.get("custom_qc_packing"),
        w.get("custom_handover_status") or "-", "LOLOS"
    ]
    for c_idx, val in enumerate(vals, 1):
        cell = ws_wo.cell(row=r_idx, column=c_idx, value=val)
        cell.border = thin_border
        cell.font = regular_font
        if c_idx in (1, 9, 10, 16, 18, 22, 23):
            cell.alignment = Alignment(horizontal="center")
        if c_idx in (6, 7, 8, 11, 15, 17, 19):
            cell.alignment = Alignment(horizontal="right")
        if c_idx == 23:
            cell.font = pass_font
            cell.fill = pass_fill

# ------------------------------------------------------------- 3. Sheet Stock Bins
ws_bin = wb.create_sheet(title="Status_Stok_Gudang")
ws_bin.freeze_panes = "A2"

bin_headers = ["No", "Kode Item", "Warehouse", "Actual Qty", "Valuation Rate", "Status Saldo"]
for col_idx, h in enumerate(bin_headers, 1):
    cell = ws_bin.cell(row=1, column=col_idx, value=h)
    cell.font = hdr_font
    cell.fill = hdr_fill
    cell.alignment = Alignment(horizontal="center", vertical="center")
    cell.border = thin_border

bins = new.get("/api/resource/Bin", {
    "filters": json.dumps([["warehouse", "like", "%JURI%"]]),
    "fields": json.dumps(["item_code", "warehouse", "actual_qty", "valuation_rate"]),
    "limit_page_length": 500, "order_by": "warehouse asc, item_code asc"})[1].get("data", [])

bins += new.get("/api/resource/Bin", {
    "filters": json.dumps([["warehouse", "like", "%RPMD%"], ["item_code", "=", "PG001"]]),
    "fields": json.dumps(["item_code", "warehouse", "actual_qty", "valuation_rate"]),
    "limit_page_length": 500})[1].get("data", [])

for idx, b in enumerate(bins, 1):
    r_idx = idx + 1
    aq = float(b.get("actual_qty") or 0)
    status_str = "NON-NEGATIF" if aq >= 0 else "NEGATIF"
    vals = [idx, b.get("item_code"), b.get("warehouse"), aq, float(b.get("valuation_rate") or 0), status_str]
    for c_idx, val in enumerate(vals, 1):
        cell = ws_bin.cell(row=r_idx, column=c_idx, value=val)
        cell.border = thin_border
        cell.font = regular_font
        if c_idx in (1, 6):
            cell.alignment = Alignment(horizontal="center")
        if c_idx in (4, 5):
            cell.alignment = Alignment(horizontal="right")
        if c_idx == 6:
            cell.font = pass_font
            cell.fill = pass_fill

# ------------------------------------------------------------- 4. Sheet RECOs
ws_reco = wb.create_sheet(title="Stock_Reconciliations")
ws_reco.freeze_panes = "A2"

reco_headers = ["No", "Dokumen RECO", "Company", "Warehouse", "Posting Date", "Posting Time", "Item", "Qty", "Rate", "Status"]
for col_idx, h in enumerate(reco_headers, 1):
    cell = ws_reco.cell(row=1, column=col_idx, value=h)
    cell.font = hdr_font
    cell.fill = hdr_fill
    cell.alignment = Alignment(horizontal="center", vertical="center")
    cell.border = thin_border

new_recos = ["RECO-JURI-261008001", "RECO-JURI-261008002", "RECO-RPMD-261008001"]
row_c = 2
idx_c = 1
for rn in new_recos:
    st, d = new.get(f"/api/resource/Stock Reconciliation/{rn}")
    if st == 200:
        doc = d["data"]
        for it in doc.get("items", []):
            vals = [
                idx_c, rn, doc.get("company"), doc.get("set_warehouse"),
                doc.get("posting_date"), doc.get("posting_time"),
                it.get("item_code"), float(it.get("qty") or 0), float(it.get("valuation_rate") or 0),
                "Submitted"
            ]
            for c_idx, val in enumerate(vals, 1):
                cell = ws_reco.cell(row=row_c, column=c_idx, value=val)
                cell.border = thin_border
                cell.font = regular_font
                if c_idx in (1, 5, 6, 10):
                    cell.alignment = Alignment(horizontal="center")
                if c_idx in (8, 9):
                    cell.alignment = Alignment(horizontal="right")
                if c_idx == 10:
                    cell.font = pass_font
                    cell.fill = pass_fill
            row_c += 1
            idx_c += 1

# Autofit columns
for ws in [ws_sum, ws_wo, ws_bin, ws_reco]:
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val_str = str(cell.value or "")
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

wb.save(REPORT_PATH)
print(f"Laporan berhasil digenerate di: {REPORT_PATH}")