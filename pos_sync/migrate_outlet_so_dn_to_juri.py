"""Migrasi Sales Order + Delivery Note Intercompany OUTLET (1-7 Okt 2026).

Konteks: lanjutan `migrate_outlet_po_to_juri.py`. PO outlet -> PT. JURI sudah
di target (252 PO, gudang `Stores - <ABBR>`). Sekarang rantai baliknya:
SO (JURI -> customer internal outlet) + DN (pengiriman JURI -> outlet).

Sumber: ERPNext Cloud LAMA (rotiropi.j.frappe.cloud), company JURI.
Target: ERPNext Cloud BARU (ropierpnext.frappe.cloud). ID dipertahankan.

Scope (ketentuan user 2026-10-08):
- Jangkar = DN `posting_date` 1-7 Okt. SO diambil dari:
  (a) SO `transaction_date` 1-7 Okt, PLUS (b) SO yang ditarik DN jangkar
  walau tanggal SO lebih tua (mis. DN 1 Okt atas SO 30 Sep) -> ikut.
- Setiap SO WAJIB punya `inter_company_order_reference` yang PO-nya ada di
  target (sumber data tetap site lama; PO-nya sudah dimigrasi lebih dulu).
  SO tanpa PO / PO-nya tidak ada -> di-skip (tercatat).
- Delanggu (`SLS-051026-006` / `DN-051026-008`) di-skip: sudah dimigrasi
  sesi intercompany.
- DN yang menarik SO di luar scope ikut di-skip.

Penyesuaian (hasil audit sumber vs target):
- ID dipertahankan (rename_doc); docstatus persis sumber (SO 1, DN 1/2).
- Customer: kode lama -> customer target via `represents_company`/nama.
  '- FRC' yang belum internal diaktifkan; customer baru dibuat bila belum ada.
- Remap bentrok kode item: BB260057 -> BB26001, BB260058 -> BB26008,
  BB260059 -> BB26009 (lihat memory/catchup_oct7).
- UOM 'Kg' -> 'kg'; factor diselaraskan ke master Item target.
- Gudang '... - ROPI' -> '... - JURI'; cost_center 'Main - ROPI' -> 'Main - JURI'.
- `purchase_order`/`purchase_order_item` di baris SO dipetakan ke row target.
- `so_detail` di baris DN dipetakan ke row SO target (by posisi/baris).
- Harga dipertahankan apa adanya (rate sumber), bukan dari price list target.

Env (/tmp/eresto_mig.env + /tmp/eresto_prod.env, jangan tulis nilai ke repo):
  ERPNEXT_OLD_CLOUD_API_KEY (site lama), ERPNEXT_URL + ERPNEXT_API_KEY (baru).

Alur: --dump -> --prep -> --so -> --dn -> --verify (idempoten, rerun aman).
"""
import argparse
import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DUMP_DIR = os.path.join(HERE, "outlet_sodn_dump")
REPORT = os.path.join(HERE, "Laporan_Migrasi_SO_DN_Outlet_ke_JURI.xlsx")

OLD_BASE = "https://rotiropi.j.frappe.cloud"
JURI = "PT. JUARA ROTI INDONESIA"
DATE_FROM, DATE_TO = "2026-10-01", "2026-10-08"

# Delanggu sudah dimigrasi sesi intercompany
SKIP_SO = {"SLS-051026-006"}
SKIP_DN = {"DN-051026-008"}

# bentrok kode lama->baru (pola catchup_oct7.py)
ITEM_MAP = {"BB260057": "BB26001", "BB260058": "BB26008", "BB260059": "BB26009", "BB260060": "BB260046"}
UOM_MAP = {"Kg": "kg", "KG": "kg"}

# fallback nama gudang site lama bila abbr tidak dipetakan
def wh_map(old):
    if not old:
        return old
    if old.endswith(" - ROPI"):
        return old[:-7] + " - JURI"
    return old


def cc_map(old):
    if not old:
        return old
    if old.endswith(" - ROPI"):
        return old[:-7] + " - JURI"
    return old


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


def fetch_doc(c, dt, name, fields=None):
    params = {"fields": json.dumps(fields)} if fields else None
    st, d = c.get(f"/api/resource/{quote(dt)}/{quote(name)}", params)
    return d.get("data") if st == 200 else None


