"""Pilot: 1 order eResto (Kebumen OR045.031026.000001) -> POS Invoice.

Alur persis frontend POSNext (doc 04):
  create_opening_shift -> update_invoice (draft) -> submit_invoice (submit)
  -> verifikasi GL/SLE. Closing shift TIDAK di sini (langkah terpisah).

Env: /tmp/eresto_mig.env (ERESTO_*, ERPNEXT_URL, ERPNEXT_API_KEY).
Idempoten: cek draft/invoice ber-remarks order_no dulu; shift open dipakai ulang.
"""
import csv
import json
import os
import sys
import time
import urllib.parse

import requests

ENV_PATH = "/tmp/eresto_mig.env"
PILOT_ORDER_NO = "OR045.031026.000001"
PILOT_DATE = "2026-10-03"          # tanggal asli di eResto (info saja)
KEBUMEN_OUTLET_ID = "24701649-e701-401d-a58b-c864a91a30dd"
PROFILE = "SHIFT 1 - TOSERBA JADI BARU KEBUMEN"
COMPANY = "TOSERBA JADI BARU KEBUMEN"


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


ENV = load_env(ENV_PATH)
ERP = ENV["ERPNEXT_URL"].rstrip("/")
API_KEY = ENV["ERPNEXT_API_KEY"]

erp = requests.Session()
erp.headers.update({"Authorization": "token " + API_KEY})


def erp_get(path, params=None):
    r = erp.get(ERP + path, params=params, timeout=60)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:500]}


def erp_post(path, payload):
    r = erp.post(ERP + path, json=payload, timeout=90)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:2000]}


def erp_put(path, payload):
    r = erp.put(ERP + path, json=payload, timeout=90)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:2000]}


def erp_method(dotted, **kwargs):
    st, d = erp_post("/api/method/" + dotted, kwargs)
    if st != 200:
        print(f"  !! {dotted} HTTP {st}: {json.dumps(d)[:1500]}")
        sys.exit(1)
    return d.get("message")


def num(v):
    try:
        return float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


# ---------- 1. fetch detail order pilot dari eResto ----------
print("== 1. fetch eResto ==")
es = requests.Session()
es.headers.update({
    "accept": "application/json, text/plain, */*",
    "authorization": f"Token token={ENV['ERESTO_TOKEN']}, email={ENV['ERESTO_EMAIL']}",
    "referer": "https://ropi.eresto.id/manager/v2/index.html",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "cache-control": "no-cache", "pragma": "no-cache",
})


def ereq(url, params):
    last = None
    for a in range(1, 4):
        r = es.get(url, params=params, timeout=90)
        if r.status_code in (429, 500, 502, 503, 504):
            last = f"HTTP {r.status_code}"
            time.sleep(2 ** a)
            continue
        r.raise_for_status()
        return r.json()
    print(f"ERROR eResto: {last}")
    sys.exit(1)


lst = ereq("https://ropi.eresto.id/v3/orders", {
    "current_user_id": ENV["ERESTO_USER_ID"],
    "date[geq]": f"{PILOT_DATE} 00:00:00.000",
    "date[leq]": f"{PILOT_DATE} 23:59:59.999",
    "domain": "ropi", "outlet_id": KEBUMEN_OUTLET_ID,
    "page": 1, "per_page": 200,
    "sort[property]": "date", "sort[order]": "asc",
    "token": ENV["ERESTO_TOKEN"], "_": int(time.time() * 1000),
})
found = [o for o in lst.get("data", [])
         if (o.get("attributes") or {}).get("order_no") == PILOT_ORDER_NO]
if not found:
    print(f"ERROR: {PILOT_ORDER_NO} tidak ketemu di list")
    sys.exit(1)
order_id = found[0]["id"]
print(f"  order {PILOT_ORDER_NO} id={order_id}")

