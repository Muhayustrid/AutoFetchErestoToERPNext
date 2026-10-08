"""Readiness check utk bulk POS Profile + Price List.
Read-only. Env: ERPNEXT_URL, ERPNEXT_API_KEY. Hanya print ringkasan."""
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
        return r.status_code, {"_raw": r.text[:200]}


st, d = get("/api/resource/Company", params={
    "fields": '["name","abbr","is_group"]', "limit_page_length": 1000})
cos = {c["name"]: c.get("abbr") for c in d.get("data", [])} if st == 200 else {}
print(f"companies: {len(cos)} (HTTP {st})")

st, d = get("/api/resource/Warehouse", params={
    "fields": '["name","company"]', "limit_page_length": 2000})
wh = d.get("data", []) if st == 200 else []
wh_names = {w["name"] for w in wh}
print(f"warehouses: {len(wh)} (HTTP {st})")
missing_wh = sorted(f"Stores - {a}" for a in cos.values()
                    if a and f"Stores - {a}" not in wh_names)
print(f"Stores-{{abbr}} hilang: {len(missing_wh)}")
for w in missing_wh[:25]:
    print(f"   - {w}")

st, d = get("/api/resource/Warehouse/" + urllib.parse.quote("Stores - RPMD"))
if st == 200:
    doc = d["data"]
    print("Stores-RPMD: company=%s is_group=%s parent=%s" % (
        doc.get("company"), doc.get("is_group"),
        doc.get("parent_warehouse")))
else:
    print(f"Stores-RPMD: HTTP {st}")

st, _ = get("/api/resource/Customer/" + urllib.parse.quote("Walk-in Customer"))
print(f"Walk-in Customer: HTTP {st}")

st, d = get("/api/resource/Address", params={
    "fields": '["name"]', "limit_page_length": 2000})
ad = {a["name"] for a in d.get("data", [])} if st == 200 else set()
print(f"addresses: {len(ad)} (HTTP {st})")
print("  Delanggu-Shipping ada:", "RS PKU MUHAMMADIYAH DELANGGU-Shipping" in ad)
print("  RSUP-Shipping ada:", "RSUP Palembang-Shipping" in ad)

st, d = get("/api/resource/POS Profile/" + urllib.parse.quote(
    "SHIFT 2- RS PKU MUHAMMADIYAH DELANGGU"))
if st == 200:
    doc = d["data"]
    for k in ["company", "warehouse", "selling_price_list",
              "custom_pos_next_price_group",
              "custom_pos_next_previous_price_list", "customer", "currency",
              "income_account", "expense_account", "write_off_account",
              "write_off_cost_center", "account_for_change_amount",
              "company_address", "pos_schedule_start", "pos_schedule_end",
              "pos_schedule_enabled", "print_format", "letter_head",
              "update_stock"]:
        print(f"  S2.{k} = {doc.get(k)}")
    print("  S2.payments =", [(p.get("mode_of_payment"), p.get("default"))
                               for p in doc.get("payments", [])])
    print("  S2.users =", [u.get("user")
                           for u in doc.get("applicable_for_users", [])])
    print("  S2.item_groups =", [g.get("item_group")
                                 for g in doc.get("item_groups", [])])
else:
    print(f"SHIFT2: HTTP {st} {str(d)[:150]}")

for co, ab in [("RSUP Palembang", "RSUPP"),
               ("Bangka Tengah (FRC)", "BTF")]:
    bad = []
    for akun in [f"4110.000 - Penjualan - {ab}",
                 f"4210.000 - HPP Pembelian - {ab}",
                 f"5510.009 - Selisih Pembayaran Customer - {ab}",
                 f"1111.003 - Kas Kasir - {ab}"]:
        st2, _ = get("/api/resource/Account/" + urllib.parse.quote(akun))
        if st2 != 200:
            bad.append((akun, st2))
    print(f"  akun {ab}: {'OK semua' if not bad else bad}")

st, d = get("/api/resource/Price List", params={
    "fields": '["name","selling","currency"]', "limit_page_length": 100})
pls = [p["name"] for p in d.get("data", [])] if st == 200 else []
print(f"price lists ({len(pls)}): {pls}")
for pl in pls:
    st2, d2 = get("/api/resource/Item Price", params={
        "fields": '["name"]', "filters": f'[["price_list","=","{pl}"]]',
        "limit_page_length": 1000})
    n = len(d2.get("data", [])) if st2 == 200 else -1
    print(f"   {pl}: {n} item prices")

st, d = get("/api/resource/POS Profile", params={
    "fields": '["name"]', "limit_page_length": 1000})
print(f"POS Profiles: {len(d.get('data', [])) if st == 200 else 'ERR'}")