# ---------------------------------------------------------------- dump
def cmd_dump(old, new, refresh=False):
    if not refresh and os.path.exists(os.path.join(DUMP_DIR, "scope.json")):
        sc = jload("scope.json")
        print(f"[dump] pakai cache: {len(sc['so'])} SO / {len(sc['dn'])} DN "
              f"(--refresh untuk tarik ulang)")
        return sc

    print("[dump] tarik DN window 1-7 Okt dari site lama ...")
    dn_win = old.list_all("Delivery Note", ["name", "posting_date", "docstatus"],
                          filters=[["company", "=", JURI],
                                   ["posting_date", ">=", DATE_FROM],
                                   ["posting_date", "<=", DATE_TO]],
                          order="name asc")
    dn_docs = {}
    dn_so = {}
    with ThreadPoolExecutor(4) as ex:
        futs = {ex.submit(fetch_doc, old, "Delivery Note", x["name"]): x["name"]
                for x in dn_win}
        for i, fu in enumerate(as_completed(futs), 1):
            name = futs[fu]
            doc = fu.result()
            if doc:
                dn_docs[name] = doc
                dn_so[name] = sorted({r["against_sales_order"] for r in doc["items"]
                                      if r.get("against_sales_order")})
            if i % 40 == 0:
                print(f"  ... DN {i}/{len(dn_win)}")

    print("[dump] tarik SO window 1-7 Okt + SO yang ditarik DN ...")
    so_win = old.list_all("Sales Order", ["name", "transaction_date", "docstatus"],
                          filters=[["company", "=", JURI],
                                   ["transaction_date", ">=", DATE_FROM],
                                   ["transaction_date", "<=", DATE_TO]],
                          order="name asc")
    cand = ({x["name"] for x in so_win} | {s for v in dn_so.values() for s in v}) \
        - SKIP_SO
    so_docs = {}
    with ThreadPoolExecutor(4) as ex:
        futs = {ex.submit(fetch_doc, old, "Sales Order", n): n for n in sorted(cand)}
        for i, fu in enumerate(as_completed(futs), 1):
            name = futs[fu]
            doc = fu.result()
            if doc:
                so_docs[name] = doc
            if i % 40 == 0:
                print(f"  ... SO {i}/{len(cand)}")

    # PO target: pastikan icr tiap SO ada di target
    icrs = sorted({d.get("inter_company_order_reference")
                   for d in so_docs.values()
                   if d.get("inter_company_order_reference")})
    po_target = set()
    for i in range(0, len(icrs), 40):
        st, d = new.get("/api/resource/Purchase Order", {
            "filters": json.dumps([["name", "in", icrs[i:i + 40]]]),
            "fields": json.dumps(["name"]), "limit_page_length": 0})
        po_target |= {x["name"] for x in d.get("data", [])}

    keep_so, skip_so = [], {}
    for n in sorted(so_docs):
        icr = so_docs[n].get("inter_company_order_reference")
        if not icr:
            skip_so[n] = "tanpa inter_company_order_reference (bukan intercompany)"
        elif icr not in po_target:
            skip_so[n] = f"PO {icr} tidak ada di target"
        else:
            keep_so.append(n)

    keep_dn, skip_dn = [], {}
    for n in sorted(dn_docs):
        if n in SKIP_DN:
            skip_dn[n] = "Delanggu (sudah dimigrasi sesi intercompany)"
            continue
        s = dn_so.get(n) or []
        if not s:
            skip_dn[n] = "tanpa link against_sales_order"
            continue
        out = [x for x in s if x not in keep_so]
        if out:
            skip_dn[n] = f"menarik SO di luar scope: {', '.join(sorted(out))}"
            continue
        keep_dn.append(n)

    jdump("so_docs.json", so_docs)
    jdump("dn_docs.json", dn_docs)
    jdump("po_target.json", sorted(po_target))
    sc = {"so": keep_so, "dn": keep_dn, "skip_so": skip_so, "skip_dn": skip_dn,
          "dn_so": {k: v for k, v in dn_so.items() if k in keep_dn}}
    jdump("scope.json", sc)
    print(f"[dump] SO dimigrasi: {len(keep_so)} (skip {len(skip_so)}) | "
          f"DN dimigrasi: {len(keep_dn)} (skip {len(skip_dn)})")
    for n, why in sorted(skip_so.items()):
        print(f"   skip SO {n}: {why}")
    for n, why in sorted(skip_dn.items()):
        print(f"   skip DN {n}: {why}")
    return sc


# ---------------------------------------------------------------- prep
def ensure_item_valuation(new, dn_docs, sc):
    """Isi Item.valuation_rate dari kolom `incoming_rate` DN SUMBER untuk item
    yang gudangnya kosong & tanpa nilai di target (ERPNext menolak submit:
    'Valuation Rate for the Item X is required').

    Nilainya BUKAN tebakan: `incoming_rate` baris DN lama = nilai akuntansi
    riil item saat keluar gudang di site lama.
    """
    from collections import defaultdict
    need = defaultdict(list)      # code -> [incoming_rate sumber]
    for n in sc["dn"]:
        doc = dn_docs[n]
        if doc.get("docstatus") != 1:
            continue
        for r in doc["items"]:
            code = ITEM_MAP.get(r["item_code"], r["item_code"])
            if r.get("incoming_rate"):
                need[code].append(r["incoming_rate"])
    hasil = []
    for code, rates in sorted(need.items()):
        st, d = new.get("/api/resource/Item/" + quote(code),
                        {"fields": json.dumps(["name", "valuation_rate"])})
        it = d.get("data") or {}
        if not it:
            hasil.append({"item": code, "status": "ITEM-HILANG"})
            continue
        cur = it.get("valuation_rate") or 0
        if cur > 0:
            hasil.append({"item": code, "status": "SUDAH ADA", "nilai": cur})
            continue
        # Catatan: stok bernilai di gudang LAIN tidak menolong — ERPNext
        # memakai Item.valuation_rate sebagai fallback saat gudang sumber
        # kosong. Nilai diambil dari incoming_rate DN sumber (nilai akuntansi
        # riil saat barang keluar di site lama), bukan tebakan.
        val = max(rates)
        st, d = new.put("Item", code, {"valuation_rate": val})
        if st != 200:
            raise SystemExit(f"[prep] GAGAL set valuation {code}: "
                             f"{json.dumps(d)[:200]}")
        print(f"[prep] item {code}: valuation_rate 0 -> {val:,.2f} "
              f"(incoming_rate DN sumber)")
        hasil.append({"item": code, "status": "DIISI", "nilai": val})
    jdump("valuation_prep.json", hasil)
    return hasil


