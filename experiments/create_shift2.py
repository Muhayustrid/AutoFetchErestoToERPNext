"""Bikin POS Profile `SHIFT 2 - <company>` untuk semua company yang
sudah punya `SHIFT 1 - <company>` (clone penuh: warehouse, akun,
price list/group, 4 metode bayar, print format), lalu daftarkan ke
Shift Group `SHIFT 2` (jadwal mengikuti grup - milik Delanggu
05:00-14:00). Company yang sudah punya SHIFT 2 (Delanggu) dilewati.
Terakhir: refresh outlet tiap Price Group agar mencatat kedua shift.
Idempoten. Env: ERPNEXT_URL, ERPNEXT_API_KEY.
"""
import json
import os
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

BASE = os.getenv("ERPNEXT_URL", "http://127.0.0.1:8081").rstrip("/")
KEY = os.getenv("ERPNEXT_API_KEY", "").strip()
if not KEY:
    sys.exit("ERROR: env ERPNEXT_API_KEY kurang")

S = requests.Session()
S.headers.update({"Authorization": "token " + KEY})

# field profil yg di-clone dari SHIFT 1 (pos_profile_group TIDAK ikut -
# membership hanya lewat tabel Members milik Shift Group)
ALLOW = [
    "company", "customer", "country", "currency", "disabled", "warehouse",
    "selling_price_list", "custom_pos_next_price_group",
    "custom_pos_next_previous_price_list",
    "pos_schedule_enabled", "pos_schedule_start", "pos_schedule_end",
    "pos_schedule_warning_minutes", "pos_schedule_enforce_closing",
    "set_grand_total_to_default_mop", "write_off_account",
    "write_off_cost_center", "write_off_limit", "income_account",
    "expense_account", "account_for_change_amount", "disable_rounded_total",
    "apply_discount_on", "allow_partial_payment",
    "posa_block_sale_beyond_available_qty", "action_on_new_invoice",
    "validate_stock_on_save", "update_stock", "posa_cash_mode_of_payment",
    "posa_allow_delete", "ignore_pricing_rule",
    "print_receipt_on_order_complete", "hide_images",
    "hide_unavailable_items", "auto_add_item_to_cart", "allow_rate_change",
    "allow_discount_change", "print_format", "letter_head",
]


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
    r = S.put(BASE + path, json=payload, timeout=300)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:300]}


def build_payload(src, new_name):
    p = {"name": new_name}
    for f in ALLOW:
        if f in src and src[f] is not None:
            p[f] = src[f]
    p["payments"] = [{"mode_of_payment": x["mode_of_payment"],
                      "default": x.get("default") or 0,
                      "allow_in_returns": x.get("allow_in_returns") or 0}
                     for x in src.get("payments", [])]
    p["item_groups"] = [{"item_group": x["item_group"]}
                        for x in src.get("item_groups", [])]
    return p


