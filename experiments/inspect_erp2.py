"""Inspect lanjutan: Supplier JURI full, MoP Cash/QRIS/Debit full,
FY 2026 company count, franchise check eResto.
Env: ERPNEXT_URL, ERPNEXT_API_KEY, ERESTO_TOKEN/EMAIL/USER_ID."""
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

s = requests.Session()
s.headers.update({"Authorization": "token " + KEY})


def get(path, params=None):
    r = s.get(BASE + path, params=params, timeout=60)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:500]}


def show(title, st, d, limit=4000):
    print("=" * 70)
    print(title, "HTTP", st)
    print(json.dumps(d, indent=1, ensure_ascii=False)[:limit])


# 1. Supplier PT. JUARA ROTI INDONESIA full
st, d = get("/api/resource/Supplier/PT. JUARA ROTI INDONESIA")
show("SUPPLIER JURI FULL", st, d)
if st != 200:
    # cari nama mirip
    st2, d2 = get("/api/resource/Supplier", params={
        "fields": '["name"]', "limit_page_length": 1000})
    names = [x["name"] for x in d2.get("data", [])]
    hit = [n for n in names if "JUARA" in n.upper() or n.upper().startswith("JURI")]
    print("kandidat supplier JURI:", hit)
    for n in hit:
        st3, d3 = get("/api/resource/Supplier/" + urllib.parse.quote(n))
        show(f"SUPPLIER FULL ({n})", st3, d3)

# 2. MoP Cash / QRIS / Debit Card / Credit Card full (accounts per company)
for mop in ["Cash", "QRIS", "Debit Card", "Credit Card", "Bank Draft", "Wire Transfer"]:
    st, d = get("/api/resource/Mode of Payment/" + urllib.parse.quote(mop))
    if st != 200:
        print(f"MOP {mop}: HTTP {st}")
        continue
    accs = d["data"].get("accounts", [])
    print("=" * 70)
    print(f"MOP {mop}: {len(accs)} accounts")
    for a in accs[:8]:
        print(f"  company={a.get('company')} default={a.get('default_account')}")
    if len(accs) > 8:
        print(f"  ... +{len(accs)-8} lagi")
    # contoh 1 baris penuh
    if accs:
        print("  contoh baris:", json.dumps(accs[0], ensure_ascii=False)[:400])

# 3. FY 2026: jumlah companies + apakah Anna/RHALB & RSUP sudah masuk
st, d = get("/api/resource/Fiscal Year/2026")
if st == 200:
    comps = [c["company"] for c in d["data"].get("companies", [])]
    print("=" * 70)
    print(f"FY 2026 companies: {len(comps)}")
    for target in ["RSUD Hj. ANNA LASMANAH BANJARNEGARA",
                   "RSUD HJ. ANNA LASMANAH BANJARNEGARA",
                   "RSUP Palembang", "TOSERBA JADI BARU KEBUMEN"]:
        print(f"  {target!r} masuk FY: {target in comps}")

# 4. Company Anna varian case: cek exact
for nm in ["RSUD Hj. ANNA LASMANAH BANJARNEGARA",
           "RSUD HJ. ANNA LASMANAH BANJARNEGARA"]:
    st, d = get("/api/resource/Company/" + urllib.parse.quote(nm))
    print(f"Company {nm!r}: HTTP {st}")

# 5. Customer count + group Outlet Franchise sample
st, d = get("/api/resource/Customer", params={
    "fields": '["name","customer_name","customer_group","is_internal_customer","represents_company"]',
    "filters": '[["customer_group","=","Outlet Franchise"]]',
    "limit_page_length": 20})
show("CUSTOMER FRANCHISE sample", st, d, limit=2500)
st, d = get("/api/resource/Customer", params={
    "fields": '["name"]', "limit_page_length": 1000})
if st == 200:
    print("total customers:", len(d.get("data", [])))
