"""Migrasi print format site lama -> site baru (docs/11): header global + konten per format.

10 format default site lama:
  - 7 format A4 "split": blok HEADER+TITLE+META (+CSS-nya) dilepas dari body;
    header pindah ke Letter Head global "Header Global Ropi" (kondisional per
    DocType, docs/11), body memanggil {{ letter_head }} di awal.
  - 3 format self-contained disalin apa adanya: Format Print Pick List (header
    per halaman), Batch QRCode Produksi (label 50x30mm), POS Invoice Format (struk).
POS Next Receipt / POS Next EOD Report TIDAK disentuh (versi app lebih baru).

Usage:
  python3 pos_sync/migrate_print_formats.py --dump   --stage local|cloud
  python3 pos_sync/migrate_print_formats.py --build  --stage local|cloud
  python3 pos_sync/migrate_print_formats.py --push   --stage local|cloud [--dry-run]
  python3 pos_sync/migrate_print_formats.py --verify --stage local|cloud
  python3 pos_sync/migrate_print_formats.py --revert --stage local|cloud

Env (nama saja; jangan commit nilai token):
  /tmp/eresto_mig.env    local: ERPNEXT_URL, ERPNEXT_API_KEY (site baru),
                         ERPNEXT_OLD_API_KEY (site lama 8082)
  /tmp/eresto_print_env  cloud-old: ERPNEXT_OLD_CLOUD_URL, ERPNEXT_OLD_CLOUD_API_KEY
  /tmp/eresto_prod.env   cloud-new: ERPNEXT_URL, ERPNEXT_API_KEY
"""
import argparse
import json
import os
import re
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(HERE, "pf_src")
DUMP_DIR = os.path.join(HERE, "pf_dump")
BUILD_DIR = os.path.join(HERE, "pf_build")
REPORT_DIR = os.path.join(HERE, "pf_reports")

MIG_ENV = "/tmp/eresto_mig.env"
PRINT_ENV = "/tmp/eresto_print_env"
PROD_ENV = "/tmp/eresto_prod.env"

# Header global hidup di Letter Head yang SUDAH terpasang eksplisit di semua
# dokumen existing (letter_head="Company Letterhead - Grey" ada di PO/PR/SE/MR/
# POS Invoice lokal & cloud, plus POS Profile) dan sekaligus default site.
# Mengganti KONTENNYA = header baru tampil di semua dokumen tanpa menyentuh satu
# dokumen pun (nama historis dipertahankan; ganti nama = rename production yang
# tidak perlu). docs/11.
GLOBAL_LETTERHEAD = "Company Letterhead - Grey"
JURI = "PT. JUARA ROTI INDONESIA"
TEMP_HTTP = {429, 500, 502, 503, 504}
PAUSE = 0.25

# name, doctype, mode (split|verbatim), prefix css, anchor body, title (split)
FORMATS = [
    {"name": "Purchase Order New", "doctype": "Purchase Order", "mode": "split", "prefix": "po", "anchor": '<div class="po-parties">', "title": "Purchase Order"},
    {"name": "Purchase Receipt Format", "doctype": "Purchase Receipt", "mode": "split", "prefix": "po", "anchor": '<div class="po-parties">', "title": "Purchase Receipt"},
    {"name": "Purchase Invoice Format", "doctype": "Purchase Invoice", "mode": "split", "prefix": "po", "anchor": '<div class="po-parties">', "title": "Purchase Invoice"},
    {"name": "Sales Order Format", "doctype": "Sales Order", "mode": "split", "prefix": "po", "anchor": '<div class="po-parties">', "title": "Sales Order"},
    {"name": "Delivery Note Format", "doctype": "Delivery Note", "mode": "split", "prefix": "po", "anchor": '<div class="po-parties">', "title": "Delivery Note"},
    {"name": "Material Request Format", "doctype": "Material Request", "mode": "split", "prefix": "mr", "anchor": '<div class="mr-parties">', "title": "Material Request"},
    {"name": "Stock Entry Template", "doctype": "Stock Entry", "mode": "split", "prefix": "ste", "anchor": '<div class="ste-parties">', "title": "Stock Entry"},
    {"name": "Format Print Pick List", "doctype": "Pick List", "mode": "verbatim", "anchor": '<div class="pl-page">', "title": ""},
    {"name": "Batch QRCode Produksi", "doctype": "Batch", "mode": "verbatim", "anchor": '<div class="batch-label">', "title": ""},
    {"name": "POS Invoice Format", "doctype": "POS Invoice", "mode": "verbatim", "anchor": "", "title": ""},
]

