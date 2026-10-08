"""Apply POS setup POSNext ke ERPNext lokal via API key.

Alur POSNext (dibaca dari controller pos_next/price_group.py):
  - Price Group memiliki 1 Price List "PG-<price_group_name>" (dibuat otomatis).
  - Item Price (unscoped) di list itu dibuat/di-update otomatis dari child
    `items` (item_code + rate; uom = stock UOM item).
  - Semua POS Profile milik company di child `outlets` diklaim otomatis
    (owner field custom_pos_next_price_group + selling_price_list di-set).
  - Save ulang Price Group = trigger klaim. Jadi urutan:
      pg (buat) -> prof (buat profil) -> claim (PUT ulang outlets).

Nama Price Group = display_name(tier):
  "MENU ROPI 12K 15 JULI 2026" -> "Menu ROPI 12K 15 Juli 2026"
  tier lain apa adanya, mis. "RSUP Palembang".
Price List = "PG-" + display_name(tier).
Rate dari experiments/pos-fetch/tier_prices.json via sku_to_item_code.csv.

Stage: prep | pg | prof | claim | verify | all. Idempoten.
Env: ERPNEXT_URL, ERPNEXT_API_KEY.
"""
import argparse
import json
import os
import sys
import time

import pandas as pd
import requests

BASE = os.getenv("ERPNEXT_URL", "http://127.0.0.1:8081").rstrip("/")
KEY = os.getenv("ERPNEXT_API_KEY", "").strip()
if not KEY:
    sys.exit("ERROR: env ERPNEXT_API_KEY kurang")

S = requests.Session()
S.headers.update({"Authorization": "token " + KEY})
REPORT = "experiments/pos_bulk_report.json"


def display_name(tier):
    t = str(tier).strip()
    if t.startswith("MENU "):
        return t.title().replace("Ropi", "ROPI")
    return t


def pl_name(tier):
    return "PG-" + display_name(tier)


def get(path, params=None):
    r = S.get(BASE + path, params=params, timeout=90)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:300]}


def post(path, payload):
    r = S.post(BASE + path, json=payload, timeout=240)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:300]}


def put(path, payload):
    r = S.put(BASE + path, json=payload, timeout=240)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:300]}


def delete(path):
    r = S.delete(BASE + path, timeout=120)
    return r.status_code, r.text[:200]


def load_matrix(only="", tier=""):
    m = pd.read_excel("experiments/Company_POS_Setup.xlsx",
                      sheet_name="Company_Tier")
    pl = m["price_list"].astype(str).str.strip()
    m = m[~pl.isin(["", "nan", "NaN", "None"])].copy()
    m["tier"] = m["tier_takeaway"].astype(str).str.strip()
    m = m[~m["tier"].isin(["", "nan", "NaN", "None"])].copy()
    m["pg_name"] = m["tier"].map(display_name)
    m["pl_final"] = m["tier"].map(pl_name)
    if only:
        m = m[m["company"].astype(str) == only]
    if tier:
        m = m[m["tier"] == tier]
    return m


def load_prices_and_map():
    prices = json.load(open("experiments/pos-fetch/tier_prices.json"))
    sku_map = pd.read_csv("experiments/sku_to_item_code.csv")
    sku2item = dict(zip(sku_map["sku_eresto"].astype(str),
                        sku_map["item_code_erpnext"].astype(str)))
    return prices, sku2item


def item_meta():
    st, d = get("/api/resource/Item", params={
        "fields": '["name","item_name","stock_uom"]',
        "limit_page_length": 2000})
    return {x["name"]: x for x in d.get("data", [])} if st == 200 else {}


def build_items(tier, prices, sku2item, items_meta, rep):
    t = prices.get(tier) or {}
    by_item = {}
    for sku, v in t.items():
        item = sku2item.get(sku)
        if not item:
            rep["unmapped"].setdefault(tier, []).append(sku)
            continue
        if item not in items_meta:
            rep["ip_fail"].append({"tier": tier, "sku": sku, "item": item,
                                   "err": "item tidak ada di master"})
            continue
        prev = by_item.get(item)
        if prev is None:
            by_item[item] = {"rate": v["price"], "n": v.get("n_total", 0)}
        else:
            if abs(prev["rate"] - v["price"]) > 0.01:
                rep.setdefault("rate_conflict", []).append(
                    {"tier": tier, "item": item,
                     "rates": [prev["rate"], v["price"]]})
            if v.get("n_total", 0) > prev["n"]:
                by_item[item] = {"rate": v["price"], "n": v.get("n_total", 0)}
    return [{"item_code": it,
             "item_name": items_meta[it].get("item_name", ""),
             "uom": items_meta[it].get("stock_uom") or "Pcs",
             "rate": v["rate"]} for it, v in sorted(by_item.items())]