det = ereq(f"https://ropi.eresto.id/v3/orders/{order_id}", {
    "current_user_id": ENV["ERESTO_USER_ID"], "domain": "ropi",
    "token": ENV["ERESTO_TOKEN"], "_": int(time.time() * 1000),
})
root = det.get("data") if isinstance(det.get("data"), dict) else det
attrs = root.get("attributes") or {}
raw_items = attrs.get("order_items") or []
pay = attrs.get("payment") or {}
lines = [it for it in raw_items
         if not it.get("void") and num(it.get("paid_quantity")) > 0]
print(f"  {len(raw_items)} baris detail -> {len(lines)} bayar")
for it in lines:
    print(f"    {it.get('product_sku')} x{it.get('paid_quantity')} "
          f"@{it.get('price')} (void={it.get('void')})")
hdr_total = num(pay.get("total"))
hdr_cash = num(pay.get("cash_amount"))
hdr_non = sum(num(pay.get(k)) for k in
              ("ewallet_amount", "credit_amount", "debit_amount",
               "transfer_amount"))
print(f"  header: total={hdr_total:g} cash={hdr_cash:g} noncash={hdr_non:g}")
assert hdr_non == 0, "pilot harus cash-only, batal"
assert abs(sum(num(i.get("paid_quantity")) * num(i.get("price"))
               for i in lines) - hdr_total) < 0.01, "total vs item mismatch"

# ---------- 2. mapping SKU + cek harga vs Item Price ----------
print("== 2. mapping + harga ==")
mp = {}
with open("experiments/sku_to_item_code.csv") as f:
    for r in csv.DictReader(f):
        mp[r["sku_eresto"]] = r["item_code_erpnext"]
unmapped = [i.get("product_sku") for i in lines
            if i.get("product_sku") not in mp]
if unmapped:
    print(f"ERROR unmapped: {unmapped}")
    sys.exit(1)

st, d = erp_get("/api/resource/POS Profile/" + urllib.parse.quote(PROFILE))
prof = d["data"]
pl = prof.get("selling_price_list")
wh = prof.get("warehouse")
print(f"  profil ok: pl={pl} wh={wh}")

inv_items = []
for it in lines:
    code = mp[it["product_sku"]]
    st, d = erp_get("/api/resource/Item/" + urllib.parse.quote(code))
    item = d["data"]
    st2, d2 = erp_get("/api/resource/Item Price", params={
        "filters": json.dumps([["price_list", "=", pl],
                               ["item_code", "=", code],
                               ["selling", "=", 1]]),
        "fields": '["price_list_rate","uom"]', "limit_page_length": 5})
    rows = d2.get("data", []) if st2 == 200 else []
    if not rows:
        print(f"ERROR: Item Price {code} tidak ada di {pl}")
        sys.exit(1)
    lp = num(rows[0]["price_list_rate"])
    rate = num(it.get("price"))
    flag = "OK" if abs(lp - rate) < 0.01 else "MISMATCH"
    print(f"  {it.get('product_sku')}->{code} eresto={rate:g} "
          f"list={lp:g} stock={item.get('is_stock_item')} [{flag}]")
    if flag != "OK":
        print("ERROR: rate beda -> server akan anggap edit manual. Batal.")
        sys.exit(1)
    inv_items.append({
        "item_code": code,
        "item_name": item.get("item_name"),
        "qty": num(it.get("paid_quantity")),
        "rate": rate,
        "price_list_rate": lp,
        "uom": rows[0].get("uom") or item.get("stock_uom"),
        "warehouse": wh,
        "conversion_factor": 1,
        "discount_percentage": 0,
        "discount_amount": 0,
    })

# ---------- 3. idempotency: sudah pernah dipost? ----------
print("== 3. idempotency ==")
st, d = erp_get("/api/resource/POS Invoice", params={
    "filters": json.dumps([["remarks", "=",
                             f"ERESTO {PILOT_ORDER_NO}"]]),
    "fields": '["name","status","grand_total"]', "limit_page_length": 5})
exist = d.get("data", []) if st == 200 else []
if exist:
    print(f"  SUDAH ADA: {exist} -> stop, tidak duplikat")
    sys.exit(0)
