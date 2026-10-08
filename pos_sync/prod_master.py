"""Tahap master PROD (docs/07): lengkapi master yang kurang sebelum dokumen.

- Manufacturing Settings: overproduction_percentage_for_work_order 0 -> 50
  (samakan lokal; tanpa ini submit WO/SE Manufacture kena batas 0%).
- 8 company baru sebagai anak "OUTLET" + customer internal + izin transaksi
  ke PT. JUARA ROTI INDONESIA (child `companies`).
- Supplier JURI: tambah 8 company baru ke Allowed To Transact With.
- Fiscal Year 2026: tambah 8 company. Mode of Payment: tambah baris akun 8
  company (hanya bila akunnya ada).
- 8 item baru + BOM-PJ260016-001 (Krim Kopi) dibuat & disubmit.

Idempoten: skip yang sudah ada. Usage: python3 prod_master.py [--dry-run]
"""
import argparse
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import (JURI, LOCAL_ENV, PROD_ENV, SRC_DIR, Client,  # noqa: E402
                         jload, load_env, load_state, pick, pick_rows,
                         save_state)

DROPS_CUSTOMER = ("naming_series", "accounts", "credit_limits", "sales_team",
                  "sales_partner", "loyalty_program", "loyalty_points")
DROPS_ITEM = ("customer_items", "supplier_items", "barcodes",
              "reorder_levels", "taxes", "website_slideshow",
              "item_manufacturers", "uom_conversions")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    le, pe = load_env(LOCAL_ENV), load_env(PROD_ENV)
    lc = Client(le["ERPNEXT_URL"], le["ERPNEXT_API_KEY"], label="local")
    pc = Client(pe["ERPNEXT_URL"], pe["ERPNEXT_API_KEY"], label="prod")
    meta = json.load(open(os.path.join(SRC_DIR, "prod_meta.json")))
    st = load_state()
    st.setdefault("customer_alias", {})
    fails = []

    def fail(what, detail):
        fails.append({"apa": what, "detail": str(detail)[:300]})
        print(f"  GAGAL {what}: {str(detail)[:200]}")

    # ---------- 1. overproduction 50 ----------
    print("== 1. Manufacturing Settings ==")
    st_get, d = pc.get("/api/method/frappe.client.get_single_value", {
        "doctype": "Manufacturing Settings",
        "field": "overproduction_percentage_for_work_order"})
    cur = d.get("message") if st_get == 200 else None
    print(f"  overprod sekarang: {cur}")
    if cur == 50:
        print("  sudah 50, skip")
    elif args.dry_run:
        print("  DRY-RUN set 50")
    else:
        st2, d2 = pc.req("POST", "/api/method/frappe.client.set_value", {
            "doctype": "Manufacturing Settings",
            "name": "Manufacturing Settings",
            "fieldname": "overproduction_percentage_for_work_order",
            "value": 50})
        st_chk, d_chk = pc.get("/api/method/frappe.client.get_single_value", {
            "doctype": "Manufacturing Settings",
            "field": "overproduction_percentage_for_work_order"})
        val = d_chk.get("message") if st_chk == 200 else None
        print(f"  set 50 -> HTTP {st2}, sekarang {val}")
        if val != 50:
            fail("overprod", d2)

    # ---------- 2. company ----------
    print("== 2. company anak OUTLET ==")
    comp_docs = jload("companies_missing.json")
    prod_companies = {c["name"] for c in pc.list_all("Company", ["name"])}
    for doc in comp_docs:
        name = doc["name"]
        if name in prod_companies:
            print(f"  skip {name}: sudah ada")
            continue
        if args.dry_run:
            print(f"  DRY-RUN buat company {name} (abbr {doc.get('abbr')})")
            continue
        st2, d2 = pc.post("Company", {
            "company_name": name, "abbr": doc.get("abbr"),
            "country": doc.get("country") or "Indonesia",
            "default_currency": "IDR", "parent_company": "OUTLET",
            "create_chart_of_accounts_based_on": "Existing Company",
            "existing_company": "OUTLET"})
        if st2 != 200:
            fail(f"company {name}", d2)
        else:
            print(f"  OK company {name}")

    # ---------- 3. customer internal ----------
    print("== 3. customer internal + allow JURI ==")
    cust_dump = jload("customers.json")
    by_name = {}
    for c in cust_dump:
        by_name.setdefault(c.get("customer_name"), c)
    prod_cust = pc.list_all("Customer", ["name", "customer_name",
                                         "is_internal_customer",
                                         "companies"])
    # list_all tidak bawa child; ambil ulang per kode saat perlu
    cust_by_name = {}
    for c in prod_cust:
        cust_by_name.setdefault(c["customer_name"], c["name"])

    def ensure_customer(name, internal):
        """Pastikan customer ada, internal sesuai, dan JURI diizinkan."""
        code = cust_by_name.get(name)
        if args.dry_run:
            print(f"  DRY-RUN customer {name} (ada={bool(code)})")
            return code
        if not code:
            doc = by_name.get(name)
            if not doc:
                fail(f"customer {name}", "tidak ada di dump lokal")
                return None
            payload = pick(doc, meta["Customer"], DROPS_CUSTOMER)
            payload["doctype"] = "Customer"
            payload["companies"] = [{"company": JURI}]
            if internal:
                payload["is_internal_customer"] = 1
                payload["represents_company"] = name
            st2, d2 = pc.post("Customer", payload)
            if st2 != 200:
                fail(f"customer {name}", d2)
                return None
            code = d2["data"]["name"]
            cust_by_name[name] = code
            st.setdefault("customer_new", {})[name] = code
            print(f"  OK customer baru {name} -> {code}")
            return code
        st2, d2 = pc.get("/api/resource/Customer/"
                         + urllib.parse.quote(code))
        doc = d2.get("data", {})
        comps = [x.get("company") for x in doc.get("companies", [])]
        want = {"is_internal_customer": 1 if internal else 0,
                "represents_company": name if internal else None}
        need_put = False
        if internal and not doc.get("is_internal_customer"):
            need_put = True
        if internal and doc.get("represents_company") != name:
            need_put = True
        if JURI not in comps:
            need_put = True
        if need_put:
            payload = {"companies": [{"company": c} for c in comps
                                     if c and c != JURI] + [{"company": JURI}]}
            if internal:
                payload.update(want)
            st3, d3 = pc.put("Customer", code, payload)
            if st3 != 200:
                fail(f"customer update {name}", d3)
            else:
                print(f"  OK update {name} ({code})")
        else:
            print(f"  skip {name} ({code}): sudah internal + JURI")
        return code

    for doc in comp_docs:
        ensure_customer(doc["name"], internal=True)
    # RSI FATIMAH BANYUWANGI: dipakai DN, non-internal di lokal
    code_fatimah = ensure_customer("RSI FATIMAH BANYUWANGI", internal=False)
    if code_fatimah:
        st["customer_alias"]["CUST-260210"] = code_fatimah
    # Harapan Indah (FRC): prod duplikat + beda kapitalisasi ("indah") ->
    # cocokkan case-insensitive, pilih kode terkecil deterministik.
    cands = [c for c in prod_cust
             if (c.get("customer_name") or "").strip().lower()
             == "harapan indah (frc)"]
    if cands:
        pick_code = sorted(c["name"] for c in cands)[0]
        if not args.dry_run:
            st2, d2 = pc.get("/api/resource/Customer/"
                             + urllib.parse.quote(pick_code))
            comps = [x.get("company") for x in
                     (d2.get("data", {}) or {}).get("companies", [])]
            if JURI not in comps:
                pc.put("Customer", pick_code,
                       {"companies": [{"company": c} for c in comps if c]
                        + [{"company": JURI}]})
        st["customer_alias"]["CUST-260211"] = pick_code
        print(f"  alias CUST-260211 -> {pick_code} "
              f"({len(cands)} kandidat, pilih terkecil)")
    else:
        fail("alias CUST-260211", "Harapan Indah (FRC) tidak ketemu di prod")
    # Wahid Hasyim: pastikan JURI diizinkan
    if not args.dry_run and "Wahid Hasyim (FRC)" in cust_by_name:
        code = cust_by_name["Wahid Hasyim (FRC)"]
        st2, d2 = pc.get("/api/resource/Customer/" + urllib.parse.quote(code))
        comps = [x.get("company") for x in (d2.get("data", {}) or {}).get(
            "companies", [])]
        if JURI not in comps:
            pc.put("Customer", code,
                   {"companies": [{"company": c} for c in comps if c]
                    + [{"company": JURI}]})
            print(f"  OK allow JURI -> Wahid Hasyim ({code})")

    # ---------- 3b. supplier baru ----------
    print("== 3b. supplier baru (dipakai PO/PR) ==")
    for sdoc in jload("suppliers_missing.json"):
        nm = sdoc.get("supplier_name") or sdoc.get("name")
        st2, d2 = pc.get("/api/resource/Supplier/" + urllib.parse.quote(nm))
        if st2 == 200:
            print(f"  skip supplier {nm}: sudah ada")
            continue
        if args.dry_run:
            print(f"  DRY-RUN buat supplier {nm}")
            continue
        st2, d2 = pc.post("Supplier", {
            "doctype": "Supplier", "supplier_name": nm,
            "supplier_group": sdoc.get("supplier_group")
                              or "All Supplier Groups",
            "supplier_type": sdoc.get("supplier_type") or "Company",
            "country": sdoc.get("country") or "Indonesia"})
        if st2 != 200:
            fail(f"supplier {nm}", d2)
        else:
            print(f"  OK supplier {nm}")

    # ---------- 4. supplier JURI ----------
    print("== 4. supplier JURI (Allowed To Transact With) ==")
    st2, d2 = pc.get("/api/resource/Supplier/" + urllib.parse.quote(JURI))
    if st2 != 200:
        fail("supplier JURI", d2)
    else:
        comps = [x.get("company") for x in d2["data"].get("companies", [])]
        need = [doc["name"] for doc in comp_docs if doc["name"] not in comps]
        if not need:
            print("  sudah lengkap, skip")
        elif args.dry_run:
            print(f"  DRY-RUN tambah {len(need)}: {need}")
        else:
            st3, d3 = pc.put("Supplier", JURI, {
                "companies": [{"company": c} for c in comps] +
                             [{"company": c} for c in need]})
            print(f"  +{len(need)} company: HTTP {st3}")
            if st3 != 200:
                fail("supplier JURI update", d3)

    # ---------- 5. Fiscal Year 2026 ----------
    print("== 5. Fiscal Year 2026 ==")
    st2, d2 = pc.get("/api/resource/Fiscal Year/2026")
    if st2 != 200:
        fail("FY2026", d2)
    else:
        comps = [x.get("company") for x in d2["data"].get("companies", [])]
        need = [doc["name"] for doc in comp_docs if doc["name"] not in comps]
        if not need:
            print("  sudah lengkap, skip")
        elif args.dry_run:
            print(f"  DRY-RUN tambah {len(need)}: {need}")
        else:
            st3, d3 = pc.put("Fiscal Year", "2026", {
                "companies": [{"company": c} for c in comps] +
                             [{"company": c} for c in need]})
            print(f"  +{len(need)} company: HTTP {st3}")
            if st3 != 200:
                fail("FY2026 update", d3)

    # ---------- 6. Mode of Payment ----------
    print("== 6. Mode of Payment (baris akun 8 company) ==")
    mops = {m["name"]: m for m in jload("mop_local.json")}
    eight = {doc["name"] for doc in comp_docs}
    for mop, doc in mops.items():
        rows = {a["company"]: a["default_account"]
                for a in doc.get("accounts", [])}
        st2, d2 = pc.get("/api/resource/Mode of Payment/"
                         + urllib.parse.quote(mop))
        if st2 != 200:
            fail(f"MoP {mop}", d2)
            continue
        cur = [{"company": a.get("company"),
                "default_account": a.get("default_account")}
               for a in d2["data"].get("accounts", [])]
        kept = [a for a in cur if a["company"] not in eight]
        added, wrong = [], []
        for cdoc in comp_docs:
            nm = cdoc["name"]
            acc = rows.get(nm)
            if not acc:
                continue
            stA, _ = pc.get("/api/resource/Account/" + urllib.parse.quote(acc))
            if stA != 200:
                print(f"  {mop}: akun {acc} tidak ada di prod, skip {nm}")
                continue
            existing = [a["default_account"] for a in cur
                        if a["company"] == nm]
            if existing and existing[0] == acc and len(existing) == 1:
                kept.append({"company": nm, "default_account": acc})
            else:
                if existing and existing[0] != acc:
                    wrong.append((nm, existing[0]))
                added.append({"company": nm, "default_account": acc})
        if not added:
            print(f"  {mop}: semua benar, skip")
            continue
        if args.dry_run:
            print(f"  DRY-RUN {mop} +{len(added)} baris "
                  f"(perbaiki {len(wrong)} akun salah)")
            continue
        st3, d3 = pc.put("Mode of Payment", mop, {"accounts": kept + added})
        print(f"  {mop}: +{len(added)} (perbaiki {len(wrong)} salah) HTTP {st3}")
        if st3 != 200:
            fail(f"MoP {mop} update", d3)

    # ---------- 7. item ----------
    print("== 7. item baru ==")
    for doc in jload("items_missing.json"):
        code = doc["item_code"]
        st2, _ = pc.get("/api/resource/Item/" + urllib.parse.quote(code))
        if st2 == 200:
            print(f"  skip {code}: sudah ada")
            continue
        if args.dry_run:
            print(f"  DRY-RUN buat item {code} ({doc.get('item_name')})")
            continue
        payload = pick(doc, meta["Item"],
                       DROPS_ITEM + ("naming_series",))
        payload["doctype"] = "Item"
        payload["uoms"] = pick_rows(doc.get("uoms"), meta["UOM Conversion Detail"])
        payload["item_defaults"] = pick_rows(doc.get("item_defaults"),
                                             meta["Item Default"])
        st2, d2 = pc.post("Item", payload)
        if st2 != 200:
            fail(f"item {code}", d2)
            continue
        name = d2["data"]["name"]
        if name != code:
            st3, d3 = pc.rename("Item", name, code)
            if st3 != 200 or (d3.get("message") or "") != code:
                fail(f"rename {name}->{code}", d3)
                continue
            print(f"  OK item {code} (rename dari {name})")
        else:
            print(f"  OK item {code}")

    # ---------- 8. BOM Krim Kopi ----------
    print("== 8. BOM-PJ260016-001 ==")
    bom = jload("bom_krim_kopi.json")[0]
    st2, d2 = pc.get("/api/resource/BOM/BOM-PJ260016-001")
    if st2 == 200:
        print("  sudah ada")
        st.setdefault("bom_map", {})["BOM-PJ260016-001"] = "BOM-PJ260016-001"
    elif args.dry_run:
        print("  DRY-RUN buat + submit BOM")
    else:
        payload = {
            "doctype": "BOM", "item": bom["item"],
            "quantity": bom["quantity"], "uom": bom["uom"],
            "company": bom["company"], "is_active": 1, "is_default": 1,
            "with_operations": 0, "transfer_material_against": "Work Order",
            "currency": "IDR", "conversion_rate": 1.0,
            "rm_cost_as_per": "Valuation Rate",
            "items": pick_rows(bom.get("items"), meta["BOM Item"]),
            "remarks": "ERESTO BOM-PJ260016-001 (resep site lama)",
        }
        st2, d2 = pc.post("BOM", payload)
        if st2 != 200:
            fail("BOM PJ260016", d2)
        else:
            bname = d2["data"]["name"]
            st3, d3 = pc.submit("BOM", bname)
            st.setdefault("bom_map", {})["BOM-PJ260016-001"] = bname
            if st3 != 200:
                fail(f"submit BOM {bname}", d3)
            else:
                print(f"  OK BOM {bname} submitted")

    save_state(st)
    print("== ringkasan ==")
    print(f"  gagal: {len(fails)}")
    for f in fails:
        print("   ", f)
    if fails and not args.dry_run:
        sys.exit(1)
    print("MASTER OK")


if __name__ == "__main__":
    main()
