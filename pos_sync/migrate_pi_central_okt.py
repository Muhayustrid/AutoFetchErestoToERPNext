"""Cek di ERPNext lama lalu migrasi faktur pembelian eResto Okt 2026 (divisi sentral).

Scope (instruksi user 2026-10-08):
- Faktur eResto bulan Oktober 2026 yang PO-nya sebelum Oktober.
- Hanya divisi sentral: 'Gudang Barang Jadi - PH Klaten', 'Gudang Produksi Klaten',
  'Gudang Jakarta'.
- Kecualikan faktur yang supplier-nya gudang internal (GBJ/GPK/GJKT) = bukan pembelian.
- Kecualikan item eResto ber-prefix 'TIDAK AKTIF' (dipetakan ke item aktif bila ada).

Alur:
1. --dump    : baca cache eResto (pos_sync/po_okt_dump) -> daftar faktur target.
2. --check   : cari dokumen serupa di ERPNext lama (PO/PR by supplier+item+qty+unit+harga)
               dan cek keberadaan PI/PR/PO di site baru.
3. --migrate : (a) migrasi PO/PR lama yang belum ada di baru (ID identik via rename_doc),
               (b) buat Purchase Invoice di baru utk faktur target dari data eResto
               (PPN 11%, bill_no = nomor INV eResto, link ke PO yang ada).
4. --verify  : cek total/qty/rate PI vs faktur eResto + tulis laporan Excel.

Idempotensi: PI dicek by bill_no (nomor INV eResto) -> rerun SKIP_EXISTS.
Semua tulis hanya ke site BARU; eResto & site lama read-only.

Env: /tmp/eresto_mig.env (ERPNEXT_OLD_CLOUD_API_KEY), /tmp/eresto_prod.env
     (ERPNEXT_URL, ERPNEXT_API_KEY).
Output: pos_sync/Laporan_Migrasi_PI_Central_Okt2026.xlsx
"""
import argparse
import json
import os
import sys

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DUMP = os.path.join(HERE, "po_okt_dump")
REPORT = os.path.join(HERE, "Laporan_Migrasi_PI_Central_Okt2026.xlsx")
RESULT = os.path.join(DUMP, "pi_migrate_result.json")

OLD_BASE = "https://rotiropi.j.frappe.cloud"

CENTRAL_DIVS = {
    "gudang barang jadi - ph klaten",
    "gudang produksi klaten",
    "gudang jakarta",
}
WH_MAP = {
    "Gudang Barang Jadi - PH Klaten": "Gudang Barang Jadi - JURI",
    "Gudang Jakarta": "Gudang Jakarta - JURI",
    "Gudang Produksi Klaten": "Gudang Produksi - JURI",
}

JURI = "PT. JUARA ROTI INDONESIA"
PPN_ACCOUNT = "1152.001 - PPN Masukan - JURI"
ACCRUAL_ACCOUNT = "2115.000 - Stock Diterima Tapi Tidak Ditagih - JURI"
AP_ACCOUNT = "2111.001 - Hutang Dagang Dalam Negeri - JURI"
COST_CENTER = "Main - JURI"
HPP_ACCOUNT = "4210.000 - HPP Pembelian - JURI"

# SKU eResto -> (item baru, uom, conversion_factor). Sumber: master Item baru +
# PI yang sudah dibuat tim hari ini (PI-JURI-261008004/261008001).
SKU_ITEM = {
    "BB0100": ("BB260042", "kg", 1000.0),
    "BB0174": ("BB260046", "ctn", 16000.0),   # 'TIDAK AKTIF Olesan Pastry' -> aktif
    "BB0340": ("BB260031", "ctn", 12000.0),
    "BB0110": ("BB260047", "ctn", 6000.0),
    "BB0081": ("BB260040", "Pcs", 250.0),
    "BB0036": ("PEL260011", "Pcs", 1.0),
    "BB0112": ("PEL260076", "Pcs", 1.0),
}

# nama supplier eResto -> nama Supplier doc di site baru (bila beda ejaan)
SUPPLIER_MAP = {
    "Tokopedia Shopee - Kemitraan": "Tokopedia - Shopee",
}