# default_print_format site lama (10 pasang) — yang dimigrasi.
DEFAULTS = {
    "Purchase Order": "Purchase Order New",
    "Purchase Receipt": "Purchase Receipt Format",
    "Purchase Invoice": "Purchase Invoice Format",
    "Sales Order": "Sales Order Format",
    "Delivery Note": "Delivery Note Format",
    "Material Request": "Material Request Format",
    "Stock Entry": "Stock Entry Template",
    "Pick List": "Format Print Pick List",
    "Batch": "Batch QRCode Produksi",
    "POS Invoice": "POS Invoice Format",
}

FORMAT_FIELDS = ["name", "html", "doc_type", "standard", "custom_format",
                 "print_format_type", "disabled", "font_size", "page_number",
                 "margin_top", "margin_bottom", "margin_left", "margin_right",
                 "default_print_language", "pdf_generator", "module"]


def load_env(path):
    d = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip().strip('"').strip("'")
    return d


class Client:
    def __init__(self, base, key, label=""):
        self.s = requests.Session()
        self.s.headers.update({"Authorization": "token " + key})
        self.base = base.rstrip("/")
        self.label = label

    def get(self, path, params=None):
        return self.req("GET", path, params=params, timeout=90)

    def post(self, doctype, payload):
        return self.req("POST", "/api/resource/" + requests.utils.quote(doctype), payload)

    def put(self, doctype, name, payload):
        return self.req("PUT", "/api/resource/" + requests.utils.quote(doctype)
                        + "/" + requests.utils.quote(name), payload)

    def delete(self, doctype, name):
        return self.req("DELETE", "/api/resource/" + requests.utils.quote(doctype)
                        + "/" + requests.utils.quote(name))

    def req(self, method, path, payload=None, params=None, timeout=120):
        last = None
        for a in (1, 2, 3):
            try:
                r = self.s.request(method, self.base + path, json=payload,
                                   params=params, timeout=timeout)
            except requests.RequestException as e:
                last = str(e)[:180]
                time.sleep(2 ** a)
                continue
            if r.status_code in TEMP_HTTP:
                last = f"HTTP {r.status_code}"
                time.sleep(2 ** a)
                continue
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, {"_raw": r.text[:500]}
        return -1, {"error": f"gagal 3x: {last}"}


def stages():
    mig = load_env(MIG_ENV)
    prod = load_env(PROD_ENV)
    cloud = load_env(PRINT_ENV) if os.path.exists(PRINT_ENV) else {}
    return {
        "local": {
            "old": Client(mig.get("ERPNEXT_OLD_BASE", "http://site-lama.localhost:8082"),
                          mig.get("ERPNEXT_OLD_API_KEY"), "local-old"),
            "new": Client(mig.get("ERPNEXT_URL", "http://erp.localhost:8081"),
                          mig.get("ERPNEXT_API_KEY"), "local-new"),
        },
        "cloud": {
            "old": Client(cloud.get("ERPNEXT_OLD_CLOUD_URL", "https://rotiropi.j.frappe.cloud"),
                          cloud.get("ERPNEXT_OLD_CLOUD_API_KEY"), "cloud-old"),
            "new": Client(prod.get("ERPNEXT_URL", "https://ropierpnext.frappe.cloud"),
                          prod.get("ERPNEXT_API_KEY"), "cloud-new"),
        },
    }


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def jsafe(text):
    return re.sub(r"\s+", " ", text or "").strip()


# ---------------------------------------------------------------- split build

def _div_end(s, i):
    """index akhir (setelah </div>) blok <div ...> yang mulai di i."""
    depth, k = 0, i
    while True:
        m = re.search(r"<div\b|</div>", s[k:])
        if not m:
            raise ValueError("div tidak balance")
        k += m.start()
        if m.group(0) == "<div":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return k + 6
        k += len(m.group(0))


