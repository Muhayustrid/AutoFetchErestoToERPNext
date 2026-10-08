# Buat Company baru di ERPNext lokal via API key.
# Sumber: experiments/Kandidat_Company_Baru.xlsx sheet Siap_Dibuat.
# Company baru nginduk ke OUTLET REGULER (group, anak JURI GROUP)
# supaya CoA-nya sama: create_chart_of_accounts_based_on =
# Existing Company + existing_company = OUTLET REGULER.
# Abbr wajib unik 2-8 char. Idempoten: skip yg sudah ada.
# Kredensial via env: ERPNEXT_URL, ERPNEXT_API_KEY.
import os
import sys

import pandas as pd
import requests

SRC = "Kandidat_Company_Baru.xlsx"


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    base = os.getenv("ERPNEXT_URL", "http://erp.localhost:8081").rstrip("/")
    key = os.getenv("ERPNEXT_API_KEY", "").strip()
    if not key:
        fail("env ERPNEXT_API_KEY kurang")
    s = requests.Session()
    s.headers.update({"Authorization": f"token {key}"})
    me = s.get(f"{base}/api/method/frappe.auth.get_logged_user",
               timeout=30)
    if me.status_code != 200:
        fail(f"API key ditolak: HTTP {me.status_code}")
    print(f"auth OK sebagai {me.json().get('message')}")

    cands = pd.read_excel(SRC, sheet_name="Siap_Dibuat").to_dict("records")
    if not cands:
        print("tidak ada kandidat Siap_Dibuat — selesai")
        return
    existing = {c["name"] for c in s.get(
        f"{base}/api/resource/Company",
        params={"fields": '["name"]', "limit_page_length": 1000},
        timeout=60).json().get("data", [])}

    for c in cands:
        name = str(c["outlet"]).strip()
        if name in existing:
            print(f"SKIP {name}: sudah ada")
            continue
        abbr = "".join(w[0] for w in name.split() if w[0].isalnum())[:8].upper()
        payload = {"company_name": name, "abbr": abbr,
                   "country": "Indonesia", "default_currency": "IDR",
                   "parent_company": "OUTLET REGULER",
                   "create_chart_of_accounts_based_on": "Existing Company",
                   "existing_company": "OUTLET REGULER"}
        r = s.post(f"{base}/api/resource/Company", json=payload,
                   timeout=120)
        if r.status_code in (200, 201):
            print(f"OK {name} ({abbr})")
        else:
            print(f"GAGAL {name}: HTTP {r.status_code} {r.text[:200]}")


if __name__ == "__main__":
    main()
