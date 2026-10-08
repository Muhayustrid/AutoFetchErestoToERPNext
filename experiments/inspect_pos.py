"""Inspect POS Profile Delanggu + Price List + Item Price eksisting.
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


def show(title, st, d, limit=6000):
    print("=" * 70)
    print(title, "HTTP", st)
    print(json.dumps(d, indent=1, ensure_ascii=False)[:limit])


# 1. POS Profile list
st, d = get("/api/resource/POS Profile", params={
    "fields": '["name","company","customer","selling_price_list"]',
    "limit_page_length": 200})
show("POS PROFILE LIST", st, d)
if st == 200:
    print("total POS Profile:", len(d.get("data", [])))

# 2. Cari profil Delanggu
st, d = get("/api/resource/POS Profile", params={
    "fields": '["name","company","customer","selling_price_list"]',
    "filters": '[["company","like","%DELANGGU%"]]',
    "limit_page_length": 10})
show("POS PROFILE DELANGGU (list)", st, d, limit=2000)
if st == 200 and d.get("data"):
    nm = d["data"][0]["name"]
    st2, d2 = get("/api/resource/POS Profile/" + urllib.parse.quote(nm))
    show(f"POS PROFILE FULL ({nm})", st2, d2, limit=8000)

# 3. Price List list
st, d = get("/api/resource/Price List", params={
    "fields": '["name","selling","buying","currency"]',
    "limit_page_length": 100})
show("PRICE LIST", st, d, limit=4000)

# 4. Item Price count + sample per price list
st, d = get("/api/resource/Item Price", params={
    "fields": '["name","item_code","price_list","price_list_rate"]',
    "limit_page_length": 5})
show("ITEM PRICE sample", st, d, limit=2000)
st, d = get("/api/resource/Item Price", params={
    "fields": '["name"]', "limit_page_length": 1000})
if st == 200:
    print("total Item Price (max 1000):", len(d.get("data", [])))
