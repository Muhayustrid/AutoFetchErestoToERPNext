#!/usr/bin/env python3
"""Onboard 2 company RS baru di ERPNext BARU (pola `migrate_po_selogiri_9okt.py`).

Konteks (instruksi user 2026-10-13: "untuk 2 company boleh ditambahkan"):
- PO eResto 12 Okt 2026 dari divisi yang Company-nya belum ada di BARU:
    * RSUD HJ. ANNA LASMANAH BANJARNEGARA   (PO187.121026.001, processing)
    * RSUD PROF H MUHAMMADIYAH YAMIN SH     (PO339.121026.001..005; 001 rejected)
- Onboarding idempoten persis pola RSUD KRAMAT JATI / Selogiri:
    Company (anak OUTLET) + Fiscal Year 2026 + Allowed To Transact With di
    supplier PT. JUARA ROTI INDONESIA + customer internal.
- PO-nya TIDAK dibuat di sini — setelah prep, jalankan ulang
  `migrate_po_juri_9_12_okt.py --date-from 2026-10-12 --date-to 2026-10-13`.

CLI:
  python pos_sync/onboard_company_rs_12okt.py [--dry-run]
"""
import argparse
import json
import os
import sys
import urllib.parse

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, JURI  # noqa: E402
import lengkapi_item_defaults_semua as lid  # noqa: E402


def load_env_file(filepath):
    env = {}
    if os.path.exists(filepath):
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV_PROD = load_env_file("/tmp/eresto_prod.env")
ERPNEXT_URL = os.environ.get("ERPNEXT_URL") or ENV_PROD.get(
    "ERPNEXT_URL", "https://ropierpnext.frappe.cloud")
ERPNEXT_KEY = os.environ.get("ERPNEXT_API_KEY") or ENV_PROD.get("ERPNEXT_API_KEY", "")

_q = urllib.parse.quote

# (company_name, abbr) — abbr wajib unik di seluruh company site.
COMPANIES = [
    ("RSUD HJ. ANNA LASMANAH BANJARNEGARA", "RSAL"),
    ("RSUD PROF H MUHAMMADIYAH YAMIN SH", "RSPY"),
]


def existing_abbrs(erp):
    abbrs = set()
    for row in erp.list_all("Company", ["name", "abbr"]):
        abbrs.add(row["abbr"])
    return abbrs


def ensure_company(erp, company, abbr, dry_run, log):
    used = existing_abbrs(erp)
    st0, d0 = erp.get("/api/resource/Company/" + _q(company))
    if st0 == 200 and (d0.get("data") or {}).get("abbr"):
        abbr = d0["data"]["abbr"]  # company sudah ada -> pakai abbr existing
    elif abbr in used:
        raise SystemExit(f"[prep] ABBR '{abbr}' sudah dipakai company lain "
                         f"(di luar {company}) — pilih abbr unik")
    st, d = erp.get("/api/resource/Company/" + _q(company))
    if st == 200:
        log.append({"Company": company, "Step": "Company", "Status": "SUDAH ADA"})
    elif dry_run:
        log.append({"Company": company, "Step": "Company", "Status": "DRY-RUN (akan dibuat)"})
        return
    else:
        st, d = erp.req("POST", "/api/resource/Company", {
            "company_name": company, "abbr": abbr, "default_currency": "IDR",
            "country": "Indonesia", "parent_company": "OUTLET",
            "create_chart_of_accounts_based_on": "Existing Company",
            "existing_company": "OUTLET"}, timeout=300)
        if st not in (200, 201):
            st2, _ = erp.get("/api/resource/Company/" + _q(company))
            if st2 != 200:
                raise SystemExit(f"[prep] GAGAL buat Company {company}: HTTP {st} "
                                 f"{json.dumps(d)[:300]}")
            log.append({"Company": company, "Step": "Company",
                        "Status": "DIBUAT (recover setelah timeout)"})
        else:
            log.append({"Company": company, "Step": "Company", "Status": "DIBUAT"})
            print(f"  [prep] company dibuat: {company} ({abbr})")

    missing = []
    for dt, nm in (("Warehouse", f"Stores - {abbr}"),
                   ("Account", f"4210.000 - HPP Pembelian - {abbr}"),
                   ("Cost Center", f"Main - {abbr}")):
        st, _ = erp.get(f"/api/resource/{_q(dt)}/{_q(nm)}")
        if st != 200:
            missing.append(f"{dt} '{nm}'")
    if missing:
        # Company existing (dibuat pihak lain) bisa belum punya master turunan
        # dengan pola ini — cek dulu abbr aktual sebelum gagal keras.
        log.append({"Company": company, "Step": "Master turunan",
                    "Status": "KURANG: " + "; ".join(missing)})
        if st0 == 200:
            raise SystemExit(
                f"[prep] Company {company} SUDAH ADA (abbr {abbr}, dibuat pihak lain) "
                f"tapi master turunan kurang: {missing}. Perlu keputusan user.")
        raise SystemExit(f"[prep] master turunan {company} kurang: " + "; ".join(missing))
    log.append({"Company": company, "Step": f"Master turunan (abbr {abbr})",
                "Status": "OK"})

    st, d = erp.get("/api/resource/Company/" + _q(company))
    if st == 200 and not d["data"].get("enable_perpetual_inventory"):
        if not dry_run:
            st, r = erp.put("Company", company, {"enable_perpetual_inventory": 1})
            if st != 200:
                raise SystemExit(f"[prep] GAGAL set perpetual inventory {company}: "
                                 f"{json.dumps(r)[:200]}")
        log.append({"Company": company, "Step": "Perpetual inventory",
                    "Status": "DIPERBAIKI (0 -> 1)" if not dry_run else "DRY-RUN"})


