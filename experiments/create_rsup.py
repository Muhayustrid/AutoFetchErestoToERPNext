"""Buat Company RSUP Palembang anak OUTLET REGULER + Customer internal +
relasi Supplier JURI + baris MoP (Cash/QRIS/Debit/Credit) + FY 2026.
Anna Lasmanah SUDAH ADA (company+customer+MoP+FY lengkap) -> skip.
Env: ERPNEXT_URL, ERPNEXT_API_KEY. Idempoten: skip yg sudah ada."""
import json
import os
import sys
import urllib.parse

import requests

BASE = os.getenv("ERPNEXT_URL", "http://127.0.0.1:8081").rstrip("/")
KEY = os.getenv("ERPNEXT_API_KEY", "").strip()
if not KEY:
    print("ERROR: env ERPNEXT_API_KEY kurang", file=sys.stderr)
    sys.exit(1)

RSUP = "RSUP Palembang"
RSUP_ABBR = "RSUPP"
JURI = "PT. JUARA ROTI INDONESIA"

s = requests.Session()
s.headers.update({"Authorization": "token " + KEY})


def get(path, params=None):
    r = s.get(BASE + path, params=params, timeout=60)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:500]}


def post(path, payload):
    r = s.post(BASE + path, json=payload, timeout=120)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:500]}


def put(path, payload):
    r = s.put(BASE + path, json=payload, timeout=120)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:500]}


def exists_company(name):
    st, _ = get("/api/resource/Company/" + urllib.parse.quote(name))
    return st == 200


def exists_customer(name):
    st, d = get("/api/resource/Customer", params={
        "fields": '["name"]',
        "filters": f'[["customer_name","=","{name}"]]',
        "limit_page_length": 5})
    return st == 200 and bool(d.get("data"))


# 1. Company RSUP anak OUTLET REGULER
if exists_company(RSUP):
    print(f"SKIP company {RSUP}: sudah ada")
else:
    st, d = post("/api/resource/Company", {
        "company_name": RSUP, "abbr": RSUP_ABBR,
        "country": "Indonesia", "default_currency": "IDR",
        "parent_company": "OUTLET REGULER",
        "create_chart_of_accounts_based_on": "Existing Company",
        "existing_company": "OUTLET REGULER",
    })
    print(f"Company {RSUP}: HTTP {st} {json.dumps(d)[:300]}")
    if st not in (200, 201):
        print("GAGAL buat company — hentikan", file=sys.stderr)
        sys.exit(1)

# 2. Verifikasi akun RSUP ikut terbentuk
st, d = get("/api/resource/Account", params={
    "fields": '["name"]',
    "filters": f'[["company","=","{RSUP}"]]',
    "limit_page_length": 3})
n_akun = len(d.get("data", [])) if st == 200 else -1
print(f"Akun {RSUP}: HTTP {st}, sample={n_akun} rows (hal1)")
# hitung total via limit 1000
st, d = get("/api/resource/Account", params={
    "fields": '["name"]',
    "filters": f'[["company","=","{RSUP}"]]',
    "limit_page_length": 1000})
print(f"Total akun {RSUP}: {len(d.get('data', [])) if st==200 else 'ERR '+str(st)}")

# 3. Customer internal RSUP (tiru Kebumen)
if exists_customer(RSUP):
    print(f"SKIP customer {RSUP}: sudah ada")
else:
    st, d = post("/api/resource/Customer", {
        "customer_name": RSUP, "customer_type": "Company",
        "customer_group": "Outlet Reguler", "territory": "Indonesia",
        "default_currency": "IDR", "default_price_list": "Harga Outlet",
        "is_internal_customer": 1, "represents_company": RSUP,
        "companies": [{"company": JURI}],
    })
    print(f"Customer {RSUP}: HTTP {st} {json.dumps(d)[:300]}")

# 4. Supplier JURI: tambah RSUP ke companies (Allowed To Transact With)
st, d = get("/api/resource/Supplier/" + urllib.parse.quote(JURI))
if st == 200:
    comps = [c.get("company") for c in d["data"].get("companies", [])]
    if RSUP in comps:
        print(f"SKIP supplier JURI: {RSUP} sudah terdaftar")
    else:
        st2, d2 = put("/api/resource/Supplier/" + urllib.parse.quote(JURI), {
            "companies": [{"company": c} for c in comps] + [{"company": RSUP}]})
        print(f"Supplier JURI +{RSUP}: HTTP {st2} {json.dumps(d2)[:200]}")
else:
    print(f"Supplier JURI: HTTP {st} — lewati")

# 5. MoP: tambah baris RSUP ke Cash/QRIS/Debit/Credit
MAP_AKUN = {
    "Cash": f"1111.003 - Kas Kasir - {RSUP_ABBR}",
    "QRIS": f"1121.005 - Qris - {RSUP_ABBR}",
    "Debit Card": f"1121.002 - Debit Card - {RSUP_ABBR}",
    "Credit Card": f"1121.003 - Credit Card - {RSUP_ABBR}",
}
for mop, akun in MAP_AKUN.items():
    st, d = get("/api/resource/Mode of Payment/" + urllib.parse.quote(mop))
    if st != 200:
        print(f"MoP {mop}: HTTP {st} — lewati")
        continue
    doc = d["data"]
    rows = doc.get("accounts", [])
    if any(a.get("company") == RSUP for a in rows):
        print(f"SKIP MoP {mop}: baris {RSUP} sudah ada")
        continue
    new_rows = [{"company": a.get("company"),
                 "default_account": a.get("default_account")}
                for a in rows] + [{"company": RSUP, "default_account": akun}]
    st2, d2 = put("/api/resource/Mode of Payment/" + urllib.parse.quote(mop),
                  {"accounts": new_rows})
    print(f"MoP {mop} +{RSUP}: HTTP {st2} {json.dumps(d2)[:200]}")

# 6. FY 2026: tambah RSUP
st, d = get("/api/resource/Fiscal Year/2026")
if st == 200:
    comps = [c.get("company") for c in d["data"].get("companies", [])]
    if RSUP in comps:
        print(f"SKIP FY 2026: {RSUP} sudah masuk")
    else:
        st2, d2 = put("/api/resource/Fiscal Year/2026",
                      {"companies": [{"company": c} for c in comps]
                       + [{"company": RSUP}]})
        print(f"FY 2026 +{RSUP}: HTTP {st2} {json.dumps(d2)[:200]}")
else:
    print(f"FY 2026: HTTP {st} — lewati")

print("SELESAI")
