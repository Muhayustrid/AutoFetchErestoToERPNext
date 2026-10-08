import os
import json
import requests

URL = "http://127.0.0.1:8082"
HEADERS = {"Authorization": f"token {os.environ.get('ERPNEXT_OLD_API_KEY', '')}"}

DOCTYPES = [
    "Quotation",
    "Sales Order",
    "Delivery Note",
    "Sales Invoice",
    "POS Invoice",
    "Purchase Order",
    "Purchase Receipt",
    "Purchase Invoice",
    "Material Request",
    "Stock Entry",
    "Stock Reconciliation",
    "Work Order",
    "Payment Entry",
    "Journal Entry",
]

def check_doctype(dt):
    try:
        params = {
            "fields": json.dumps(["name", "docstatus", "creation", "modified"]),
            "limit_page_length": 5000,
        }
        r = requests.get(f"{URL}/api/resource/{dt}", headers=HEADERS, params=params, timeout=30)
        if r.status_code == 404:
            return {"exists": False, "total": 0}
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}: {r.text[:100]}"}
        
        data = r.json().get("data", [])
        total = len(data)
        draft = sum(1 for d in data if d.get("docstatus") == 0)
        submitted = sum(1 for d in data if d.get("docstatus") == 1)
        cancelled = sum(1 for d in data if d.get("docstatus") == 2)
        return {
            "exists": True,
            "total": total,
            "draft": draft,
            "submitted": submitted,
            "cancelled": cancelled,
        }
    except Exception as e:
        return {"error": str(e)}

def main():
    print(f"=== SENSUS TRANSAKSI DI ERPNEXT LAMA ({URL}) ===\n")
    for dt in DOCTYPES:
        res = check_doctype(dt)
        if "error" in res:
            print(f"[-] {dt:25s}: ERROR ({res['error']})")
        elif not res.get("exists"):
            pass
        else:
            tot = res["total"]
            print(f"[+] {dt:25s}: Total={tot:5d} (Draft={res['draft']:4d}, Submitted={res['submitted']:4d}, Cancelled={res['cancelled']:4d})")

if __name__ == "__main__":
    main()