def ensure_customer_internal(new, rep_company):
    """Customer internal utk outlet: `represents_company` = company outlet
    (bukan JURI). Wajib agar SO lolos `validate_inter_company_party`
    (party internal dicek `represents_company == company`).

    Mengembalikan nama customer (dibuat bila belum ada).
    """
    st, d = new.get("/api/resource/Customer", {
        "filters": json.dumps([["represents_company", "=", rep_company],
                               ["is_internal_customer", "=", 1]]),
        "fields": json.dumps(["name", "companies"]), "limit_page_length": 1})
    rows = d.get("data", [])
    if rows:
        code = rows[0]["name"]
        comps = [x.get("company") for x in rows[0].get("companies", [])]
        if JURI not in comps:
            st, d = new.put("Customer", code,
                            {"companies": [{"company": c} for c in comps + [JURI]]})
            if st != 200:
                raise SystemExit(f"[prep] GAGAL set companies {code}: "
                                 f"{json.dumps(d)[:200]}")
            print(f"[prep] customer {code}: +allowed company {JURI}")
            return code, "DIPERBAIKI"
        return code, "SUDAH"

    # cari customer existing dengan nama sama (belum internal)
    st, d = new.get("/api/resource/Customer", {
        "filters": json.dumps([["customer_name", "=", rep_company]]),
        "fields": json.dumps(["name", "is_internal_customer", "represents_company"]),
        "limit_page_length": 1})
    rows = d.get("data", [])
    if rows:
        code = rows[0]["name"]
        st, d = new.put("Customer", code, {
            "is_internal_customer": 1, "represents_company": rep_company,
            "companies": [{"company": JURI}]})
        if st != 200:
            raise SystemExit(f"[prep] GAGAL jadikan internal {code}: "
                             f"{json.dumps(d)[:200]}")
        print(f"[prep] customer {code} -> internal (rep: {rep_company})")
        return code, "DIAKTIFKAN"

    # buat baru
    st, d = new.post("Customer", {
        "customer_name": rep_company, "customer_type": "Company",
        "customer_group": "Outlet Reguler", "territory": "Indonesia",
        "is_internal_customer": 1, "represents_company": rep_company,
        "companies": [{"company": JURI}]})
    if st != 200:
        raise SystemExit(f"[prep] GAGAL buat customer {rep_company}: "
                         f"{json.dumps(d)[:250]}")
    code = d["data"]["name"]
    print(f"[prep] customer dibuat: {rep_company} -> {code} (internal)")
    return code, "DIBUAT"


def cmd_prep(old, new, sc):
    """Pastikan tiap customer SO punya internal-customer pasangan di target.

    Sumber: SO lama -> `customer` (kode lama) -> Customer lama
    `represents_company` (nama company outlet). Di target dicari customer
    internal dengan `represents_company` sama; kalau tidak ada, dibuat.
    """
    so_docs = jload("so_docs.json")
    need = sorted({so_docs[n]["customer"] for n in sc["so"]})

    old_cust = {}
    for i in range(0, len(need), 40):
        st, d = old.get("/api/resource/Customer", {
            "filters": json.dumps([["name", "in", need[i:i + 40]]]),
            "fields": json.dumps(["name", "customer_name", "represents_company",
                                  "is_internal_customer"]),
            "limit_page_length": 0})
        for x in d.get("data", []):
            old_cust[x["name"]] = x

    cust_map, hasil = {}, []
    for c in need:
        o = old_cust.get(c) or {}
        rep = o.get("represents_company") or o.get("customer_name") or c
        code, status = ensure_customer_internal(new, rep)
        cust_map[c] = code
        hasil.append({"customer_lama": c, "rep_company": rep,
                      "customer_baru": code, "status": status})

    # validasi: setiap customer terpetakan & internal
    bad = []
    for c, code in cust_map.items():
        if not code:
            bad.append(c)
    if bad:
        raise SystemExit(f"[prep] customer tak terpetakan: {bad[:10]}")

    jdump("cust_map.json", cust_map)
    jdump("cust_prep.json", hasil)
    from collections import Counter
    print(f"[prep] customer: {len(cust_map)} dipetakan "
          f"({dict(Counter(x['status'] for x in hasil))})")

    # valuation fallback utk item yang bakal memblokir submit DN
    dn_docs = jload("dn_docs.json", {})
    val = ensure_item_valuation(new, dn_docs, sc)
    n_isi = sum(1 for x in val if x["status"] == "DIISI")
    print(f"[prep] valuation: {n_isi} item diisi dari incoming_rate DN sumber")
    return cust_map


