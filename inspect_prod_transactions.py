import os
import json
import requests

URL = "https://ropierpnext.frappe.cloud"
HEADERS = {"Authorization": f"token {os.environ.get('ERPNEXT_API_KEY', '')}"}

DOCTYPES = [
    # Selling
    "Quotation",
    "Sales Order",
    "Delivery Note",
    "Sales Invoice",
    "POS Invoice",
    "POS Opening Entry",
    "POS Closing Entry",
    "POS Opening Shift",
    "POS Closing Shift",
    # Buying
    "Request for Quotation",
    "Supplier Quotation",
    "Purchase Order",
    "Purchase Receipt",
    "Purchase Invoice",
    # Stock
    "Material Request",
    "Stock Entry",
    "Stock Reconciliation",
    "Pick List",
    "Delivery Trip",
    "Landed Cost Voucher",
    # Manufacturing
    "Production Plan",
    "Work Order",
    "Job Card",
    "Subcontracting Order",
    "Subcontracting Receipt",
    # Accounts
    "Payment Entry",
    "Journal Entry",
    "Payment Reconciliation",
    "Period Closing Voucher",
    "Asset Capitalization",
    "Asset Repair",
    # HR / Payroll
    "Payroll Entry",
    "Salary Slip",
    "Expense Claim",
]

def check_doctype(dt):
    try:
        # Check count by docstatus (0: Draft, 1: Submitted, 2: Cancelled)
        # Using GET /api/resource/{dt}?fields=["docstatus"]
        params = {
            "fields": json.dumps(["name", "docstatus", "creation", "modified"]),
            "limit_page_length": 5000,
        }
        r = requests.get(f"{URL}/api/resource/{dt}", headers=HEADERS, params=params, timeout=30)
        if r.status_code == 404:
            return {"exists": False, "total": 0, "draft": 0, "submitted": 0, "cancelled": 0, "samples": []}
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}: {r.text[:100]}"}
        
        data = r.json().get("data", [])
        total = len(data)
        draft = sum(1 for d in data if d.get("docstatus") == 0)
        submitted = sum(1 for d in data if d.get("docstatus") == 1)
        cancelled = sum(1 for d in data if d.get("docstatus") == 2)
        samples = [d.get("name") for d in data[:5]]
        return {
            "exists": True,
            "total": total,
            "draft": draft,
            "submitted": submitted,
            "cancelled": cancelled,
            "samples": samples,
            "data": data,
        }
    except Exception as e:
        return {"error": str(e)}

def main():
    print(f"=== SENSUS TRANSAKSI DI {URL} ===\n")
    summary = []
    total_tx_all = 0
    total_tx_non_je = 0
    
    for dt in DOCTYPES:
        res = check_doctype(dt)
        if "error" in res:
            print(f"[-] {dt:25s}: ERROR ({res['error']})")
        elif not res.get("exists"):
            pass # DocType does not exist on this site
        else:
            tot = res["total"]
            if tot > 0:
                total_tx_all += tot
                if dt != "Journal Entry":
                    total_tx_non_je += tot
                print(f"[+] {dt:25s}: Total={tot:5d} (Draft={res['draft']:4d}, Submitted={res['submitted']:4d}, Cancelled={res['cancelled']:4d}) | Cth: {res['samples'][:3]}")
                summary.append((dt, res))
            else:
                print(f"[0] {dt:25s}: 0")

    print("\n" + "="*50)
    print(f"Total semua transaksi               : {total_tx_all}")
    print(f"Total transaksi NON-Journal Entry   : {total_tx_non_je}")
    print("="*50)

if __name__ == "__main__":
    main()
