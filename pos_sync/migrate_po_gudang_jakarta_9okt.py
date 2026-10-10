#!/usr/bin/env python3
"""Tarikan PO eResto supplier 'Gudang Jakarta' -> ERPNext Baru (default 9 Okt 2026).

Konteks (lihat memori proyek `po-eresto-internal-gudang-mapping` + PROJECT_STATE):
- Supplier eResto 'Gudang Jakarta' = gudang milik PT. JUARA ROTI INDONESIA (JURI).
- Pemetaan internal gudang:
    * Company       = divisi outlet pemesan (nama di eResto `purchase.division.name`)
    * Supplier      = 'PT. JUARA ROTI INDONESIA'
    * set_warehouse = 'Stores - <ABBR>' (gudang penerimaan outlet)
    * set_from_warehouse = 'Gudang Jakarta - JURI' (source warehouse alur SO/DN JURI)
    * Buying Price List = 'Harga Outlet'
    * Beban baris = '4210.000 - HPP Pembelian - <ABBR>', Cost Center 'Main - <ABBR>'
- ID dokumen = nomor PO eResto (rename_doc). docstatus mengikuti status eResto:
  processing/completed -> submit (1); pending/rejected/dll -> draft (0).
- Idempoten: dokumen yang sudah ada (by name ATAU title 'ERESTO <PO>') di-skip.
- Baris dengan SKU tak termap / PO dengan charges-diskon tak terduga TIDAK
  ditebak: PO masuk sheet Skipped dengan alasan.

Preseden UOM (dipakai apa adanya, bukan tebakan):
- PEL260070 (Gelas 14 oz): eResto 'Pack' = master Pack (cf 150), rate per Pack.
- PEL260071 (Gelas Cup 9 oz): eResto 'Pack' TIDAK ada di master -> 1 Pack = 1
  slop = 50 Pcs (preseden PO120.051026.001 dsb. di site baru, rate 55.000/slop
  = Item Price 1.100/Pcs).
- Sisanya: UOM dicocokkan langsung ke master Item (uoms child); kg->kg cf 1000,
  Pack->Pack sesuai master, Pcs->Pcs.

CLI:
  python pos_sync/migrate_po_gudang_jakarta_9okt.py [--date 2026-10-09]
      [--dry-run] [--only PO138.091026.001 ...] [--no-older-audit]

Env: /tmp/eresto_mig.env (ERESTO_*) + /tmp/eresto_prod.env (ERPNEXT_URL,
ERPNEXT_API_KEY). Token tidak pernah ditulis ke output.
"""
import os
import sys
import json
import time
import argparse
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ============================================================
# ENV & KONSTANTA
# ============================================================

def load_env_file(filepath):
    env_vars = {}
    if os.path.exists(filepath):
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env_vars[k.strip()] = v.strip().strip('"').strip("'")
    return env_vars

ENV_MIG = load_env_file("/tmp/eresto_mig.env")
ENV_PROD = load_env_file("/tmp/eresto_prod.env")

ERESTO_BASE_URL = "https://ropi.eresto.id"
ERESTO_DOMAIN   = "ropi"
ERESTO_TOKEN    = os.environ.get("ERESTO_TOKEN") or ENV_MIG.get("ERESTO_TOKEN", "")
ERESTO_EMAIL    = os.environ.get("ERESTO_EMAIL") or ENV_MIG.get("ERESTO_EMAIL", "")
ERESTO_USER_ID  = os.environ.get("ERESTO_USER_ID") or ENV_MIG.get("ERESTO_USER_ID", "")

ERPNEXT_URL     = os.environ.get("ERPNEXT_URL") or ENV_PROD.get("ERPNEXT_URL", "https://ropierpnext.frappe.cloud")
ERPNEXT_KEY     = os.environ.get("ERPNEXT_API_KEY") or ENV_PROD.get("ERPNEXT_API_KEY", "")

JURI_COMPANY     = "PT. JUARA ROTI INDONESIA"
SUPPLIER_ERESTO  = "Gudang Jakarta"
SOURCE_WH        = "Gudang Jakarta - JURI"
PRICE_LIST       = "Harga Outlet"
REPORT_PATH      = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "Laporan_Migrasi_PO_Gudang_Jakarta_9Okt2026.xlsx")

# Mapping SKU eResto -> Item Code ERPNext Baru.
# Basis = migrasi PO eResto 8-9 Okt (pos_sync/migrate_po_eresto_8_9_okt.py),
# +6 SKU baru yang muncul di PO Gudang Jakarta 9 Okt (dari stok mapping:
# experiments/build_stok_mapping.py & inject_reco_*.py).
ITEM_MAP = {
    "BB0046": "PJ260012",  # Dough Ropi Butter
    "BB0047": "PJ260013",  # Dough Ropi Coklat
    "BB0049": "PJ260014",  # Dough Ropi Keju
    "BB0066": "PEL260072", # Goodie Bag
    "BB0071": "BB260039",  # Gula Stik
    "BB0081": "BB260040",  # Keju Chedar
    "BB0085": "PJ260016",  # Krim Kopi
    "BB0102": "BB260043",  # Olesan Choco Crunchy (1 kg)
    "BB0103": "BB260044",  # Olesan Dark Choco (1 kg)      [BARU 9 Okt]
    "BB0105": "BB260045",  # Olesan Margarine
    "BB0110": "BB260047",  # Olesan Tiramisu (1 kg)
    "BB0112": "PEL260076", # Paper Bag Ropi
    "BB0117": "PEL260077", # Plastik Alas Gempi
    "BB0118": "PEL260081", # Plastik Kresek Kecil (17)
    "BB0119": "PEL260080", # Plastik Kresek Besar (24)
    "BB0120": "BB260019",  # Plastik Krim                  [BARU 9 Okt]
    "BB0122": "PEL260083", # Plastik Seal Ropi
    "BB0132": "BHP260027", # Sarung Tangan Plastik
    "BB0134": "PEL260084", # Sedotan
    "BB0143": "PEL260085", # Stirrer                       [BARU 9 Okt]
    "BB0168": "PJ260010",  # Dough Croissant
    "BB0171": "PEL260069", # Box Gempi (100 pcs)
    "BB0174": "BB260046",  # TIDAK AKTIF Olesan Pastry -> Olesan Pastry
    "BB0191": "PEL260075", # Kertas Thermal
    "BB0257": "PEL260071", # Gelas Cup 9 Oz (isi 50 pcs)   [BARU 9 Okt]
    "BB0261": "PJ260011",  # Dough Gempi
    "BB0296": "PEL260078", # Plastik Kresek 1 Cup
    "BB0297": "PEL260079", # Plastik Kresek 2 Cup
    "BB0298": "PEL260070", # Gelas (14 oz) (50 pcs)
    "BB0304": "BB260037",  # Bubuk Susu Jahe                [BARU 9 Okt]
    "BB0305": "BB260038",  # Gula Cair Sachet               [BARU 9 Okt]
    "BB0312": "PJ260009",  # Air Mineral Outlet 600 ml      [BARU 9 Okt, PO140.091026.002]
    "BB0329": "BB260030",  # Jasmine Green Tea (750 g)
    "BB0340": "BB260031",  # Coffee Latte (500 g)
    "BB0341": "BB260032",  # Coffee Classic (120 g)
    "BB0342": "BB260033",  # Dark Cocoa Drink (1 kg)
}