def stage_prep(m, rep):
    """Bersihkan Price List manual yang belum dimiliki Price Group
    (mis. PG-RSUP Palembang dari pilot) supaya PG bisa membuatnya sendiri."""
    for tier in dict.fromkeys(m["tier"]):
        pl = pl_name(tier)
        pg = display_name(tier)
        st, d = get("/api/resource/Price Group/" + requests.utils.quote(pg))
        pg_exists = st == 200
        st2, d2 = get("/api/resource/Price List/" + requests.utils.quote(pl),
                      params={"fields": '["name","custom_pos_next_price_group"]'})
        if st2 != 200:
            continue
        owner = (d2.get("data") or {}).get("custom_pos_next_price_group")
        if owner == pg:
            rep["prep_ok"].append(pl)
            continue
        if owner:
            rep["prep_fail"].append({"pl": pl, "owner": owner})
            print(f"! {pl} dimiliki {owner}, bukan {pg} — dilewati")
            continue
        if pg_exists:
            rep["prep_fail"].append({"pl": pl, "err": "PG ada, PL tanpa owner"})
            print(f"! {pg} ada tapi {pl} tanpa owner — perlu diperiksa manual")
            continue
        # PL manual tanpa owner: hapus IPs tanpa owner dulu, lalu PL.
        st3, d3 = get("/api/resource/Item Price", params={
            "fields": '["name"]',
            "filters": json.dumps([["price_list", "=", pl],
                                   ["custom_pos_next_price_group", "is",
                                    "not set"]]),
            "limit_page_length": 500})
        ips = [x["name"] for x in d3.get("data", [])] if st3 == 200 else []
        for ip in ips:
            delete("/api/resource/Item Price/" + requests.utils.quote(ip))
        delete("/api/resource/Price List/" + requests.utils.quote(pl))
        rep["prep_cleaned"].append({"pl": pl, "ip_deleted": len(ips)})
        print(f"cleanup {pl}: hapus {len(ips)} item price + price list")


def stage_pg(m, prices, sku2item, im, rep):
    done = set()
    for tier in dict.fromkeys(m["tier"]):
        pg, pl = display_name(tier), pl_name(tier)
        if pg in done:
            continue
        done.add(pg)
        st, _ = get("/api/resource/Price Group/" + requests.utils.quote(pg))
        if st == 200:
            rep["pg_skip"].append(pg)
            print(f"SKIP price group {pg}")
            continue
        items = build_items(tier, prices, sku2item, im, rep)
        if not items:
            rep.setdefault("pg_fail", []).append(
                {"pg": pg, "err": "tiada item terpetakan"})
            print(f"GAGAL {pg}: tiada item")
            continue
        rows = m[m["tier"] == tier]
        outlets = [{"company": str(r["company"]),
                    "warehouse": f"Stores - {r['abbr']}"}
                   for r in rows.to_dict("records")]
        st, d = post("/api/resource/Price Group", {
            "price_group_name": pg, "enabled": 1, "currency": "IDR",
            "items": items, "outlets": outlets})
        if st in (200, 201):
            rep["pg_created"].append({"pg": pg, "items": len(items),
                                      "outlets": len(outlets)})
            print(f"OK price group {pg}: {len(items)} item, {len(outlets)} outlet")
        else:
            rep.setdefault("pg_fail", []).append(
                {"pg": pg, "http": st, "body": str(d)[:300]})
            print(f"GAGAL {pg}: HTTP {st} {str(d)[:220]}")
        time.sleep(0.2)


