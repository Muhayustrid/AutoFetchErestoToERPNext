"""Sampling harga per tier: tarik ~40 order pertama per outlet contoh,
ambil detail, kumpulkan (sku -> price mode) per tier.
Pakai data detail yg sudah tersimpan utk 12K (Kebumen) & Bangka.
Output: experiments/pos-fetch/tier_prices.json (+ cetak ringkas).
Env: ERESTO_TOKEN/EMAIL/USER_ID."""
import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests

BASE = "https://ropi.eresto.id"
DOMAIN = "ropi"
MAX_WORKERS = 8
TEMP = {429, 500, 502, 503, 504}
TOKEN = os.getenv("ERESTO_TOKEN", "").strip()
EMAIL = os.getenv("ERESTO_EMAIL", "").strip()
USER = os.getenv("ERESTO_USER_ID", "").strip()
if not (TOKEN and EMAIL and USER):
    sys.exit("ERROR: env ERESTO_TOKEN/EMAIL/USER_ID kurang")

S = requests.Session()
S.headers.update({
    "accept": "application/json, text/plain, */*",
    "authorization": f"Token token={TOKEN}, email={EMAIL}",
    "referer": "https://ropi.eresto.id/manager/v2/index.html",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "cache-control": "no-cache", "pragma": "no-cache",
})


def req(url, params):
    last = None
    for a in range(1, 4):
        try:
            r = S.get(url, params=params, timeout=90)
            if r.status_code in TEMP:
                last = f"HTTP {r.status_code}"
                time.sleep(2 ** a)
                continue
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last = str(e)[:150]
            time.sleep(2 ** a)
    raise RuntimeError(f"{url}: {last}")


def base_params():
    return {"current_user_id": USER, "domain": DOMAIN, "token": TOKEN,
            "_": int(time.time() * 1000)}


def fetch_orders(date, outlet_id, limit=40):
    p = base_params()
    p.update({
        "date[geq]": f"{date} 00:00:00.000",
        "date[leq]": f"{date} 23:59:59.999",
        "outlet_id": outlet_id, "page": 1, "per_page": 200,
        "sort[property]": "date", "sort[order]": "asc",
    })
    d = req(f"{BASE}/v3/orders", p)
    return d.get("data", [])[:limit]


def fetch_range(date_from, date_to, outlet_id, limit=40):
    p = base_params()
    p.update({
        "date[geq]": f"{date_from} 00:00:00.000",
        "date[leq]": f"{date_to} 23:59:59.999",
        "outlet_id": outlet_id, "page": 1, "per_page": 200,
        "sort[property]": "date", "sort[order]": "desc",
    })
    d = req(f"{BASE}/v3/orders", p)
    return d.get("data", [])[:limit]


def fetch_detail(order_id):
    p = base_params()
    d = req(f"{BASE}/v3/orders/{order_id}", p)
    # Respons: {"data":{"id":..,"type":"order","attributes":{...}}}
    root = d.get("data") if isinstance(d.get("data"), dict) else d
    attrs = root.get("attributes") or {}
    return attrs.get("order_items") or []


def collect(store, tier, lines, src):
    """lines: list of dict with product_sku, price, paid_quantity, void."""
    n = 0
    for it in lines:
        if it.get("void"):
            continue
        try:
            pq = float(it.get("paid_quantity") or 0)
            price = float(it.get("price") or 0)
        except (TypeError, ValueError):
            continue
        sku = str(it.get("product_sku") or "").strip()
        if not sku or pq <= 0 or price <= 0:
            continue
        e = store[tier].setdefault(sku, {"counts": {}, "name": "",
                                         "src": []})
        k = f"{price:g}"
        e["counts"][k] = e["counts"].get(k, 0) + 1
        if not e["name"]:
            e["name"] = str(it.get("product_name") or "")
        if src not in e["src"]:
            e["src"].append(src)
        n += 1
    return n


def load_saved(store, tier, path):
    df = pd.read_excel(path, sheet_name="Order_Items")
    collect(store, tier, df.to_dict("records"), os.path.basename(path))