# Aturan UOM khusus yang tidak bisa dicocokkan langsung ke master Item.
# (item_code, uom_eresto) -> (uom_erpnext, conversion_factor, catatan)
UOM_SPECIAL = {
    ("PEL260071", "Pack"): (
        "slop", 50.0,
        "Gelas Cup 9 oz: 1 Pack eResto = 1 slop = 50 Pcs "
        "(preseden PO120.051026.001 / rate 55.000 = Item Price 1.100/Pcs × 50)",
    ),
}

# ============================================================
# KLIEN
# ============================================================

def safe_float(v):
    try:
        if v is None or v == "":
            return 0.0
        if isinstance(v, str):
            return float(v.strip().replace(",", "."))
        return float(v)
    except Exception:
        return 0.0

def safe_str(v):
    return "" if v is None else str(v).strip()


class ErestoClient:
    def __init__(self, base_url, token, email, user_id):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.email = email
        self.user_id = user_id
        self.session = requests.Session()
        self.session.headers.update({
            "accept": "application/json, text/plain, */*",
            "authorization": f"Token token={self.token}, email={self.email}",
            "referer": f"{self.base_url}/manager/v2/index.html",
        })

    def _fetch_paged(self, window):
        out = {}
        page = 1
        while True:
            params = dict(window)
            params.update({"current_user_id": self.user_id, "domain": ERESTO_DOMAIN,
                           "token": self.token, "per_page": 200, "page": page})
            res = self.session.get(f"{self.base_url}/v2/purchases", params=params, timeout=60)
            if res.status_code != 200:
                raise SystemExit(f"[eResto] GET /v2/purchases HTTP {res.status_code}: {res.text[:200]}")
            rows = res.json().get("purchases", [])
            for p in rows:
                out[p["id"]] = p
            if len(rows) < 200:
                break
            page += 1
        return out

    def fetch_purchases(self, date_from, date_to):
        """Union window date[] dan created_at[] (PO backdate / input beda hari)."""
        results = self._fetch_paged({"date[geq]": date_from, "date[leq]": date_to})
        results.update(self._fetch_paged({
            "created_at[geq]": f"{date_from}T00:00:00",
            "created_at[leq]": f"{date_to}T23:59:59",
        }))
        return list(results.values())

    def fetch_purchase_detail(self, purchase_id):
        params = {"domain": ERESTO_DOMAIN, "token": self.token}
        res = self.session.get(f"{self.base_url}/v2/purchases/{purchase_id}/detail",
                               params=params, timeout=60)
        if res.status_code == 200:
            return res.json().get("purchase_detail", {})
        return {}


class ERPNextClient:
    def __init__(self, base_url, api_key):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"token {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    def _get_all(self, doctype, fields, page_size=500):
        out = []
        offset = 0
        while True:
            res = self.session.get(
                f"{self.base_url}/api/resource/{doctype}",
                params={"fields": json.dumps(fields),
                        "limit_page_length": page_size, "limit_start": offset},
                timeout=60)
            if res.status_code != 200:
                raise SystemExit(f"[ERPNext] GET {doctype} HTTP {res.status_code}: {res.text[:200]}")
            rows = res.json().get("data", [])
            out.extend(rows)
            if len(rows) < page_size:
                break
            offset += page_size
        return out

    def get_existing_po_index(self):
        """{name: row} + alias title 'ERESTO <PO>' -> row."""
        index = {}
        for row in self._get_all("Purchase Order", ["name", "title", "docstatus", "grand_total", "status"]):
            index[row["name"]] = row
            title = row.get("title") or ""
            if title.startswith("ERESTO "):
                index[title.replace("ERESTO ", "").strip()] = row
        return index

    def get_companies_and_abbrs(self):
        return {c["name"]: c["abbr"]
                for c in self._get_all("Company", ["name", "abbr"])}

    def get_supplier_companies(self, supplier):
        res = self.session.get(f"{self.base_url}/api/resource/Supplier/{supplier.replace(' ', '%20')}",
                               timeout=60)
        if res.status_code != 200:
            return set()
        return {x.get("company") for x in (res.json().get("data", {}).get("companies") or [])}

    def get_item_master(self, code):
        res = self.session.get(f"{self.base_url}/api/resource/Item/{code}", timeout=60)
        if res.status_code != 200:
            return None
        d = res.json().get("data", {})
        return {
            "name": d.get("name"),
            "item_name": d.get("item_name"),
            "stock_uom": d.get("stock_uom"),
            "disabled": bool(d.get("disabled")),
            "uoms": {u["uom"]: float(u["conversion_factor"]) for u in d.get("uoms", [])},
        }

    def get_items_master(self, codes):
        out = {}
        with ThreadPoolExecutor(max_workers=5) as ex:
            futs = {ex.submit(self.get_item_master, c): c for c in sorted(set(codes))}
            for fu in as_completed(futs):
                out[futs[fu]] = fu.result()
        return out

    def doc_exists(self, doctype, name):
        res = self.session.get(f"{self.base_url}/api/resource/{doctype}/{name.replace(' ', '%20')}",
                               timeout=60)
        return res.status_code == 200

    def create_po(self, payload):
        res = self.session.post(f"{self.base_url}/api/resource/Purchase Order",
                                json=payload, timeout=60)
        try:
            body = res.json()
        except Exception:
            body = {"raw": res.text[:300]}
        return res.status_code, body

    def rename_doc(self, old_name, new_name):
        # Jebakan: frappe.client.rename_doc wajib FORM-encoded; session ini
        # default Content-Type JSON -> server balas 417 'Invalid request body'.
        res = self.session.post(
            f"{self.base_url}/api/method/frappe.client.rename_doc",
            data={"doctype": "Purchase Order", "old_name": old_name,
                  "new_name": new_name, "merge": 0},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=90)
        return res.status_code, res.text

    def submit_doc(self, name):
        res = self.session.put(f"{self.base_url}/api/resource/Purchase Order/{name}",
                               json={"docstatus": 1}, timeout=60)
        try:
            body = res.json()
        except Exception:
            body = {"raw": res.text[:300]}
        return res.status_code, body

    def get_po(self, name):
        res = self.session.get(f"{self.base_url}/api/resource/Purchase Order/{name}",
                               timeout=60)
        if res.status_code != 200:
            return None
        return res.json().get("data", {})

