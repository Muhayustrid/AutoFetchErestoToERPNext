"""Verifikasi pra-eksekusi: duplikat Anna, RSUP 404, customer Anna,
baris MoP per abbr, pola akun per company.
Env: ERPNEXT_URL, ERPNEXT_API_KEY."""
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


# 1. Anna: dua varian case — apakah 1 doc atau 2?
st, d = get("/api/resource/Company", params={
    "fields": '["name","abbr","parent_company","is_group"]',
    "filters": '[["name","like","%ANNA LASMANAH%"]]',
    "limit_page_length": 10})
print("ANNA like-query:", st, json.dumps(d, ensure_ascii=False)[:800])

# 2. RSUP Palembang company ada?
st, d = get("/api/resource/Company/" + urllib.parse.quote("RSUP Palembang"))
print("RSUP company:", st, str(d)[:200])

# 3. Customer Anna + RSUP?
for cust in ["RSUD Hj. ANNA LASMANAH BANJARNEGARA", "RSUP Palembang"]:
    st, d = get("/api/resource/Customer", params={
        "fields": '["name","customer_name","customer_group","is_internal_customer","represents_company"]',
        "filters": f'[["customer_name","=","{cust}"]]',
        "limit_page_length": 5})
    print(f"Customer {cust!r}:", st, json.dumps(d, ensure_ascii=False)[:600])

# 4. Baris MoP Cash untuk RHALB (Anna) — ada?
st, d = get("/api/resource/Mode of Payment/Cash")
accs = d.get("data", {}).get("accounts", []) if st == 200 else []
hit = [a for a in accs if a.get("company", "").upper().find("ANNA") >= 0]
print("MoP Cash rows Anna:", json.dumps(hit, ensure_ascii=False)[:600] or "TIDAK ADA")
print("MoP Cash total rows:", len(accs))

# 5. Akun TJBK (contoh anak OUTLET REGULER): nama akun kas & qris
st, d = get("/api/resource/Account", params={
    "fields": '["name","account_name","company"]',
    "filters": '[["company","=","TOSERBA JADI BARU KEBUMEN"],["account_name","like","%Kas%"]]',
    "limit_page_length": 20})
print("Akun Kas TJBK:", st, json.dumps(d, ensure_ascii=False)[:1000])

# 6. Supplier JURI: isi companies sekarang
st, d = get("/api/resource/Supplier/PT. JUARA ROTI INDONESIA")
if st == 200:
    doc = d["data"]
    print("Supplier JURI companies:", json.dumps(doc.get("companies", []))[:500])
    print("is_internal_supplier:", doc.get("is_internal_supplier"),
          "represents_company:", repr(doc.get("represents_company")))

# 7. Abbr RSUPP bentrok?
st, d = get("/api/resource/Company", params={
    "fields": '["name","abbr"]',
    "filters": '[["abbr","=","RSUPP"]]',
    "limit_page_length": 5})
print("Abbr RSUPP bentrok:", st, json.dumps(d, ensure_ascii=False)[:300])
