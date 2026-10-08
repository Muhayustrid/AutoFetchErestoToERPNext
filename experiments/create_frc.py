"""Buat 7 Company FRC aktif (nama persis eResto, termasuk "(FRC)")
sbg anak OUTLET REGULER + Customer internal + relasi Supplier JURI +
baris MoP (Cash/QRIS/Debit/Credit) + FY 2026.
Idempoten: skip yg sudah ada. Env: ERPNEXT_URL, ERPNEXT_API_KEY."""
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

JURI = "PT. JUARA ROTI INDONESIA"

# (nama persis eResto, abbr unik — semua sudah dicek tidak bentrok)
FRC = [
    ("RSU San Medica (FRC)", "RSSMF"),
    ("Bangka Tengah (FRC)", "BTF"),
    ("Plaza Haji alQosbah (FRC)", "PHAQF"),
    ("RS Medina Garut (FRC)", "RMGF"),
    ("Jambi Sarulangun (FRC)", "JSF"),
    ("Sungai Penuh (FRC)", "SPF"),
    ("Mitra Swalayan Gombong (FRC)", "MSGF"),
]

MOP_AKUN = {
    "Cash": "1111.003 - Kas Kasir - {abbr}",
    "QRIS": "1121.005 - Qris - {abbr}",
    "Debit Card": "1121.002 - Debit Card - {abbr}",
    "Credit Card": "1121.003 - Credit Card - {abbr}",
}

s = requests.Session()
s.headers.update({"Authorization": "token " + KEY})


def get(path, params=None):
    r = s.get(BASE + path, params=params, timeout=60)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:300]}


def post(path, payload):
    r = s.post(BASE + path, json=payload, timeout=120)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:300]}


def put(path, payload):
    r = s.put(BASE + path, json=payload, timeout=120)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:300]}


def company_exists(name):
    st, _ = get("/api/resource/Company/" + urllib.parse.quote(name))
    return st == 200


def abbr_taken(abbr):
    st, d = get("/api/resource/Company", params={
        "fields": '["name","abbr"]',
        "filters": f'[["abbr","=","{abbr}"]]', "limit_page_length": 5})
    return st == 200 and bool(d.get("data"))


def find_customer(name):
    st, d = get("/api/resource/Customer", params={
        "fields": '["name","customer_name","customer_group"]',
        "filters": f'[["customer_name","=","{name}"]]',
        "limit_page_length": 5})
    rows = d.get("data", []) if st == 200 else []
    return rows[0] if rows else None


# 1. Company anak OUTLET REGULER
for name, abbr in FRC:
    if company_exists(name):
        print(f"SKIP company {name}: sudah ada")
        continue
    if abbr_taken(abbr):
        print(f"SKIP company {name}: abbr {abbr} bentrok!")
        continue
    st, d = post("/api/resource/Company", {
        "company_name": name, "abbr": abbr,
        "country": "Indonesia", "default_currency": "IDR",
        "parent_company": "OUTLET REGULER",
        "create_chart_of_accounts_based_on": "Existing Company",
        "existing_company": "OUTLET REGULER",
    })
    ok = "OK" if st in (200, 201) else "GAGAL"
    print(f"{ok} company {name} ({abbr}): HTTP {st} "
          f"{json.dumps(d)[:150]}")

# 2. Customer: jadikan internal + represents_company = nama company.
#    Customer FRC lama (6) non-internal -> update. Jambi (belum ada) -> buat.
for name, _abbr in FRC:
    c = find_customer(name)
    if c is None:
        st, d = post("/api/resource/Customer", {
            "customer_name": name, "customer_type": "Company",
            "customer_group": "Outlet Franchise", "territory": "Indonesia",
            "default_currency": "IDR", "default_price_list": "Harga Outlet",
            "is_internal_customer": 1, "represents_company": name,
            "companies": [{"company": JURI}],
        })
        print(f"{'OK' if st in (200,201) else 'GAGAL'} customer baru {name}: "
              f"HTTP {st} {json.dumps(d)[:150]}")
    else:
        st, d = get("/api/resource/Customer/"
                    + urllib.parse.quote(c["name"]))
        doc = d.get("data", {}) if st == 200 else {}
        comps = [x.get("company") for x in doc.get("companies", [])]
        if JURI not in comps:
            comps.append(JURI)
        st2, d2 = put("/api/resource/Customer/"
                       + urllib.parse.quote(c["name"]), {
                           "is_internal_customer": 1,
                           "represents_company": name,
                           "companies": [{"company": x} for x in comps],
                       })
        print(f"{'OK' if st2==200 else 'GAGAL'} customer internal {name} "
              f"({c['name']}): HTTP {st2} {json.dumps(d2)[:150]}")

# 3. Supplier JURI: tambahkan 7 company FRC ke allowed companies
st, d = get("/api/resource/Supplier/" + urllib.parse.quote(JURI))
if st == 200:
    comps = [c.get("company") for c in d["data"].get("companies", [])]
    need = [n for n, _a in FRC if n not in comps]
    if not need:
        print("SKIP supplier JURI: 7 FRC sudah terdaftar semua")
    else:
        st2, d2 = put("/api/resource/Supplier/" + urllib.parse.quote(JURI),
                      {"companies": [{"company": c} for c in comps + need]})
        print(f"{'OK' if st2==200 else 'GAGAL'} supplier JURI +{len(need)} FRC: "
              f"HTTP {st2} {json.dumps(d2)[:150]}")
else:
    print(f"Supplier JURI: HTTP {st} — lewati")

# 4. MoP: tambah baris per company FRC
abbr_of = dict(FRC)
for mop, pola in MOP_AKUN.items():
    st, d = get("/api/resource/Mode of Payment/" + urllib.parse.quote(mop))
    if st != 200:
        print(f"MoP {mop}: HTTP {st} — lewati")
        continue
    rows = d["data"].get("accounts", [])
    punya = {a.get("company") for a in rows}
    baru = [(n, pola.format(abbr=abbr_of[n])) for n, _a in FRC
            if n not in punya]
    if not baru:
        print(f"SKIP MoP {mop}: 7 FRC sudah ada semua")
        continue
    new_rows = [{"company": a.get("company"),
                 "default_account": a.get("default_account")} for a in rows]
    new_rows += [{"company": n, "default_account": akun} for n, akun in baru]
    st2, d2 = put("/api/resource/Mode of Payment/" + urllib.parse.quote(mop),
                  {"accounts": new_rows})
    print(f"{'OK' if st2==200 else 'GAGAL'} MoP {mop} +{len(baru)} FRC: "
          f"HTTP {st2} {json.dumps(d2)[:150]}")

# 5. FY 2026: tambah 7 company FRC
st, d = get("/api/resource/Fiscal Year/2026")
if st == 200:
    comps = [c.get("company") for c in d["data"].get("companies", [])]
    need = [n for n, _a in FRC if n not in comps]
    if not need:
        print("SKIP FY 2026: 7 FRC sudah masuk semua")
    else:
        st2, d2 = put("/api/resource/Fiscal Year/2026",
                      {"companies": [{"company": c} for c in comps + need]})
        print(f"{'OK' if st2==200 else 'GAGAL'} FY 2026 +{len(need)} FRC: "
              f"HTTP {st2} {json.dumps(d2)[:150]}")
else:
    print(f"FY 2026: HTTP {st} — lewati")

print("SELESAI")