# target -> (po baru, po_detail row, pr baru, pr_detail row, posting_date, tax?)
TARGET_CFG = {
    "INVGBJ.061026.029": {"skip_reason": "PI sudah ada (PI-JURI-261008004)",
                          "existing_pi": "PI-JURI-261008004"},
    "INVGBJ.061026.030": {"skip_reason": "PI sudah ada (PI-JURI-261008001)",
                          "existing_pi": "PI-JURI-261008001"},
    "INVGBJ.081026.001": {"po": "PO-250926-008", "po_detail": "ea3s9nrqvc",
                          "pr": "PR-051026-001", "posting_date": "2026-10-05",
                          "tax": True, "rate_override": {},
                          "note": "Harga PR/lama 270.000 vs faktur eResto 299.243,23 — PI pakai harga faktur"},
    "INVCK2.081026.003": {"po": "POCK2.250926.001", "po_detail": "ai0nfb1vq9",
                          "pr": "PR-011026-021", "posting_date": "2026-10-01",
                          "tax": True, "rate_override": {},
                          "note": "PR duplikat PR-061026-011 (PO-061026-005) dibiarkan"},
    "INVCK2.011026.002": {"po": "POCK2.280926.001", "po_detail": "0i1tjr9fge",
                          "pr": "PR-011026-022", "posting_date": "2026-10-01",
                          "tax": False, "rate_override": {},
                          "note": "Tanpa PPN (sama dengan PR lama); PR duplikat PR-061026-012"},
    "INVCK2.081026.001": {"po": "PO-061026-004", "po_detail": "b9ed5fgru4",
                          "pr": "PR-061026-010", "posting_date": "2026-10-05",
                          "tax": True, "rate_override": {},
                          "note": "PO eResto POCK2.300926.001 -> baru PO-061026-004"},
    "INVCK2.081026.009": {"po": "POCK2.300926.002", "po_detail": None,
                          "pr": "PR-081026-005", "posting_date": "2026-10-08",
                          "tax": True, "rate_override": {},
                          "note": "PO+PR belum ada di baru -> migrasi dulu dari lama",
                          "migrate_old": True},
}

# dokumen eResto Okt di divisi 'Gudang Bahan Baku' (tidak diminta user; catatan saja)
GBBK_NOTE = "Divisi Gudang Bahan Baku - PH Klaten TIDAK diminta (catatan)"


def num(v):
    try:
        return float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def norm(s):
    s = str(s or "").lower().replace("tidak aktif", " ")
    return "".join(ch for ch in s if ch.isalnum())


# ---------------------------------------------------------------- dump
def build_targets():
    """Baca cache eResto -> daftar faktur target + baris item (SKU) hasil join PO."""
    invoices = json.load(open(os.path.join(DUMP, "invoices_okt.json")))
    details = json.load(open(os.path.join(DUMP, "po_details.json")))

    rows = []
    for inv in invoices:
        div = (inv.get("division") or {}).get("name") or ""
        sup = (inv.get("supplier") or {}).get("name") or ""
        if div.strip().lower() not in CENTRAL_DIVS:
            continue
        if sup.strip().lower() in CENTRAL_DIVS:
            continue
        po = details.get(inv.get("purchase_id")) or {}
        if not po or str(po.get("date", ""))[:10] >= "2026-10-01":
            continue
        po_items = {it.get("id"): it for it in (po.get("purchase_items") or [])}
        lines = []
        for li in inv.get("purchase_invoice_items") or []:
            poi = po_items.get(li.get("purchase_item_id")) or {}
            inv_obj = poi.get("inventory") or {}
            unit = poi.get("unit") or {}
            lines.append({
                "sku": inv_obj.get("sku") or "",
                "name": inv_obj.get("name") or "",
                "qty": num(li.get("amount")),
                "unit": unit.get("name") or "",
                "price": num(li.get("price")),
                "total": num(li.get("total_price")),
            })
        rows.append({
            "inv_no": inv["transaction_number"],
            "inv_date": str(inv["transaction_date"])[:10],
            "division": div,
            "supplier": sup,
            "total": num(inv.get("total_amount")),
            "po_eresto": po.get("purchase_number"),
            "po_date": str(po.get("date", ""))[:10],
            "po_total": num(po.get("total_cost")),
            "lines": lines,
        })
    return rows


# ---------------------------------------------------------------- check lama
LAMA_SUP_MAP = {
    "CV Sinnar Luciana Jaya": "SUP260165",
    "CV Mitra Sukses Sejati": "SUP260168",
    "PT Alkindo Naratama": "SUP260115",
    "PT Ayla Java Mandiri": "SUP260107",
    "Tokopedia Shopee - Kemitraan": "SUP260020",
    "Surya Karya Pangan": "SUP260202",
    "PT Sinar Niaga Sejahtera": "SUP260062",
}


