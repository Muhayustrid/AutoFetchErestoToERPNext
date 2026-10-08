import json
import os
import requests

URL = "https://ropierpnext.frappe.cloud"
HEADERS = {"Authorization": f"token {os.environ.get('ERPNEXT_API_KEY', '')}"}

AUDIT_DOCTYPES = [
    # POS
    "POS Closing Shift",
    "POS Invoice",
    "POS Opening Shift",
    # Sales
    "Delivery Note",
    "Sales Order",
    # Buying
    "Purchase Receipt",
    "Purchase Order",
    # Manufacturing & Stock
    "Stock Entry",
    "Work Order",
    "Stock Reconciliation",
    # Accounts
    "Journal Entry",
]

def fetch_all(dt):
    out = []
    start = 0
    while True:
        params = {
            "fields": json.dumps(["name", "docstatus", "creation", "modified", "company"]),
            "limit_page_length": 500,
            "limit_start": start,
        }
        r = requests.get(f"{URL}/api/resource/{dt}", headers=HEADERS, params=params, timeout=30)
        if r.status_code != 200:
            break
        rows = r.json().get("data", [])
        if not rows:
            break
        out.extend(rows)
        start += len(rows)
        if len(rows) < 500:
            break
    return out

def main():
    census = {}
    for dt in AUDIT_DOCTYPES:
        rows = fetch_all(dt)
        census[dt] = rows
        print(f"{dt:25s}: {len(rows)} docs")

    os.makedirs("audit_logs", exist_ok=True)
    with open("audit_logs/prod_census_pre_cleanup.json", "w") as f:
        json.dump(census, f, indent=2)
    print("\nSaved census to audit_logs/prod_census_pre_cleanup.json")

if __name__ == "__main__":
    main()
