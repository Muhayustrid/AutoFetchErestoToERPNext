"""
Injeksi Stock Reconciliation Gudang Bahan Baku ke ERPNext Cloud (ropierpnext.frappe.cloud).
Sumber: Data Stock Opname eResto per 30 September 2026 jam 11:24:00.
Target: Gudang Bahan Baku - JURI (PT. JUARA ROTI INDONESIA).
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
WAREHOUSE = "Gudang Bahan Baku - JURI"
POSTING_DATE = "2026-09-30"
POSTING_TIME = "11:24:00"
PURPOSE = "Opening Stock"
EXPENSE_ACCOUNT = "1171.000 - Pembukaan sementara - JURI"
COST_CENTER = "Main - JURI"

ITEMS_BB = [
    # 1. BB0004 Air Galon Produksi (1 Galon = 19000 ml)
    {"sku": "BB0004", "name": "Air Galon Produksi", "item_code": "BB260004", "item_name": "Air Galon",
     "eresto_qty": 33.0, "eresto_uom": "Galon", "eresto_rate": 17000.0,
     "custom_uom": "Galon", "custom_qty_after": 33.0, "conversion_factor": 19000.0,
     "stock_uom": "ml", "native_qty": 33.0 * 19000.0, "native_rate": 17000.0 / 19000.0},

    # 2. BB0169 Butterblend (1 kg = 1000 g)
    {"sku": "BB0169", "name": "Butterblend", "item_code": "BB260005", "item_name": "Margarine Croissant",
     "eresto_qty": 75.0, "eresto_uom": "kg", "eresto_rate": 29489.47,
     "custom_uom": "kg", "custom_qty_after": 75.0, "conversion_factor": 1000.0,
     "stock_uom": "g", "native_qty": 75.0 * 1000.0, "native_rate": 29489.47 / 1000.0},

    # 3. BB0095 Filling Butter (1 ctn = 12000 g)
    {"sku": "BB0095", "name": "Filling Butter", "item_code": "BB260007", "item_name": "Filling Butter",
     "eresto_qty": 21.0, "eresto_uom": "ctn", "eresto_rate": 467576.85,
     "custom_uom": "ctn", "custom_qty_after": 21.0, "conversion_factor": 12000.0,
     "stock_uom": "g", "native_qty": 21.0 * 12000.0, "native_rate": 467576.85 / 12000.0},

    # 4. BB0056 Filling Coklat (1 kg = 1000 g)
    {"sku": "BB0056", "name": "Filling Coklat", "item_code": "BB260008", "item_name": "Filling Coklat",
     "eresto_qty": 730.0, "eresto_uom": "kg", "eresto_rate": 41425.27,
     "custom_uom": "kg", "custom_qty_after": 730.0, "conversion_factor": 1000.0,
     "stock_uom": "g", "native_qty": 730.0 * 1000.0, "native_rate": 41425.27 / 1000.0},

    # 5. BB0083 Filling Keju (1 kg = 1000 g)
    {"sku": "BB0083", "name": "Filling Keju", "item_code": "BB260009", "item_name": "Filling Keju",
     "eresto_qty": 240.0, "eresto_uom": "kg", "eresto_rate": 72180.03,
     "custom_uom": "kg", "custom_qty_after": 240.0, "conversion_factor": 1000.0,
     "stock_uom": "g", "native_qty": 240.0 * 1000.0, "native_rate": 72180.03 / 1000.0},

    # 6. BB0060 Garam (1 kg = 1000 g)
    {"sku": "BB0060", "name": "Garam", "item_code": "BB260010", "item_name": "Garam",
     "eresto_qty": 210.0, "eresto_uom": "kg", "eresto_rate": 7249.89,
     "custom_uom": "kg", "custom_qty_after": 210.0, "conversion_factor": 1000.0,
     "stock_uom": "g", "native_qty": 210.0 * 1000.0, "native_rate": 7249.89 / 1000.0},

    # 7. BB0069 Gula Halus (1 ctn = 10000 g)
    {"sku": "BB0069", "name": "Gula Halus", "item_code": "BB260011", "item_name": "Gula Halus",
     "eresto_qty": 53.0, "eresto_uom": "ctn", "eresto_rate": 180180.00,
     "custom_uom": "ctn", "custom_qty_after": 53.0, "conversion_factor": 10000.0,
     "stock_uom": "g", "native_qty": 53.0 * 10000.0, "native_rate": 180180.00 / 10000.0},

    # 8. BB0070 Gula Pasir (1 zak = 50000 g)
    {"sku": "BB0070", "name": "Gula Pasir", "item_code": "BB260012", "item_name": "Gula Pasir",
     "eresto_qty": 4.0, "eresto_uom": "zak", "eresto_rate": 849956.47,
     "custom_uom": "zak", "custom_qty_after": 4.0, "conversion_factor": 50000.0,
     "stock_uom": "g", "native_qty": 4.0 * 50000.0, "native_rate": 849956.47 / 50000.0},

    # 9. BB0155-b Karet Gelang (1 Pack = 1050 Pcs)
    {"sku": "BB0155-b", "name": "Karet Gelang", "item_code": "BB260002", "item_name": "Karet Gelang Produksi",
     "eresto_qty": 88.0, "eresto_uom": "Pack", "eresto_rate": 24232.68,
     "custom_uom": "Pack", "custom_qty_after": 88.0, "conversion_factor": 1050.0,
     "stock_uom": "Pcs", "native_qty": 88.0 * 1050.0, "native_rate": 24232.68 / 1050.0},

    # 10. BB0057 Margarine Dough (1 ctn = 15000 g)
    {"sku": "BB0057", "name": "Margarine Dough", "item_code": "BB260014", "item_name": "Margarine Dough",
     "eresto_qty": 94.0, "eresto_uom": "ctn", "eresto_rate": 256764.13,
     "custom_uom": "ctn", "custom_qty_after": 94.0, "conversion_factor": 15000.0,
     "stock_uom": "g", "native_qty": 94.0 * 15000.0, "native_rate": 256764.13 / 15000.0},

    # 11. BB0094 Margarine Krim (1 ctn = 15000 g)
    {"sku": "BB0094", "name": "Margarine Krim", "item_code": "BB260015", "item_name": "Margarine Krim",
     "eresto_qty": 41.0, "eresto_uom": "ctn", "eresto_rate": 256756.76,
     "custom_uom": "ctn", "custom_qty_after": 41.0, "conversion_factor": 15000.0,
     "stock_uom": "g", "native_qty": 41.0 * 15000.0, "native_rate": 256756.76 / 15000.0},

    # 12. BB0015 Pasta Coffee Caramel (1 kg = 1000 g)
    {"sku": "BB0015", "name": "Pasta Coffee Caramel", "item_code": "BB260016", "item_name": "Pasta Coffee Caramel",
     "eresto_qty": 216.0, "eresto_uom": "kg", "eresto_rate": 231876.64,
     "custom_uom": "kg", "custom_qty_after": 216.0, "conversion_factor": 1000.0,
     "stock_uom": "g", "native_qty": 216.0 * 1000.0, "native_rate": 231876.64 / 1000.0},

    # 13. BB0120 Plastik Krim (1 Pcs = 1 Pcs)
    {"sku": "BB0120", "name": "Plastik Krim", "item_code": "BB260019", "item_name": "Plastik Krim",
     "eresto_qty": 30000.0, "eresto_uom": "Pcs", "eresto_rate": 395.54,
     "custom_uom": "Pcs", "custom_qty_after": 30000.0, "conversion_factor": 1.0,
     "stock_uom": "Pcs", "native_qty": 30000.0, "native_rate": 395.54},

    # 14. BB0121-b Plastik Paking Dough (1 kg = 160 Pcs)
    {"sku": "BB0121-b", "name": "Plastik Paking Dough", "item_code": "BB260020", "item_name": "Plastik Paking Dough",
     "eresto_qty": 195.0, "eresto_uom": "kg", "eresto_rate": 38182.11,
     "custom_uom": "kg", "custom_qty_after": 195.0, "conversion_factor": 160.0,
     "stock_uom": "Pcs", "native_qty": 195.0 * 160.0, "native_rate": 38182.11 / 160.0},

    # 15. BHP260024 Plastik Sampah (1 kg = 1 kg)
    {"sku": "BB0138", "name": "Plastik Sampah", "item_code": "BHP260024", "item_name": "Plastik Sampah",
     "eresto_qty": 548.0, "eresto_uom": "kg", "eresto_rate": 20962.40,
     "custom_uom": "kg", "custom_qty_after": 548.0, "conversion_factor": 1.0,
     "stock_uom": "kg", "native_qty": 548.0, "native_rate": 20962.40},

    # 16. BB0194 Plastik Wayang (1 Pack = 1 Pack)
    {"sku": "BB0194", "name": "Plastik Wayang", "item_code": "BB260021", "item_name": "Plastik Wayang",
     "eresto_qty": 8.0, "eresto_uom": "Pack", "eresto_rate": 15215.69,
     "custom_uom": "Pack", "custom_qty_after": 8.0, "conversion_factor": 1.0,
     "stock_uom": "Pack", "native_qty": 8.0, "native_rate": 15215.69},

    # 17. BB0132 Sarung Tangan Plastik (1 Pack = 1 Pack)
    {"sku": "BB0132", "name": "Sarung Tangan Plastik", "item_code": "BHP260027", "item_name": "Sarung Tangan Plastik",
     "eresto_qty": 33.0, "eresto_uom": "Pack", "eresto_rate": 21374.07,
     "custom_uom": "Pack", "custom_qty_after": 33.0, "conversion_factor": 1.0,
     "stock_uom": "Pack", "native_qty": 33.0, "native_rate": 21374.07},

    # 18. BB0144 Susu Dough (1 zak = 25000 g)
    {"sku": "BB0144", "name": "Susu Dough", "item_code": "BB260025", "item_name": "Susu Dough",
     "eresto_qty": 10.0, "eresto_uom": "zak", "eresto_rate": 1325000.00,
     "custom_uom": "zak", "custom_qty_after": 10.0, "conversion_factor": 25000.0,
     "stock_uom": "g", "native_qty": 10.0 * 25000.0, "native_rate": 1325000.00 / 25000.0},

    # 19. BB0216 Susu Gempi (1 kg = 1000 g)
    {"sku": "BB0216", "name": "Susu Gempi", "item_code": "BB260026", "item_name": "Susu Gempi",
     "eresto_qty": 25.0, "eresto_uom": "kg", "eresto_rate": 80666.67,
     "custom_uom": "kg", "custom_qty_after": 25.0, "conversion_factor": 1000.0,
     "stock_uom": "g", "native_qty": 25.0 * 1000.0, "native_rate": 80666.67 / 1000.0},

    # 20. BB0154 Tepung Dough (1 zak = 25000 g)
    {"sku": "BB0154", "name": "Tepung Dough", "item_code": "BB260028", "item_name": "Tepung Dough",
     "eresto_qty": 74.0, "eresto_uom": "zak", "eresto_rate": 221922.20,
     "custom_uom": "zak", "custom_qty_after": 74.0, "conversion_factor": 25000.0,
     "stock_uom": "g", "native_qty": 74.0 * 25000.0, "native_rate": 221922.20 / 25000.0},

    # 21. BB0158 Tepung Krim (1 zak = 25000 g)
    {"sku": "BB0158", "name": "Tepung Krim", "item_code": "BB260029", "item_name": "Tepung Krim",
     "eresto_qty": 79.0, "eresto_uom": "zak", "eresto_rate": 166537.21,
     "custom_uom": "zak", "custom_qty_after": 79.0, "conversion_factor": 25000.0,
     "stock_uom": "g", "native_qty": 79.0 * 25000.0, "native_rate": 166537.21 / 25000.0},
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
    print(f"Total item yang akan diinjeksi: {len(ITEMS_BB)}")

    # 1. Cek keberadaan dan Item Defaults
    print("\n[1/4] Memeriksa Item Code dan Item Defaults di ERPNext...")
    for it in ITEMS_BB:
        code = it["item_code"]
        st, res = req("GET", f"/api/resource/Item/{urllib.parse.quote(code)}")
        if st != 200:
            print(f"  FATAL: {code} tidak ditemukan di ERPNext!")
            sys.exit(1)
        doc = res.get("data", {})
        defaults = doc.get("item_defaults", [])
        juri = next((d for d in defaults if d.get("company") == COMPANY), None)
        if not juri or not juri.get("default_inventory_account"):
            acc = "1143.000 - Raw Material - JURI"
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

    for it in ITEMS_BB:
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
    excel_path = "pos_sync/Injeksi_Reco_Gudang_Bahan_Baku.xlsx"
    df_report = pd.DataFrame(ITEMS_BB)
    df_report["erpnext_reco_no"] = reco_name
    df_report["warehouse"] = WAREHOUSE
    df_report["posting_date"] = f"{POSTING_DATE} {POSTING_TIME}"
    df_report["total_value"] = df_report["custom_qty_after"] * df_report["eresto_rate"]
    
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df_report.to_excel(writer, sheet_name="Reco_Gudang_Bahan_Baku", index=False)
    print(f"\nLaporan injeksi disimpan di: {excel_path}")

if __name__ == "__main__":
    main()