def ensure_fiscal_year(erp, company, dry_run, log):
    st, d = erp.get("/api/resource/Fiscal Year/2026")
    if st != 200:
        raise SystemExit("[prep] Fiscal Year 2026 tidak ada")
    comps = [x.get("company") for x in d["data"].get("companies", [])]
    if company in comps:
        log.append({"Company": company, "Step": "Fiscal Year 2026", "Status": "SUDAH ADA"})
        return
    if dry_run:
        log.append({"Company": company, "Step": "Fiscal Year 2026", "Status": "DRY-RUN"})
        return
    st, r = erp.put("Fiscal Year", "2026",
                    {"companies": [{"company": c} for c in comps + [company]]})
    if st != 200:
        raise SystemExit(f"[prep] GAGAL update Fiscal Year utk {company}: "
                         f"{json.dumps(r)[:250]}")
    log.append({"Company": company, "Step": "Fiscal Year 2026", "Status": "DITAMBAHKAN"})
    print(f"  [prep] Fiscal Year 2026: +{company}")


def ensure_supplier_allowed(erp, company, dry_run, log):
    st, d = erp.get("/api/resource/Supplier/" + _q(JURI))
    if st != 200:
        raise SystemExit("[prep] Supplier JURI tidak ditemukan")
    comps = [x["company"] for x in d["data"].get("companies", [])]
    if company in comps:
        log.append({"Company": company, "Step": "Allowed di supplier JURI",
                    "Status": "SUDAH ADA"})
        return
    if dry_run:
        log.append({"Company": company, "Step": "Allowed di supplier JURI",
                    "Status": "DRY-RUN"})
        return
    st, r = erp.put("Supplier", JURI,
                    {"companies": [{"company": c} for c in comps + [company]]})
    if st != 200:
        raise SystemExit(f"[prep] GAGAL update supplier utk {company}: "
                         f"{json.dumps(r)[:250]}")
    log.append({"Company": company, "Step": "Allowed di supplier JURI",
                "Status": f"DITAMBAHKAN (total {len(comps) + 1})"})
    print(f"  [prep] supplier JURI: +{company} diizinkan")


