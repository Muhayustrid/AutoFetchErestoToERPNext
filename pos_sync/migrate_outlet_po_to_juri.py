"""Migrasi Purchase Order OUTLET -> PT. JUARA ROTI INDONESIA (25 Sep - 7 Okt 2026).

Sumber: ERPNext Cloud LAMA (rotiropi.j.frappe.cloud) — supplier SUP260008
(PT. Juara Roti Indonesia), company != 'PT. JUARA ROTI INDONESIA'.
Target: ERPNext Cloud BARU (ropierpnext.frappe.cloud). ID dipertahankan.

Alur: --dump -> --prep -> --migrate -> --verify (semua idempoten, rerun aman).
PO yang sudah terlanjur masuk dengan gudang transit: --rewarehouse.

Penyesuaian (hasil audit sumber vs target):
- ID bawaan dipertahankan (rename_doc); docstatus persis sumber (1/0).
- Supplier lama SUP260008 -> 'PT. JUARA ROTI INDONESIA'.
- Gudang target = 'Stores - <ABBR>' per company (revisi user 2026-10-08),
  bukan 'Goods In Transit - <ABBR>' bawaan site lama.
- Remap bentrok kode: BB260059 (lama 'Gula Cair 250 g') -> BB26009 (baru);
  konsisten dgn pos_sync/catchup_oct7.py.
- UOM 'Kg'/'KG' -> 'kg'; conversion factor diselaraskan ke master Item baru.
- 'Cost of Goods Sold - RFB' -> '4210.000 - HPP Pembelian - RFB' (RFB baru
  pakai CoA OUTLET).
- Baris PEL260007 (balon; item sengaja dihapus di site baru) dilewati + dicatat.
- Prep: company yang belum ada (RSI FATIMAH BANYUWANGI / RFB, RS RIDHOKA
  SALMA CIKARANG / RRSC) dibuat anak OUTLET; 'Allowed To Transact With'
  supplier JURI dilengkapi 114 outlet; UOM master item dilengkapi.

Env (/tmp/eresto_mig.env + /tmp/eresto_prod.env, jangan tulis nilai ke repo):
  ERPNEXT_OLD_CLOUD_API_KEY (site lama), ERPNEXT_URL + ERPNEXT_API_KEY (baru).
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DUMP_DIR = os.path.join(HERE, "outlet_po_dump")
REPORT = os.path.join(HERE, "Laporan_Migrasi_PO_Outlet_ke_JURI.xlsx")

OLD_BASE = "https://rotiropi.j.frappe.cloud"
JURI = "PT. JUARA ROTI INDONESIA"
SUPPLIER_OLD = "SUP260008"
DATE_FROM, DATE_TO = "2026-09-25", "2026-10-08"

ITEM_MAP = {"BB260059": "BB26009"}          # bentrok kode, lihat catchup_oct7.py
UOM_MAP = {"Kg": "kg", "KG": "kg"}

# Revisi user 2026-10-08: gudang PO di TARGET = 'Stores - <ABBR>' milik company
# outlet (bukan 'Goods In Transit - <ABBR>' bawaan site lama).
WAREHOUSE_TARGET = "Stores"

# baris yang dilewati: item tidak dibuat ulang di site baru (keputusan lama)
SKIP_ROWS = {
    "PO185.051026.001": {
        "PEL260007": "item Balon Kuning dihapus di site baru (ACC user 2026-10-07)",
    },
}

# UOM tambahan pada master Item site baru agar cocok dgn baris sumber.
# PEL260071 'Pack' sengaja TIDAK ditambah: baris sumbernya artefak (cf=1 ==
# Pcs) -> diretur ke stock_uom Pcs oleh aturan fallback di build_payload.
ITEM_UOM_FIX = {
    "PEL260072": ("Pack", 10.0),
    "PEL260056": ("Pcs", 1.0),
    "PEL260058": ("Pcs", 1.0),
}

HDR_KEEP = [
    "company", "transaction_date", "transaction_time", "schedule_date",
    "currency", "conversion_rate", "buying_price_list", "price_list_currency",
    "plc_conversion_rate", "ignore_pricing_rule", "set_warehouse",
    "language", "disable_rounded_total", "group_same_items", "tax_category",
]
ROW_KEEP = [
    "item_code", "qty", "rate", "uom", "conversion_factor", "stock_uom",
    "warehouse", "expense_account", "cost_center", "schedule_date",
]


def read_env(path):
    d = {}
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def clients():
    mig = read_env("/tmp/eresto_mig.env")
    prod = read_env("/tmp/eresto_prod.env")
    old_key = mig.get("ERPNEXT_OLD_CLOUD_API_KEY")
    new_key = prod.get("ERPNEXT_API_KEY")
    new_base = prod.get("ERPNEXT_URL") or "https://ropierpnext.frappe.cloud"
    if not old_key or not new_key:
        raise SystemExit("env kurang: butuh ERPNEXT_OLD_CLOUD_API_KEY (mig) "
                         "dan ERPNEXT_API_KEY (prod)")
    return (Client(OLD_BASE, old_key, "lama"),
            Client(new_base, new_key, "baru"))


def jdump(name, obj):
    os.makedirs(DUMP_DIR, exist_ok=True)
    with open(os.path.join(DUMP_DIR, name), "w") as f:
        json.dump(obj, f, indent=1, default=str)


def jload(name, default=None):
    path = os.path.join(DUMP_DIR, name)
    if not os.path.exists(path):
        return default
    return json.load(open(path))


# ---------------------------------------------------------------- dump
def cmd_dump(old, refresh=False):
    if not refresh and os.path.exists(os.path.join(DUMP_DIR, "po_docs.json")):
        docs = jload("po_docs.json")
        print(f"[dump] pakai cache: {len(docs)} PO (--refresh untuk tarik ulang)")
        return docs
    print("[dump] tarik daftar PO outlet -> JURI dari site lama ...")
    rows = old.list_all("Purchase Order", ["name"], filters=[
        ["transaction_date", ">=", DATE_FROM],
        ["transaction_date", "<=", DATE_TO],
        ["supplier", "=", SUPPLIER_OLD],
        ["company", "!=", JURI],
    ], order="transaction_date asc, name asc")
    names = [r["name"] for r in rows]
    print(f"[dump] {len(names)} PO, ambil detail ...")
    docs = {}

    def one(c, n):
        st, d = c.get("/api/resource/Purchase Order/" + quote(n))
        return n, (d.get("data") if st == 200 else None)

    with ThreadPoolExecutor(4) as ex:
        futs = [ex.submit(one, old, n) for n in names]
        for i, fu in enumerate(as_completed(futs), 1):
            n, doc = fu.result()
            if doc:
                docs[n] = doc
            if i % 50 == 0:
                print(f"  ... {i}/{len(names)}")
    jdump("po_docs.json", docs)

    abbrs = {}
    for c in sorted({d["company"] for d in docs.values()}):
        st, d = old.get("/api/resource/Company/" + quote(c),
                        {"fields": json.dumps(["name", "abbr"])})
        if st == 200:
            abbrs[c] = d["data"]["abbr"]
    jdump("company_abbr.json", abbrs)
    print(f"[dump] selesai: {len(docs)} PO, {len(abbrs)} company")
    return docs


# ---------------------------------------------------------------- prep
def ensure_companies(new, docs):
    comps = sorted({d["company"] for d in docs.values()})
    abbrs = jload("company_abbr.json", {})
    have = {c["name"] for c in new.list_all("Company", ["name"])}
    dibuat = []
    for c in comps:
        if c in have:
            continue
        abbr = abbrs.get(c) or "".join(w[0] for w in c.split()
                                       if w[0].isalnum())[:8].upper()
        st, d = new.post("Company", {
            "company_name": c, "abbr": abbr, "default_currency": "IDR",
            "country": "Indonesia", "parent_company": "OUTLET",
            "create_chart_of_accounts_based_on": "Existing Company",
            "existing_company": "OUTLET"})
        if st != 200:
            raise SystemExit(f"[prep] GAGAL buat company {c}: HTTP {st} "
                             f"{json.dumps(d)[:300]}")
        dibuat.append({"company": c, "abbr": abbr, "status": "DIBUAT"})
        print(f"[prep] company dibuat: {c} ({abbr})")

    miss = []
    for c in comps:
        ab = abbrs.get(c)
        if not ab:
            miss.append((c, "abbr tidak diketahui"))
            continue
        for dt, nm in (("Warehouse", f"Goods In Transit - {ab}"),
                       ("Account", f"4210.000 - HPP Pembelian - {ab}"),
                       ("Cost Center", f"Main - {ab}")):
            st, _ = new.get(f"/api/resource/{quote(dt)}/{quote(nm)}")
            if st != 200:
                miss.append((c, f"{dt} '{nm}' tidak ada"))
    if miss:
        raise SystemExit("[prep] master kurang: " + json.dumps(miss[:10]))
    jdump("companies_prep.json", dibuat)
    print(f"[prep] companies OK ({len(dibuat)} baru, {len(comps)} dipakai)")
    return dibuat


def ensure_supplier_allowed(new, docs):
    comps = sorted({d["company"] for d in docs.values()})
    st, d = new.get("/api/resource/Supplier/" + quote(JURI))
    sup = d.get("data") or {}
    cur = [x["company"] for x in sup.get("companies", [])]
    add = [c for c in comps if c not in cur]
    if add:
        st, d = new.put("Supplier", JURI,
                        {"companies": [{"company": c} for c in cur + add]})
        if st != 200:
            raise SystemExit(f"[prep] GAGAL update supplier: {json.dumps(d)[:300]}")
        print(f"[prep] supplier JURI: +{len(add)} company diizinkan "
              f"(total {len(cur)+len(add)})")
    else:
        print("[prep] supplier JURI: allowed list sudah lengkap")
    jdump("supplier_allowed.json",
          {"ditambahkan": add, "total": len(cur) + len(add)})
    return add


def ensure_item_uoms(new):
    hasil = []
    for code, (uom, cf) in ITEM_UOM_FIX.items():
        st, d = new.get("/api/resource/Item/" + quote(code),
                        {"fields": json.dumps(["name", "uoms"])})
        if st != 200:
            raise SystemExit(f"[prep] item {code} tidak ada di site baru")
        rows = [{"uom": x["uom"], "conversion_factor": x["conversion_factor"]}
                for x in d["data"].get("uoms", [])]
        if any(x["uom"] == uom for x in rows):
            hasil.append({"item": code, "uom": uom, "cf": cf,
                          "status": "SUDAH ADA"})
            continue
        rows.append({"uom": uom, "conversion_factor": cf})
        st, d = new.put("Item", code, {"uoms": rows})
        if st != 200:
            raise SystemExit(f"[prep] GAGAL update UOM {code}: "
                             f"{json.dumps(d)[:200]}")
        hasil.append({"item": code, "uom": uom, "cf": cf, "status": "DITAMBAH"})
        print(f"[prep] item {code}: UOM {uom}={cf} ditambahkan")
        # segarkan cache master item agar migrate tidak pakai data basi
        cache = jload("items_master.json", {})
        if code in cache:
            cache[code]["uoms"] = rows
            jdump("items_master.json", cache)
    jdump("item_uom_prep.json", hasil)
    return hasil


def ensure_fiscal_year(new, docs):
    """Company baru harus terdaftar di Fiscal Year yang mencakup tanggal PO-nya,
    jika tidak POST PO gagal FiscalYearError.

    Jebakan Frappe: satu company ditolak masuk dua FY yang rentangnya overlap
    (site punya FY '2026' dan 'Training' dengan rentang identik) -> company
    dilewati bila sudah ada di FY lain yang tumpang tindih.
    """
    from collections import defaultdict
    need = defaultdict(list)        # company -> [tanggal PO]
    for d in docs.values():
        need[d["company"]].append(d["transaction_date"])
    fys = []
    for f in new.list_all("Fiscal Year", ["name", "year_start_date",
                                          "year_end_date", "disabled"],
                          filters=[["disabled", "=", 0]]):
        st, d = new.get("/api/resource/Fiscal Year/" + quote(f["name"]))
        f["_companies"] = [x.get("company")
                           for x in (d.get("data") or {}).get("companies", [])]
        fys.append(f)

    def overlaps(a, b):
        return (a["year_start_date"] <= b["year_end_date"]
                and b["year_start_date"] <= a["year_end_date"])

    ditambah = []
    for fy in sorted(fys, key=lambda f: f["year_start_date"]):
        cur = fy["_companies"]
        if not cur:
            continue                # FY global
        add = []
        for c, dates in need.items():
            if c in cur:
                continue
            if not any(fy["year_start_date"] <= dt <= fy["year_end_date"]
                       for dt in dates):
                continue
            lain = [f for f in fys if f is not fy and c in f["_companies"]
                    and overlaps(f, fy)]
            if lain:
                continue            # sudah di FY overlap -> Frappe menolak
            add.append(c)
        if not add:
            continue
        st, d = new.put("Fiscal Year", fy["name"],
                        {"companies": [{"company": c} for c in cur + add]})
        if st != 200:
            raise SystemExit(f"[prep] GAGAL update Fiscal Year {fy['name']}: "
                             f"{json.dumps(d)[:200]}")
        ditambah.append({"fy": fy["name"], "companies": add})
        print(f"[prep] Fiscal Year {fy['name']}: +{len(add)} company")
    return ditambah


def cmd_prep(old, new, docs):
    dibuat = ensure_companies(new, docs)
    fy = ensure_fiscal_year(new, docs)
    add = ensure_supplier_allowed(new, docs)
    uoms = ensure_item_uoms(new)
    jdump("fiscal_year_prep.json", fy)
    return dibuat, add, uoms


# ---------------------------------------------------------------- migrate
def fetch_item(client, code):
    st, d = client.get("/api/resource/Item/" + quote(code),
                       {"fields": json.dumps(["name", "stock_uom", "uoms"])})
    return code, (d.get("data") if st == 200 else None)


def load_items_master(new, docs):
    """Master item site baru per kode (uoms child TIDAK ikut di list query)."""
    used = sorted({ITEM_MAP.get(it["item_code"], it["item_code"])
                   for d in docs.values() for it in d.get("items", [])})
    cache = jload("items_master.json", {})
    missing = [c for c in used if c not in cache]
    if missing:
        print(f"[migrate] ambil master {len(missing)} item dari site baru ...")
        with ThreadPoolExecutor(6) as ex:
            futs = [ex.submit(fetch_item, new, c) for c in missing]
            for fu in as_completed(futs):
                code, doc = fu.result()
                if doc:
                    cache[code] = doc
        jdump("items_master.json", cache)
    return cache


def wh_target(old_wh, abbr):
    """Gudang target PO = 'Stores - <ABBR>' (revisi user 2026-10-08);
    sumber site lama memakai 'Goods In Transit - <ABBR>'.

    ABBR diambil dari company site TARGET (bisa beda dari suffix nama gudang
    lama, mis. 'Gudang RnD - ROPI' -> 'Gudang R&D - JURI'); suffix sumber hanya
    dipakai sebagai fallback bila abbr tidak diketahui.
    """
    if not abbr and old_wh:
        abbr = old_wh.rsplit(" - ", 1)[-1]
    return f"{WAREHOUSE_TARGET} - {abbr or ''}".strip()


def target_wh_for(abbrs, company, src_wh):
    """Gudang target utk company: pakai abbr dari peta; bila tidak ada,
    JANGAN pakai nama company (bikin gudang palsu) — pakai suffix gudang
    sumber via wh_target."""
    return wh_target(src_wh, abbrs.get(company))


def build_payload(src, items_master, abbrs=None):
    """Payload PO target: field bersih + item disesuaikan. -> (payload, skipped, alert)"""
    abbrs = abbrs or {}
    payload = {k: src[k] for k in HDR_KEEP if src.get(k) is not None}
    payload["supplier"] = JURI
    payload["title"] = f"ERESTO {src['name']}"
    payload["set_warehouse"] = target_wh_for(abbrs, src["company"],
                                             src.get("set_warehouse"))
    items, skipped, alert = [], [], []
    for it in src.get("items", []):
        code = ITEM_MAP.get(it["item_code"], it["item_code"])
        if it["item_code"] in SKIP_ROWS.get(src["name"], {}):
            skipped.append({"po": src["name"], "item": it["item_code"],
                            "amount": it.get("amount"),
                            "alasan": SKIP_ROWS[src["name"]][it["item_code"]]})
            continue
        row = {k: it[k] for k in ROW_KEEP if it.get(k) is not None}
        row["item_code"] = code
        row["warehouse"] = target_wh_for(abbrs, src["company"],
                                         it.get("warehouse"))
        ni = items_master.get(code)
        uom = UOM_MAP.get(it.get("uom"), it.get("uom"))
        cf = it.get("conversion_factor")
        if ni:
            su = ni.get("stock_uom")
            conv = {u["uom"]: u["conversion_factor"]
                    for u in ni.get("uoms") or []}
            if uom == su:
                cf = 1.0
            elif conv.get(uom):
                cf = conv[uom]
            elif it.get("conversion_factor") == 1.0:
                # artefak sumber (uom == qty 1:1 tapi beda nama, mis. 'Pack'
                # utk item Pcs) -> pakai stock_uom baru
                alert.append(f"{src['name']} {code}: UOM '{uom}' absen & cf=1 "
                             f"-> dikembalikan ke stock_uom '{su}'")
                uom, cf = su, 1.0
            else:
                alert.append(f"{src['name']} {code}: UOM '{uom}' tidak ada "
                             f"di master (pakai factor sumber {cf})")
            row["stock_uom"] = su
        if it.get("conversion_factor") and cf \
                and abs(cf - it["conversion_factor"]) > 1e-9:
            alert.append(f"{src['name']} {code}: factor "
                         f"{it['conversion_factor']} -> {cf} (master baru)")
        row["uom"] = uom
        row["conversion_factor"] = cf
        if it.get("description"):
            row["description"] = it["description"]
        ea = row.get("expense_account") or ""
        if ea.startswith("Cost of Goods Sold"):
            abbr = ea.rsplit(" - ", 1)[-1]
            row["expense_account"] = f"4210.000 - HPP Pembelian - {abbr}"
        items.append(row)
    payload["items"] = items
    return payload, skipped, alert


def migrate_one(new, src, items_master, abbrs, names_set, titles_set, dry):
    name = src["name"]
    idem_title = f"ERESTO {name}"
    if name in names_set or idem_title in titles_set:
        return {"name": name, "status": "SKIP_EXISTS", "skipped": [], "alert": []}
    payload, skipped, alert = build_payload(src, items_master, abbrs)
    if not payload["items"]:
        return {"name": name, "status": "SKIP_KOSONG", "skipped": skipped,
                "alert": alert}
    if dry:
        return {"name": name, "status": "DRY-RUN", "skipped": skipped,
                "alert": alert, "items": len(payload["items"]),
                "grand_total": src.get("grand_total")}
    st, d = new.post("Purchase Order", payload)
    if st != 200:
        return {"name": name, "status": "FAIL_POST",
                "err": json.dumps(d)[:300], "skipped": skipped, "alert": alert}
    final = d["data"]["name"]
    st2, _ = new.rename("Purchase Order", final, name)
    if st2 == 200:
        final = name
    if src.get("docstatus") == 1:
        st3, d3 = new.submit("Purchase Order", final)
        if st3 != 200:
            return {"name": name, "status": "FAIL_SUBMIT", "final": final,
                    "err": json.dumps(d3)[:300], "skipped": skipped,
                    "alert": alert}
    elif src.get("docstatus") == 2:
        new.submit("Purchase Order", final)
        new.cancel("Purchase Order", final)
    return {"name": name, "status": "MIGRATED", "final": final,
            "skipped": skipped, "alert": alert,
            "items": len(payload["items"]), "grand_total": src.get("grand_total")}


def cmd_migrate(old, new, docs, args):
    items_master = load_items_master(new, docs)
    abbrs = jload("company_abbr.json", {})

    existing = new.list_all("Purchase Order", ["name", "title"])
    names_set = {p["name"] for p in existing}
    titles_set = {p["title"] for p in existing if p.get("title")}
    # PO yang sudah ada tapi rename-nya dulu gagal (nama fallback) -> perbaiki
    repair = {p["title"][len("ERESTO "):]: p["name"] for p in existing
              if (p.get("title") or "").startswith("ERESTO ")
              and p["title"][len("ERESTO "):] in docs
              and p["name"] != p["title"][len("ERESTO "):]}

    todo = sorted(docs)
    if args.only:
        todo = [n for n in todo if n == args.only]
    if args.limit:
        todo = todo[: args.limit]

    if repair and not args.dry_run:
        for tgt, cur in sorted(repair.items()):
            st, d = new.rename("Purchase Order", cur, tgt)
            print(f"  [repair] rename {cur} -> {tgt}: "
                  f"{'OK' if st == 200 else 'GAGAL ' + json.dumps(d)[:150]}")
            if st == 200:
                names_set.discard(cur)
                names_set.add(tgt)
                titles_set.add(f"ERESTO {tgt}")

    hasil = []
    t0 = time.time()
    with ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(migrate_one, new, docs[n], items_master, abbrs,
                          names_set, titles_set, args.dry_run): n for n in todo}
        for i, fu in enumerate(as_completed(futs), 1):
            r = fu.result()
            hasil.append(r)
            mark = {"MIGRATED": "+", "SKIP_EXISTS": "=", "DRY-RUN": "?",
                    "SKIP_KOSONG": "-"}.get(r["status"], "!")
            if mark == "!" or i % 25 == 0:
                print(f"  [{mark}] {r['name']}: {r['status']}"
                      + (f" | {r.get('err', '')}" if mark == "!" else ""))
    n_ok = sum(1 for r in hasil
               if r["status"] in ("MIGRATED", "SKIP_EXISTS", "DRY-RUN"))
    n_fail = len(hasil) - n_ok
    print(f"[migrate] {n_ok}/{len(hasil)} OK, {n_fail} gagal "
          f"dalam {time.time()-t0:.0f}s (dry_run={args.dry_run})")
    jdump("migrate_result.json", hasil)

    alerts = [(r["name"], a) for r in hasil for a in r.get("alert", [])]
    if alerts and not args.dry_run:
        jdump("alerts.json", alerts)
    if args.dry_run:
        for n, a in alerts[:60]:
            print(f"  [alert] {a}")
        print(f"[migrate] total alert: {len(alerts)}")
    return hasil


# ---------------------------------------------------------------- rewarehouse
SETTER_FIELDS = [("Purchase Order", "set_warehouse"),
                 ("Purchase Order Item", "warehouse")]


def _setter_value(new, dt, field, value="1"):
    """Set allow_on_submit sementara pada field (pola catchup_oct7.py)."""
    st, d = new.get("/api/resource/Property Setter", {
        "filters": json.dumps([["doc_type", "=", dt], ["field_name", "=", field],
                               ["property", "=", "allow_on_submit"]]),
        "fields": json.dumps(["name", "value"]), "limit_page_length": 1})
    rows = d.get("data", []) if st == 200 else []
    if rows:
        if str(rows[0]["value"]) == value:
            return
        new.put("Property Setter", rows[0]["name"], {"value": value})
        return
    st, d = new.post("Property Setter", {
        "doctype": "Property Setter", "doctype_or_field": "DocField",
        "doc_type": dt, "field_name": field, "property": "allow_on_submit",
        "property_type": "Check", "value": value})
    if st != 200:
        raise SystemExit(f"[rewarehouse] GAGAL buat setter {dt}.{field}: "
                         f"{json.dumps(d)[:200]}")


def cmd_rewarehouse(old, new, docs, args):
    """Ubah gudang PO yang sudah termigrasi ke 'Stores - <ABBR>' in-place.

    Field `warehouse`/`set_warehouse` read-only setelah submit -> pakai
    Property Setter allow_on_submit sementara, lalu dipulihkan ke 0.
    """
    abbrs = jload("company_abbr.json", {})
    target = fetch_target_pos(new, docs, ["name", "company", "docstatus"])
    todo = [n for n in sorted(target) if not args.only or n == args.only]
    if args.limit:
        todo = todo[: args.limit]
    print(f"[rewarehouse] {len(todo)} PO akan diubah ke "
          f"'{WAREHOUSE_TARGET} - <ABBR>'")

    if not args.dry_run:
        for dt, field in SETTER_FIELDS:
            _setter_value(new, dt, field, "1")
        print("[rewarehouse] setter sementara allow_on_submit=1 dipasang")

    hasil = []
    try:
        for i, name in enumerate(todo, 1):
            st, d = new.get("/api/resource/Purchase Order/" + quote(name))
            doc = d.get("data") or {}
            comp = doc.get("company")
            want_head = target_wh_for(abbrs, comp, doc.get("set_warehouse"))
            changes_hdr = doc.get("set_warehouse") != want_head
            row_changes = [(r, target_wh_for(abbrs, comp, r.get("warehouse")))
                           for r in doc.get("items", [])
                           if r.get("warehouse") != target_wh_for(abbrs, comp, r.get("warehouse"))]
            if not changes_hdr and not row_changes:
                hasil.append({"po": name, "status": "SUDAH"})
                continue
            if args.dry_run:
                hasil.append({"po": name, "status": "DRY-RUN",
                              "dari": doc.get("set_warehouse"), "ke": want_head})
                continue
            fails = []
            for r, want in row_changes:
                st2, d2 = new.req("PUT", "/api/resource/Purchase Order Item/"
                                  + r["name"], payload={"warehouse": want})
                if st2 != 200:
                    fails.append(f"{r['item_code']}: {json.dumps(d2)[:120]}")
            if changes_hdr:
                st3, d3 = new.put("Purchase Order", name,
                                  {"set_warehouse": want_head})
                if st3 != 200:
                    fails.append(f"header: {json.dumps(d3)[:120]}")
            status = "DIUBAH" if not fails else "GAGAL"
            hasil.append({"po": name, "status": status,
                          "dari": doc.get("set_warehouse"), "ke": want_head,
                          "baris": len(row_changes), "err": fails[:3]})
            if status == "GAGAL" or i % 25 == 0:
                print(f"  [{'~' if status == 'DIUBAH' else '!'}] {name}: "
                      f"{status} {fails[:1] if fails else ''}")
    finally:
        if not args.dry_run:
            for dt, field in SETTER_FIELDS:
                _setter_value(new, dt, field, "0")
            print("[rewarehouse] setter dipulihkan ke 0")

    n_ok = sum(1 for r in hasil if r["status"] in ("DIUBAH", "SUDAH", "DRY-RUN"))
    n_fail = len(hasil) - n_ok
    print(f"[rewarehouse] {n_ok}/{len(hasil)} OK, {n_fail} gagal"
          f" (dry_run={args.dry_run})")
    jdump("rewarehouse_result.json", hasil)
    return hasil


# ---------------------------------------------------------------- verify
def fetch_target_pos(new, names, fields=None):
    """Ambil PO target per potongan (filter `in` 252 nama > limit request line)."""
    fields = fields or ["name", "docstatus", "grand_total", "status"]
    out = {}
    names = sorted(names)
    for i in range(0, len(names), 40):
        st, d = new.get("/api/resource/Purchase Order", {
            "filters": json.dumps([["name", "in", names[i:i + 40]]]),
            "fields": json.dumps(fields), "limit_page_length": 0})
        if st != 200:
            raise SystemExit(f"[verify] query gagal: {json.dumps(d)[:200]}")
        for x in d.get("data", []):
            out[x["name"]] = x
    return out


def cmd_verify(old, new, docs):
    abbrs = jload("company_abbr.json", {})
    target = fetch_target_pos(new, docs)

    rows, skipped_all = [], []
    n_val_ok = n_rows_ok = n_ds_ok = n_wh_ok = 0
    total_src = total_tgt = 0.0

    for name in sorted(docs):
        src = docs[name]
        tgt = target.get(name)
        sk = SKIP_ROWS.get(name, {})
        for c, alasan in sk.items():
            skipped_all.append({"po": name, "item": c, "alasan": alasan})
        skip_amt = sum(it.get("amount", 0) for it in src.get("items", [])
                       if it["item_code"] in sk)
        exp_total = (src.get("grand_total") or 0) - skip_amt
        exp_rows = len(src.get("items", [])) - len(sk)

        want_wh = target_wh_for(abbrs, src["company"],
                                src.get("set_warehouse"))
        tgt_rows = None
        wh_ok = False
        if tgt:
            st2, d2 = new.get("/api/resource/Purchase Order/" + quote(name),
                              {"fields": json.dumps(["name", "set_warehouse",
                                                     "items"])})
            tdoc = d2.get("data") or {}
            tgt_rows = len(tdoc.get("items", []))
            wh_ok = (tdoc.get("set_warehouse") == want_wh
                     and all(r.get("warehouse") == want_wh
                             for r in tdoc.get("items", [])))
        val_ok = bool(tgt) and abs((tgt.get("grand_total") or 0) - exp_total) < 1.0
        row_ok = tgt_rows == exp_rows
        ds_ok = bool(tgt) and tgt.get("docstatus") == src.get("docstatus")
        n_val_ok += val_ok
        n_rows_ok += row_ok
        n_ds_ok += ds_ok
        n_wh_ok += wh_ok
        total_src += exp_total
        if tgt:
            total_tgt += tgt.get("grand_total") or 0
        rows.append({
            "po": name, "company": src["company"],
            "tanggal": src["transaction_date"],
            "docstatus_lama": src.get("docstatus"),
            "docstatus_baru": tgt.get("docstatus") if tgt else None,
            "baris_lama": len(src.get("items", [])), "baris_baru": tgt_rows,
            "nilai_lama": exp_total,
            "nilai_baru": tgt.get("grand_total") if tgt else None,
            "selisih": round((tgt.get("grand_total", 0) if tgt else 0)
                             - exp_total, 2),
            "status": "ADA" if tgt else "HILANG",
            "status_dok": (tgt or {}).get("status"),
            "gudang_target": want_wh,
            "gudang_cocok": "YA" if wh_ok else "TIDAK",
            "catatan": ("baris dilewati: " + ", ".join(sk)) if sk else "",
        })

    n = len(docs)
    checks = [
        ("Jumlah PO target = sumber", f"{len(target)}/{n}",
         "LOLOS" if len(target) == n else "GAGAL"),
        ("Nilai grand_total cocok", f"{n_val_ok}/{n}",
         "LOLOS" if n_val_ok == n else "GAGAL"),
        ("Docstatus cocok", f"{n_ds_ok}/{n}",
         "LOLOS" if n_ds_ok == n else "GAGAL"),
        ("Jumlah baris item cocok", f"{n_rows_ok}/{n}",
         "LOLOS" if n_rows_ok == n else "GAGAL"),
        ("Gudang = Stores - <ABBR>", f"{n_wh_ok}/{n}",
         "LOLOS" if n_wh_ok == n else "GAGAL"),
        ("Total nilai sumber = target", f"{total_src:,.0f} vs {total_tgt:,.0f}",
         "LOLOS" if abs(total_src - total_tgt) < 1 else "GAGAL"),
    ]
    if skipped_all:
        checks.append(("Baris dilewati (terdokumentasi)",
                       f"{len(skipped_all)} baris", "CATATAN"))

    result = jload("migrate_result.json", []) or []
    failed = [r for r in result if r["status"] not in
              ("MIGRATED", "SKIP_EXISTS", "DRY-RUN", "SKIP_KOSONG")]
    write_report(rows, checks, skipped_all, failed)
    for c in checks:
        print(f"  {c[2]}: {c[0]} ({c[1]})")
    n_gagal = sum(1 for c in checks if c[2] == "GAGAL")
    print(f"[verify] {'SELURUH CEK LOLOS' if not n_gagal else f'{n_gagal} CEK GAGAL'}"
          f" — laporan: {os.path.basename(REPORT)}")
    return n_gagal


def write_report(rows, checks, skipped, failed):
    HEAD = PatternFill("solid", fgColor="D9EAF7")
    ws = openpyxl.Workbook()
    s1 = ws.active
    s1.title = "Rekap_PO"
    cols = ["po", "company", "tanggal", "docstatus_lama", "docstatus_baru",
            "baris_lama", "baris_baru", "nilai_lama", "nilai_baru", "selisih",
            "status", "status_dok", "gudang_target", "gudang_cocok", "catatan"]
    s1.append(cols)
    for r in rows:
        s1.append([r[c] for c in cols])
    s2 = ws.create_sheet("Skipped")
    s2.append(["po", "item", "alasan"])
    for r in skipped:
        s2.append([r["po"], r["item"], r["alasan"]])
    s3 = ws.create_sheet("Validation")
    s3.append(["check", "hasil", "status"])
    for c in checks:
        s3.append(list(c))
    s4 = ws.create_sheet("Failed")
    s4.append(["po", "status", "err"])
    for r in failed:
        s4.append([r["name"], r["status"], str(r.get("err", ""))[:300]])
    for s in (s1, s2, s3, s4):
        for cell in s[1]:
            cell.fill = HEAD
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center")
        s.freeze_panes = "A2"
    s1.column_dimensions["B"].width = 38
    s1.column_dimensions["C"].width = 12
    s1.column_dimensions["J"].width = 14
    s1.column_dimensions["M"].width = 46
    s2.column_dimensions["C"].width = 60
    s3.column_dimensions["A"].width = 40
    s3.column_dimensions["B"].width = 30
    s4.column_dimensions["C"].width = 60
    ws.save(REPORT)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", action="store_true", help="tarik PO dari site lama")
    ap.add_argument("--refresh", action="store_true", help="paksa tarik ulang dump")
    ap.add_argument("--prep", action="store_true",
                    help="siapkan company/supplier/UOM di site baru")
    ap.add_argument("--migrate", action="store_true", help="import ke site baru")
    ap.add_argument("--rewarehouse", action="store_true",
                    help="ubah gudang PO termigrasi ke 'Stores - <ABBR>'")
    ap.add_argument("--verify", action="store_true", help="verifikasi + laporan")
    ap.add_argument("--dry-run", action="store_true", help="uji tanpa tulis")
    ap.add_argument("--only", help="satu nama PO saja")
    ap.add_argument("--limit", type=int, help="batasi jumlah PO")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    if not any([args.dump, args.prep, args.migrate, args.rewarehouse,
                args.verify, args.dry_run]):
        ap.print_help()
        return

    old, new = clients()
    docs = jload("po_docs.json")
    if docs is None or args.refresh or args.dump:
        docs = cmd_dump(old, refresh=True)

    if args.prep:
        cmd_prep(old, new, docs)
    if args.migrate or (args.dry_run and not args.rewarehouse):
        cmd_migrate(old, new, docs, args)
    if args.rewarehouse:
        cmd_rewarehouse(old, new, docs, args)
    if args.verify:
        cmd_verify(old, new, docs)


if __name__ == "__main__":
    main()