def main():
    store = defaultdict(dict)

    # 1. Data tersimpan
    for f in ["experiments/pos-fetch/POS_Orders_045_2026-10-02_v2_detail.xlsx",
              "experiments/pos-fetch/POS_Orders_045_2026-10-03_v2_detail.xlsx"]:
        if os.path.exists(f):
            load_saved(store, "MENU ROPI 12K 15 JULI 2026", f)
    f = "experiments/pos-fetch/POS_Orders_097_2026-10-03_v2_detail.xlsx"
    if os.path.exists(f):
        load_saved(store, "ROPI BANGKA TENGAH FRC", f)

    # 2. Sample outlet per tier
    TARGETS = [
        ("MENU ROPI 12K 15 JULI 2026", [
            ("RSUD Bangil", "7efd86a2-8b08-442e-a211-af0aeb9ee520"),
            ("RSUD Sekayu", "d922fd1c-8ecf-4a28-bf24-fcf247713abd")]),
        ("MENU ROPI 14K 15 JULI 2026", [
            ("RSCM Jakarta", "7ea62c0b-52e5-41cc-80a1-892ed188c08b"),
            ("RS Yos Sudarso", "79da348b-3e7c-4bea-8d94-c3e97ee82987")]),
        ("ROPI 12K MARET 2026", [
            ("RSI Jakarta Sukapura", "6e35534d-0f9a-4cfe-b270-466c6a116833"),
            ("Plaza Haji alQosbah FRC", "3bdbd880-1722-47f8-be64-6330dbd25a38")]),
        ("MENU 12K 24 MEI 2026", [
            ("RSUD Soegiri", "ffb65dcd-dc63-4788-a84b-68c10b1b5a8e"),
            ("RS Rahman Rahim Sidoarjo", "efd8993d-fb38-40ad-8061-8f27249f2113")]),
        ("JAMBI SOROLANGUN FRC", [
            ("Jambi Sarulangun FRC", "44cde3a5-cf6e-49d7-98f9-87cd160bfa0d")]),
        ("MENU 10K 11 JUNI 2026", [
            ("RS Hosana Medica", "4059b3cd-882f-43e4-843f-776e42f8cca2")]),
        ("MENU 12K 11 JUNI 2026", [
            ("RS Annisa Tangerang", "7689dcc2-1d74-4126-aad5-56f4243acb3d")]),
        ("ROPI 10 K", [
            ("Mitra Swalayan Gombong", "fc8bd60f-e9f2-44ce-a0a4-29654966dae3")]),
        ("ROPI BANGKA TENGAH FRC", [
            ("Bangka Tengah FRC", "3a716972-b8da-4540-af93-4de713352a37")]),
        ("ROPI RS MEDINA GARUT", [
            ("RS Medina Garut FRC", "7ff934f3-fcd5-4dcb-bda1-2697028d4544")]),
        ("ROPI SAN MEDICA CENTER", [
            ("RSU San Medica FRC", "da3d56dd-f4d8-452e-8951-bc390e1fe54e")]),
        ("ROPI SUNGAI PENUH", [
            ("Sungai Penuh FRC", "0fccd719-553d-4921-b510-3862a3dfb428")]),
        ("RSJD DR ARIF ZAINUDDIN SURAKARTA 10K MARET 2026", [
            ("RSJD Arif Zainuddin", "b4f03357-eb0a-46b1-9b55-9cbf1b2015fa")]),
        ("RSUP Palembang", [
            ("RSUP Palembang", "11b23fbd-18ee-4945-b75e-b3e73c1a758a")]),
        ("UMBUL PELEM", [
            ("ROPI Umbul Pelem", "900e6f6e-4412-4be6-adb4-b656569e5dcf")]),
    ]

    DAYS = ["2026-10-03", "2026-10-02", "2026-10-04", "2026-10-01"]
    for tier, outlets in TARGETS:
        for name, oid in outlets:
            orders, used = [], ""
            for day in DAYS:
                try:
                    orders = fetch_orders(day, oid)
                except Exception as e:
                    print(f"  ! {tier} / {name} {day}: {str(e)[:80]}")
                    orders = []
                if orders:
                    used = day
                    break
            if not orders:
                try:
                    orders = fetch_range("2026-09-15", "2026-10-04", oid)
                    used = "range 15Sep-4Okt"
                except Exception as e:
                    print(f"  ! {tier} / {name} range: {str(e)[:80]}")
            print(f"[{tier}] {name}: {len(orders)} order ({used or 'kosong'})")
            if not orders:
                continue
            ids = [o.get("id") for o in orders if o.get("id")]
            n_lines = 0
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                futs = {pool.submit(fetch_detail, i): i for i in ids}
                for fu in as_completed(futs):
                    try:
                        n_lines += collect(store, tier, fu.result(),
                                           f"{name} {used}")
                    except Exception as e:
                        print(f"  ! detail {futs[fu]}: {str(e)[:80]}")
            print(f"   -> {n_lines} baris harga")

    out = {}
    for tier, skus in store.items():
        t = {}
        for sku, e in skus.items():
            best = max(e["counts"].items(), key=lambda kv: kv[1])
            t[sku] = {"price": float(best[0]), "n": best[1],
                      "n_total": sum(e["counts"].values()),
                      "name": e["name"], "variants": e["counts"],
                      "src": e["src"][:4]}
        out[tier] = t
    p = "experiments/pos-fetch/tier_prices.json"
    json.dump(out, open(p, "w"), ensure_ascii=False, indent=1)
    print(f"\n== {p}")
    for tier, t in out.items():
        top = sorted(t.items(), key=lambda kv: -kv[1]["n_total"])[:6]
        print(f"\n{tier}: {len(t)} SKU")
        for sku, v in top:
            print(f"   {sku:10s} {v['price']:>10g} (n={v['n']}/{v['n_total']})"
                  f" {v['name'][:40]} variants={v['variants']}")


if __name__ == "__main__":
    main()