def ensure_customer_internal(erp, company, dry_run, log):
    st, d = erp.get("/api/resource/Customer", {
        "filters": json.dumps([["represents_company", "=", company],
                               ["is_internal_customer", "=", 1]]),
        "fields": json.dumps(["name", "companies"]), "limit_page_length": 1})
    rows = d.get("data", []) if st == 200 else []
    if rows:
        code = rows[0]["name"]
        comps = [x.get("company") for x in rows[0].get("companies", [])]
        if JURI not in comps and not dry_run:
            st, r = erp.put("Customer", code,
                            {"companies": [{"company": c} for c in comps + [JURI]]})
            if st != 200:
                raise SystemExit(f"[prep] GAGAL set companies {code}: "
                                 f"{json.dumps(r)[:200]}")
            log.append({"Company": company, "Step": f"Customer internal {code}",
                        "Status": f"DIPERBAIKI (+{JURI})"})
        else:
            log.append({"Company": company, "Step": f"Customer internal {code}",
                        "Status": "SUDAH ADA"})
        return
    if dry_run:
        log.append({"Company": company, "Step": "Customer internal",
                    "Status": "DRY-RUN (akan dibuat)"})
        return
    st, d = erp.post("Customer", {
        "customer_name": company, "customer_type": "Company",
        "customer_group": "Outlet Reguler", "territory": "Indonesia",
        "is_internal_customer": 1, "represents_company": company,
        "companies": [{"company": JURI}]})
    if st != 200:
        raise SystemExit(f"[prep] GAGAL buat customer {company}: "
                         f"{json.dumps(d)[:250]}")
    code = d["data"]["name"]
    log.append({"Company": company, "Step": f"Customer internal {code}",
                "Status": "DIBUAT"})
    print(f"  [prep] customer internal dibuat: {company} -> {code}")


def ensure_item_defaults(erp, company, dry_run, log):
    """Baris item_defaults company baru utk item wajib-semua-outlet
    (aturan akun di `lengkapi_item_defaults_semua.py`)."""
    st, d = erp.get("/api/resource/Company/" + _q(company))
    if st != 200:
        log.append({"Company": company, "Step": "Item defaults",
                    "Status": "DRY-RUN (company belum ada)"})
        return
    company = d["data"]["name"]  # nama kanonik (lookup MariaDB case-insensitive: 'HJ.' vs 'Hj.')
    items, wajib, plan, skipped, no_rule = lid.build_plan(erp, [company], set())
    n = sum(len(p["fill"]) + len(p["add"]) for p in plan.values())
    if dry_run:
        status = f"DRY-RUN ({n} baris akan ditulis)"
    else:
        for code, p in sorted(plan.items()):
            lid.apply_item(erp, code, p)
        # cek akhir: rencana ulang harus kosong (semua item wajib punya baris berakun)
        left = lid.build_plan(erp, [company], set())[2]
        status = f"DITULIS {n} baris" if not left else f"WARNING: {len(left)} item masih kurang"
        if left:
            print(f"  [prep] WARNING item_defaults {company} kurang: {sorted(left)[:10]}")
    if no_rule:
        status += f" | TANPA ATURAN: {no_rule}"
    log.append({"Company": company, "Step": f"Item defaults ({len(wajib) - len(skipped)} item)",
                "Status": status})


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="tanpa POST/PUT")
    args = ap.parse_args()

    erp = Client(ERPNEXT_URL, ERPNEXT_KEY, label="BARU", pause=0.15)
    print("=" * 84)
    print(f"  ONBOARD COMPANY RS BARU -> {erp.base}")
    print(f"  Mode: {'DRY-RUN' if args.dry_run else 'EXECUTE'} | {len(COMPANIES)} company")
    print("=" * 84)

    log = []
    for company, abbr in COMPANIES:
        print(f"\n-- {company} ({abbr})")
        ensure_company(erp, company, abbr, args.dry_run, log)
        ensure_fiscal_year(erp, company, args.dry_run, log)
        ensure_supplier_allowed(erp, company, args.dry_run, log)
        ensure_customer_internal(erp, company, args.dry_run, log)
        ensure_item_defaults(erp, company, args.dry_run, log)

    print("\n" + "=" * 84)
    for row in log:
        print(f"  {row['Company']:38} | {row['Step']:44} | {row['Status']}")
    print("=" * 84)


if __name__ == "__main__":
    main()