def check_old(old, tgt):
    """Cari PR lama serupa (supplier + baris item cocok nama/qty/unit/harga)."""
    code = LAMA_SUP_MAP.get(tgt["supplier"])
    out = {"candidates": [], "best": None}
    if not code:
        return out
    st, d = old.get("/api/resource/Purchase Receipt", {
        "filters": json.dumps([["supplier", "=", code],
                               ["posting_date", ">=", "2026-08-01"],
                               ["posting_date", "<=", "2026-10-09"]]),
        "fields": json.dumps(["name", "posting_date", "grand_total", "status"]),
        "limit_page_length": 0, "order_by": "posting_date asc"})
    for pr in d.get("data", []) if st == 200 else []:
        st2, d2 = old.get("/api/resource/Purchase Receipt/" + pr["name"])
        if st2 != 200:
            continue
        p = d2["data"]
        plines = p.get("items") or []
        matched, name_ok, qty_ok, rate_ok, unit_ok = [], True, True, True, True
        for l in tgt["lines"]:
            best = None
            for it in plines:
                if norm(l["name"]) == norm(it.get("item_name")):
                    best = it
                    break
            if best is None:  # fallback: qty+unit sama
                for it in plines:
                    if abs(num(it.get("qty")) - l["qty"]) < 0.01 and \
                            str(it.get("uom", "")).lower() == l["unit"].lower():
                        best = it
                        break
            if best is None:
                name_ok = qty_ok = rate_ok = unit_ok = False
                matched.append({"line": l, "lama": None})
                continue
            n_ok = norm(l["name"]) == norm(best.get("item_name"))
            q_ok = abs(num(best.get("qty")) - l["qty"]) < 0.01
            r_ok = abs(num(best.get("rate")) - l["price"]) <= max(1.0, l["price"] * 0.01)
            u_ok = str(best.get("uom", "")).lower() == l["unit"].lower()
            name_ok &= n_ok
            qty_ok &= q_ok
            rate_ok &= r_ok
            unit_ok &= u_ok
            matched.append({"line": l, "lama": best,
                            "name_ok": n_ok, "qty_ok": q_ok, "rate_ok": r_ok,
                            "unit_ok": u_ok})
        t_ok = abs(num(p.get("grand_total")) - tgt["total"]) <= 1.0
        out["candidates"].append({
            "name": pr["name"], "posting_date": pr["posting_date"],
            "grand_total": num(p.get("grand_total")), "status": p.get("status"),
            "total_ok": t_ok, "name_ok": name_ok, "qty_ok": qty_ok,
            "rate_ok": rate_ok, "unit_ok": unit_ok, "matched": matched,
            "po_names": sorted(set(it.get("purchase_order") for it in plines
                                   if it.get("purchase_order"))),
        })
    # kandidat terbaik: utamakan yang total+qty+nama semua cocok
    hits = [c for c in out["candidates"] if c["qty_ok"] and c["name_ok"]]
    if not hits:
        hits = [c for c in out["candidates"] if c["qty_ok"]]
    out["best"] = max(
        hits, key=lambda c: (c["total_ok"], c["name_ok"], c["rate_ok"],
                             -abs(c["grand_total"] - tgt["total"]))) if hits else None
    return out


def check_new(new, tgt, cfg):
    """Cek keberadaan PI / PR / PO di site baru."""
    out = {"pi": None, "pr": None, "po": None}
    if cfg.get("existing_pi"):
        st, d = new.get("/api/resource/Purchase Invoice/" + cfg["existing_pi"])
        if st == 200 and d.get("data"):
            p = d["data"]
            out["pi"] = {"name": cfg["existing_pi"],
                         "grand_total": num(p.get("grand_total")),
                         "status": p.get("status"), "docstatus": p.get("docstatus")}
    st, d = new.get("/api/resource/Purchase Invoice", {
        "filters": json.dumps([["bill_no", "=", tgt["inv_no"]],
                               ["docstatus", "<", 2]]),
        "fields": json.dumps(["name", "grand_total", "status", "docstatus",
                              "posting_date"]),
        "limit_page_length": 3})
    rows = d.get("data", []) if isinstance(d, dict) else []
    if not out["pi"] and rows:
        out["pi"] = rows[0]
    for key, dt in (("pr", "Purchase Receipt"), ("po", "Purchase Order")):
        name = cfg.get(key)
        if not name:
            continue
        st, d = new.get(f"/api/resource/{dt}/{name}")
        if st == 200 and isinstance(d, dict) and d.get("data"):
            p = d["data"]
            out[key] = {"name": name, "grand_total": num(p.get("grand_total")),
                        "status": p.get("status"), "docstatus": p.get("docstatus")}
    return out