def stage_prof(m, rep):
    # pastikan POS Profile Group ALL TIME
    st, _ = get("/api/resource/POS Profile Group/ALL TIME")
    if st != 200:
        post("/api/resource/POS Profile Group",
             {"group_name": "ALL TIME", "pos_schedule_enabled": 0,
              "profiles": []})
    st, d = get("/api/resource/POS Profile", params={
        "fields": '["name","company"]', "limit_page_length": 1000})
    have = {x["company"] for x in d.get("data", [])} if st == 200 else set()

    def acc_map(num):
        st, d = get("/api/resource/Account", params={
            "fields": '["name","company"]',
            "filters": json.dumps([["account_number", "=", num]]),
            "limit_page_length": 2000})
        out = {}
        if st == 200:
            for x in d.get("data", []):
                out.setdefault(x["company"], x["name"])
        return out

    a_selisih, a_income = acc_map("5510.009"), acc_map("4110.000")
    a_hpp, a_kas = acc_map("4210.000"), acc_map("1111.003")
    st, d = get("/api/resource/Cost Center", params={
        "fields": '["name","company"]',
        "filters": json.dumps([["cost_center_name", "=", "Main"]]),
        "limit_page_length": 2000})
    cc = {}
    if st == 200:
        for x in d.get("data", []):
            cc.setdefault(x["company"], x["name"])

    for r in m.to_dict("records"):
        co, abbr, tier = str(r["company"]), str(r["abbr"]), r["tier"]
        pg, pl = display_name(tier), pl_name(tier)
        pname = f"SHIFT 1 - {co}"
        if co in have:
            rep["prof_skip"].append(co)
            continue
        missing = [n for n, ok in [
            ("5510.009", co in a_selisih), ("4110.000", co in a_income),
            ("4210.000", co in a_hpp), ("1111.003", co in a_kas),
            ("Main CC", co in cc)] if not ok]
        if missing:
            rep["prof_fail"].append({"company": co, "err": f"akun kurang: {missing}"})
            print(f"GAGAL profile {co}: akun kurang {missing}")
            continue
        st_pg, _ = get("/api/resource/Price Group/" + requests.utils.quote(pg))
        pg_ok = st_pg == 200
        # pos_profile_group sengaja TIDAK diisi di sini: membership POSNext
        # hanya boleh lewat tabel Members milik Shift Group (stage `group`).
        payload = {
            "name": pname, "company": co, "customer": "Walk-in Customer",
            "country": "Indonesia", "currency": "IDR", "disabled": 0,
            "warehouse": f"Stores - {abbr}",
            "selling_price_list": pl if pg_ok else "Standard Selling",
            "pos_schedule_enabled": 1, "pos_schedule_start": "0:00:00",
            "pos_schedule_end": "23:59:59",
            "pos_schedule_warning_minutes": 0, "pos_schedule_enforce_closing": 0,
            "set_grand_total_to_default_mop": 1,
            "write_off_account": a_selisih[co], "write_off_limit": 1.0,
            "write_off_cost_center": cc[co],
            "income_account": a_income[co], "expense_account": a_hpp[co],
            "account_for_change_amount": a_kas[co],
            "disable_rounded_total": 0, "apply_discount_on": "Grand Total",
            "allow_partial_payment": 0,
            "posa_block_sale_beyond_available_qty": 1,
            "action_on_new_invoice": "Always Ask",
            "validate_stock_on_save": 0, "update_stock": 1,
            "posa_cash_mode_of_payment": "Cash",
            "posa_allow_delete": 0, "ignore_pricing_rule": 0,
            "print_receipt_on_order_complete": 0, "hide_images": 0,
            "hide_unavailable_items": 0, "auto_add_item_to_cart": 0,
            "allow_rate_change": 0, "allow_discount_change": 0,
            "print_format": "POS Next Receipt",
            "letter_head": "Company Letterhead - Grey",
            "payments": [{"mode_of_payment": "Cash", "default": 1,
                          "allow_in_returns": 1}],
            "item_groups": [{"item_group": "Products"}],
        }
        if pg_ok:
            payload["custom_pos_next_price_group"] = pg
            payload["custom_pos_next_previous_price_list"] = "Standard Selling"
        st, d = post("/api/resource/POS Profile", payload)
        if st in (200, 201):
            rep["prof_created"].append(co)
            print(f"OK profile {co}" + ("" if pg_ok else " (tanpa PG!)"))
        else:
            rep["prof_fail"].append({"company": co, "http": st,
                                     "body": str(d)[:250]})
            print(f"GAGAL profile {co}: HTTP {st} {str(d)[:200]}")
        time.sleep(0.1)


