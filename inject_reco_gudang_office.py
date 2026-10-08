"""
Injeksi Stock Reconciliation Gudang Office (GA) ke ERPNext Cloud (ropierpnext.frappe.cloud).
Sumber: Data Stock Opname eResto SAGOFF.021026.001 per 2 Oktober 2026 jam 10:00:00.
Target: Gudang GA - JURI (PT. JUARA ROTI INDONESIA).
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
WAREHOUSE = "Gudang GA - JURI"
POSTING_DATE = "2026-10-02"
POSTING_TIME = "10:00:00"
PURPOSE = "Opening Stock"
EXPENSE_ACCOUNT = "1171.000 - Pembukaan sementara - JURI"
COST_CENTER = "Main - JURI"

ITEMS_OFFICE = [
    # 1. BB0210 Sepatu Produksi
    {"sku": "BB0210", "name": "Sepatu Produksi", "item_code": "SG260005", "item_name": "Sepatu Pabrik",
     "eresto_qty": 8.0, "eresto_uom": "Pcs", "eresto_rate": 106995.20,
     "custom_uom": "Pcs", "custom_qty_after": 8.0, "conversion_factor": 1.0,
     "stock_uom": "Pair", "native_qty": 8.0, "native_rate": 106995.20},

    # 2. BB0212 Tinta Hitam Printer
    {"sku": "BB0212", "name": "Tinta Hitam Printer", "item_code": "BHP260008", "item_name": "Tinta Hitam Printer",
     "eresto_qty": 6.0, "eresto_uom": "Pcs", "eresto_rate": 92343.08,
     "custom_uom": "Pcs", "custom_qty_after": 6.0, "conversion_factor": 1.0,
     "stock_uom": "Pcs", "native_qty": 6.0, "native_rate": 92343.08},

    # 3. BB0214 Seragam Celana Pabrik
    {"sku": "BB0214", "name": "Seragam Celana Pabrik", "item_code": "SG260013", "item_name": "Seragam Celana Pabrik",
     "eresto_qty": 28.0, "eresto_uom": "Pcs", "eresto_rate": 69635.26,
     "custom_uom": "Pcs", "custom_qty_after": 28.0, "conversion_factor": 1.0,
     "stock_uom": "Pcs", "native_qty": 28.0, "native_rate": 69635.26},

    # 4. BB0215 Seragam Baju Pabrik
    {"sku": "BB0215", "name": "Seragam Baju Pabrik", "item_code": "SG260014", "item_name": "Seragam Baju Pabrik",
     "eresto_qty": 89.0, "eresto_uom": "Pcs", "eresto_rate": 102665.30,
     "custom_uom": "Pcs", "custom_qty_after": 89.0, "conversion_factor": 1.0,
     "stock_uom": "Pcs", "native_qty": 89.0, "native_rate": 102665.30},

    # 5. BB0253 Kertas A4
    {"sku": "BB0253", "name": "Kertas A4", "item_code": "ATK260039", "item_name": "Kertas A4",
     "eresto_qty": 37.0, "eresto_uom": "Pack", "eresto_rate": 38831.92,
     "custom_uom": "Pack", "custom_qty_after": 37.0, "conversion_factor": 1.0,
     "stock_uom": "rim", "native_qty": 37.0, "native_rate": 38831.92},
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
    print(f"Total item yang akan diinjeksi: {len(ITEMS_OFFICE)}")

    # 1. Cek keberadaan dan Item Defaults
    print("\n[1/4] Memeriksa Item Code dan Item Defaults di ERPNext...")
    for it in ITEMS_OFFICE:
        code = it["item_code"]
        st, res = req("GET", f"/api/resource/Item/{urllib.parse.quote(code)}")
        if st != 200:
            print(f"  FATAL: {code} tidak ditemukan di ERPNext!")
            sys.exit(1)
        doc = res.get("data", {})
        defaults = doc.get("item_defaults", [])
        juri = next((d for d in defaults if d.get("company") == COMPANY), None)
        if not juri or not juri.get("default_inventory_account"):
            acc = "1145.000 - Finished Good - JURI"
            print(f"  Menambahkan Item Default untuk {code} (Acc: {acc})...")
            if not juri:
                defaults.append({
                    "company": COMPANY,
                    "default_warehouse": WAREHOUSE,
                    "default_inventory_account": acc
                })
                req("PUT", f"/api/resource/Item/{urllib.parse.quote(code)}", {"item_defaults": defaults})
            else:
                req("POST", "/api/method/frappe.client.set_value", {
                    "doctype": "Item Default",
                    "name": juri["name"],
                    "fieldname": "default_inventory_account",
                    "value": acc
                })
    print("  OK: Semua item terdaftar dan memiliki akun persediaan default.")

    # 2. Susun dokumen Stock Reconciliation
    print(f"\n[2/4] Menyusun dokumen Stock Reconciliation ({POSTING_DATE} {POSTING_TIME})...")
    reco_items = []
    total_val = 0.0

    for it in ITEMS_OFFICE:
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
    excel_path = "pos_sync/Injeksi_Reco_Gudang_Office.xlsx"
    df_report = pd.DataFrame(ITEMS_OFFICE)
    df_report["erpnext_reco_no"] = reco_name
    df_report["warehouse"] = WAREHOUSE
    df_report["posting_date"] = f"{POSTING_DATE} {POSTING_TIME}"
    df_report["total_value"] = df_report["custom_qty_after"] * df_report["eresto_rate"]
    
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df_report.to_excel(writer, sheet_name="Reco_Gudang_Office", index=False)
    print(f"\nLaporan injeksi disimpan di: {excel_path}")

if __name__ == "__main__":
    main()