# ---------------------------------------------------------------- migrate lama docs
def ensure_allow_rename(new, dt):
    st, d = new.get("/api/resource/Property Setter", {
        "filters": json.dumps([["doc_type", "=", dt], ["property", "=", "allow_rename"]]),
        "fields": json.dumps(["name"]), "limit_page_length": 1})
    if isinstance(d, dict) and d.get("data"):
        return
    new.post("Property Setter", {
        "doctype": "Property Setter", "doctype_or_field": "DocType",
        "doc_type": dt, "property": "allow_rename", "property_type": "Check",
        "value": "1"})


def migrate_po_pr(new, old, tgt, cfg):
    """Migrasi PO + PR dari lama ke baru (ID identik via rename_doc)."""
    po_name = tgt["po_eresto"]           # POCK2.300926.002
    pr_name = cfg["pr"]                  # PR-081026-005
    log = []
    ensure_allow_rename(new, "Purchase Order")
    ensure_allow_rename(new, "Purchase Receipt")

    st, d = old.get("/api/resource/Purchase Order/" + po_name)
    po = d["data"]
    st2, d2 = new.get("/api/resource/Purchase Order/" + po_name)
    if st2 != 200:
        payload = {
            "doctype": "Purchase Order",
            "company": JURI,
            "supplier": po.get("supplier_name") or po.get("supplier"),
            "transaction_date": str(po.get("transaction_date"))[:10],
            "currency": po.get("currency", "IDR"),
            "conversion_rate": 1,
            "buying_price_list": po.get("buying_price_list", "Standard Buying"),
            "set_warehouse": "Gudang Jakarta - JURI",
            "taxes_and_charges": "Purchase Tax - JURI",
            "taxes": [{"charge_type": "On Net Total", "account_head": PPN_ACCOUNT,
                       "description": "PPN Masukan @ 11.0 - JURI", "rate": 11.0,
                       "cost_center": COST_CENTER}],
            "items": [],
            "remarks": f"Migrasi Site Lama | Ref: {po_name}",
            "title": f"ERESTO {po_name}",
        }
        for it in po.get("items") or []:
            payload["items"].append({
                "item_code": it["item_code"], "item_name": it.get("item_name"),
                "qty": num(it.get("qty")), "uom": it.get("uom"),
                "conversion_factor": num(it.get("conversion_factor")) or 1,
                "rate": num(it.get("rate")), "warehouse": "Gudang Jakarta - JURI",
                "expense_account": HPP_ACCOUNT, "cost_center": COST_CENTER,
                "schedule_date": str(it.get("schedule_date") or po.get("transaction_date"))[:10],
            })
        stp, dp = new.post("Purchase Order", payload)
        if stp != 200:
            return {"status": "GAGAL-PO", "err": json.dumps(dp)[:300]}
        temp = dp["data"]["name"]
        st_r, dr = new.rename("Purchase Order", temp, po_name)
        final = po_name if st_r == 200 else temp
        st_s, ds = new.submit("Purchase Order", final)
        log.append(f"PO {final} dibuat (rename {'OK' if st_r == 200 else 'fallback'}, "
                   f"submit {'OK' if st_s == 200 else ds})")
    else:
        final = po_name
        log.append(f"PO {po_name} sudah ada")

    st, d = new.get("/api/resource/Purchase Order/" + po_name)
    po_row = None
    for it in d["data"].get("items") or []:
        if it.get("item_code") == "BB260040":
            po_row = it.get("name")
    tgt["po_detail"] = po_row   # dibaca build_pi_payload via tgt.get("po_detail")

    st2, d2 = new.get("/api/resource/Purchase Receipt/" + pr_name)
    if st2 != 200:
        st, d = old.get("/api/resource/Purchase Receipt/" + pr_name)
        pr = d["data"]
        payload = {
            "doctype": "Purchase Receipt",
            "company": JURI,
            "supplier": pr.get("supplier_name") or pr.get("supplier"),
            "posting_date": str(pr.get("posting_date"))[:10],
            "posting_time": str(pr.get("posting_time") or "12:00:00"),
            "set_posting_time": 1,
            "currency": pr.get("currency", "IDR"),
            "conversion_rate": 1,
            "set_warehouse": "Gudang Jakarta - JURI",
            "taxes_and_charges": "Purchase Tax - JURI",
            "taxes": [{"charge_type": "On Net Total", "account_head": PPN_ACCOUNT,
                       "description": "PPN Masukan @ 11.0 - JURI", "rate": 11.0,
                       "cost_center": COST_CENTER}],
            "items": [],
            "remarks": f"Migrasi Site Lama | Ref: {pr_name}",
            "title": f"ERESTO {pr_name}",
        }
        for it in pr.get("items") or []:
            payload["items"].append({
                "item_code": it["item_code"], "item_name": it.get("item_name"),
                "qty": num(it.get("qty")), "uom": it.get("uom"),
                "conversion_factor": num(it.get("conversion_factor")) or 1,
                "rate": num(it.get("rate")), "warehouse": "Gudang Jakarta - JURI",
                "expense_account": HPP_ACCOUNT, "cost_center": COST_CENTER,
                "purchase_order": po_name, "purchase_order_item": po_row,
            })
        stp, dp = new.post("Purchase Receipt", payload)
        if stp != 200:
            return {"status": "GAGAL-PR", "err": json.dumps(dp)[:300]}
        temp = dp["data"]["name"]
        st_r, dr = new.rename("Purchase Receipt", temp, pr_name)
        final = pr_name if st_r == 200 else temp
        st_s, ds = new.submit("Purchase Receipt", final)
        log.append(f"PR {final} dibuat (rename {'OK' if st_r == 200 else 'fallback'}, "
                   f"submit {'OK' if st_s == 200 else ds})")
    else:
        log.append(f"PR {pr_name} sudah ada")
    return {"status": "OK", "log": log, "po_row": po_row}