def split_format(html, prefix):
    """Lepas blok header + CSS + var-set milik header; awali {{ letter_head }}."""
    hdr_cls = f"{prefix}-header"
    i = html.find(f'<div class="{hdr_cls}">')
    if i < 0:
        raise ValueError(f"header {hdr_cls} tidak ditemukan")
    j = _div_end(html, i)
    core = html[:i] + html[j:]

    core, n_sets = re.subn(
        r"\{%-?\s*set\s+(?:company_doc|po_refs|so_refs|pr_refs|dn_refs)\s*=.*?%\}",
        "", core, flags=re.S)

    s0 = core.find("<style>") + len("<style>")
    s1 = core.find("</style>")
    css = core[s0:s1]
    tokens = (f".{prefix}-header", f".{prefix}-meta", f".{prefix}-logo",
              f".{prefix}-title", ".company-info", ".company-name")
    kept, dropped = [], []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sel, body = m.group(1), m.group(2)
        (dropped if any(t in sel for t in tokens) else kept).append(m.group(0))
    core = core[:s0] + "".join(kept) + core[s1:]

    out = (f'{{# Header (logo/judul/meta) dirender Letter Head "{GLOBAL_LETTERHEAD}" — docs/11. #}}\n'
           "{{ letter_head }}\n" + core)
    return out, {"dropped_rules": len(dropped), "kept_rules": len(kept),
                 "dropped_sets": n_sets, "removed_html": j - i}


def do_build(stage):
    dump_file = os.path.join(DUMP_DIR, stage, "old_formats.json")
    if not os.path.exists(dump_file):
        sys.exit(f"belum ada {dump_file} — jalankan --dump dulu")
    old = {r["name"]: r for r in json.load(open(dump_file))}
    out_dir = os.path.join(BUILD_DIR, stage)
    os.makedirs(out_dir, exist_ok=True)

    lh_src = os.path.join(SRC_DIR, "letterhead.html")
    lh_html = open(lh_src).read()
    with open(os.path.join(out_dir, "letterhead.html"), "w") as f:
        f.write(lh_html)

    manifest, fails = [], []
    for spec in FORMATS:
        src = old.get(spec["name"])
        if not src:
            fails.append((spec["name"], "tidak ada di dump site lama"))
            continue
        try:
            if spec["mode"] == "split":
                html, stats = split_format(src["html"], spec["prefix"])
                assert stats["dropped_rules"] >= 10, f"css header cuma {stats['dropped_rules']} rule"
                assert "{{ letter_head }}" in html
            else:
                html, stats = src["html"], {"dropped_rules": 0, "kept_rules": 0,
                                            "dropped_sets": 0, "removed_html": 0}
            fname = slug(spec["name"]) + ".html"
            with open(os.path.join(out_dir, fname), "w") as f:
                f.write(html)
            manifest.append({**spec, "file": fname, "src_bytes": len(src["html"]),
                             "bytes": len(html), **stats})
        except Exception as e:
            fails.append((spec["name"], str(e)))

    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    print(f"[build:{stage}] {len(manifest)} ok, {len(fails)} gagal")
    for r in manifest:
        print(f"  {r['name']:28s} {r['mode']:8s} {r['src_bytes']:6d}B -> {r['bytes']:6d}B"
              f"  (hapus {r['removed_html']}B html, {r['dropped_rules']} rule, {r['dropped_sets']} set)")
    for nm, err in fails:
        print(f"  GAGAL {nm}: {err}")
    if fails:
        sys.exit(1)
    return manifest


# ---------------------------------------------------------------- dump / push