# ---------------------------------------------------------------- payloads
def map_row_common(row, items_master, abbrs, company, alerts, ctx):
    code = ITEM_MAP.get(row["item_code"], row["item_code"])
    row["item_code"] = code          # WAJIB: remap bentrok kode

    it = items_master.get(code)
    uom = UOM_MAP.get(row.get("uom"), row.get("uom"))
    cf = row.get("conversion_factor")
    if it:
        su = it.get("stock_uom")
        conv = {u["uom"]: u["conversion_factor"] for u in it.get("uoms") or []}
        if uom == su:
            cf = 1.0
        elif conv.get(uom):
            cf = conv[uom]
        elif row.get("conversion_factor") == 1.0:
            alerts.append(f"{ctx} {code}: UOM '{uom}' absen & cf=1 -> '{su}'")
            uom, cf = su, 1.0
        else:
            alerts.append(f"{ctx} {code}: UOM '{uom}' absen, pakai cf "
                          f"sumber {cf}")
        row["stock_uom"] = su
    row["uom"] = uom
    row["conversion_factor"] = cf
    if row.get("warehouse"):
        row["warehouse"] = wh_map(row["warehouse"])
    row["cost_center"] = cc_map(row.get("cost_center"))
    return row


KEEP_SO_HDR = ["company", "customer", "transaction_date", "transaction_time",
               "delivery_date", "currency", "conversion_rate",
               "selling_price_list", "price_list_currency", "plc_conversion_rate",
               "ignore_pricing_rule", "set_warehouse", "language",
               "disable_rounded_total", "group_same_items", "order_type",
               "skip_delivery_note"]
KEEP_SO_ROW = ["item_code", "qty", "rate", "uom", "conversion_factor",
               "stock_uom", "warehouse", "delivery_date", "cost_center",
               "price_list_rate"]
KEEP_DN_HDR = ["company", "customer", "posting_date", "posting_time",
               "currency", "conversion_rate", "selling_price_list",
               "price_list_currency", "plc_conversion_rate", "ignore_pricing_rule",
               "set_warehouse", "language", "disable_rounded_total",
               "group_same_items"]
KEEP_DN_ROW = ["item_code", "qty", "rate", "uom", "conversion_factor",
               "stock_uom", "warehouse", "cost_center", "price_list_rate"]


def build_so(src, items_master, cust_map, abbrs, po_rows):
    alerts = []
    payload = {k: src[k] for k in KEEP_SO_HDR if src.get(k) is not None}
    payload["customer"] = cust_map.get(src["customer"], src["customer"])
    payload["set_warehouse"] = wh_map(src.get("set_warehouse"))
    payload["inter_company_order_reference"] = src["inter_company_order_reference"]
    payload["title"] = f"ERESTO {src['name']}"
    icr = src["inter_company_order_reference"]
    rows_po = po_rows.get(icr, {})
    items = []
    for it in src.get("items", []):
        row = {k: it[k] for k in KEEP_SO_ROW if it.get(k) is not None}
        row = map_row_common(row, items_master, abbrs, src["company"], alerts,
                             src["name"])
        code = ITEM_MAP.get(it["item_code"], it["item_code"])
        if code in rows_po:
            row["purchase_order"] = icr
            row["purchase_order_item"] = rows_po[code]
            row["item_code"] = code
        elif it["item_code"] in rows_po:
            row["purchase_order"] = icr
            row["purchase_order_item"] = rows_po[it["item_code"]]
        else:
            alerts.append(f"{src['name']} {code}: tidak ada baris PO pasangan")
        items.append(row)
    payload["items"] = items
    return payload, alerts


def build_dn(src, items_master, cust_map, abbrs, so_rows):
    alerts = []
    payload = {k: src[k] for k in KEEP_DN_HDR if src.get(k) is not None}
    payload["customer"] = cust_map.get(src["customer"], src["customer"])
    payload["set_warehouse"] = wh_map(src.get("set_warehouse"))
    payload["set_posting_time"] = 1
    payload["title"] = f"ERESTO {src['name']}"
    items = []
    for it in src.get("items", []):
        row = {k: it[k] for k in KEEP_DN_ROW if it.get(k) is not None}
        row = map_row_common(row, items_master, abbrs, src["company"], alerts,
                             src["name"])
        code = ITEM_MAP.get(it["item_code"], it["item_code"])
        so_name = it.get("against_sales_order")
        if so_name:
            row["against_sales_order"] = so_name
            det = (so_rows.get(so_name) or {}).get(code)
            if det:
                row["so_detail"] = det
            else:
                alerts.append(f"{src['name']} {code}: so_detail tidak ketemu "
                              f"di {so_name}")
        items.append(row)
    payload["items"] = items
    return payload, alerts