# ---------------------------------------------------------------- create PI
def fetch_pr_rows(new, pr_name):
    """{item_code: row_name} dari PR di site baru (utk link pr_detail)."""
    if not pr_name:
        return {}
    st, d = new.get("/api/resource/Purchase Receipt/" + pr_name)
    if st != 200 or not isinstance(d, dict) or not d.get("data"):
        return {}
    return {it["item_code"]: it["name"] for it in d["data"].get("items") or []}


def build_pi_payload(tgt, cfg, pr_rows=None):
    from datetime import date, timedelta
    pr_rows = pr_rows or {}
    pd = date.fromisoformat(cfg["posting_date"])
    payload = {
        "doctype": "Purchase Invoice",
        "company": JURI,
        "supplier": SUPPLIER_MAP.get(tgt["supplier"], tgt["supplier"]),
        "posting_date": cfg["posting_date"],
        "set_posting_time": 1,
        "bill_no": tgt["inv_no"],
        "due_date": (pd + timedelta(days=1)).isoformat(),
        "update_stock": 0,
        "update_billed_amount_in_purchase_receipt": 1,
        "credit_to": AP_ACCOUNT,
        "cost_center": COST_CENTER,
        "remarks": (f"Migrasi eResto {tgt['inv_no']} | PO eResto {tgt['po_eresto']} "
                    f"| PO baru {cfg['po']} | PR {cfg.get('pr')}"),
        "items": [],
    }
    if cfg.get("tax"):
        payload["taxes_and_charges"] = "Purchase Tax - JURI"
        payload["taxes"] = [{"charge_type": "On Net Total",
                             "account_head": PPN_ACCOUNT,
                             "description": "PPN Masukan @ 11.0 - JURI",
                             "rate": 11.0, "cost_center": COST_CENTER}]
    else:
        payload["taxes"] = []
    for l in tgt["lines"]:
        if l["name"].upper().startswith("TIDAK AKTIF"):
            payload.setdefault("_skipped_lines", []).append(l["name"])
            continue
        item = SKU_ITEM.get(l["sku"])
        if not item:
            raise SystemExit(f"SKU {l['sku']} belum dipetakan")
        code, uom, cf = item
        rate = cfg.get("rate_override", {}).get(l["sku"], l["price"])
        row = {
            "item_code": code, "qty": l["qty"], "uom": uom,
            "conversion_factor": cf, "rate": rate,
            "warehouse": WH_MAP[tgt["division"]],
            "expense_account": ACCRUAL_ACCOUNT, "cost_center": COST_CENTER,
        }
        if cfg.get("po"):
            row["purchase_order"] = cfg["po"]
            po_detail = cfg.get("po_detail") or tgt.get("po_detail")
            if po_detail:
                row["po_detail"] = po_detail
        if cfg.get("pr"):
            row["purchase_receipt"] = cfg["pr"]
            if pr_rows.get(code):
                row["pr_detail"] = pr_rows[code]
        payload["items"].append(row)
    return payload