def dump_state(stage):
    global _STAGES
    st = _STAGES[stage]
    out = os.path.join(DUMP_DIR, stage)
    os.makedirs(out, exist_ok=True)

    # site lama: 10 format + default setter
    old_formats = []
    for spec in FORMATS:
        code, d = st["old"].get("/api/resource/" + requests.utils.quote("Print Format")
                                + "/" + requests.utils.quote(spec["name"]),
                                {"fields": json.dumps(FORMAT_FIELDS)})
        if code != 200:
            sys.exit(f"site lama tidak punya format {spec['name']!r}: {code}")
        old_formats.append(d["data"])
    json.dump(old_formats, open(os.path.join(out, "old_formats.json"), "w"), indent=1)

    code, d = st["old"].get("/api/resource/Property Setter", {
        "fields": json.dumps(["name", "doc_type", "value"]),
        "filters": json.dumps([["property", "=", "default_print_format"]]),
        "limit_page_length": 0})
    old_defs = {r["doc_type"]: {"setter": r["name"], "value": r["value"]}
                for r in d.get("data", [])}
    json.dump(old_defs, open(os.path.join(out, "old_defaults.json"), "w"), indent=1)

    # site baru: state sebelum push (untuk revert)
    before = {"formats": {}, "setters": {}, "letterheads": []}
    for spec in FORMATS:
        code, d = st["new"].get("/api/resource/Print Format/" + requests.utils.quote(spec["name"]),
                                {"fields": json.dumps(FORMAT_FIELDS)})
        before["formats"][spec["name"]] = d["data"] if code == 200 else None
    for dt in DEFAULTS:
        code, d = st["new"].get("/api/resource/Property Setter", {
            "fields": json.dumps(["name", "value"]),
            "filters": json.dumps([["property", "=", "default_print_format"],
                                   ["doc_type", "=", dt]]), "limit_page_length": 1})
        before["setters"][dt] = d["data"][0] if code == 200 and d.get("data") else None
    code, d = st["new"].get("/api/resource/Letter Head", {
        "fields": json.dumps(["name", "is_default", "content", "source"]),
        "limit_page_length": 0})
    before["letterheads"] = d.get("data", [])
    json.dump(before, open(os.path.join(out, "new_before_push.json"), "w"), indent=1)

    print(f"[dump:{stage}] lama {len(old_formats)} format + {len(old_defs)} default; "
          f"baru: {sum(1 for v in before['formats'].values() if v)} format sudah ada, "
          f"{len(before['letterheads'])} letter head")
    return old_defs, before


def _exists(client, doctype, name):
    code, _ = client.get("/api/resource/" + requests.utils.quote(doctype) + "/"
                         + requests.utils.quote(name), {"fields": '["name"]'})
    return code == 200


def _upsert(client, doctype, name, payload, before_doc):
    # cek live (bukan dump) agar rerun idempoten walau state dump sudah basi
    if _exists(client, doctype, name) or before_doc is not None:
        code, d = client.put(doctype, name, payload)
    else:
        code, d = client.post(doctype, payload)
    time.sleep(PAUSE)
    if code not in (200, 201):
        raise RuntimeError(f"upsert {doctype} {name!r} -> {code}: {jsafe(json.dumps(d))[:200]}")
    return code