def load_items_master(new, codes):
    cache = jload("items_master.json", {})
    missing = [c for c in codes if c not in cache]
    if missing:
        print(f"[items] ambil {len(missing)} master item ...")
        with ThreadPoolExecutor(6) as ex:
            futs = {ex.submit(fetch_doc, new, "Item", c,
                              ["name", "stock_uom", "uoms", "valuation_rate"]): c
                    for c in missing}
            for fu in as_completed(futs):
                c = futs[fu]
                doc = fu.result()
                if doc:
                    cache[c] = doc
        jdump("items_master.json", cache)
    return cache


def load_po_rows(new, po_names):
    """{po: {item_code: row_name}} dari PO target."""
    cache = jload("po_rows.json", {})
    missing = [p for p in po_names if p not in cache]
    for i in range(0, len(missing), 30):
        chunk = missing[i:i + 30]
        with ThreadPoolExecutor(6) as ex:
            futs = {ex.submit(fetch_doc, new, "Purchase Order", p, ["name", "items"]): p
                    for p in chunk}
            for fu in as_completed(futs):
                p = futs[fu]
                doc = fu.result() or {}
                cache[p] = {}
                for r in doc.get("items", []):
                    cache[p].setdefault(r["item_code"], r["name"])
        jdump("po_rows.json", cache)
    return cache


# ---------------------------------------------------------------- migrate
def _existing_map(new, dt):
    """{name: docstatus} + {title: name} dokumen yang sudah ada di target."""
    out = new.list_all(dt, ["name", "title", "docstatus"])
    by_name = {x["name"]: x.get("docstatus") for x in out}
    by_title = {x["title"]: x["name"] for x in out if x.get("title")}
    return by_name, by_title


def _heal_existing(new, dt, name, cur_ds, want_ds):
    """Dokumen sudah ada tapi docstatus belum sesuai -> submit/cancel.

    Penting: percobaan sebelumnya bisa gagal di tengah (POST sukses, submit
    gagal) sehingga tersisa draft. Rerun harus MENYELESAIKAN, bukan bilang OK.
    """
    if cur_ds == want_ds:
        return None
    if want_ds == 1 and cur_ds == 0:
        st, d = new.submit(dt, name)
        return ("DIPERBAIKI-SUBMIT" if st == 200 else "GAGAL-SUBMIT", str(d)[:200])
    if want_ds == 2:
        if cur_ds == 0:
            new.submit(dt, name)
        st, d = new.cancel(dt, name)
        return ("DIPERBAIKI-CANCEL" if st == 200 else "GAGAL-CANCEL", str(d)[:200])
    return ("DOCSTATUS-BEDA", f"target={cur_ds} sumber={want_ds}")


def migrate_so(new, src, cust_map, items_master, abbrs, po_rows, ex_names,
               ex_titles, dry):
    name = src["name"]
    want_ds = src.get("docstatus", 1)
    if name in ex_names or f"ERESTO {name}" in ex_titles:
        cur = ex_names.get(name)
        if cur is None:
            cur = ex_names.get(ex_titles.get(f"ERESTO {name}"))
        if dry:
            return {"name": name, "status": "DRY-RUN-EXIST", "alerts": []}
        fix = _heal_existing(new, "Sales Order", name, cur, want_ds)
        if fix:
            return {"name": name, "status": fix[0], "alerts": [fix[1]]}
        return {"name": name, "status": "SKIP_EXISTS", "alerts": []}
    payload, alerts = build_so(src, items_master, cust_map, abbrs, po_rows)
    if dry:
        return {"name": name, "status": "DRY-RUN", "alerts": alerts,
                "rows": len(payload["items"]), "grand_total": src.get("grand_total")}
    st, d = new.post("Sales Order", payload)
    if st != 200:
        return {"name": name, "status": "FAIL_POST", "alerts": alerts,
                "err": json.dumps(d)[:300]}
    final = d["data"]["name"]
    st2, _ = new.rename("Sales Order", final, name)
    if st2 == 200:
        final = name
    if src.get("docstatus") == 1:
        st3, d3 = new.submit("Sales Order", final)
        if st3 != 200:
            return {"name": name, "status": "FAIL_SUBMIT", "final": final,
                    "alerts": alerts, "err": json.dumps(d3)[:300]}
    elif src.get("docstatus") == 2:
        new.submit("Sales Order", final)
        new.cancel("Sales Order", final)
    return {"name": name, "status": "MIGRATED", "final": final,
            "alerts": alerts, "rows": len(payload["items"]),
            "grand_total": src.get("grand_total")}


