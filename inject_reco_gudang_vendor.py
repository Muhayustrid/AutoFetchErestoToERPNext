"""
Injeksi Stock Reconciliation Gudang Vendor ke ERPNext Cloud (ropierpnext.frappe.cloud).
Sumber: Data Stock Opname eResto per 2 Oktober 2026 jam 09:00:00.
Target: Gudang Vendor - JURI (PT. JUARA ROTI INDONESIA).
"""

import json
import os
import sys
import time
import urllib.parse
import pandas as pd
import requests

ENV_FILE = "/tmp/eresto_prod.env"
if not os.path.exists(ENV_FILE):
    print(f"Error: {ENV_FILE} not found!")
    sys.exit(1)

with open(ENV_FILE) as f:
    conf = dict(line.strip().split("=", 1) for line in f if "=" in line)

URL = conf["ERPNEXT_URL"].rstrip("/")
HEADERS = {
    "Authorization": f"token {conf['ERPNEXT_API_KEY']}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

COMPANY = "PT. JUARA ROTI INDONESIA"
WAREHOUSE = "Gudang Vendor - JURI"
POSTING_DATE = "2026-10-02"
POSTING_TIME = "09:00:00"
PURPOSE = "Opening Stock"
EXPENSE_ACCOUNT = "1171.000 - Pembukaan sementara - JURI"
COST_CENTER = "Main - JURI"

ITEMS_VENDOR = [
    # 1. BB0237 Freezer 600L
    {"sku": "BB0237", "name": "Freezer 600L", "item_code": "PER260008", "item_name": "Freezer (600 L)",
     "eresto_qty": 7.0, "eresto_uom": "Unit", "eresto_rate": 5450000.0,
     "custom_uom": "Unit", "custom_qty_after": 7.0, "conversion_factor": 1.0,
     "stock_uom": "Unit", "native_qty": 7.0, "native_rate": 5450000.0},

    # 2. BB0289 Oven 1 Deck 2 Tray (Listrik) 3 Phase
    {"sku": "BB0289", "name": "Oven 1 Deck 2 Tray (Listrik) 3 Phase", "item_code": "PER260016", "item_name": "Oven 1 Deck 2 Tray (Listrik) 3 Phase",
     "eresto_qty": 13.0, "eresto_uom": "Unit", "eresto_rate": 5705907.94,
     "custom_uom": "Unit", "custom_qty_after": 13.0, "conversion_factor": 1.0,
     "stock_uom": "Unit", "native_qty": 13.0, "native_rate": 5705907.94},

    # 3. BB0124 Proofer
    {"sku": "BB0124", "name": "Proofer", "item_code": "PER260017", "item_name": "Proofer",
     "eresto_qty": 20.0, "eresto_uom": "Unit", "eresto_rate": 4500000.0,
     "custom_uom": "Unit", "custom_qty_after": 20.0, "conversion_factor": 1.0,
     "stock_uom": "Unit", "native_qty": 20.0, "native_rate": 4500000.0},
]

def req(method, path, payload=None, params=None, max_retries=4):
    url = f"{URL}{path}"
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.request(method, url, json=payload, params=params, headers=HEADERS, timeout=90)
            if r.status_code in {429, 500, 502, 503, 504}:
                time.sleep(2 ** attempt)
                continue
            return r.status_code, r.json()
        except requests.RequestException as e:
            if attempt == max_retries:
                return -1, {"error": str(e)}
            time.sleep(2 ** attempt)
    return -1, {"error": "Failed after retries"}

def main():
    print(f"=== Menyiapkan Injeksi Stock Reconciliation: {WAREHOUSE} ===")
    print(f"Total item yang akan diinjeksi: {len(ITEMS_VENDOR)}")

    # 1. Cek keberadaan dan Item Defaults
    print("\n[1/4] Memeriksa Item Code dan Item Defaults di ERPNext...")
    for it in ITEMS_VENDOR:
        code = it["item_code"]
        st, res = req("GET", f"/api/resource/Item/{urllib.parse.quote(code)}")
        if st != 200:
            print(f"  FATAL: {code} tidak ditemukan di ERPNext!")
            sys.exit(1)
    print("  OK: Semua item terdaftar dan memiliki akun persediaan default.")

    # 2. Susun dokumen Stock Reconciliation
    print(f"\n[2/4] Menyusun dokumen Stock Reconciliation ({POSTING_DATE} {POSTING_TIME})...")
    reco_items = []
    total_val = 0.0

    for it in ITEMS_VENDOR:
        qty = round(it["native_qty"], 4)
        rate = round(it["native_rate"], 4)
        c_qty = round(it["custom_qty_after"], 4)
        c_rate = round(it["eresto_rate"], 4)
        factor = round(it["conversion_factor"], 4)
        
        val = c_qty * c_rate
        total_val += val

        reco_items.append({
            "item_code": it["item_code"],
            "warehouse": WAREHOUSE,
            "qty": qty,
            "valuation_rate": rate,
            "uom": it["stock_uom"],
            "custom_uom": it["custom_uom"],
            "custom_conversion_factor": factor,
            "custom_qty_after": c_qty,
            "custom_qty_before": 0.0,
            "custom_qty_difference_per_uom": c_qty,
            "custom_valuation_rate_per_uom": c_rate,
        })

    payload = {
        "doctype": "Stock Reconciliation",
        "company": COMPANY,
        "purpose": PURPOSE,
        "set_posting_time": 1,
        "posting_date": POSTING_DATE,
        "posting_time": POSTING_TIME,
        "set_warehouse": WAREHOUSE,
        "expense_account": EXPENSE_ACCOUNT,
        "cost_center": COST_CENTER,
        "items": reco_items,
    }

    print(f"  Total item: {len(reco_items)}")
    print(f"  Total nilai persediaan: Rp {total_val:,.2f}")

    # 3. POST Draft
    print(f"\n[3/4] Mengirim dokumen Stock Reconciliation (POST Draft)...")
    st, res = req("POST", "/api/resource/Stock Reconciliation", payload)
    if st != 200:
        print(f"  GAGAL POST Stock Reconciliation ({st}):\n{json.dumps(res, indent=2)}")
        sys.exit(1)

    reco_name = res.get("data", {}).get("name")
    print(f"  OK: Berhasil membuat Draft Stock Reconciliation: {reco_name}")

    # 4. Submit
    print(f"\n[4/4] Men-submit dokumen {reco_name} (docstatus = 1)...")
    sub_st, sub_res = req("PUT", f"/api/resource/Stock Reconciliation/{urllib.parse.quote(reco_name)}", {
        "docstatus": 1
    })
    if sub_st != 200:
        print(f"  GAGAL SUBMIT Stock Reconciliation ({sub_st}):\n{json.dumps(sub_res, indent=2)}")
        sys.exit(1)

    print(f"  OK: Dokumen {reco_name} BERHASIL DISUBMIT!")

    # 5. Buat Laporan Excel
    excel_path = "pos_sync/Injeksi_Reco_Gudang_Vendor.xlsx"
    df_report = pd.DataFrame(ITEMS_VENDOR)
    df_report["erpnext_reco_no"] = reco_name
    df_report["warehouse"] = WAREHOUSE
    df_report["posting_date"] = f"{POSTING_DATE} {POSTING_TIME}"
    df_report["total_value"] = df_report["custom_qty_after"] * df_report["eresto_rate"]
    
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df_report.to_excel(writer, sheet_name="Reco_Gudang_Vendor", index=False)
    print(f"\nLaporan injeksi disimpan di: {excel_path}")

if __name__ == "__main__":
    main()