def push_formats(stage, dry_run=False):
    manifest = json.load(open(os.path.join(BUILD_DIR, stage, "manifest.json")))
    before = json.load(open(os.path.join(DUMP_DIR, stage, "new_before_push.json")))
    st = _STAGES[stage]["new"]
    results = []
    for r in manifest:
        html = open(os.path.join(BUILD_DIR, stage, r["file"]), newline="").read()
        payload = {"doctype": "Print Format", "name": r["name"], "doc_type": r["doctype"],
                   "print_format_type": "Jinja", "custom_format": 1, "standard": "No",
                   "disabled": 0, "html": html, "font_size": 14, "page_number": "Hide",
                   "margin_top": 15, "margin_bottom": 15, "margin_left": 15, "margin_right": 15,
                   "default_print_language": "en", "pdf_generator": "wkhtmltopdf"}
        if dry_run:
            results.append((r["name"], "dry-run"))
            continue
        _upsert(st, "Print Format", r["name"], payload, before["formats"].get(r["name"]))
        results.append((r["name"], "ok"))

    # Letter Head global: isi ulang konten LH yang sudah dipin semua dokumen.
    if not dry_run:
        lh_html = open(os.path.join(BUILD_DIR, stage, "letterhead.html")).read()
        # 1) jangan tinggalkan lebih dari satu LH default
        code, d = st.get("/api/resource/Letter Head", {
            "fields": json.dumps(["name", "is_default"]), "limit_page_length": 0})
        for lh in d.get("data", []):
            if lh["name"] != GLOBAL_LETTERHEAD and lh.get("is_default"):
                _upsert(st, "Letter Head", lh["name"], {"is_default": 0}, {"x": 1})
                print(f"  default letter head lama dilepas: {lh['name']}")
                results.append((f"LetterHead unset {lh['name']}", "ok"))
        # 2) upsert konten global (before_insert memaksa source=Image -> pastikan HTML)
        lh_payload = {"source": "HTML", "content": lh_html, "is_default": 1}
        if _exists(st, "Letter Head", GLOBAL_LETTERHEAD):
            _upsert(st, "Letter Head", GLOBAL_LETTERHEAD, lh_payload, {"x": 1})
        else:
            code, d = st.post("Letter Head", {"doctype": "Letter Head",
                                              "letter_head_name": GLOBAL_LETTERHEAD,
                                              **lh_payload})
            time.sleep(PAUSE)
            if code not in (200, 201):
                raise RuntimeError(f"buat letter head -> {code}: {jsafe(json.dumps(d))[:200]}")
        results.append((GLOBAL_LETTERHEAD, "ok"))

    # default_print_format setters
    old_defs = json.load(open(os.path.join(DUMP_DIR, stage, "old_defaults.json")))
    for dt, fmt in DEFAULTS.items():
        want = old_defs.get(dt, {}).get("value")
        if want and want != fmt:
            print(f"  PERINGATAN: default lama {dt} = {want!r}, rencana {fmt!r}")
        payload = {"doctype": "Property Setter", "doc_type": dt, "property": "default_print_format",
                   "property_type": "Link", "value": fmt, "doctype_or_field": "DocType"}
        if dry_run:
            results.append((f"default {dt}", "dry-run"))
            continue
        prev = before["setters"].get(dt)
        setter_name = (prev["name"] if prev else f"{dt}-main-default_print_format")
        if _exists(st, "Property Setter", setter_name):
            _upsert(st, "Property Setter", setter_name, {"value": fmt}, prev)
        else:
            code, d = st.post("Property Setter", payload)
            time.sleep(PAUSE)
            if code not in (200, 201):
                raise RuntimeError(f"setter {dt} -> {code}: {jsafe(json.dumps(d))[:200]}")
        results.append((f"default {dt}", "ok"))

    print(f"[push:{stage}] {len(results)} aksi" + (" (dry-run)" if dry_run else ""))
    json.dump(results, open(os.path.join(DUMP_DIR, stage, "push_results.json"), "w"), indent=1)


def do_revert(stage):
    before = json.load(open(os.path.join(DUMP_DIR, stage, "new_before_push.json")))
    st = _STAGES[stage]["new"]
    for spec in FORMATS:
        prev = before["formats"].get(spec["name"])
        if prev is None:
            code, d = st.delete("Print Format", spec["name"])
            print(f"  hapus format {spec['name']}: {code}")
        else:
            code, d = st.put("Print Format", spec["name"], {"html": prev["html"]})
            print(f"  pulihkan format {spec['name']}: {code}")
        time.sleep(PAUSE)
    for dt, prev in before["setters"].items():
        if prev is None:
            code, d = st.get("/api/resource/Property Setter", {
                "filters": json.dumps([["property", "=", "default_print_format"],
                                       ["doc_type", "=", dt]]), "limit_page_length": 1})
            if d.get("data"):
                code, d = st.delete("Property Setter", d["data"][0]["name"])
                print(f"  hapus setter {dt}: {code}")
        else:
            code, d = st.put("Property Setter", prev["name"], {"value": prev["value"]})
            print(f"  pulihkan setter {dt} -> {prev['value']!r}: {code}")
        time.sleep(PAUSE)
    lh_existing = next((x for x in before["letterheads"] if x["name"] == GLOBAL_LETTERHEAD), None)
    if lh_existing is None:
        code, d = st.delete("Letter Head", GLOBAL_LETTERHEAD)
        print(f"  hapus letter head {GLOBAL_LETTERHEAD}: {code}")
    else:
        code, d = st.put("Letter Head", GLOBAL_LETTERHEAD,
                         {"content": lh_existing["content"], "is_default": lh_existing["is_default"]})
        print(f"  pulihkan letter head {GLOBAL_LETTERHEAD}: {code}")
    time.sleep(PAUSE)
    for lh in before["letterheads"]:
        if lh.get("is_default") and lh["name"] != GLOBAL_LETTERHEAD:
            code, d = st.put("Letter Head", lh["name"], {"is_default": 1})
            print(f"  default letter head pulih: {lh['name']} -> {code}")
    print(f"[revert:{stage}] selesai")