def stage_claim(m, rep, im):
    for tier in dict.fromkeys(m["tier"]):
        pg, pl = display_name(tier), pl_name(tier)
        st, d = get("/api/resource/Price Group/" + requests.utils.quote(pg))
        if st != 200:
            continue
        doc = d["data"]
        items = [{"item_code": x["item_code"], "uom": x.get("uom"),
                  "rate": x.get("rate")} for x in doc.get("items", [])]
        rows = m[m["tier"] == tier]
        outlets = [{"company": str(r["company"]),
                    "warehouse": f"Stores - {r['abbr']}"}
                   for r in rows.to_dict("records")]
        st2, d2 = put("/api/resource/Price Group/" + requests.utils.quote(pg),
                      {"enabled": 1, "currency": "IDR", "items": items,
                       "outlets": outlets})
        if st2 == 200:
            rep["claim_ok"].append({"pg": pg, "outlets": len(outlets)})
            print(f"OK claim {pg}: {len(outlets)} outlet")
        else:
            rep.setdefault("claim_fail", []).append(
                {"pg": pg, "http": st2, "body": str(d2)[:250]})
            print(f"GAGAL claim {pg}: HTTP {st2} {str(d2)[:200]}")


def stage_group(m, rep):
    """Tambah semua profil ke Shift Group 'ALL TIME' (membership resmi),
    jadwal 00:00-23:59:59 tanpa enforcement. Delanggu 2 shift ikut
    dimasukkan supaya tidak ter-unlink saat group disimpan."""
    st, d = get("/api/resource/POS Profile Group/ALL TIME")
    members = {}
    if st == 200:
        for x in d["data"].get("profiles", []):
            members[x["pos_profile"]] = x.get("company") or ""
    else:
        st2, d2 = post("/api/resource/POS Profile Group", {
            "group_name": "ALL TIME", "pos_schedule_enabled": 1,
            "pos_schedule_start": "0:00:00", "pos_schedule_end": "23:59:59",
            "pos_schedule_warning_minutes": 0,
            "pos_schedule_enforce_closing": 0, "profiles": []})
        print(f"buat group ALL TIME: HTTP {st2}")

    # profil Delanggu (2 shift) + semua SHIFT 1 company di matrix yg sudah ada
    st, d = get("/api/resource/POS Profile", params={
        "fields": '["name","company","pos_profile_group"]',
        "limit_page_length": 2000})
    all_prof = d.get("data", []) if st == 200 else []
    want = set()
    for x in all_prof:
        g = (x.get("pos_profile_group") or "").strip()
        if g and g != "ALL TIME":
            # milik Shift Group lain (mis. "SHIFT 2" milik user) — jangan diutak-atik
            rep.setdefault("group_skipped", []).append(
                {"profile": x["name"], "group": g})
            continue
        if x["company"] == "RS PKU MUHAMMADIYAH DELANGGU":
            want.add(x["name"])
    co_of = {x["name"]: x["company"] for x in all_prof}
    for r in m.to_dict("records"):
        pname = f"SHIFT 1 - {r['company']}"
        if pname in co_of:
            want.add(pname)
    for pn in want:
        members[pn] = co_of.get(pn, members.get(pn, ""))
    # buang dari members yg ternyata milik group lain (defensif)
    for pn in list(members):
        g = next((x.get("pos_profile_group") for x in all_prof
                  if x["name"] == pn), "")
        if g and g != "ALL TIME":
            del members[pn]
    rows = [{"pos_profile": pn, "company": members[pn]}
            for pn in sorted(members)]
    print(f"members ALL TIME target: {len(rows)}")

    def save_group(rowset, label):
        st, d = put("/api/resource/POS Profile Group/ALL TIME", {
            "group_name": "ALL TIME", "pos_schedule_enabled": 1,
            "pos_schedule_start": "0:00:00", "pos_schedule_end": "23:59:59",
            "pos_schedule_warning_minutes": 0,
            "pos_schedule_enforce_closing": 0, "profiles": rowset})
        ok = st == 200
        rep["group_ok" if ok else "group_fail"].append(
            {"label": label, "n": len(rowset),
             "http": st, "body": "" if ok else str(d)[:200]})
        print(f"{'OK' if ok else 'GAGAL'} group {label}: {len(rowset)} member"
              + ("" if ok else f" HTTP {st} {str(d)[:160]}"))
        return ok

    # Catatan: save grup meng-unlink profil yang terhubung tapi tak ada di
    # Members. Jadi setiap save selalu membawa daftar kumulatif; tambah per
    # batch kecil, fallback satu-per-satu bila ada member yg bikin gagal.
    st, d = get("/api/resource/POS Profile", params={
        "fields": '["name","company","pos_profile_group"]',
        "filters": json.dumps([["pos_profile_group", "=", "ALL TIME"]]),
        "limit_page_length": 2000})
    linked = {x["name"] for x in d.get("data", [])} if st == 200 else set()
    seed = [r for r in rows if r["pos_profile"] in linked]
    rest = [r for r in rows if r["pos_profile"] not in linked]
    cumulative = list(seed)
    if seed:
        save_group(cumulative, "seed")
    for i in range(0, len(rest), 20):
        chunk = rest[i:i + 20]
        trial = cumulative + chunk
        if save_group(trial, f"batch {i//20 + 1}"):
            cumulative = trial
            continue
        for r in chunk:
            trial = cumulative + [r]
            if save_group(trial, f"single {r['pos_profile'][:40]}"):
                cumulative = trial