# ============================================================
# RESOLUSI UOM
# ============================================================

def resolve_uom(code, unit, master):
    """Kembalikan (uom, conversion_factor, catatan). Tidak pernah menebak
    diam-diam: fallback apa pun selalu dicatat di `catatan`."""
    su = master["stock_uom"]
    uoms = master["uoms"]
    unit = {"Kg": "kg", "KG": "kg"}.get(unit, unit)

    if unit == su:
        return unit, uoms.get(su, 1.0), ""
    if unit in uoms:
        return unit, uoms[unit], ""

    special = UOM_SPECIAL.get((code, unit))
    if special:
        return special[0], special[1], special[2]

    # Artefak historis (cf sumber == 1.0, mis. 'Pack' utk item Pcs) dibalikkan
    # ke stock_uom — pola sama dengan aturan fallback migrate_outlet_po_to_juri.
    return su, uoms.get(su, 1.0), f"UOM '{unit}' tidak ada di master -> fallback {su} cf=1"

# ============================================================
# VERIFY MODE — laporan final dari kondisi live (tanpa POST)
# ============================================================

def run_verify(args):
    """Bandingkan eResto vs ERPNext BARU untuk seluruh PO Gudang Jakarta
    pada tanggal target dan tulis laporan final (Rekap/Raw/Cross_Check/
    Validation/Catatan). Tidak menulis apa pun ke ERPNext."""
    eresto = ErestoClient(ERESTO_BASE_URL, ERESTO_TOKEN, ERESTO_EMAIL, ERESTO_USER_ID)
    erp = ERPNextClient(ERPNEXT_URL, ERPNEXT_KEY)

    print("=" * 84)
    print(f"  VERIFIKASI PO eResto 'Gudang Jakarta' {args.date} vs ERPNext BARU")
    print("=" * 84)

    raw_pos = eresto.fetch_purchases(args.date, args.date)
    target_pos = [p for p in raw_pos
                  if safe_str((p.get("supplier") or {}).get("name")) == SUPPLIER_ERESTO]
    if args.only:
        target_pos = [p for p in target_pos if p.get("purchase_number") in set(args.only)]

    details = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(eresto.fetch_purchase_detail, p["id"]): p for p in target_pos}
        for fu in as_completed(futs):
            d = fu.result()
            if d:
                details.append(d)
    details.sort(key=lambda x: safe_str(x.get("purchase_number")))
    print(f"  {len(details)} PO sumber eResto.")

    items_master = erp.get_items_master(ITEM_MAP.values())

    rekap, raw_rows, cross_rows, issues = [], [], [], []
    for d in details:
        pnum = safe_str(d.get("purchase_number"))
        pdate = safe_str(d.get("date"))[:10]
        company = safe_str((d.get("division") or {}).get("name"))
        st_eresto = safe_str(d.get("status"))
        e_total = safe_float(d.get("total_cost"))
        e_lines = len(d.get("purchase_items") or [])

        doc = erp.get_po(pnum)
        if not doc:
            issues.append(f"{pnum}: TIDAK ADA di ERPNext BARU")
            rekap.append({"PO Number": pnum, "ERPNext ID": "-", "Tanggal": pdate,
                          "Company": company, "Total eResto": e_total,
                          "Grand Total ERPNext": "", "Selisih": "",
                          "Baris eResto": e_lines, "Baris ERPNext": "",
                          "Docstatus": "", "Status eResto": st_eresto,
                          "Hasil": "TIDAK ADA"})
            continue

        g_total = safe_float(doc.get("grand_total"))
        diff = abs(g_total - e_total)
        n_erp = len(doc.get("items", []))
        expected_ds = 1 if st_eresto in ("processing", "completed") else 0
        ds_ok = doc.get("docstatus") == expected_ds
        lines_ok = all(
            abs(safe_float(x.get("qty")) * safe_float(x.get("rate"))
                - safe_float(x.get("amount"))) < 0.01
            and abs(safe_float(x.get("stock_qty"))
                    - safe_float(x.get("qty")) * safe_float(x.get("conversion_factor"))) < 1e-6
            for x in doc.get("items", []))
        ok = diff <= 1 and n_erp == e_lines and ds_ok and lines_ok
        if not ok:
            issues.append(f"{pnum}: diff={diff} baris {n_erp}/{e_lines} ds={doc.get('docstatus')} "
                          f"(harus {expected_ds}) lines_ok={lines_ok}")
        rekap.append({"PO Number": pnum, "ERPNext ID": doc.get("name"), "Tanggal": pdate,
                      "Company": company, "Total eResto": e_total,
                      "Grand Total ERPNext": g_total, "Selisih": diff,
                      "Baris eResto": e_lines, "Baris ERPNext": n_erp,
                      "Docstatus": doc.get("docstatus"), "Status eResto": st_eresto,
                      "Status ERPNext": doc.get("status"),
                      "Hasil": "LOLOS" if ok else "CEK"})
        cross_rows.append({
            "PO Number": pnum, "Cek Total": "OK" if diff <= 1 else "BEDA",
            "Cek Baris": "OK" if n_erp == e_lines else "BEDA",
            "Cek Docstatus": "OK" if ds_ok else "BEDA",
            "Cek Baris qty×rate & stock_qty": "OK" if lines_ok else "BEDA",
        })

        for it in d.get("purchase_items") or []:
            inv = it.get("inventory") or {}
            sku = safe_str(inv.get("sku"))
            code = ITEM_MAP.get(sku, "")
            master = items_master.get(code) or {}
            unit = safe_str((it.get("unit") or {}).get("name"))
            uom, cf, note = ("", "", "")
            if master:
                uom, cf, note = resolve_uom(code, unit, master)
            raw_rows.append({
                "PO Number": pnum, "Tanggal": pdate, "Company (Divisi)": company,
                "SKU": sku, "Nama eResto": safe_str(inv.get("name")),
                "Qty eResto": safe_float(it.get("amount")), "Unit eResto": unit,
                "Harga eResto": safe_float(it.get("price")), "Total eResto": safe_float(it.get("total_price")),
                "Item Code": code, "Item Name": master.get("item_name", ""),
                "UOM ERPNext": uom, "CF": cf, "Catatan UOM": note,
                "Status eResto": st_eresto,
            })

    # audit PO Gudang Jakarta lama yang belum ada (kecuali diminta skip)
    older_missing = []
    if not args.no_older_audit and not args.only:
        existing = erp.get_existing_po_index()
        prev = eresto.fetch_purchases("2026-10-01", args.date)
        for p in sorted([x for x in prev
                         if safe_str((x.get("supplier") or {}).get("name")) == SUPPLIER_ERESTO
                         and safe_str(x.get("date"))[:10] < args.date],
                        key=lambda x: safe_str(x.get("purchase_number"))):
            pn = safe_str(p.get("purchase_number"))
            if pn not in existing:
                older_missing.append({
                    "PO Number": pn, "Tanggal": safe_str(p.get("date"))[:10],
                    "Divisi": safe_str((p.get("division") or {}).get("name")),
                    "Total": safe_float(p.get("total_cost")),
                    "Status eResto": safe_str(p.get("status"))})

    # ---------- tulis laporan ----------
    wb = Workbook()
    header_fill = PatternFill(start_color="D9EAF7", end_color="D9EAF7", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True)
    center_align = Alignment(horizontal="center", vertical="center")
    thin_border = Border(left=Side(style="thin", color="D3D3D3"),
                         right=Side(style="thin", color="D3D3D3"),
                         top=Side(style="thin", color="D3D3D3"),
                         bottom=Side(style="thin", color="D3D3D3"))

    def write_sheet(ws, title, rows, columns):
        ws.title = title
        ws.append(columns)
        for r in rows:
            ws.append([r.get(c, "") for c in columns])
        ws.freeze_panes = "A2"
        for col_idx in range(1, ws.max_column + 1):
            c = ws.cell(row=1, column=col_idx)
            c.fill = header_fill
            c.font = header_font
            c.alignment = center_align
        for row in ws.iter_rows(min_row=2, max_row=ws.max_row,
                                min_col=1, max_col=ws.max_column):
            for c in row:
                c.border = thin_border
        for col in ws.columns:
            ml = max(len(str(c.value or "")) for c in col)
            ws.column_dimensions[get_column_letter(col[0].column)].width = max(ml + 3, 12)

    rekap_cols = ["PO Number", "ERPNext ID", "Tanggal", "Company", "Total eResto",
                  "Grand Total ERPNext", "Selisih", "Baris eResto", "Baris ERPNext",
                  "Docstatus", "Status eResto", "Status ERPNext", "Hasil"]
    raw_cols = ["PO Number", "Tanggal", "Company (Divisi)", "SKU", "Nama eResto",
                "Qty eResto", "Unit eResto", "Harga eResto", "Total eResto",
                "Item Code", "Item Name", "UOM ERPNext", "CF", "Catatan UOM",
                "Status eResto"]
    cross_cols = ["PO Number", "Cek Total", "Cek Baris", "Cek Docstatus",
                  "Cek Baris qty×rate & stock_qty"]

    ws = wb.active
    write_sheet(ws, "Rekap_Migrasi", rekap, rekap_cols)
    write_sheet(wb.create_sheet(), "Raw_eResto", raw_rows, raw_cols)
    write_sheet(wb.create_sheet(), "Cross_Check", cross_rows, cross_cols)

    total_e = sum(r["Total eResto"] for r in rekap if r["Hasil"] in ("LOLOS", "CEK"))
    total_g = sum(safe_float(r.get("Grand Total ERPNext")) for r in rekap
                  if r["Hasil"] in ("LOLOS", "CEK"))
    val_rows = [
        {"Parameter": "PO sumber eResto", "Nilai": len(details), "Status": "OK",
         "Keterangan": f"supplier '{SUPPLIER_ERESTO}' tanggal {args.date}"},
        {"Parameter": "PO ada di ERPNext BARU", "Nilai": sum(1 for r in rekap if r["Hasil"] != "TIDAK ADA"),
         "Status": "LOLOS" if not any(r["Hasil"] == "TIDAK ADA" for r in rekap) else "CEK",
         "Keterangan": "0 hilang"},
        {"Parameter": "Cocok penuh (nilai, baris, docstatus, line math)",
         "Nilai": sum(1 for r in rekap if r["Hasil"] == "LOLOS"),
         "Status": "LOLOS" if not issues else "CEK",
         "Keterangan": "; ".join(issues) if issues else "semua klop"},
        {"Parameter": "Total nilai eResto vs ERPNext",
         "Nilai": f"{total_e:,.0f} vs {total_g:,.0f}",
         "Status": "LOLOS" if abs(total_e - total_g) <= 1 else "CEK",
         "Keterangan": "toleransi ≤ Rp1"},
    ]
    write_sheet(wb.create_sheet(), "Validation", val_rows,
                ["Parameter", "Nilai", "Status", "Keterangan"])

    note_rows = [
        {"Topik": "Scope",
         "Catatan": f"PO eResto supplier 'Gudang Jakarta' tanggal {args.date}; source warehouse "
                    f"'{SOURCE_WH}'; ID dokumen = nomor PO eResto; status processing/completed -> submit, "
                    f"lainnya -> draft. Data hari berjalan bisa bertambah — rerun script = aman (idempoten)."},
        {"Topik": "Temuan PO084.081026.001 (di luar scope)",
         "Catatan": "Di BARU tercatat 3 Pack cf=50 @190.000 (edit manual 2026-10-09 08:31), "
                    "sedangkan sumber eResto saat ini 5 Pack cf=150 @114.000 (total sama Rp570.000). "
                    "Menunggu keputusan user — tidak disentuh script ini."},
    ]
    for om in older_missing:
        note_rows.append({"Topik": f"Belum ada di BARU: {om['PO Number']}",
                          "Catatan": f"tanggal {om['Tanggal']} | divisi {om['Divisi']} | "
                                     f"Rp {om['Total']:,.0f} | status eResto {om['Status eResto']} "
                                     f"(di luar scope tanggal; menunggu keputusan)"})
    write_sheet(wb.create_sheet(), "Catatan", note_rows, ["Topik", "Catatan"])

    wb.save(REPORT_PATH)
    print(f"  Laporan: {REPORT_PATH}")
    print("=" * 84)
    print(f"  LOLOS: {sum(1 for r in rekap if r['Hasil'] == 'LOLOS')}/{len(rekap)} | "
          f"Issues: {issues if issues else 'tidak ada'}")
    print(f"  Total eResto: Rp {total_e:,.0f} | Total ERPNext: Rp {total_g:,.0f}")
    if older_missing:
        print(f"  CATATAN: {len(older_missing)} PO Gudang Jakarta sebelum {args.date} belum ada di BARU.")
    print("=" * 84)