print("  belum ada invoice pilot -> lanjut")

# ---------- 4. pastikan user API terdaftar di profil ----------
print("== 4. akses profil ==")
me = erp_method("frappe.auth.get_logged_user")
print(f"  session user: {me}")
users = [u.get("user") for u in prof.get("applicable_for_users", [])]
if me not in users:
    print(f"  tambah {me} ke POS Profile User...")
    st, d = erp_put("/api/resource/POS Profile/" + urllib.parse.quote(PROFILE),
                    {"applicable_for_users": [{"user": me}]})
    if st != 200:
        print(f"  !! PUT profil HTTP {st}: {json.dumps(d)[:1000]}")
        sys.exit(1)
    print("  ok")
else:
    print("  sudah terdaftar")

# ---------- 5. opening shift ----------
print("== 5. opening shift ==")
chk = erp_method("pos_next.api.shifts.check_opening_shift")
if chk:
    shift = chk["pos_opening_shift"]["name"]
    print(f"  pakai shift terbuka: {shift}")
else:
    res = erp_method(
        "pos_next.api.shifts.create_opening_shift",
        pos_profile=PROFILE, company=COMPANY,
        balance_details=[{"mode_of_payment": m, "opening_amount": 0}
                         for m in ("Cash", "Debit Card",
                                   "Credit Card", "QRIS")])
    shift = res["pos_opening_shift"]["name"]
    print(f"  shift baru: {shift}")

# ---------- 6. draft ----------
print("== 6. update_invoice (draft) ==")
draft = erp_method("pos_next.api.invoices.update_invoice", data={
    "pos_profile": PROFILE,
    "posa_pos_opening_shift": shift,
    "customer": "Walk-in Customer",
    "items": inv_items,
    "payments": [{"mode_of_payment": "Cash", "amount": hdr_cash}],
    "discount_amount": 0,
    "apply_discount_on": "Grand Total",
    "remarks": f"ERESTO {PILOT_ORDER_NO}",
})
print(f"  draft: {draft.get('name')} "
      f"grand={draft.get('grand_total')} paid={draft.get('paid_amount')}")

# ---------- 7. submit ----------
print("== 7. submit_invoice ==")
out = erp_method("pos_next.api.invoices.submit_invoice",
                 invoice=draft,
                 data={"change_amount": 0, "write_off_amount": 0})
print(f"  hasil: {json.dumps(out, default=str)[:800]}")
name = out.get("name")

# ---------- 8. verifikasi ----------
print("== 8. verifikasi ==")
st, d = erp_get("/api/resource/POS Invoice/" + urllib.parse.quote(name))
doc = d.get("data", {}) if st == 200 else {}
print(f"  status={doc.get('status')} grand={doc.get('grand_total')} "
      f"outstanding={doc.get('outstanding_amount')} "
      f"shift={doc.get('posa_pos_opening_shift')}")
st, d = erp_get("/api/resource/GL Entry", params={
    "filters": json.dumps([["voucher_no", "=", name]]),
    "fields": '["account","debit","credit","against"]',
    "limit_page_length": 20})
gles = d.get("data", []) if st == 200 else []
print(f"  GL ({len(gles)} baris):")
for g in gles:
    print(f"    Dr={g['debit']} Cr={g['credit']} {g['account']}")
bal = sum(num(g["debit"]) - num(g["credit"]) for g in gles)
print(f"  balance check: {bal} (harus 0)")
st, d = erp_get("/api/resource/Stock Ledger Entry", params={
    "filters": json.dumps([["voucher_no", "=", name]]),
    "fields": '["item_code","actual_qty","warehouse"]',
    "limit_page_length": 20})
sles = d.get("data", []) if st == 200 else []
print(f"  SLE ({len(sles)} baris, ekspektasi 0 krn non-stok): {sles}")
print(f"\nPILOT OK: {name} | shift {shift} | tutup shift manual langkah berikut")