def migrate_dn(new, src, cust_map, items_master, abbrs, so_rows, ex_names,
               ex_titles, dry):
    name = src["name"]
    want_ds = src.get("docstatus", 1)
    if name in ex_names or f"ERESTO {name}" in ex_titles:
        cur = ex_names.get(name)
        if cur is None:
            cur = ex_names.get(ex_titles.get(f"ERESTO {name}"))
        if dry:
            return {"name": name, "status": "DRY-RUN-EXIST", "alerts": []}
        fix = _heal_existing(new, "Delivery Note", name, cur, want_ds)
        if fix:
            return {"name": name, "status": fix[0], "alerts": [fix[1]]}
        return {"name": name, "status": "SKIP_EXISTS", "alerts": []}
    payload, alerts = build_dn(src, items_master, cust_map, abbrs, so_rows)
    if dry:
        return {"name": name, "status": "DRY-RUN", "alerts": alerts,
                "rows": len(payload["items"]), "grand_total": src.get("grand_total")}
    st, d = new.post("Delivery Note", payload)
    if st != 200:
        return {"name": name, "status": "FAIL_POST", "alerts": alerts,
                "err": json.dumps(d)[:300]}
    final = d["data"]["name"]
    st2, _ = new.rename("Delivery Note", final, name)
    if st2 == 200:
        final = name
    if src.get("docstatus") == 1:
        st3, d3 = new.submit("Delivery Note", final)
        if st3 != 200:
            return {"name": name, "status": "FAIL_SUBMIT", "final": final,
                    "alerts": alerts, "err": json.dumps(d3)[:300]}
    elif src.get("docstatus") == 2:
        new.submit("Delivery Note", final)
        new.cancel("Delivery Note", final)
    return {"name": name, "status": "MIGRATED", "final": final,
            "alerts": alerts, "rows": len(payload["items"]),
            "grand_total": src.get("grand_total")}


def cmd_migrate(old, new, sc, args, which):
    so_docs = jload("so_docs.json")
    dn_docs = jload("dn_docs.json")
    cust_map = jload("cust_map.json", {})
    abbrs = jload("outlet_po_dump/company_abbr.json", {}) if False else \
        json.load(open(os.path.join(HERE, "outlet_po_dump", "company_abbr.json")))

    codes = sorted({ITEM_MAP.get(it["item_code"], it["item_code"])
                    for src in list(so_docs.values()) + list(dn_docs.values())
                    for it in src.get("items", [])})
    items_master = load_items_master(new, codes)

    ex_names, ex_titles = _existing_map(new, which)

    if which == "Sales Order":
        po_names = sorted({so_docs[n]["inter_company_order_reference"] for n in sc["so"]})
        po_rows = load_po_rows(new, po_names)
        todo = sc["so"]
        fn = lambda n: migrate_so(new, so_docs[n], cust_map, items_master, abbrs,
                                  po_rows, ex_names, ex_titles, args.dry_run)
    else:
        # pastikan SO target ada; petakan so_detail baris
        so_rows = {}
        for i in range(0, len(sc["so"]), 25):
            chunk = sc["so"][i:i + 25]
            with ThreadPoolExecutor(6) as ex:
                futs = {ex.submit(fetch_doc, new, "Sales Order", s,
                                  ["name", "items"]): s for s in chunk}
                for fu in as_completed(futs):
                    s = futs[fu]
                    doc = fu.result() or {}
                    so_rows[s] = {r["item_code"]: r["name"]
                                  for r in doc.get("items", [])}
        todo = sc["dn"]
        fn = lambda n: migrate_dn(new, dn_docs[n], cust_map, items_master, abbrs,
                                 so_rows, ex_names, ex_titles, args.dry_run)

    todo = sorted(todo)
    if args.only:
        todo = [n for n in todo if n == args.only]
    if args.limit:
        todo = todo[: args.limit]

    hasil = []
    t0 = time.time()
    with ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(fn, n): n for n in todo}
        for i, fu in enumerate(as_completed(futs), 1):
            r = fu.result()
            hasil.append(r)
            mark = {"MIGRATED": "+", "SKIP_EXISTS": "=", "DRY-RUN": "?",
                    "DIPERBAIKI-SUBMIT": "~", "DIPERBAIKI-CANCEL": "~",
                    "DRY-RUN-EXIST": "="}.get(r["status"], "!")
            if mark == "!" or i % 25 == 0:
                print(f"  [{mark}] {r['name']}: {r['status']}"
                      + (f" | {r.get('err', '')[:180]}" if mark == "!" else ""))
    OK_STATUS = ("MIGRATED", "SKIP_EXISTS", "DRY-RUN", "DRY-RUN-EXIST",
                 "DIPERBAIKI-SUBMIT", "DIPERBAIKI-CANCEL")
    n_ok = sum(1 for r in hasil if r["status"] in OK_STATUS)
    print(f"[migrate {which}] {n_ok}/{len(hasil)} OK, {len(hasil)-n_ok} gagal "
          f"dalam {time.time()-t0:.0f}s (dry_run={args.dry_run})")
    jdump(f"result_{which.replace(' ', '_')}.json", hasil)
    alerts = [(r["name"], a) for r in hasil for a in r.get("alerts", [])]
    if alerts:
        jdump(f"alerts_{which.replace(' ', '_')}.json", alerts)
    if args.dry_run:
        for _, a in alerts[:40]:
            print("   [alert]", a)
        print(f"   total alert: {len(alerts)}")
    return hasil