def main():
    rep = {"created": [], "created_fail": [], "skip_existing": [],
           "group_ok": [], "group_fail": [], "outlets_ok": [],
           "outlets_fail": [], "samples": {}}

    # ---------- 1. daftar profil sekarang ----------
    st, d = get("/api/resource/POS Profile", params={
        "fields": '["name","company"]', "limit_page_length": 2000})
    rows = d.get("data", []) if st == 200 else []
    shift1 = {r["name"]: r["company"] for r in rows
              if r["name"].upper().startswith("SHIFT 1")}
    has_shift2 = {}
    for r in rows:
        if "SHIFT 2" in r["name"].upper():
            has_shift2.setdefault(r["company"], []).append(r["name"])
    print(f"profil total: {len(rows)} | SHIFT 1: {len(shift1)} | "
          f"company dgn SHIFT 2: {len(has_shift2)}")

    # ---------- 2. ambil doc SHIFT 1 (paralel) ----------
    def fetch(nm):
        return nm, get("/api/resource/POS Profile/" + urllib.parse.quote(nm))

    docs = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for fu in as_completed({pool.submit(fetch, nm): nm for nm in shift1}):
            nm, (st2, d2) = fu.result()
            if st2 == 200:
                docs[nm] = d2["data"]
    print(f"doc SHIFT 1 terbaca: {len(docs)}")

    # ---------- 3. buat SHIFT 2 ----------
    todo = []
    for nm, src in sorted(docs.items()):
        comp = str(src.get("company") or "")
        if comp in has_shift2:
            rep["skip_existing"].append({"company": comp,
                                         "existing": has_shift2[comp]})
            continue
        todo.append((comp, nm, src))
    print(f"company siap dibuat SHIFT 2: {len(todo)}")

    for i, (comp, src_name, src) in enumerate(todo, 1):
        new_name = f"SHIFT 2 - {comp}"
        st2, _ = get("/api/resource/POS Profile/" +
                     urllib.parse.quote(new_name))
        if st2 == 200:
            rep["skip_existing"].append({"company": comp, "existing": [new_name]})
            continue
        st2, d2 = post("/api/resource/POS Profile",
                       build_payload(src, new_name))
        if st2 in (200, 201):
            rep["created"].append(new_name)
        else:
            rep["created_fail"].append({"profile": new_name, "http": st2,
                                        "body": str(d2)[:220]})
            print(f"GAGAL buat {new_name}: HTTP {st2} {str(d2)[:160]}")
        if i % 20 == 0:
            print(f"  ... {i}/{len(todo)} dibuat")
        time.sleep(0.08)
    print(f"SHIFT 2 dibuat: {len(rep['created'])} | gagal: "
          f"{len(rep['created_fail'])} | skip: {len(rep['skip_existing'])}")

    # ---------- 4. masukkan ke grup SHIFT 2 ----------
    st, d = get("/api/resource/POS Profile Group/SHIFT 2")
    if st != 200:
        sys.exit("ERROR: grup SHIFT 2 tidak ada (restore dulu)")
    grp = d["data"]
    sched = (grp.get("pos_schedule_start") or "5:00:00",
             grp.get("pos_schedule_end") or "14:00:00")
    print(f"grup SHIFT 2: jadwal {sched[0]}-{sched[1]}, member "
          f"{len(grp.get('profiles', []))}")

    st, d = get("/api/resource/POS Profile", params={
        "fields": '["name","company"]', "limit_page_length": 2000})
    all_shift2 = sorted(r["name"] for r in d.get("data", [])
                        if "SHIFT 2" in r["name"].upper())
    comp_of = {r["name"]: r["company"] for r in d.get("data", [])}
    existing = {x["pos_profile"] for x in grp.get("profiles", [])}
    members = [{"pos_profile": x["pos_profile"],
                "company": x.get("company") or comp_of.get(x["pos_profile"], "")}
               for x in grp.get("profiles", [])]
    new_members = [{"pos_profile": nm, "company": comp_of.get(nm, "")}
                   for nm in all_shift2 if nm not in existing]
    print(f"target member: {len(members)} existing + {len(new_members)} baru")

    def save_group(mem, label):
        st2, d2 = put("/api/resource/POS Profile Group/SHIFT 2", {
            "group_name": "SHIFT 2",
            "pos_schedule_enabled": grp.get("pos_schedule_enabled") or 1,
            "pos_schedule_start": sched[0],
            "pos_schedule_end": sched[1],
            "pos_schedule_warning_minutes":
                grp.get("pos_schedule_warning_minutes") or 0,
            "pos_schedule_enforce_closing":
                grp.get("pos_schedule_enforce_closing") or 0,
            "profiles": mem})
        ok = st2 == 200
        rep["group_ok" if ok else "group_fail"].append(
            {"label": label, "n": len(mem), "http": st2,
             "body": "" if ok else str(d2)[:220]})
        print(f"{'OK' if ok else 'GAGAL'} grup [{label}]: {len(mem)} member"
              + ("" if ok else f" HTTP {st2} {str(d2)[:160]}"))
        return ok

    # coba langsung semua; kalau gagal, tambah per batch (kumulatif),
    # lalu per satu bila batch gagal
    cumulative = list(members)
    if new_members:
        full = cumulative + new_members
        if not save_group(full, "full"):
            for i in range(0, len(new_members), 20):
                chunk = new_members[i:i + 20]
                trial = cumulative + chunk
                if save_group(trial, f"batch {i // 20 + 1}"):
                    cumulative = trial
                    continue
                for r in chunk:
                    trial = cumulative + [r]
                    if save_group(trial, f"single {r['pos_profile'][:38]}"):
                        cumulative = trial
        else:
            cumulative = full

    # ---------- 5. refresh outlet tiap Price Group ----------
    st, d = get("/api/resource/POS Profile", params={
        "fields": '["name","company","warehouse",'
                  '"custom_pos_next_price_group"]',
        "limit_page_length": 2000})
    own = {}
    for r in d.get("data", []):
        pg = (r.get("custom_pos_next_price_group") or "").strip()
        if pg:
            own.setdefault(pg, {})[r["company"]] = r.get("warehouse")
    st, d = get("/api/resource/Price Group", params={
        "fields": '["name"]', "limit_page_length": 300})
    for pg in d.get("data", []):
        name = pg["name"]
        st2, d2 = get("/api/resource/Price Group/" + urllib.parse.quote(name))
        if st2 != 200:
            continue
        doc = d2["data"]
        items = [{"item_code": x["item_code"], "uom": x.get("uom"),
                  "rate": x.get("rate")} for x in doc.get("items", [])]
        outlets = [{"company": c, "warehouse": w}
                   for c, w in sorted(own.get(name, {}).items())]
        if not outlets:
            continue
        st3, d3 = put("/api/resource/Price Group/" + urllib.parse.quote(name),
                      {"enabled": doc.get("enabled", 1),
                       "currency": doc.get("currency") or "IDR",
                       "items": items, "outlets": outlets})
        if st3 == 200:
            rep["outlets_ok"].append({"pg": name, "n": len(outlets)})
        else:
            rep["outlets_fail"].append({"pg": name, "http": st3,
                                        "body": str(d3)[:220]})
            print(f"GAGAL refresh outlets {name}: HTTP {st3} "
                  f"{str(d3)[:160]}")
    print(f"outlets refresh: {len(rep['outlets_ok'])} ok, "
          f"{len(rep['outlets_fail'])} gagal")

    # ---------- 6. verifikasi ----------
    st, d = get("/api/resource/POS Profile", params={
        "fields": '["name","company","custom_pos_next_price_group"]',
        "limit_page_length": 2000})
    profs = d.get("data", [])
    rep["final_profiles"] = len(profs)
    st, d = get("/api/resource/POS Profile Group/ALL TIME")
    rep["final_all_time"] = len(d["data"].get("profiles", [])) if st == 200 else -1
    st, d = get("/api/resource/POS Profile Group/SHIFT 2")
    rep["final_shift2"] = len(d["data"].get("profiles", [])) if st == 200 else -1
    for comp in ["TOSERBA JADI BARU KEBUMEN", "RSUP Palembang",
                 "Bangka Tengah (FRC)"]:
        nm = f"SHIFT 2 - {comp}"
        st2, d2 = get("/api/resource/POS Profile/" + urllib.parse.quote(nm))
        if st2 == 200:
            x = d2["data"]
            rep["samples"][nm] = {
                "group": x.get("pos_profile_group"),
                "schedule": f"{x.get('pos_schedule_start')}-"
                            f"{x.get('pos_schedule_end')}",
                "price_list": x.get("selling_price_list"),
                "pg": x.get("custom_pos_next_price_group"),
                "payments": [p.get("mode_of_payment")
                             for p in x.get("payments", [])]}
    print(f"\nfinal: profil {rep['final_profiles']} | ALL TIME "
          f"{rep['final_all_time']} | SHIFT 2 {rep['final_shift2']}")
    print("samples:", json.dumps(rep["samples"], ensure_ascii=False, indent=1))
    json.dump(rep, open("experiments/create_shift2_report.json", "w"),
              ensure_ascii=False, indent=1)
    print("report: experiments/create_shift2_report.json")


if __name__ == "__main__":
    main()