def create_pi(new, tgt, cfg, dry=False):
    pr = new.get("/api/resource/Purchase Invoice", {
        "filters": json.dumps([["bill_no", "=", tgt["inv_no"]],
                               ["docstatus", "<", 2]]),
        "fields": json.dumps(["name", "grand_total", "status", "docstatus"]),
        "limit_page_length": 3})
    rows = pr[1].get("data", []) if isinstance(pr[1], dict) else []
    if rows:
        return {"status": "SKIP_EXISTS", "pi": rows[0]["name"],
                "total": num(rows[0].get("grand_total")), "note": "sudah ada"}
    if dry:
        return {"status": "DRY-RUN"}
    pr_rows = fetch_pr_rows(new, cfg.get("pr"))
    payload = build_pi_payload(tgt, cfg, pr_rows)
    skipped_lines = payload.pop("_skipped_lines", [])
    st, d = new.post("Purchase Invoice", payload)
    if st != 200:
        return {"status": "GAGAL", "err": json.dumps(d)[:400],
                "skipped_lines": skipped_lines}
    pi_name = d["data"]["name"]
    st_s, ds = new.submit("Purchase Invoice", pi_name)
    return {"status": "OK" if st_s == 200 else "DRAFT-SUBMIT-GAGAL",
            "pi": pi_name, "total": num(d["data"].get("grand_total")),
            "submit_err": None if st_s == 200 else json.dumps(ds)[:200],
            "skipped_lines": skipped_lines}


# ---------------------------------------------------------------- report
def style(ws):
    fill = PatternFill("solid", fgColor="D9EAF7")
    for c in ws[1]:
        c.fill, c.font = fill, Font(bold=True)
        c.alignment = Alignment(horizontal="center", vertical="center",
                                wrap_text=True)
    ws.freeze_panes = "A2"
    try:
        ws.auto_filter.ref = ws.dimensions
    except Exception:
        pass