# ---------------------------------------------------------------- verify
def cmd_verify(old, new, sc):
    so_docs = jload("so_docs.json")
    dn_docs = jload("dn_docs.json")
    rows, skipped, failed = [], [], []
    n_ok = {"so": 0, "dn": 0, "so_ds": 0, "dn_ds": 0, "so_rows": 0, "dn_rows": 0,
            "so_link": 0, "dn_link": 0}
    tot = {"so_src": 0.0, "so_tgt": 0.0, "dn_src": 0.0, "dn_tgt": 0.0}

    for kind, docs, names in (("so", so_docs, sc["so"]), ("dn", dn_docs, sc["dn"])):
        dt = "Sales Order" if kind == "so" else "Delivery Note"
        exist = {}
        for i in range(0, len(names), 40):
            st, d = new.get(f"/api/resource/{quote(dt)}", {
                "filters": json.dumps([["name", "in", names[i:i + 40]]]),
                "fields": json.dumps(["name", "docstatus", "grand_total"]),
                "limit_page_length": 0})
            for x in d.get("data", []):
                exist[x["name"]] = x
        for n in sorted(names):
            src = docs[n]
            tgt = exist.get(n)
            exp_gt = src.get("grand_total") or 0
            tot[f"{kind}_src"] += exp_gt
            if tgt:
                tot[f"{kind}_tgt"] += tgt.get("grand_total") or 0
            val_ok = bool(tgt) and abs((tgt.get("grand_total") or 0) - exp_gt) < 1.0
            ds_ok = bool(tgt) and tgt.get("docstatus") == src.get("docstatus")
            link_ok = ""
            row_ok = None
            if tgt:
                st2, d2 = new.get(f"/api/resource/{quote(dt)}/{quote(n)}",
                                  {"fields": json.dumps(
                                      ["name", "items", "inter_company_order_reference"]
                                      if kind == "so" else
                                      ["name", "items"])})
                tdoc = d2.get("data") or {}
                row_ok = len(tdoc.get("items", [])) == len(src.get("items", []))
                if kind == "so":
                    link_ok = tdoc.get("inter_company_order_reference") == \
                        src.get("inter_company_order_reference")
                    n_ok["so_rows"] += bool(row_ok)
                    n_ok["so_link"] += bool(link_ok)
                else:
                    det = all(r.get("so_detail") for r in tdoc.get("items", []))
                    link_ok = all(r.get("against_sales_order")
                                  for r in tdoc.get("items", [])) and det
                    n_ok["dn_rows"] += bool(row_ok)
                    n_ok["dn_link"] += bool(link_ok)
            n_ok[kind] += val_ok
            n_ok[f"{kind}_ds"] += ds_ok
            rows.append({"tipe": dt, "dokumen": n,
                         "company": src.get("company"),
                         "customer": src.get("customer"),
                         "tanggal": src.get("transaction_date") or src.get("posting_date"),
                         "docstatus_lama": src.get("docstatus"),
                         "docstatus_baru": tgt.get("docstatus") if tgt else None,
                         "baris_lama": len(src.get("items", [])),
                         "baris_baru": row_ok,
                         "nilai_lama": exp_gt,
                         "nilai_baru": tgt.get("grand_total") if tgt else None,
                         "status": "ADA" if tgt else "HILANG",
                         "link": link_ok, "errors": ""})

    for n, why in sorted(sc.get("skip_so", {}).items()):
        skipped.append({"tipe": "Sales Order", "dokumen": n, "alasan": why})
    for n, why in sorted(sc.get("skip_dn", {}).items()):
        skipped.append({"tipe": "Delivery Note", "dokumen": n, "alasan": why})
    for f in ("result_Sales_Order.json", "result_Delivery_Note.json"):
        for r in jload(f, []) or []:
            if r["status"] not in ("MIGRATED", "SKIP_EXISTS", "DRY-RUN",
                                   "DRY-RUN-EXIST", "DIPERBAIKI-SUBMIT",
                                   "DIPERBAIKI-CANCEL"):
                failed.append({"dokumen": r["name"], "status": r["status"],
                               "err": str(r.get("err", ""))[:300]})

    ns, nd = len(sc["so"]), len(sc["dn"])
    checks = [
        ("Jumlah SO target", f"{n_ok['so']}/{ns}",
         "LOLOS" if n_ok["so"] == ns else "GAGAL"),
        ("Nilai SO cocok", f"{tot['so_src']:,.0f} vs {tot['so_tgt']:,.0f}",
         "LOLOS" if abs(tot["so_src"] - tot["so_tgt"]) < 1 else "GAGAL"),
        ("Docstatus SO cocok", f"{n_ok['so_ds']}/{ns}",
         "LOLOS" if n_ok["so_ds"] == ns else "GAGAL"),
        ("Baris SO cocok", f"{n_ok['so_rows']}/{ns}",
         "LOLOS" if n_ok["so_rows"] == ns else "GAGAL"),
        ("Link SO -> PO", f"{n_ok['so_link']}/{ns}",
         "LOLOS" if n_ok["so_link"] == ns else "GAGAL"),
        ("Jumlah DN target", f"{n_ok['dn']}/{nd}",
         "LOLOS" if n_ok["dn"] == nd else "GAGAL"),
        ("Nilai DN cocok", f"{tot['dn_src']:,.0f} vs {tot['dn_tgt']:,.0f}",
         "LOLOS" if abs(tot["dn_src"] - tot["dn_tgt"]) < 1 else "GAGAL"),
        ("Docstatus DN cocok", f"{n_ok['dn_ds']}/{nd}",
         "LOLOS" if n_ok["dn_ds"] == nd else "GAGAL"),
        ("Baris DN cocok", f"{n_ok['dn_rows']}/{nd}",
         "LOLOS" if n_ok["dn_rows"] == nd else "GAGAL"),
        ("Link DN -> SO", f"{n_ok['dn_link']}/{nd}",
         "LOLOS" if n_ok["dn_link"] == nd else "GAGAL"),
        ("Dokumen di-skip (terdokumentasi)", f"{len(skipped)}", "CATATAN"),
    ]
    write_report(rows, checks, skipped, failed)
    for c in checks:
        print(f"  {c[2]}: {c[0]} ({c[1]})")
    gagal = sum(1 for c in checks if c[2] == "GAGAL")
    print(f"[verify] {'SELURUH CEK LOLOS' if not gagal else f'{gagal} CEK GAGAL'}"
          f" — laporan: {os.path.basename(REPORT)}")
    return gagal