# ---------------------------------------------------------------- verify

def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def payload(doctype, company):
    base = {"doctype": doctype, "name": "TEST-0001", "docstatus": 1, "status": "Submitted",
            "owner": "Administrator", "creation": "2026-10-07 08:00:00",
            "modified": "2026-10-07 08:00:00", "company": company, "currency": "IDR",
            "conversion_rate": 1, "address_display": "", "contact_mobile": "",
            "company_address_display": "", "shipping_address": "", "shipping_address_name": "",
            "customer_address_display": "", "terms": "", "taxes": [],
            "discount_amount": 0, "net_total": 2000, "grand_total": 2000,
            "total_taxes_and_charges": 0, "rounding_adjustment": 0, "rounded_total": 2000,
            "in_words": "dua ribu rupiah", "total_qty": 2}
    item = {"idx": 1, "item_code": "BB260061", "item_name": "Kopi Hitam 6gr",
            "description": "", "qty": 2, "uom": "Nos", "stock_uom": "Nos", "rate": 1000,
            "amount": 2000, "basic_rate": 900, "warehouse": "Stores - RPMD",
            "s_warehouse": "Stores - RPMD", "t_warehouse": "Stores - RPMD",
            "purchase_order": "", "purchase_receipt": "", "sales_order": "",
            "delivery_note": "", "against_sales_order": "", "expense_account": "",
            "cost_center": "", "batch_no": "", "serial_no": "", "actual_qty": 2,
            "transfer_qty": 2, "conversion_factor": 1}
    items = [dict(item), dict(item, idx=2, item_code="BB260039", item_name="Gula Stik")]
    base["items"] = items
    if doctype == "Purchase Order":
        base.update({"supplier": "SUP-001", "supplier_name": "Supplier Uji",
                     "set_warehouse": "", "schedule_date": "2026-10-10",
                     "payment_terms_template": "", "po_no": "", "custom_note": ""})
    elif doctype == "Purchase Receipt":
        base.update({"supplier": "SUP-001", "supplier_name": "Supplier Uji",
                     "set_warehouse": "", "posting_date": "2026-10-06",
                     "supplier_delivery_note": "", "payment_terms_template": ""})
        base["items"][0]["purchase_order"] = "PO-011026-001"
    elif doctype == "Purchase Invoice":
        base.update({"supplier": "SUP-001", "supplier_name": "Supplier Uji",
                     "set_warehouse": "", "posting_date": "2026-10-06",
                     "due_date": "2026-11-06", "bill_no": "", "payment_terms_template": ""})
        base["items"][0].update({"purchase_order": "PO-011026-001",
                                 "purchase_receipt": "PR-011026-021"})
    elif doctype == "Sales Order":
        base.update({"customer": "CUST-001", "customer_name": "Customer Uji",
                     "transaction_date": "2026-10-06", "delivery_date": "2026-10-07",
                     "po_no": "", "payment_terms_template": ""})
    elif doctype == "Delivery Note":
        base.update({"customer": "CUST-001", "customer_name": "Customer Uji",
                     "posting_date": "2026-10-06", "po_no": "", "payment_terms_template": ""})
        base["items"][0]["against_sales_order"] = "SO-011026-001"
    elif doctype == "Material Request":
        base.update({"transaction_date": "2026-10-06", "schedule_date": "2026-10-07",
                     "material_request_type": "Material Transfer",
                     "set_from_warehouse": "Stores - RPMD", "set_warehouse": "Stores - RPMD",
                     "reason_for_request": ""})
    elif doctype == "Stock Entry":
        base.update({"posting_date": "2026-10-06", "posting_time": "09:00:00",
                     "purpose": "Material Transfer for Manufacture",
                     "from_warehouse": "Stores - RPMD", "to_warehouse": "Stores - RPMD",
                     "work_order": "", "custom_note": ""})
    elif doctype == "Pick List":
        base.update({"locations": [], "purpose": "Delivery", "status": "Submitted"})
    elif doctype == "Batch":
        base = {"doctype": "Batch", "name": "BATCH-2610-0001", "item_name": "Kopi Hitam 6gr",
                "item": "BB260061", "manufacturing_date": "2026-10-01",
                "expiry_date": "2027-04-01"}
    elif doctype == "POS Invoice":
        base.update({"posting_date": "2026-10-06", "posting_time": "09:30:00",
                     "customer": "CUST-001", "customer_name": "Customer Uji",
                     "cashier": "", "pos_profile": "", "custom_nama_customer": "",
                     "paid_amount": 2000, "change_amount": 0, "base_paid_amount": 2000,
                     "base_change_amount": 0, "is_return": 0, "return_against": "",
                     "payments": [{"mode_of_payment": "Cash", "amount": 2000,
                                   "base_amount": 2000, "type": "Cash"}]})
        base["items"][0].update({"rate": 2000})
    return base