def write_report(targets, checks_old, checks_new, results, gbbk_rows, checks):
    wb = openpyxl.Workbook()
    s = wb.active
    s.title = "Rekap_Faktur"
    s.append(["inv_no", "tgl_faktur", "divisi", "supplier", "total_faktur",
              "po_eresto", "tgl_po", "status_lama", "doc_lama", "status_baru",
              "pi_baru", "aksi", "catatan"])
    for t in targets:
        oldc = checks_old[t["inv_no"]]["best"] or {}
        newc = checks_new[t["inv_no"]]
        res = results.get(t["inv_no"], {})
        cfg = TARGET_CFG.get(t["inv_no"], {})
        catatan = cfg.get("skip_reason") or cfg.get("note") or ""
        if cfg.get("skip_reason") and cfg.get("note"):
            catatan = f"{cfg['skip_reason']} | {cfg['note']}"
        s.append([t["inv_no"], t["inv_date"], t["division"], t["supplier"],
                  t["total"], t["po_eresto"], t["po_date"],
                  ("serupa: " + oldc.get("name", "-")) if oldc else "tidak ada",
                  oldc.get("name", ""),
                  res.get("status", "SKIP" if newc.get("pi") else "BELUM"),
                  (newc.get("pi") or {}).get("name", ""),
                  res.get("status", ""), catatan])

    s2 = wb.create_sheet("Cek_Lama_Line")
    s2.append(["inv_no", "doc_lama", "item_eResto", "qty", "unit", "price",
               "item_lama", "qty_lama", "unit_lama", "rate_lama",
               "name_ok", "qty_ok", "unit_ok", "rate_ok"])
    for t in targets:
        best = checks_old[t["inv_no"]]["best"]
        if not best:
            continue
        for m in best["matched"]:
            l = m["line"]; la = m.get("lama") or {}
            s2.append([t["inv_no"], best["name"], l["name"], l["qty"], l["unit"],
                       l["price"], la.get("item_name"), la.get("qty"),
                       la.get("uom"), la.get("rate"),
                       m.get("name_ok"), m.get("qty_ok"), m.get("unit_ok"),
                       m.get("rate_ok")])

    s3 = wb.create_sheet("Migrasi_PO_PR")
    s3.append(["invoice", "aksi", "detail"])
    for inv, res in results.items():
        if res.get("po_pr_log"):
            for line in res["po_pr_log"]:
                s3.append([inv, "PO/PR", line])

    s4 = wb.create_sheet("GBBK_Catatan")
    s4.append(["inv_no", "tgl", "divisi", "supplier", "total", "status_baru"])
    for r in gbbk_rows:
        s4.append(r)

    s5 = wb.create_sheet("Skipped")
    s5.append(["invoice", "item_dilewati", "alasan"])
    for inv, res in results.items():
        for ln in res.get("skipped_lines", []) or []:
            s5.append([inv, ln, "item eResto 'TIDAK AKTIF' (dipetakan ke item aktif bila ada)"])

    s6 = wb.create_sheet("Validation")
    s6.append(["check", "hasil", "status"])
    for c in checks:
        s6.append(list(c))

    for ws in (s, s2, s3, s4, s5, s6):
        style(ws)
    wb.save(REPORT)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default=None, help="hanya satu nomor INV")
    args = ap.parse_args()

    mig = load_env("/tmp/eresto_mig.env")
    prod = load_env("/tmp/eresto_prod.env")
    old = Client(OLD_BASE, mig["ERPNEXT_OLD_CLOUD_API_KEY"], "lama")
    new = Client(prod["ERPNEXT_URL"], prod["ERPNEXT_API_KEY"], "baru")

    targets = build_targets()
    print(f"[dump] {len(targets)} faktur target (divisi sentral, supplier eksternal, PO < Okt)")

    checks_old, checks_new, results = {}, {}, {}
    for t in targets:
        print(f"\n=== {t['inv_no']} | {t['supplier']} | Rp{t['total']:,.0f} | PO {t['po_eresto']}")
        c_old = check_old(old, t)
        checks_old[t["inv_no"]] = c_old
        best = c_old["best"]
        if best:
            print(f"    lama: {best['name']} ({best['posting_date']}, Rp{best['grand_total']:,.2f}) "
                  f"total_ok={best['total_ok']} qty_ok={best['qty_ok']} "
                  f"name_ok={best['name_ok']} rate_ok={best['rate_ok']}")
        else:
            print("    lama: tidak ada kandidat")

        cfg = TARGET_CFG.get(t["inv_no"])
        if not cfg:
            print("    [!] tidak ada cfg; skip")
            continue
        c_new = check_new(new, t, cfg)
        checks_new[t["inv_no"]] = c_new
        print(f"    baru: PI={c_new['pi'] and c_new['pi']['name']} "
              f"PR={c_new['pr'] and c_new['pr']['name']} "
              f"PO={c_new['po'] and c_new['po']['name']}")

        if cfg.get("skip_reason"):
            results[t["inv_no"]] = {"status": "SKIP_EXISTS",
                                    "pi": c_new["pi"] and c_new["pi"]["name"]}
            continue
        if args.only and t["inv_no"] != args.only:
            continue

        # migrasi PO/PR lama dulu bila perlu
        if cfg.get("migrate_old"):
            if not c_new.get("po") and not args.dry_run:
                r = migrate_po_pr(new, old, t, cfg)
                results[t["inv_no"]] = {"status": r["status"],
                                        "po_pr_log": r.get("log", [])}
                if r["status"] != "OK":
                    print(f"    [FAIL] migrasi PO/PR: {r}")
                    continue
                print("    " + " | ".join(r.get("log", [])))
            else:
                # sudah ada (dibuat run sebelumnya) -> catat keadaan live
                log = []
                if c_new.get("po"):
                    log.append(f"PO {cfg['po']} ada (status {c_new['po'].get('status')}, "
                               f"ds={c_new['po'].get('docstatus')})")
                if c_new.get("pr"):
                    log.append(f"PR {cfg['pr']} ada (status {c_new['pr'].get('status')}, "
                               f"ds={c_new['pr'].get('docstatus')})")
                results[t["inv_no"]] = {"po_pr_log": log}
        res = create_pi(new, t, cfg, dry=args.dry_run)
        res["po_pr_log"] = (results.get(t["inv_no"]) or {}).get("po_pr_log", [])
        results[t["inv_no"]] = res
        print(f"    aksi: {json.dumps(res)[:220]}")

    # GBBK catatan: faktur Okt divisi Gudang Bahan Baku dengan PO pre-Okt (bukan
    # scope user — divisi tidak diminta; status PI existing dicek live).
    gbbk_rows = []
    gbbk_map = {  # inv -> PI existing (dicek live); None = belum ada
        "INVGBBK.061026.003": "PI-JURI-261008002",
        "INVGBBK.061026.004": "PI-JURI-261008006",
        "INVGBBK.061026.002": "PI-JURI-261008005",
        "INVGBBK.081026.001": None,
    }
    invoices = json.load(open(os.path.join(DUMP, "invoices_okt.json")))
    details = json.load(open(os.path.join(DUMP, "po_details.json")))
    for inv in invoices:
        div = (inv.get("division") or {}).get("name") or ""
        if "bahan baku" not in div.lower():
            continue
        no = inv["transaction_number"]
        if no not in gbbk_map:
            continue
        po = details.get(inv.get("purchase_id")) or {}
        if not po or str(po.get("date", ""))[:10] >= "2026-10-01":
            continue
        pi_name = gbbk_map[no]
        note = "belum ada PI — kandidat (menunggu keputusan user)"
        if pi_name:
            st, d = new.get("/api/resource/Purchase Invoice/" + pi_name)
            if st == 200 and isinstance(d, dict) and d.get("data"):
                note = f"{pi_name} ds={d['data'].get('docstatus')} ({d['data'].get('status')})"
            else:
                note = f"{pi_name} tidak ditemukan"
        gbbk_rows.append([
            no, str(inv["transaction_date"])[:10], div,
            (inv.get("supplier") or {}).get("name"),
            num(inv.get("total_amount")), note,
        ])

    # checks
    checks = []
    n_ok = sum(1 for r in results.values() if r.get("status") in ("OK", "SKIP_EXISTS"))
    checks.append(("Target diproses", f"{n_ok}/{len(targets)}",
                   "LOLOS" if (n_ok == len(targets) or args.dry_run or args.only) else "CATATAN"))
    created = [inv for inv, r in results.items() if r.get("status") == "OK"]
    dries = [inv for inv, r in results.items() if r.get("status") == "DRY-RUN"]
    skipped = [inv for inv, r in results.items() if r.get("status") == "SKIP_EXISTS"]
    failed = [inv for inv, r in results.items()
              if r.get("status") not in ("OK", "SKIP_EXISTS", "DRY-RUN")]
    if dries:
        checks.append(("Dry-run (belum tulis)", f"{len(dries)}: {', '.join(dries)}", "CATATAN"))
        created = dries
    if created:
        checks.append(("PI dibuat run ini", f"{len(created)}: {', '.join(created)}",
                       "LOLOS" if not failed else "GAGAL"))
    checks.append(("PI sudah ada (skip)", f"{len(skipped)}: {', '.join(skipped)}", "CATATAN"))
    checks.append(("Gagal", f"{len(failed)}: {', '.join(failed)}", "LOLOS" if not failed else "GAGAL"))

    # verify totals: setiap target harus punya PI di baru dengan total = faktur eResto (≤Rp1)
    mism, verified = [], []
    for t in targets:
        inv = t["inv_no"]
        res = results.get(inv, {})
        pi_name = res.get("pi") or (checks_new.get(inv, {}).get("pi") or {}).get("name")
        if not pi_name:
            if not args.dry_run:
                mism.append(f"{inv}: belum ada PI")
            continue
        st, d = new.get("/api/resource/Purchase Invoice/" + pi_name)
        if st != 200 or not isinstance(d, dict) or not d.get("data"):
            mism.append(f"{inv}: PI {pi_name} tidak ditemukan")
            continue
        p = d["data"]
        diff = abs(num(p.get("grand_total")) - t["total"])
        verified.append(f"{inv}->{pi_name}")
        if diff > 1.0:
            mism.append(f"{inv}: ΔRp{diff:,.2f} ({num(p.get('grand_total')):,.2f} vs {t['total']:,.2f})")
    if not args.dry_run:
        checks.append(("Total PI = total faktur eResto (≤Rp1)",
                       f"{len(verified)} PI dicek" + ("; " + "; ".join(mism) if mism else "; semua klop"),
                       "LOLOS" if not mism else "GAGAL"))

    if not args.dry_run:
        write_report(targets, checks_old, checks_new, results, gbbk_rows, checks)
        json.dump(results, open(RESULT, "w"), default=str, indent=1)

    print("\n=== RINGKASAN ===")
    for c in checks:
        print(f"  {c[2]}: {c[0]} ({c[1]})")
    print(f"\nlaporan: {REPORT}" if not args.dry_run else "(dry-run: laporan tidak ditulis)")


if __name__ == "__main__":
    main()