def write_report(rows, checks, skipped, failed):
    HEAD = PatternFill("solid", fgColor="D9EAF7")
    ws = openpyxl.Workbook()
    s1 = ws.active
    s1.title = "Rekap"
    cols = ["tipe", "dokumen", "company", "customer", "tanggal", "docstatus_lama",
            "docstatus_baru", "baris_lama", "baris_baru", "nilai_lama",
            "nilai_baru", "status", "link", "errors"]
    s1.append(cols)
    for r in rows:
        s1.append([r[c] for c in cols])
    s2 = ws.create_sheet("Skipped")
    s2.append(["tipe", "dokumen", "alasan"])
    for r in skipped:
        s2.append([r["tipe"], r["dokumen"], r["alasan"]])
    s3 = ws.create_sheet("Validation")
    s3.append(["check", "hasil", "status"])
    for c in checks:
        s3.append(list(c))
    s4 = ws.create_sheet("Failed")
    s4.append(["dokumen", "status", "err"])
    for r in failed:
        s4.append([r["dokumen"], r["status"], r["err"]])
    for s in (s1, s2, s3, s4):
        for cell in s[1]:
            cell.fill = HEAD
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center")
        s.freeze_panes = "A2"
    s1.column_dimensions["B"].width = 18
    s1.column_dimensions["C"].width = 30
    s1.column_dimensions["D"].width = 34
    s2.column_dimensions["C"].width = 60
    s3.column_dimensions["A"].width = 32
    s3.column_dimensions["B"].width = 30
    s4.column_dimensions["C"].width = 60
    ws.save(REPORT)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dump", action="store_true", help="tarik SO/DN dari site lama")
    ap.add_argument("--refresh", action="store_true", help="paksa tarik ulang")
    ap.add_argument("--prep", action="store_true", help="siapkan customer di target")
    ap.add_argument("--so", action="store_true", help="migrasi Sales Order")
    ap.add_argument("--dn", action="store_true", help="migrasi Delivery Note")
    ap.add_argument("--verify", action="store_true", help="verifikasi + laporan")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="satu nama dokumen")
    ap.add_argument("--limit", type=int, help="batasi jumlah")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    if not any([args.dump, args.prep, args.so, args.dn, args.verify, args.dry_run]):
        ap.print_help()
        return

    old, new = clients()
    sc = jload("scope.json")
    if sc is None or args.refresh or args.dump:
        sc = cmd_dump(old, new, refresh=True)

    if args.prep:
        cmd_prep(old, new, sc)
    if args.so or (args.dry_run and not args.dn):
        cmd_migrate(old, new, sc, args, "Sales Order")
    if args.dn:
        cmd_migrate(old, new, sc, args, "Delivery Note")
    if args.dry_run and not args.so and not args.dn:
        cmd_migrate(old, new, sc, args, "Sales Order")
    if args.verify:
        cmd_verify(old, new, sc)


if __name__ == "__main__":
    main()
