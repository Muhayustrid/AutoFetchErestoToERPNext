"""Probe read-only kesiapan pilot: 1 order Kebumen -> POS Invoice.

Hanya GET ke eResto + ERPNext. Env dibaca dari /tmp/eresto_mig.env,
tidak ada secret yang di-print.
"""
import json
import os
import sys
import time
import urllib.parse

import requests

ENV_PATH = "/tmp/eresto_mig.env"
KEBUMEN_OUTLET_ID = "24701649-e701-401d-a58b-c864a91a30dd"
PILOT_DATE = "2026-10-03"


def load_env(path):
    d = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def main():
    env = load_env(ENV_PATH)
    erp_base = env.get("ERPNEXT_URL", "http://127.0.0.1:8081").rstrip("/")
    erp_key = env.get("ERPNEXT_API_KEY", "")
    etoken = env.get("ERESTO_TOKEN", "")
    eemail = env.get("ERESTO_EMAIL", "")
    euser = env.get("ERESTO_USER_ID", "")
    if not (erp_key and etoken and eemail and euser):
        print("ERROR: env kurang (cek /tmp/eresto_mig.env)")
        sys.exit(1)

    erp = requests.Session()
    erp.headers.update({"Authorization": "token " + erp_key})

    def erp_get(path, params=None):
        r = erp.get(erp_base + path, params=params, timeout=60)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"_raw": r.text[:300]}

    print("== ERPNext ==")
    st, d = erp_get("/api/method/frappe.auth.get_logged_user")
    print(f"logged user: {d} (HTTP {st})")

    st, d = erp_get("/api/resource/POS Next Global Settings/"
                    "POS Next Global Settings")
    if st == 200:
        g = d.get("data", {})
        for k in ["invoice_type", "allow_negative_stock",
                  "allow_user_to_edit_rate", "max_discount_allowed",
                  "price_replay_audit_only", "require_refund_code",
                  "enable_pos_queue", "tax_inclusive",
                  "allow_credit_sale", "allow_change_posting_date"]:
            print(f"  global.{k} = {g.get(k)}")
    else:
        print(f"  Global Settings: HTTP {st} {str(d)[:200]}")

    st, d = erp_get("/api/resource/Stock Settings/Stock Settings")
    if st == 200:
        print(f"  Stock.allow_negative_stock = "
              f"{d.get('data', {}).get('allow_negative_stock')}")
    else:
        print(f"  Stock Settings: HTTP {st}")

    st, d = erp_get("/api/resource/Company", params={
        "filters": '[["name","like","%KEBUMEN%"]]',
        "fields": '["name","abbr"]', "limit_page_length": 50})
    cos = d.get("data", []) if st == 200 else []
    print(f"company ~KEBUMEN: {cos} (HTTP {st})")
    kebumen = cos[0]["name"] if cos else None
    abbr = cos[0].get("abbr") if cos else None

    if kebumen:
        prof = f"SHIFT 1 - {kebumen}"
        st, d = erp_get("/api/resource/POS Profile/"
                        + urllib.parse.quote(prof))
        if st == 200:
            p = d["data"]
            print(f"  profil {prof}: company={p.get('company')} "
                  f"wh={p.get('warehouse')} pl={p.get('selling_price_list')} "
                  f"cust={p.get('customer')} upd_stock={p.get('update_stock')}")
            print(f"  payments={[(x.get('mode_of_payment'), x.get('default')) for x in p.get('payments', [])]}")
        else:
            print(f"  profil {prof}: HTTP {st}")

        if abbr:
            wh = f"Stores - {abbr}"
            st, d = erp_get("/api/resource/Bin", params={
                "filters": f'[["warehouse","=","{wh}"]]',
                "fields": '["item_code","actual_qty"]',
                "limit_page_length": 5})
            rows = d.get("data", []) if st == 200 else []
            print(f"  bin {wh}: {len(rows)} baris sampel "
                  f"{rows[:3]} (HTTP {st})")

    st, d = erp_get("/api/resource/Item", params={
        "filters": '[["item_code","in",'
                   '["RP001","RP002","RP003","AM001","CP001"]]]',
        "fields": '["item_code","is_stock_item","stock_uom","item_group"]',
        "limit_page_length": 10})
    print(f"item sampel: {d.get('data', []) if st == 200 else st}")

    st, d = erp_get("/api/resource/POS Opening Shift", params={
        "fields": '["name","status","user","pos_profile"]',
        "limit_page_length": 20})
    print(f"opening shift existing: "
          f"{d.get('data', []) if st == 200 else st}")

    print("== eResto (1 page ringan) ==")
    es = requests.Session()
    es.headers.update({
        "accept": "application/json, text/plain, */*",
        "authorization": f"Token token={etoken}, email={eemail}",
        "referer": "https://ropi.eresto.id/manager/v2/index.html",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "cache-control": "no-cache",
        "pragma": "no-cache",
    })
    r = es.get("https://ropi.eresto.id/v3/orders", params={
        "current_user_id": euser,
        "date[geq]": f"{PILOT_DATE} 00:00:00.000",
        "date[leq]": f"{PILOT_DATE} 23:59:59.999",
        "domain": "ropi",
        "outlet_id": KEBUMEN_OUTLET_ID,
        "page": 1, "per_page": 5,
        "sort[property]": "date", "sort[order]": "asc",
        "token": etoken,
        "_": int(time.time() * 1000),
    }, timeout=90)
    print(f"GET /v3/orders: HTTP {r.status_code}")
    if r.status_code == 200:
        payload = r.json()
        data = payload.get("data", [])
        meta = payload.get("meta", {})
        print(f"  total_count={meta.get('total_count')} "
              f"terima={len(data)} di page 1")
        for o in data[:3]:
            a = o.get("attributes", {})
            p = a.get("payment", {}) or {}
            print(f"  {a.get('order_no')} | qty={a.get('item_quantity')} "
                  f"| total={p.get('total')} cash={p.get('cash_amount')} "
                  f"ew={p.get('ewallet_amount')} d/c/t={p.get('debit_amount')}/"
                  f"{p.get('credit_amount')}/{p.get('transfer_amount')}")
    else:
        print(f"  body: {r.text[:300]}")


if __name__ == "__main__":
    main()