def stage_verify(m, rep):
    st, d = get("/api/resource/POS Profile", params={
        "fields": '["name","company","selling_price_list",'
                  '"custom_pos_next_price_group"]',
        "limit_page_length": 2000})
    profs = d.get("data", []) if st == 200 else []
    print(f"POS Profile total: {len(profs)}")
    claimed = [p for p in profs if p.get("custom_pos_next_price_group")]
    print(f"  dengan price group: {len(claimed)}")
    nopg = [p["company"] for p in profs
            if not p.get("custom_pos_next_price_group")]
    print(f"  tanpa price group: {len(nopg)}")
    for x in nopg[:10]:
        print(f"    - {x}")
    st, d = get("/api/resource/Price Group", params={
        "fields": '["name","price_list"]', "limit_page_length": 300})
    print(f"Price Group total: {len(d.get('data', [])) if st == 200 else 'ERR'}")
    st, d = get("/api/resource/Price List", params={
        "fields": '["name","custom_pos_next_price_group"]',
        "limit_page_length": 300})
    pls = d.get("data", []) if st == 200 else []
    print(f"Price List total: {len(pls)} | ber-owner PG: "
          f"{sum(1 for x in pls if x.get('custom_pos_next_price_group'))}")
    # sample checks
    for co in ["RSUP Palembang", "RS PKU MUHAMMADIYAH DELANGGU",
               "Bangka Tengah (FRC)"]:
        st, d = get("/api/resource/POS Profile/" +
                    requests.utils.quote(f"SHIFT 1 - {co}"),
                    params={"fields": '["name","selling_price_list",'
                                      '"custom_pos_next_price_group"]'})
        if st == 200:
            x = d.get("data") or {}
            print(f"  {co}: PL={x.get('selling_price_list')} "
                  f"PG={x.get('custom_pos_next_price_group')}")
        else:
            print(f"  {co}: profile tidak ada")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all",
                    choices=["prep", "pg", "prof", "claim", "group",
                             "verify", "all"])
    ap.add_argument("--only", default="")
    ap.add_argument("--tier", default="")
    args = ap.parse_args()

    try:
        rep = json.load(open(REPORT))
    except Exception:
        rep = {}
    for k in ["prep_ok", "prep_cleaned", "prep_fail", "pg_created", "pg_skip",
              "pg_fail", "prof_created", "prof_skip", "prof_fail",
              "claim_ok", "claim_fail", "ip_fail", "unmapped",
              "rate_conflict", "group_ok", "group_fail", "group_skipped"]:
        rep.setdefault(k, [])

    m = load_matrix(args.only, args.tier)
    if m.empty:
        sys.exit("matrix kosong utk filter itu")
    prices, sku2item = load_prices_and_map()
    im = item_meta()
    print(f"matrix: {len(m)} company | item master: {len(im)}")

    if args.stage in ("prep", "all"):
        print("\n== STAGE prep ==")
        stage_prep(m, rep)
    if args.stage in ("pg", "all"):
        print("\n== STAGE pg ==")
        stage_pg(m, prices, sku2item, im, rep)
    if args.stage in ("prof", "all"):
        print("\n== STAGE prof ==")
        stage_prof(m, rep)
    if args.stage in ("claim", "all"):
        print("\n== STAGE claim ==")
        stage_claim(m, rep, im)
    if args.stage in ("group", "all"):
        print("\n== STAGE group ==")
        stage_group(m, rep)
    if args.stage in ("verify", "all"):
        print("\n== STAGE verify ==")
        stage_verify(m, rep)

    json.dump(rep, open(REPORT, "w"), ensure_ascii=False, indent=1)
    print(f"\nreport: {REPORT}")


if __name__ == "__main__":
    main()