def company_common(st):
    lists = []
    for client in (st["old"], st["new"]):
        code, d = client.get("/api/resource/Company", {"fields": json.dumps(["name"]),
                                                       "limit_page_length": 0})
        lists.append({r["name"] for r in d.get("data", [])} if code == 200 else set())
    common = sorted(lists[0] & lists[1])
    pick = JURI if JURI in common else (common[0] if common else JURI)
    return pick


def do_verify(stage):
    st = _STAGES[stage]
    manifest = {r["name"]: r for r in json.load(open(os.path.join(BUILD_DIR, stage, "manifest.json")))}
    old_src = {r["name"]: (r.get("html") or "") for r in json.load(open(os.path.join(DUMP_DIR, stage, "old_formats.json")))}
    company = company_common(st)
    print(f"[verify:{stage}] company uji: {company}")
    rows, fails = [], []
    for spec in FORMATS:
        r = manifest[spec["name"]]
        p = payload(spec["doctype"], company)
        code_o, o = st["old"].get("/api/method/frappe.www.printview.get_html_and_style",
                                  {"doc": json.dumps(p), "print_format": spec["name"]})
        code_n, n = st["new"].get("/api/method/frappe.www.printview.get_html_and_style",
                                  {"doc": json.dumps(p), "print_format": spec["name"]})
        row = {"format": spec["name"], "doctype": spec["doctype"], "mode": r["mode"],
               "old_render": code_o, "new_render": code_n, "letter_head": "-",
               "parity": "-", "note": ""}
        built = open(os.path.join(BUILD_DIR, stage, r["file"]), newline="").read()
        if code_n != 200 or (spec["mode"] == "split" and code_o != 200):
            row["parity"] = "GAGAL"
            row["note"] = jsafe(json.dumps(o if code_o != 200 else n))[:180]
            fails.append((spec["name"], row["note"]))
            rows.append(row)
            continue
        hn = n["message"]["html"]
        if spec["mode"] == "split":
            ho = o["message"]["html"]
            to = norm(ho[ho.find(spec["anchor"]):])
            tn = norm(hn[hn.find(spec["anchor"]):])
            lh_ok = ("jh-header" in hn and f">{spec['title']}</div>" in hn
                     and "TEST-0001" in hn)
            row["letter_head"] = "ya" if "jh-header" in hn else "TIDAK"
            row["parity"] = "OK" if (to == tn and lh_ok) else "BEDA"
            if row["parity"] != "OK":
                if not lh_ok and to == tn:
                    row["note"] = "letter head tidak memuat judul/meta yang diharapkan"
                else:
                    i = next((k for k in range(min(len(to), len(tn))) if to[k] != tn[k]), min(len(to), len(tn)))
                    row["note"] = f"beda di {i}: ...{to[i:i+90]!r} VS {tn[i:i+90]!r}"
                fails.append((spec["name"], row["note"]))
        else:
            # verbatim: yang penting sumbernya identik & render sukses (konten
            # render beda antar-site boleh, itu data — logo/nama company).
            same_src = built == old_src.get(spec["name"])
            row["letter_head"] = "n/a"
            row["parity"] = "OK" if same_src else "BEDA"
            if not same_src:
                row["note"] = "sumber terbangun != sumber site lama (byte)"
                fails.append((spec["name"], row["note"]))
        rows.append(row)

    # PDF nyata (site baru) untuk doctype yang punya dokumen
    pdf_rows = []
    out_dir = os.path.join(REPORT_DIR, stage)
    os.makedirs(out_dir, exist_ok=True)
    for spec in FORMATS:
        code, d = st["new"].get("/api/resource/" + requests.utils.quote(spec["doctype"]),
                                {"fields": json.dumps(["name"]), "limit_page_length": 1,
                                 "order_by": "creation desc"})
        docname = (d.get("data") or [{}])[0].get("name") if code == 200 else None
        if not docname:
            pdf_rows.append({"format": spec["name"], "doc": "-", "pdf": "skip (tanpa dokumen)"})
            continue
        resp = st["new"].s.get(st["new"].base + "/api/method/frappe.utils.print_format.download_pdf",
                               params={"doctype": spec["doctype"], "name": docname,
                                       "format": spec["name"], "no_letterhead": 0}, timeout=300)
        ok = resp.status_code == 200 and resp.content[:5] == b"%PDF-"
        path = ""
        if ok:
            path = os.path.join(out_dir, slug(spec["name"]) + ".pdf")
            with open(path, "wb") as f:
                f.write(resp.content)
        pdf_rows.append({"format": spec["name"], "doc": docname,
                         "pdf": "OK" if ok else f"GAGAL {resp.status_code}",
                         "file": os.path.basename(path)})
        print(f"  PDF {spec['name']:28s} {docname:24s} {'OK' if ok else resp.status_code}")

    write_report(stage, rows, pdf_rows, company)
    print(f"[verify:{stage}] render {sum(1 for r in rows if r['parity'] == 'OK')}/{len(rows)} OK, "
          f"PDF {sum(1 for r in pdf_rows if r['pdf'] == 'OK')}/{len(pdf_rows)}")
    for nm, err in fails:
        print(f"  GAGAL {nm}: {err}")
    return rows, pdf_rows