# ============================================================
# ALUR UTAMA
# ============================================================

def run():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default="2026-10-09", help="tanggal PO eResto (YYYY-MM-DD)")
    ap.add_argument("--dry-run", action="store_true", help="hanya rencana, tanpa POST")
    ap.add_argument("--verify", action="store_true",
                    help="mode verifikasi: laporan final dari kondisi live (read-only)")
    ap.add_argument("--only", nargs="*", default=None, help="batasi ke nomor PO tertentu")
    ap.add_argument("--no-older-audit", action="store_true",
                    help="lewati audit PO Gudang Jakarta < tanggal target yang belum ada")
    args = ap.parse_args()

    if args.verify:
        run_verify(args)
        return

    date_from = date_to = args.date

    print("=" * 84)
    print(f"  MIGRASI PO eResto 'Gudang Jakarta' -> ERPNext BARU")
    print(f"  Tanggal: {args.date} | Target: {ERPNEXT_URL}")
    print("=" * 84)

    eresto = ErestoClient(ERESTO_BASE_URL, ERESTO_TOKEN, ERESTO_EMAIL, ERESTO_USER_ID)
    erp = ERPNextClient(ERPNEXT_URL, ERPNEXT_KEY)

    # ------------------------------------------------------------
    print(f"\n[1/5] Tarik list PO eResto tanggal {args.date} ...")
    raw_pos = eresto.fetch_purchases(date_from, date_to)
    target_pos = [p for p in raw_pos
                  if safe_str((p.get("supplier") or {}).get("name")) == SUPPLIER_ERESTO]
    if args.only:
        target_pos = [p for p in target_pos if p.get("purchase_number") in set(args.only)]
    print(f"  {len(raw_pos)} PO eResto di jendela; {len(target_pos)} PO supplier '{SUPPLIER_ERESTO}'.")

    print("[2/5] Ambil detail PO ...")
    details = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(eresto.fetch_purchase_detail, p["id"]): p for p in target_pos}
        for fu in as_completed(futs):
            d = fu.result()
            if d:
                details.append(d)
    details.sort(key=lambda x: safe_str(x.get("purchase_number")))
    print(f"  {len(details)} detail berhasil diambil.")

    # ------------------------------------------------------------
    print("[3/5] Ambil master ERPNext (PO existing, company, supplier, item) ...")
    existing = erp.get_existing_po_index()
    abbrs = erp.get_companies_and_abbrs()
    supplier_companies = erp.get_supplier_companies(JURI_COMPANY)

    all_codes = set()
    for d in details:
        for it in d.get("purchase_items") or []:
            code = ITEM_MAP.get(safe_str((it.get("inventory") or {}).get("sku")))
            if code:
                all_codes.add(code)
    items_master = erp.get_items_master(all_codes)
    print(f"  {len(existing)} PO existing | {len(abbrs)} company | "
          f"{len(supplier_companies)} company diizinkan supplier JURI | "
          f"{len(items_master)} item master.")

    # ------------------------------------------------------------
    print("[4/5] Migrasi ...")
    migrated, skipped, raw_rows = [], [], []

    for d in details:
        pnum = safe_str(d.get("purchase_number"))
        pdate = safe_str(d.get("date"))[:10]
        company = safe_str((d.get("division") or {}).get("name"))
        st_eresto = safe_str(d.get("status"))
        total_cost = safe_float(d.get("total_cost"))
        items = d.get("purchase_items") or []
        charges = d.get("purchase_charges") or []
        discounts = d.get("purchase_discounts") or []

        base_rec = {"PO Number": pnum, "Tanggal": pdate, "Company": company,
                    "Total eResto": total_cost, "Status eResto": st_eresto}

        # -- guard: charges/diskon tidak terduga (jangan tebak) --
        if charges or discounts:
            skipped.append({**base_rec, "Kategori": "Charges/Diskon",
                            "Alasan": f"PO punya {len(charges)} charges & {len(discounts)} discounts; "
                                      "butuh pemetaan manual (tidak ditebak)"})
            continue

        # -- idempotensi --
        if pnum in existing:
            rec = existing[pnum]
            actual_name = rec.get("name")
            rename_note = ""
            # self-heal: dokumen ada tapi namanya masih fallback (rename
            # sebelumnya gagal, mis. karena 417 form-vs-json) -> perbaiki.
            if actual_name != pnum and not args.dry_run:
                st_ren, body = erp.rename_doc(actual_name, pnum)
                if st_ren == 200:
                    print(f"  [REPAIR] {pnum}: rename {actual_name} -> {pnum}")
                    rename_note = f"repair rename {actual_name} -> {pnum}"
                    actual_name = pnum
                    rec = erp.get_po(pnum) or rec
                else:
                    rename_note = f"rename masih gagal: {body[:120]}"
            print(f"  [SKIP_EXISTS] {pnum} -> {actual_name} (ds={rec.get('docstatus')})")
            migrated.append({**base_rec, "ERPNext ID": actual_name,
                             "Company": company, "Supplier": JURI_COMPANY,
                             "Target WH": "", "Source WH": SOURCE_WH,
                             "Jumlah Baris": "", "Grand Total ERPNext": rec.get("grand_total"),
                             "Docstatus": rec.get("docstatus"), "Status ERPNext": rec.get("status"),
                             "Hasil": "SKIP_EXISTS",
                             "Catatan": rename_note or "sudah ada (rerun aman)"})
            continue

        # -- guard: company/prasyarat --
        problems = []
        if company not in abbrs:
            problems.append(f"Company '{company}' belum ada")
        if company not in supplier_companies:
            problems.append("Company belum diizinkan di supplier JURI")
        abbr = abbrs.get(company)
        if abbr:
            for dt, nm in (("Warehouse", f"Stores - {abbr}"),
                           ("Account", f"4210.000 - HPP Pembelian - {abbr}"),
                           ("Cost Center", f"Main - {abbr}")):
                if not erp.doc_exists(dt, nm):
                    problems.append(f"{dt} '{nm}' tidak ada")
        if problems:
            skipped.append({**base_rec, "Kategori": "Prasyarat",
                            "Alasan": "; ".join(problems)})
            continue

        # -- susun baris item --
        rows_payload, row_audit, row_problems = [], [], []
        for it in items:
            inv = it.get("inventory") or {}
            sku = safe_str(inv.get("sku"))
            qty = safe_float(it.get("amount"))
            price = safe_float(it.get("price"))
            unit = safe_str((it.get("unit") or {}).get("name"))

            code = ITEM_MAP.get(sku)
            if not code:
                row_problems.append(f"SKU {sku} belum ada mapping")
                continue
            master = items_master.get(code)
            if not master:
                row_problems.append(f"Item {code} tidak ada di master")
                continue
            if master.get("disabled"):
                row_problems.append(f"Item {code} disabled")
                continue

            uom, cf, note = resolve_uom(code, unit, master)
            if qty <= 0:
                row_problems.append(f"SKU {sku} qty {qty} (skip baris)")
                continue

            rows_payload.append({
                "item_code": code, "qty": qty, "uom": uom, "conversion_factor": cf,
                "rate": price, "warehouse": f"Stores - {abbr}",
                "expense_account": f"4210.000 - HPP Pembelian - {abbr}",
                "cost_center": f"Main - {abbr}",
                "schedule_date": pdate,
            })
            row_audit.append({
                "PO Number": pnum, "Tanggal": pdate, "Company (Divisi)": company,
                "SKU": sku, "Nama eResto": safe_str(inv.get("name")),
                "Qty eResto": qty, "Unit eResto": unit, "Harga eResto": price,
                "Item Code": code, "Item Name": master.get("item_name"),
                "UOM ERPNext": uom, "CF": cf, "Stock Qty": qty * cf, "Rate": price,
                "Amount": round(qty * price, 2), "Catatan UOM": note,
                "Status eResto": st_eresto,
            })

        if row_problems or not rows_payload:
            skipped.append({**base_rec, "Kategori": "Item",
                            "Alasan": "; ".join(row_problems) or "tidak ada baris valid"})
            continue

        raw_rows.extend(row_audit)

        expected_ds = 1 if st_eresto in ("processing", "completed") else 0
        payload = {
            "doctype": "Purchase Order",
            "company": company,
            "supplier": JURI_COMPANY,
            "transaction_date": pdate,
            "schedule_date": pdate,
            "set_warehouse": f"Stores - {abbr}",
            "set_from_warehouse": SOURCE_WH,
            "buying_price_list": PRICE_LIST,
            "currency": "IDR",
            "title": f"ERESTO {pnum}",
            "items": rows_payload,
        }

        if args.dry_run:
            print(f"  [DRY-RUN] {pnum} -> {company} ({len(rows_payload)} baris, "
                  f"status eResto {st_eresto}, target ds={expected_ds})")
            migrated.append({**base_rec, "ERPNext ID": "(dry-run)", "Supplier": JURI_COMPANY,
                             "Target WH": f"Stores - {abbr}", "Source WH": SOURCE_WH,
                             "Jumlah Baris": len(rows_payload), "Grand Total ERPNext": "",
                             "Docstatus": "", "Status ERPNext": "", "Hasil": "DRY_RUN",
                             "Catatan": ""})
            continue

        # -- POST + rename + submit --
        print(f"  [POST] {pnum} -> {company} ({len(rows_payload)} baris) ...")
        st, res = erp.create_po(payload)
        if st != 200:
            msg = json.dumps(res)[:300]
            print(f"    [GAGAL] {pnum}: {msg}")
            migrated.append({**base_rec, "ERPNext ID": "", "Supplier": JURI_COMPANY,
                             "Target WH": f"Stores - {abbr}", "Source WH": SOURCE_WH,
                             "Jumlah Baris": len(rows_payload), "Grand Total ERPNext": "",
                             "Docstatus": 0, "Status ERPNext": "GAGAL",
                             "Hasil": "FAIL_POST", "Catatan": msg})
            continue

        temp_name = res.get("data", {}).get("name")
        final_name, rename_note = temp_name, ""
        st_ren, _ = erp.rename_doc(temp_name, pnum)
        if st_ren == 200:
            final_name = pnum
        else:
            rename_note = f"rename gagal -> tetap '{temp_name}'"

        docstatus_final, status_final = 0, "Draft"
        if expected_ds == 1:
            st_sub, res_sub = erp.submit_doc(final_name)
            if st_sub == 200:
                docstatus_final = 1
                status_final = res_sub.get("data", {}).get("status", "Submitted")
            else:
                rename_note = (rename_note + " | " if rename_note else "") + \
                              f"submit gagal: {json.dumps(res_sub)[:120]}"

        rec = erp.get_po(final_name) or {}
        print(f"    [OK] {final_name} | ds={docstatus_final} | {status_final} | "
              f"Rp {rec.get('grand_total', '?')}")
        migrated.append({**base_rec, "ERPNext ID": final_name, "Supplier": JURI_COMPANY,
                         "Target WH": f"Stores - {abbr}", "Source WH": SOURCE_WH,
                         "Jumlah Baris": len(rows_payload),
                         "Grand Total ERPNext": rec.get("grand_total", ""),
                         "Docstatus": docstatus_final, "Status ERPNext": status_final,
                         "Hasil": "BERHASIL", "Catatan": rename_note})
        time.sleep(0.2)

    # ------------------------------------------------------------
    print("[5/5] Verifikasi & laporan ...")
    ver_rows, verify_issues = [], []
    if not args.dry_run:
        for m in migrated:
            if m["Hasil"] not in ("BERHASIL", "SKIP_EXISTS"):
                continue
            rec = erp.get_po(m["ERPNext ID"])
            if not rec:
                verify_issues.append(f"{m['PO Number']}: dokumen hilang setelah create")
                continue
            exp_total = m["Total eResto"]
            got_total = safe_float(rec.get("grand_total"))
            diff = abs(got_total - exp_total)
            n_items = len(rec.get("items", []))
            line_ok = all(abs(safe_float(x.get("qty")) * safe_float(x.get("rate"))
                              - safe_float(x.get("amount"))) < 0.01
                          and abs(safe_float(x.get("stock_qty"))
                                  - safe_float(x.get("qty")) * safe_float(x.get("conversion_factor"))) < 1e-6
                          for x in rec.get("items", []))
            ok = diff <= 1.0 and line_ok
            if not ok:
                verify_issues.append(f"{m['PO Number']}: diff total Rp{diff:,.2f} "
                                     f"line_ok={line_ok}")
            ver_rows.append({"PO": m["PO Number"], "ERPNext ID": m["ERPNext ID"],
                             "Grand Total eResto": exp_total, "Grand Total ERPNext": got_total,
                             "Selisih": diff, "Baris": n_items, "Line OK": line_ok,
                             "Status": "LOLOS" if ok else "CEK"})

    # audit tambahan: PO Gudang Jakarta sebelum tanggal target yang belum ada
    older_missing = []
    if not args.no_older_audit and not args.only:
        prev = eresto.fetch_purchases("2026-10-01", args.date)
        prev = [p for p in prev if safe_str((p.get("supplier") or {}).get("name")) == SUPPLIER_ERESTO
                and safe_str(p.get("date"))[:10] < args.date]
        for p in sorted(prev, key=lambda x: safe_str(x.get("purchase_number"))):
            pn = safe_str(p.get("purchase_number"))
            if pn not in existing:
                older_missing.append({
                    "PO Number": pn, "Tanggal": safe_str(p.get("date"))[:10],
                    "Divisi": safe_str((p.get("division") or {}).get("name")),
                    "Total": safe_float(p.get("total_cost")),
                    "Status eResto": safe_str(p.get("status"))})

    # ---------- Excel ----------
    wb = Workbook()
    header_fill = PatternFill(start_color="D9EAF7", end_color="D9EAF7", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True)
    center_align = Alignment(horizontal="center", vertical="center")
    thin_border = Border(left=Side(style="thin", color="D3D3D3"),
                         right=Side(style="thin", color="D3D3D3"),
                         top=Side(style="thin", color="D3D3D3"),
                         bottom=Side(style="thin", color="D3D3D3"))

    def write_sheet(ws, title, rows, columns):
        ws.title = title
        ws.append(columns)
        for r in rows:
            ws.append([r.get(c, "") for c in columns])
        ws.freeze_panes = "A2"
        for col_idx in range(1, ws.max_column + 1):
            c = ws.cell(row=1, column=col_idx)
            c.fill = header_fill
            c.font = header_font
            c.alignment = center_align
        for row in ws.iter_rows(min_row=2, max_row=ws.max_row,
                                min_col=1, max_col=ws.max_column):
            for c in row:
                c.border = thin_border
        for col in ws.columns:
            ml = max(len(str(c.value or "")) for c in col)
            ws.column_dimensions[get_column_letter(col[0].column)].width = max(ml + 3, 12)

    rekap_cols = ["PO Number", "ERPNext ID", "Tanggal", "Company", "Supplier",
                  "Target WH", "Source WH", "Jumlah Baris", "Total eResto",
                  "Grand Total ERPNext", "Docstatus", "Status ERPNext", "Hasil",
                  "Status eResto", "Catatan"]
    raw_cols = ["PO Number", "Tanggal", "Company (Divisi)", "SKU", "Nama eResto",
                "Qty eResto", "Unit eResto", "Harga eResto", "Item Code", "Item Name",
                "UOM ERPNext", "CF", "Stock Qty", "Rate", "Amount", "Catatan UOM",
                "Status eResto"]
    skip_cols = ["PO Number", "Tanggal", "Company", "Total eResto", "Status eResto",
                 "Kategori", "Alasan"]

    ws = wb.active
    write_sheet(ws, "Rekap_Migrasi", migrated, rekap_cols)
    write_sheet(wb.create_sheet(), "Raw_eResto", raw_rows, raw_cols)
    write_sheet(wb.create_sheet(), "Skipped", skipped, skip_cols)

    # Validation
    n_ok = sum(1 for m in migrated if m["Hasil"] == "BERHASIL")
    n_skip = sum(1 for m in migrated if m["Hasil"] == "SKIP_EXISTS")
    n_fail = sum(1 for m in migrated if m["Hasil"] in ("FAIL_POST",))
    total_eresto = sum(m["Total eResto"] for m in migrated if m["Hasil"] == "BERHASIL")
    total_erp = sum(safe_float(m["Grand Total ERPNext"]) for m in migrated if m["Hasil"] == "BERHASIL")
    ds_ok = all((m["Docstatus"] == (1 if m["Status eResto"] in ("processing", "completed") else 0))
                for m in migrated if m["Hasil"] == "BERHASIL")
    val_rows = [
        {"Parameter": "PO eResto 'Gudang Jakarta' ditemukan", "Nilai": len(details),
         "Status": "OK", "Keterangan": f"tanggal {args.date}"},
        {"Parameter": "PO BERHASIL dimigrasikan", "Nilai": n_ok,
         "Status": "LOLOS" if not args.dry_run else "DRY-RUN",
         "Keterangan": "ID identik eResto (rename_doc)"},
        {"Parameter": "PO SKIP_EXISTS (rerun)", "Nilai": n_skip, "Status": "OK",
         "Keterangan": "idempoten, 0 duplikat"},
        {"Parameter": "PO GAGAL", "Nilai": n_fail, "Status": "LOLOS" if n_fail == 0 else "CEK",
         "Keterangan": "harus 0"},
        {"Parameter": "PO di-skip karena prasyarat/item", "Nilai": len(skipped),
         "Status": "LOLOS" if not skipped else "CEK",
         "Keterangan": "tidak ditebak; lihat sheet Skipped"},
        {"Parameter": "Total nilai eResto vs ERPNext", "Nilai": f"{total_eresto:,.2f} vs {total_erp:,.2f}",
         "Status": "LOLOS" if abs(total_eresto - total_erp) <= 1 else "CEK",
         "Keterangan": "toleransi ≤ Rp1"},
        {"Parameter": "Docstatus sesuai status eResto", "Nilai": "ya" if ds_ok else "tidak",
         "Status": "LOLOS" if ds_ok else "CEK",
         "Keterangan": "processing/completed -> submit; lainnya -> draft"},
        {"Parameter": "Verifikasi baris (qty×rate=amount, stock_qty=qty×cf)",
         "Nilai": f"{len(ver_rows)} dok", "Status": "LOLOS" if not verify_issues else "CEK",
         "Keterangan": "; ".join(verify_issues) if verify_issues else "semua klop"},
    ]
    write_sheet(wb.create_sheet(), "Validation", val_rows,
                ["Parameter", "Nilai", "Status", "Keterangan"])

    # Catatan
    note_rows = [
        {"Topik": "Scope",
         "Catatan": f"PO eResto supplier 'Gudang Jakarta' tanggal {args.date}; source warehouse "
                    f"'{SOURCE_WH}' (dipakai alur SO/DN JURI). Data hari berjalan bisa bertambah — rerun script = aman."},
        {"Topik": "Temuan PO084.081026.001 (di luar scope)",
         "Catatan": "Di BARU tercatat 3 Pack cf=50 @190.000 (edit manual 2026-10-09 08:31), "
                    "sedangkan sumber eResto 5 Pack cf=150 @114.000 (per saai ini). Total sama Rp570.000. "
                    "Menunggu keputusan user — tidak disentuh script ini."},
    ]
    for om in older_missing:
        note_rows.append({"Topik": f"Belum ada di BARU: {om['PO Number']}",
                          "Catatan": f"tanggal {om['Tanggal']} | divisi {om['Divisi']} | "
                                     f"Rp {om['Total']:,.0f} | status eResto {om['Status eResto']} "
                                     f"(di luar scope tanggal; menunggu keputusan)"})
    write_sheet(wb.create_sheet(), "Catatan", note_rows, ["Topik", "Catatan"])

    wb.save(REPORT_PATH)
    print(f"  Laporan: {REPORT_PATH}")

    # ---------- Ringkasan stdout ----------
    print("\n" + "=" * 84)
    print(f"  BERHASIL : {n_ok} | SKIP_EXISTS : {n_skip} | GAGAL : {n_fail} | SKIPPED : {len(skipped)}")
    if not args.dry_run:
        print(f"  Nilai eResto : Rp {total_eresto:,.2f}")
        print(f"  Nilai ERPNext: Rp {total_erp:,.2f}")
        print(f"  Docstatus OK : {ds_ok} | Verifikasi baris: {'OK' if not verify_issues else verify_issues}")
    if older_missing:
        print(f"  CATATAN: {len(older_missing)} PO Gudang Jakarta sebelum {args.date} belum ada di BARU (lihat sheet Catatan).")
    print("=" * 84)


if __name__ == "__main__":
    run()
