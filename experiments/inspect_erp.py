"""Inspect ERPNext lokal: company tree, customer, supplier, MoP, Fiscal Year.
Env: ERPNEXT_URL, ERPNEXT_API_KEY. Tidak print token."""
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


def show(title, st, d, limit=3000):
    print("=" * 70)
    print(title, "HTTP", st)
    txt = json.dumps(d, indent=1, ensure_ascii=False)
    print(txt[:limit])


# 1. Company tree: parent + is_group
st, d = get("/api/resource/Company", params={
    "fields": '["name","abbr","parent_company","is_group"]',
    "limit_page_length": 1000, "order_by": "name asc"})
show("COMPANY TREE", st, d, limit=6000)
if st == 200:
    rows = d.get("data", [])
    groups = [c for c in rows if c.get("is_group")]
    print(f"total={len(rows)} groups={len(groups)}")
    for c in groups:
        print(f"  GROUP {c['name']} abbr={c.get('abbr')} parent={c.get('parent_company')}")
    # anak OUTLET REGULER sample
    anak = [c for c in rows if c.get("parent_company") == "OUTLET REGULER"]
    print(f"anak OUTLET REGULER: {len(anak)} sample:")
    for c in anak[:5]:
        print("  ", c)

# 2. Satu customer penuh (contoh Kebumen) untuk tiru polanya
st, d = get("/api/resource/Customer", params={
    "fields": '["name","customer_name","customer_group","territory","is_internal_customer","represents_company"]',
    "filters": '[["customer_name","=","TOSERBA JADI BARU KEBUMEN"]]',
    "limit_page_length": 5})
show("CUSTOMER KEBUMEN (list)", st, d)
if st == 200 and d.get("data"):
    nm = d["data"][0]["name"]
    st2, d2 = get("/api/resource/Customer/" + urllib.parse.quote(nm))
    show("CUSTOMER KEBUMEN (full)", st2, d2, limit=4000)

# 3. Customer group + territory list (untuk validasi nilai)
st, d = get("/api/resource/Customer Group", params={"fields": '["name"]', "limit_page_length": 100})
show("CUSTOMER GROUP", st, d, limit=1500)
st, d = get("/api/resource/Territory", params={"fields": '["name"]', "limit_page_length": 100})
show("TERRITORY", st, d, limit=1500)

# 4. Supplier list minimal
st, d = get("/api/resource/Supplier", params={"fields": '["name"]', "limit_page_length": 1000})
show("SUPPLIER LIST", st, d, limit=3000)

# 5. Mode of Payment list + satu contoh penuh
st, d = get("/api/resource/Mode of Payment", params={"fields": '["name"]', "limit_page_length": 100})
show("MODE OF PAYMENT LIST", st, d, limit=2000)
if st == 200 and d.get("data"):
    first = d["data"][0]["name"]
    st2, d2 = get("/api/resource/Mode of Payment/" + urllib.parse.quote(first))
    show(f"MOP FULL ({first})", st2, d2, limit=5000)

# 6. Fiscal Year list + 2026 penuh
st, d = get("/api/resource/Fiscal Year", params={"fields": '["name","year"]', "limit_page_length": 50, "order_by": "name desc"})
show("FISCAL YEAR LIST", st, d, limit=2000)
for cand in ["2026", "2026-2027", "FY 2026"]:
    st2, d2 = get("/api/resource/Fiscal Year/" + urllib.parse.quote(cand))
    if st2 == 200:
        show(f"FISCAL YEAR FULL ({cand})", st2, d2, limit=5000)
        break