def write_report(stage, rows, pdf_rows, company):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Formats"
    head = ["Format", "DocType", "Mode", "LetterHead", "ParityRender", "PDF", "PDFFile", "Catatan"]
    ws.append(head)
    pdf_by = {r["format"]: r for r in pdf_rows}
    for r in rows:
        pr = pdf_by.get(r["format"], {})
        ws.append([r["format"], r["doctype"], r["mode"], r["letter_head"], r["parity"],
                   pr.get("pdf", ""), pr.get("file", ""), r["note"]])
    ws2 = wb.create_sheet("Defaults")
    ws2.append(["DocType", "Default di site lama", "Target baru"])
    for dt, fmt in DEFAULTS.items():
        ws2.append([dt, fmt, fmt])
    ws3 = wb.create_sheet("Meta")
    ws3.append(["stage", stage, "company uji", company])

    fill = PatternFill("solid", fgColor="D9EAF7")
    for sheet in (ws, ws2, ws3):
        for c in sheet[1]:
            c.fill = fill
            c.font = Font(bold=True)
            c.alignment = Alignment(horizontal="center", vertical="center")
        sheet.freeze_panes = "A2"
        for col in range(1, sheet.max_column + 1):
            width = max(len(str(sheet.cell(row=r, column=col).value or ""))
                        for r in range(1, sheet.max_row + 1))
            sheet.column_dimensions[get_column_letter(col)].width = min(max(width + 2, 12), 60)
    path = os.path.join(REPORT_DIR, f"Migrasi_Print_Format_{stage}.xlsx")
    wb.save(path)
    print(f"  laporan: {path}")


# ---------------------------------------------------------------- main

_STAGES = {}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--stage", choices=["local", "cloud"], required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    _STAGES = stages()
    if args.dump:
        dump_state(args.stage)
    if args.build:
        do_build(args.stage)
    if args.push:
        push_formats(args.stage, args.dry_run)
    if args.verify:
        do_verify(args.stage)
    if args.revert:
        do_revert(args.stage)
    if not any([args.dump, args.build, args.push, args.verify, args.revert]):
        ap.print_help()
