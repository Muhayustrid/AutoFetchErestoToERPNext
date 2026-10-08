"""Cek 7 FRC aktif: company, customer, MoP, FY.
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

FRC = [
    "RSU San Medica (FRC)",
    "Bangka Tengah (FRC)",
    "Plaza Haji alQosbah (FRC)",
    "RS Medina Garut (FRC)",
    "Jambi Sarulangun (FRC)",
    "Sungai Penuh (FRC)",
    "Mitra Swalayan Gombong (FRC)",
]

s = requests.Session()
s.headers.update({"Authorization": "token " + KEY})


def get(path, params=None):
    r = s.get(BASE + path, params=params, timeout=60)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:300]}


for name in FRC:
    st_c, _ = get("/api/resource/Company/" + urllib.parse.quote(name))
    st, d = get("/api/resource/Customer", params={
        "fields": '["name","customer_name","customer_group","is_internal_customer","represents_company"]',
        "filters": f'[["customer_name","=","{name}"]]',
        "limit_page_length": 5})
    cust = d.get("data", []) if st == 200 else []
    print(f"{name}: company HTTP {st_c} | customer: "
          f"{json.dumps(cust, ensure_ascii=False)[:300] if cust else 'TIDAK ADA'}")
    if cust:
        cn = cust[0]["name"]
        st2, d2 = get("/api/resource/Customer/" + urllib.parse.quote(cn))
        if st2 == 200:
            comps = [c.get("company") for c in d2["data"].get("companies", [])]
            print(f"   -> allowed JURI: {'PT. JUARA ROTI INDONESIA' in comps} "
                  f"companies={comps}")

# MoP totals (apakah baris FRC sudah ada?)
for mop in ["Cash", "QRIS", "Debit Card", "Credit Card"]:
    st, d = get("/api/resource/Mode of Payment/" + urllib.parse.quote(mop))
    n = len(d.get("data", {}).get("accounts", [])) if st == 200 else -1
    print(f"MoP {mop}: {n} rows")
st, d = get("/api/resource/Fiscal Year/2026")
if st == 200:
    print("FY 2026 total:", len(d["data"].get("companies", [])))
# abbr clash check
for a in ["RSMSF", "BTF", "PHAQF", "RMGF", "JSF", "SPF", "MSGF",
          "RSMS", "BTFRC", "MSGFRC"]:
    st, d = get("/api/resource/Company", params={
        "fields": '["name","abbr"]',
        "filters": f'[["abbr","=","{a}"]]', "limit_page_length": 5})
    rows = d.get("data", []) if st == 200 else []
    if rows:
        print(f"abbr {a} BENTROK: {rows}")
print("cek abbr selesai")
