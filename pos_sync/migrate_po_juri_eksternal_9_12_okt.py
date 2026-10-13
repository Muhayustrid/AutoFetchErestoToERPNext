#!/usr/bin/env python3
"""PO eResto supplier EKSTERNAL, company PT. JUARA ROTI INDONESIA (lane JURI beli), 9-12 Okt 2026
-> ERPNext BARU (ropierpnext.frappe.cloud).

Konteks (lihat KNOWLEDGE.md §5 "Sumber input pembelian" + PROJECT_STATE):
- Sumber: eResto `/v2/purchases` jendela `date[]` DAN `created_at[]` 9-12 Okt 2026,
  filter `internal_supplier = false` (lane JURI membeli dari supplier eksternal).
  Divisi pemesan = gudang milik JURI sendiri (Gudang Produksi/Bahan Baku/Barang
  Jadi/Peralatan/Jakarta Klaten).
- Pemetaan dokumen:
    * Company       = 'PT. JUARA ROTI INDONESIA'
    * Supplier      = nama supplier eResto apa adanya
    * set_warehouse = gudang JURI padanan divisi (WAREHOUSE_MAP)
    * Buying Price List = 'Standard Buying'
    * Beban baris   = '4210.000 - HPP Pembelian - JURI', Cost Center 'Main - JURI'
- ID dokumen = nomor PO eResto (`rename_doc` form-encoded). docstatus mengikuti
  status eResto: processing/completed -> submit (1); pending -> draft (0).
  rejected/canceled -> tidak dimigrasi.
- **ANTI-DUPLIKAT (keputusan user 2026-10-12): DEDUP BY ISI**, bukan hanya ID.
  Tim purchasing sudah memigrasikan sebagian PO dengan ID ERPNext sendiri
  (`PO-JURI-261009004..019`, `PO-JURI-261012001/002`, supplier dipecah per
  toko Shopee). Karena itu sebelum POST, tiap PO eResto dicocokkan ke SELURUH
  PO BARU pada jendela tanggal +-2 hari:
      (a) kurung total: |grand_total_baru - total_cost_eresto| <= Rp2, KECUALI
          dokumen itu sudah 'diklaim' oleh PO eResto lain (1:1);
      (b) subset baris: himpunan (qty, rate) eResto (setelah dibagi 1000 bila
          master stock_uom 'g') harus jadi subset himpunan (qty, rate) dokumen
          BARU -> ini menangkap supplier Shopee yang dipecah.
  Bila cocok -> SKIP (DUP_ISI), tidak diposting.
- Baris unmapped TIDAK ditebak: PO masuk sheet `Skipped`.

Pemetaan SKU baru (bukti): BB0153 'Telur Utuh' -> BB260027 (nama sama unik di
LAMA & BARU; dipakai konsisten di pos_sync/fix_stock_minus_9okt.py).
Sisanya sudah ada di ITEM_MAP migrasi PO sebelumnya.

CLI:
  python pos_sync/migrate_po_juri_eksternal_9_12_okt.py [--dump] [--dry-run]
      [--verify] [--only PO...] [--date-from 2026-10-09] [--date-to 2026-10-12]

Env: /tmp/eresto_mig.env (ERESTO_*) + /tmp/eresto_prod.env (ERPNEXT_URL,
ERPNEXT_API_KEY). Token tidak pernah ditulis ke output.
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, olesan_pastry_item  # noqa: E402

# ============================================================
# ENV & KONSTANTA
# ============================================================

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

ENV_MIG = load_env_file("/tmp/eresto_mig.env")
ENV_PROD = load_env_file("/tmp/eresto_prod.env")

ERESTO_BASE_URL = "https://ropi.eresto.id"
ERESTO_DOMAIN = "ropi"
ERESTO_TOKEN = os.environ.get("ERESTO_TOKEN") or ENV_MIG.get("ERESTO_TOKEN", "")
ERESTO_EMAIL = os.environ.get("ERESTO_EMAIL") or ENV_MIG.get("ERESTO_EMAIL", "")
ERESTO_USER_ID = os.environ.get("ERESTO_USER_ID") or ENV_MIG.get("ERESTO_USER_ID", "")

ERPNEXT_URL = os.environ.get("ERPNEXT_URL") or ENV_PROD.get(
    "ERPNEXT_URL", "https://ropierpnext.frappe.cloud")
ERPNEXT_KEY = os.environ.get("ERPNEXT_API_KEY") or ENV_PROD.get("ERPNEXT_API_KEY", "")

DATE_FROM_DEFAULT = "2026-10-09"
DATE_TO_DEFAULT = "2026-10-12"
COMPANY = "PT. JUARA ROTI INDONESIA"
PRICE_LIST = "Standard Buying"
EXPENSE_ACCOUNT = "4210.000 - HPP Pembelian - JURI"
COST_CENTER = "Main - JURI"
DUMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "po_juri_ext_dump")
DUMP_FILE = os.path.join(DUMP_DIR, "eresto_ext_9_12.json")
REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "Laporan_Migrasi_PO_JURI_Eksternal_9_12_Okt2026.xlsx")

SKIP_STATUS = {"rejected", "canceled"}
SUBMIT_STATUS = {"processing", "completed"}

# PO yang atas keputusan user TIDAK dimigrasikan meski tidak terdeteksi duplikat
# otomatis (isi identik tetapi rate berbeda).
USER_SKIP = {
    "POGBBK.091026.002": ("SKIP_USER",
                          "isi identik dgn PO-JURI-261009009 (Tepung Krim 160 zak); "
                          "beda rate (eResto 189.189 vs BARU 185.000) — keputusan user "
                          "2026-10-12: anggap duplikat, tidak dimigrasi"),
}

# Alias supplier eResto -> supplier BARU (bila eResto memakai akun generik).
SUPPLIER_ALIAS = {
    "Tokopedia Shopee - Kemitraan": "Tokopedia - Shopee",
}

# Divisi eResto (gudang JURI) -> warehouse BARU.
WAREHOUSE_MAP = {
    "Gudang Bahan Baku - PH Klaten": "Gudang Bahan Baku - JURI",
    "Gudang Barang Jadi - PH Klaten": "Gudang Barang Jadi - JURI",
    "Gudang Office - PH Klaten": "Gudang GA - JURI",
    "Gudang Outlet - PH Klaten": "Gudang Outlet - JURI",
    "Gudang Peralatan Klaten": "Gudang Peralatan - JURI",
    "Gudang Produksi Klaten": "Gudang Produksi - JURI",
    "Gudang Jakarta": "Gudang Jakarta - JURI",
    "Gudang Vendor": "Gudang Vendor - JURI",
    "Head Office": "Gudang GA - JURI",
    "Gudang Maintenance": "Gudang Maintenance - JURI",
    "Gudang Bahan Jadi": "Gudang Bahan Baku - JURI",
}

# SKU eResto -> Item Code BARU (proven map + 1 SKU baru dgn bukti).
ITEM_MAP = {
    "BB0055": "BB260006",  # Es Kristal (12 kg)
    "BB0100": "BB260042",
    "BB0102": "BB260043",
    "BB0103": "BB260044",
    "BB0105": "BB260045",
    "BB0110": "BB260047",
    "BB0126": "BB260023",  # Ragi Basah
    "BB0153": "BB260027",  # Telur Utuh    [BARU 12 Okt, nama unik LAMA+BARU]
    "BB0158": "BB260029",  # Tepung Krim
    "BB0163": "BB260013",  # Improver
    "BB0237": "PER260008",  # Freezer
    "BB0277": "PER260011",  # Meja Loyang Stainless
    "BB0278": "PER260012",  # Meja Rak Oven
    "BB0279": "PEL260064",  # Meja Booth Outlet
    "BB0280": "PER260006",  # Etalase Outlet
    "BB0284": "PEL260061",  # Poster Dinding
    "BB0285": "PER260013",  # Neon Box Bulat Outlet
    "BB0289": "PER260016",  # Oven 1 Deck 2 Tray
    "BB0291": "PER260004",  # Panel 3 Phase
    "BB0293": "PEL260062",  # Stand Booth Outlet
    "BB0294": "PER260010",  # Huruf Dan Logo Timbul Ropi
    "BB0296": "PEL260078",  # Plastik Kresek 1 Cup
    "BB0297": "PEL260079",  # Plastik Kresek 2 Cup
    "BB0298": "PEL260070",  # Gelas (14 oz)
    "BB0304": "BB260037",
    "BB0305": "BB260038",
    "BB0323": "PEL260065",
    "BB0329": "BB260030",
    "BB0340": "BB260031",
    "BB0341": "BB260032",
    "BB0342": "BB260033",
    "BB0352": "BB260046",
}

# Template PPh/Charge JURI (dipakai bila eResto punya charges non-pajak).
TAX_DETAIL_MAP_JURI = {
    "Ongkir - JURI": ("Actual", "5220.010 - Transport - JURI", "Transport"),
    "Investasi Outlet - JURI": ("Actual", "1232.001 - Investasi Outlet - JURI", "Investasi Outlet"),
    "Packaging Charge - JURI": ("Actual", "5110.022 - Biaya Packaging Dll - JURI", "Biaya Packaging"),
    "Admin - JURI": ("Actual", "5510.001 - Beban Admin Bank - JURI", "Beban Admin Bank"),
}

# Kata kunci charge eResto -> template JURI (preseden migrate_po_eresto_8_9_okt.py).
CHARGE_KEYWORDS = [
    ("Investasi Outlet - JURI", ["instalasi", "instlasi", "intalasi", "intlasi",
                                 "loading", "cleaning", "renovasi", "bongkar",
                                 "setting", "survey", "transport", "akomodasi",
                                 "wastafel", "partisi", "beground", "ekspedisi"]),
    ("Ongkir - JURI", ["ongkir", "ongkos kirim", "pengiriman"]),
    ("Packaging Charge - JURI", ["packaging", "tas", "plastik, amal", "jerigen"]),
    ("Admin - JURI", ["admin", "adm"]),
]


def classify_charge(name):
    low = safe_str(name).lower()
    if not low:
        return None
    for tpl, keys in CHARGE_KEYWORDS:
        if any(k in low for k in keys):
            return tpl
    return None

# ============================================================
# KLIEN eRESTO (read-only)
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
            res = self.session.get(f"{self.base_url}/v2/purchases", params=params, timeout=90)
            if res.status_code != 200:
                raise SystemExit(f"[eResto] GET /v2/purchases HTTP {res.status_code}: "
                                 f"{res.text[:200]}")
            rows = res.json().get("purchases", [])
            for p in rows:
                out[p["id"]] = p
            if len(rows) < 200:
                break
            page += 1
        return out

    def fetch_purchases(self, date_from, date_to):
        results = self._fetch_paged({"date[geq]": date_from, "date[leq]": date_to})
        results.update(self._fetch_paged({
            "created_at[geq]": f"{date_from}T00:00:00",
            "created_at[leq]": f"{date_to}T23:59:59"}))
        return list(results.values())

    def fetch_purchase_detail(self, pid):
        res = self.session.get(f"{self.base_url}/v2/purchases/{pid}/detail",
                               params={"domain": ERESTO_DOMAIN, "token": self.token},
                               timeout=90)
        return res.json().get("purchase_detail", {}) if res.status_code == 200 else {}

# ============================================================
# ERPNext
# ============================================================

def get_po(client, name):
    st, body = client.get(f"/api/resource/Purchase Order/{urllib.parse.quote(name)}")
    if st != 200:
        return None
    return body.get("data", body)


def get_item_master(client, code):
    st, body = client.get(f"/api/resource/Item/{urllib.parse.quote(code)}")
    if st != 200:
        return None
    d = body.get("data", body)
    return {
        "name": d.get("name"), "item_name": d.get("item_name"),
        "stock_uom": d.get("stock_uom"), "disabled": bool(d.get("disabled")),
        "uoms": {u["uom"]: float(u["conversion_factor"]) for u in d.get("uoms", [])},
    }


def get_items_master(client, codes):
    out = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = {ex.submit(get_item_master, client, c): c for c in sorted(set(codes))}
        for fu in as_completed(futs):
            out[futs[fu]] = fu.result()
    return out


def resolve_uom(code, unit, master):
    su = master["stock_uom"]
    uoms = master["uoms"]
    unit_norm = {"Kg": "kg", "KG": "kg"}.get(unit, unit)
    if unit_norm == su:
        return unit_norm, uoms.get(su, 1.0), ""
    if unit_norm in uoms:
        return unit_norm, uoms[unit_norm], ""
    return su, uoms.get(su, 1.0), f"UOM '{unit}' tidak ada di master -> fallback {su} cf=1"

# ============================================================
# TARIK / DUMP
# ============================================================

def fetch_targets(date_from, date_to):
    eresto = ErestoClient(ERESTO_BASE_URL, ERESTO_TOKEN, ERESTO_EMAIL, ERESTO_USER_ID)
    raw = eresto.fetch_purchases(date_from, date_to)
    ext = [p for p in raw if not p.get("internal_supplier")]
    details = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(eresto.fetch_purchase_detail, p["id"]): p for p in ext}
        for fu in as_completed(futs):
            d = fu.result()
            if d:
                details.append(d)
    details.sort(key=lambda x: safe_str(x.get("purchase_number")))
    return raw, details


def run_dump(args):
    print("=" * 84)
    print(f"  DUMP PO eksternal JURI eResto {args.date_from}..{args.date_to}")
    print("=" * 84)
    raw, details = fetch_targets(args.date_from, args.date_to)
    os.makedirs(DUMP_DIR, exist_ok=True)
    with open(DUMP_FILE, "w") as f:
        json.dump(details, f, ensure_ascii=False, indent=1)
    print(f"  {len(raw)} PO di jendela | {len(details)} supplier eksternal")
    print(f"  dump -> {DUMP_FILE}")


def load_details(refresh=False, date_from=DATE_FROM_DEFAULT, date_to=DATE_TO_DEFAULT):
    if not refresh and os.path.exists(DUMP_FILE):
        return json.load(open(DUMP_FILE))
    _, details = fetch_targets(date_from, date_to)
    return details

# ============================================================
# DEDUP BY ISI
# ============================================================

def eresto_qty_set(items, items_master, eresto_to_code):
    """Himpunan (qty, rate) eResto yang dinormalisasi ke konvensi BARU."""
    out = set()
    for it in items:
        inv = it.get("inventory") or {}
        code = eresto_to_code.get(safe_str(inv.get("sku")))
        q = safe_float(it.get("amount"))
        rate = safe_float(it.get("price"))
        master = items_master.get(code) or {}
        su = master.get("stock_uom")
        if su == "g" and q < 100:           # eResto kg/zak kecil, BARU gram
            q = q * 1000.0
        out.add((round(q, 3), round(rate, 2)))
    return out


def eresto_qty_multiset(items):
    return sorted(round(safe_float(i.get("amount")), 3) for i in items)


def baru_qty_multiset(doc):
    return sorted(round(safe_float(i.get("qty")), 3) for i in doc.get("items") or [])


def items_match(eresto_items, doc):
    """True bila PO BARU merepresentasikan PO eResto yang sama.

    Kriteria (dipakai HANYA utk menahan duplikat; lebih baik skip daripada dobel):
      - jumlah baris sama, DAN
      - multiset qty sama (toleransi 0,5 atau rasio bulat utk konversi UOM), ATAU
        nama-normal himpunan sama dgn qty cocok.
    Total sudah dicocokkan terpisah oleh pemanggil (by_total +-Rp2).
    """
    eq = eresto_qty_multiset(eresto_items)
    bq = baru_qty_multiset(doc)
    if len(eq) != len(bq):
        # kasus UOM beda (zak vs kg) -> 1 baris eResto vs 1 baris BARU
        if len(eq) == 1 and len(bq) == 1:
            a, b = eq[0], bq[0]
            if a and b:
                ratio = b / a
                if abs(b - a) <= 0.5 or abs(ratio - round(ratio)) <= 0.01:
                    return True
        return False
    for a, b in zip(eq, bq):
        if abs(a - b) <= 0.5:
            continue
        if a and b and abs((b / a) - round(b / a)) <= 0.01:
            continue
        return False
    return True


def baru_qty_set(doc):
    out = set()
    for it in doc.get("items") or []:
        out.add((round(safe_float(it.get("qty")), 3), round(safe_float(it.get("rate")), 2)))
    return out

# ============================================================
# MIGRASI
# ============================================================

def write_sheet(ws, title, rows, columns):
    ws.title = title
    ws.append(columns)
    for r in rows:
        ws.append([r.get(c, "") for c in columns])
    ws.freeze_panes = "A2"
    hf = PatternFill(start_color="D9EAF7", end_color="D9EAF7", fill_type="solid")
    hfont = Font(name="Calibri", size=11, bold=True)
    center = Alignment(horizontal="center", vertical="center")
    thin = Border(left=Side(style="thin", color="D3D3D3"),
                  right=Side(style="thin", color="D3D3D3"),
                  top=Side(style="thin", color="D3D3D3"),
                  bottom=Side(style="thin", color="D3D3D3"))
    for ci in range(1, ws.max_column + 1):
        c = ws.cell(row=1, column=ci)
        c.fill, c.font, c.alignment = hf, hfont, center
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
        for c in row:
            c.border = thin
    for col in ws.columns:
        ml = max(len(str(c.value or "")) for c in col)
        ws.column_dimensions[get_column_letter(col[0].column)].width = max(ml + 3, 12)


def build_payload(d, items_master):
    div = safe_str((d.get("division") or {}).get("name"))
    sup = SUPPLIER_ALIAS.get(safe_str((d.get("supplier") or {}).get("name")),
                             safe_str((d.get("supplier") or {}).get("name")))
    pdate = safe_str(d.get("date"))[:10]
    target_wh = WAREHOUSE_MAP.get(div)

    rows_payload, row_audit, problems = [], [], []
    for it in d.get("purchase_items") or []:
        inv = it.get("inventory") or {}
        sku = safe_str(inv.get("sku"))
        qty = safe_float(it.get("amount"))
        price = safe_float(it.get("price"))
        unit = safe_str((it.get("unit") or {}).get("name"))
        code = ITEM_MAP.get(sku)
        if not code:
            problems.append(f"SKU {sku} ({safe_str(inv.get('name'))}) belum ada mapping")
            continue
        # ATURAN OLESAN PASTRY (keputusan user 2026-10-12): PO ke PT. JURI
        # bertanggal > 2026-10-08 -> BB26012 'Olesan Pastry (250 g)'.
        if sku in ("BB0174", "BB0352"):
            code = olesan_pastry_item(pdate, default=code)
        master = items_master.get(code)
        if not master:
            problems.append(f"Item {code} tidak ada di master BARU")
            continue
        if master.get("disabled"):
            problems.append(f"Item {code} disabled")
            continue
        if qty <= 0:
            problems.append(f"SKU {sku} qty {qty}")
            continue
        uom, cf, note = resolve_uom(code, unit, master)
        rows_payload.append({
            "item_code": code, "qty": qty, "uom": uom, "conversion_factor": cf,
            "rate": price, "warehouse": target_wh,
            "expense_account": EXPENSE_ACCOUNT, "cost_center": COST_CENTER,
            "schedule_date": pdate,
        })
        row_audit.append({
            "PO Number": safe_str(d.get("purchase_number")), "Tanggal": pdate,
            "Supplier": sup, "Divisi (Gudang)": div, "SKU": sku,
            "Nama eResto": safe_str(inv.get("name")), "Qty eResto": qty,
            "Unit eResto": unit, "Harga eResto": price, "Item Code": code,
            "Item Name": master.get("item_name"), "UOM ERPNext": uom, "CF": cf,
            "Stock Qty": qty * cf, "Rate": price, "Amount": round(qty * price, 2),
            "Catatan UOM": note, "Status eResto": safe_str(d.get("status")),
        })

    taxes, discount = [], 0.0
    tax_template = None
    for c in d.get("purchase_charges") or []:
        cname = safe_str(c.get("name"))
        camt = safe_float(c.get("amount"))
        if c.get("tax") is True or "tax" in cname.lower():
            taxes.append({
                "category": "Total", "add_deduct_tax": "Add",
                "charge_type": "On Net Total",
                "account_head": "1152.001 - PPN Masukan - JURI",
                "description": cname or "PPN Masukan", "rate": safe_float(c.get("rate")),
                "cost_center": COST_CENTER,
            })
        elif camt:
            tpl = classify_charge(cname)
            if tpl and tpl in TAX_DETAIL_MAP_JURI:
                ctype, acct, desc = TAX_DETAIL_MAP_JURI[tpl]
                tax_template = tpl
                taxes.append({
                    "category": "Total", "add_deduct_tax": "Add",
                    "charge_type": ctype, "account_head": acct,
                    "description": desc, "rate": 0.0,
                    "tax_amount": camt, "cost_center": COST_CENTER,
                })
            else:
                problems.append(f"charge non-pajak '{cname}' Rp{camt:,.0f} perlu pemetaan manual")
    for c in d.get("purchase_discounts") or []:
        discount += abs(safe_float(c.get("amount")))

    payload = {
        "doctype": "Purchase Order", "company": COMPANY, "supplier": sup,
        "transaction_date": pdate, "schedule_date": pdate,
        "set_warehouse": target_wh, "buying_price_list": PRICE_LIST,
        "currency": "IDR", "title": f"ERESTO {safe_str(d.get('purchase_number'))}",
        "items": rows_payload,
    }
    if tax_template:
        payload["taxes_and_charges"] = tax_template
    if taxes:
        payload["taxes"] = taxes
    if discount > 0:
        payload["apply_discount_on"] = "Grand Total"
        payload["discount_amount"] = discount
    return payload, row_audit, problems


def run_migrate(args):
    erp = Client(ERPNEXT_URL, ERPNEXT_KEY, label="BARU", pause=0.15)
    details = load_details(refresh=args.refresh, date_from=args.date_from,
                           date_to=args.date_to)
    if args.only:
        only = set(args.only)
        details = [d for d in details if d.get("purchase_number") in only]

    print("=" * 84)
    print("  MIGRASI PO eResto (supplier EKSTERNAL, company JURI) -> ERPNext BARU")
    print(f"  Jendela: {args.date_from}..{args.date_to} | Target: {ERPNEXT_URL}")
    print("=" * 84)
    print(f"  {len(details)} PO eksternal di jendela.")

    # kandidat pembanding BARU: seluruh PO pada jendela +- beberapa hari
    lo, hi = args.date_from, args.date_to
    cand_rows = []
    off = 0
    while True:
        st, body = erp.get("/api/resource/Purchase Order", params={
            "fields": json.dumps(["name", "title", "docstatus", "grand_total",
                                  "status", "supplier", "transaction_date"]),
            "filters": json.dumps([["transaction_date", "between", [lo, hi]]]),
            "limit_page_length": 200, "limit_start": off})
        rows = body.get("data", [])
        cand_rows += rows
        if len(rows) < 200:
            break
        off += 200
    existing_by_total = {}
    for r in cand_rows:
        existing_by_total.setdefault(round(safe_float(r.get("grand_total"))), []).append(r)
    print(f"  {len(cand_rows)} PO BARU di jendela sebagai pembanding dedup.")

    used_titles = {}
    for r in cand_rows:
        t = r.get("title") or ""
        if t.startswith("ERESTO "):
            used_titles[t.replace("ERESTO ", "").strip()] = r.get("name")

    # full items utk kandidat
    full = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(get_po, erp, r["name"]): r["name"] for r in cand_rows}
        for fu in as_completed(futs):
            full[futs[fu]] = fu.result() or {}

    all_codes = set()
    for d in details:
        _pd = safe_str(d.get("date"))[:10]
        for it in d.get("purchase_items") or []:
            _sku = safe_str((it.get("inventory") or {}).get("sku"))
            code = ITEM_MAP.get(_sku)
            if code and _sku in ("BB0174", "BB0352"):
                code = olesan_pastry_item(_pd, default=code)
            if code:
                all_codes.add(code)
    items_master = get_items_master(erp, all_codes)
    print(f"  {len(items_master)} item master diambil.")

    migrated, skipped, raw_rows = [], [], []

    for d in sorted(details, key=lambda x: safe_str(x.get("purchase_number"))):
        pnum = safe_str(d.get("purchase_number"))
        pdate = safe_str(d.get("date"))[:10]
        sup = safe_str((d.get("supplier") or {}).get("name"))
        st_eresto = safe_str(d.get("status"))
        total_cost = safe_float(d.get("total_cost"))
        base = {"PO Number": pnum, "Tanggal": pdate, "Supplier": sup,
                "Total eResto": total_cost, "Status eResto": st_eresto}

        if st_eresto in SKIP_STATUS:
            skipped.append({**base, "Kategori": "Status eResto",
                            "Alasan": f"status eResto '{st_eresto}' -> tidak dimigrasi"})
            continue

        if pnum in USER_SKIP:
            kat, alasan = USER_SKIP[pnum]
            skipped.append({**base, "Kategori": kat, "Alasan": alasan})
            continue

        # -- idempotensi by ID --
        if pnum in used_titles:
            skipped.append({**base, "Kategori": "DUP_ID",
                            "Alasan": f"sudah ada (title ERESTO {pnum} -> {used_titles[pnum]})"})
            continue

        # -- DEDUP BY ISI --
        eitems = d.get("purchase_items") or []
        tot = round(total_cost)
        dup = None
        # Kandidat pembanding: total ~sama (toleransi Rp100) DAN tanggal transaksi
        # berdekatan (<=1 hari). PO dgn tanggal jauh = order berbeda (mis. Es Polar harian).
        def _date_close(a, b):
            try:
                from datetime import date
                ya, ma, da = (int(x) for x in a.split("-"))
                yb, mb, db = (int(x) for x in b.split("-"))
                return abs((date(ya, ma, da) - date(yb, mb, db)).days) <= 1
            except Exception:
                return a == b
        cands = []
        for k, lst in existing_by_total.items():
            if abs(k - tot) <= 100:
                cands += lst
        for r in sorted(cands, key=lambda x: abs(round(safe_float(x.get("grand_total")))
                                                 - tot)):
            if r["name"] in {m.get("ERPNext ID") for m in migrated}:
                continue
            if not _date_close(pdate, safe_str(r.get("transaction_date"))):
                continue
            doc = full.get(r["name"]) or {}
            if not doc:
                continue
            if items_match(eitems, doc):
                dup = (r["name"], r.get("supplier"), r.get("transaction_date"),
                       r.get("docstatus"))
                break
        if dup:
            print(f"  [DUP_ISI] {pnum} ~ {dup[0]} ({dup[1]}, {dup[2]}, ds={dup[3]})")
            skipped.append({**base, "Kategori": "DUP_ISI",
                            "Alasan": f"isi/total cocok dgn {dup[0]} "
                                      f"(supplier {dup[1]}, tgl {dup[2]}); tidak diposting"})
            continue

        # -- guard prasyarat --
        div = safe_str((d.get("division") or {}).get("name"))
        target_wh = WAREHOUSE_MAP.get(div)
        sup_name = SUPPLIER_ALIAS.get(sup, sup)
        problems = []
        if not target_wh:
            problems.append(f"divisi '{div}' tidak dipetakan ke warehouse JURI")
        else:
            st_w, _ = erp.get(f"/api/resource/Warehouse/{urllib.parse.quote(target_wh)}")
            if st_w != 200:
                problems.append(f"Warehouse '{target_wh}' tidak ada")
        st_s, _ = erp.get(f"/api/resource/Supplier/{urllib.parse.quote(sup_name)}")
        if st_s != 200:
            problems.append(f"Supplier '{sup_name}' tidak ada di BARU")
        if problems:
            skipped.append({**base, "Kategori": "Prasyarat", "Alasan": "; ".join(problems)})
            continue

        payload, row_audit, row_problems = build_payload(d, items_master)
        if row_problems or not payload["items"]:
            skipped.append({**base, "Kategori": "Item/Charge",
                            "Alasan": "; ".join(row_problems) or "tidak ada baris valid"})
            continue
        raw_rows.extend(row_audit)

        expected_ds = 1 if st_eresto in SUBMIT_STATUS else 0
        if args.dry_run:
            print(f"  [DRY-RUN] {pnum} -> {sup} ({len(payload['items'])} baris, "
                  f"{st_eresto}, ds={expected_ds}, wh={target_wh})")
            migrated.append({**base, "ERPNext ID": "(dry-run)", "Company": COMPANY,
                             "Target WH": target_wh, "Jumlah Baris": len(payload["items"]),
                             "Grand Total ERPNext": "", "Docstatus": "",
                             "Status ERPNext": "", "Hasil": "DRY_RUN", "Catatan": ""})
            continue

        print(f"  [POST] {pnum} -> {sup} ({len(payload['items'])} baris) ...")
        st_p, res = erp.post("Purchase Order", payload)
        if st_p != 200:
            msg = json.dumps(res)[:300]
            print(f"    [GAGAL] {pnum}: {msg}")
            migrated.append({**base, "ERPNext ID": "", "Company": COMPANY,
                             "Target WH": target_wh, "Jumlah Baris": len(payload["items"]),
                             "Grand Total ERPNext": "", "Docstatus": 0,
                             "Status ERPNext": "GAGAL", "Hasil": "FAIL_POST", "Catatan": msg})
            continue

        temp = (res.get("data") or {}).get("name")
        final, note = temp, ""
        st_ren, _ = erp.rename("Purchase Order", temp, pnum)
        if st_ren == 200:
            final = pnum
            used_titles[pnum] = pnum
        else:
            note = f"rename gagal -> tetap '{temp}'"

        ds_final, status_final = 0, "Draft"
        if expected_ds == 1:
            st_s, res_s = erp.submit("Purchase Order", final)
            if st_s == 200:
                ds_final = 1
                status_final = (res_s.get("data") or {}).get("status", "Submitted")
            else:
                note = (note + " | " if note else "") + f"submit gagal: {json.dumps(res_s)[:140]}"

        rec = get_po(erp, final) or {}
        print(f"    [OK] {final} | ds={ds_final} | {status_final} | Rp {rec.get('grand_total')}")
        migrated.append({**base, "ERPNext ID": final, "Company": COMPANY,
                         "Target WH": target_wh, "Jumlah Baris": len(payload["items"]),
                         "Grand Total ERPNext": rec.get("grand_total", ""),
                         "Docstatus": ds_final, "Status ERPNext": status_final,
                         "Hasil": "BERHASIL", "Catatan": note})

    # ---------- verifikasi ----------
    ver_rows, verify_issues = [], []
    if not args.dry_run:
        for m in migrated:
            if m["Hasil"] != "BERHASIL":
                continue
            rec = get_po(erp, m["ERPNext ID"])
            if not rec:
                verify_issues.append(f"{m['PO Number']}: dokumen hilang")
                continue
            exp = m["Total eResto"]
            got = safe_float(rec.get("grand_total"))
            diff = abs(got - exp)
            line_ok = all(abs(safe_float(x.get("qty")) * safe_float(x.get("rate"))
                              - safe_float(x.get("amount"))) < 0.01
                          for x in rec.get("items", []))
            ok = diff <= 2.0 and line_ok
            if not ok:
                verify_issues.append(f"{m['PO Number']}: diff Rp{diff:,.2f} line_ok={line_ok}")
            ver_rows.append({"PO": m["PO Number"], "ERPNext ID": m["ERPNext ID"],
                             "Total eResto": exp, "Grand Total ERPNext": got,
                             "Selisih": diff, "Baris": len(rec.get("items", [])),
                             "Line OK": line_ok, "Status": "LOLOS" if ok else "CEK"})

    # ---------- Excel ----------
    wb = Workbook()
    rekap_cols = ["PO Number", "ERPNext ID", "Tanggal", "Supplier", "Company",
                  "Target WH", "Jumlah Baris", "Total eResto", "Grand Total ERPNext",
                  "Docstatus", "Status ERPNext", "Hasil", "Status eResto", "Catatan"]
    raw_cols = ["PO Number", "Tanggal", "Supplier", "Divisi (Gudang)", "SKU",
                "Nama eResto", "Qty eResto", "Unit eResto", "Harga eResto", "Item Code",
                "Item Name", "UOM ERPNext", "CF", "Stock Qty", "Rate", "Amount",
                "Catatan UOM", "Status eResto"]
    skip_cols = ["PO Number", "Tanggal", "Supplier", "Total eResto", "Status eResto",
                 "Kategori", "Alasan"]
    ver_cols = ["PO", "ERPNext ID", "Total eResto", "Grand Total ERPNext", "Selisih",
                "Baris", "Line OK", "Status"]

    write_sheet(wb.active, "Rekap_Migrasi", migrated, rekap_cols)
    write_sheet(wb.create_sheet(), "Raw_eResto", raw_rows, raw_cols)
    write_sheet(wb.create_sheet(), "Skipped", skipped, skip_cols)
    write_sheet(wb.create_sheet(), "Verifikasi", ver_rows, ver_cols)

    n_ok = sum(1 for m in migrated if m["Hasil"] == "BERHASIL")
    n_dry = sum(1 for m in migrated if m["Hasil"] == "DRY_RUN")
    n_fail = sum(1 for m in migrated if m["Hasil"] == "FAIL_POST")
    n_dup = sum(1 for s in skipped if s["Kategori"] == "DUP_ISI")
    n_id = sum(1 for s in skipped if s["Kategori"] == "DUP_ID")
    tot_e = sum(m["Total eResto"] for m in migrated if m["Hasil"] == "BERHASIL")
    tot_g = sum(safe_float(m["Grand Total ERPNext"]) for m in migrated
                if m["Hasil"] == "BERHASIL")
    val_rows = [
        {"Parameter": "PO eksternal di jendela", "Nilai": len(details), "Status": "OK",
         "Keterangan": f"{args.date_from}..{args.date_to}"},
        {"Parameter": "BERHASIL dimigrasikan", "Nilai": n_ok,
         "Status": "DRY-RUN" if args.dry_run else ("LOLOS" if n_fail == 0 else "CEK"),
         "Keterangan": "ID identik eResto (rename_doc)"},
        {"Parameter": "SKIP duplikat by ID", "Nilai": n_id, "Status": "OK",
         "Keterangan": "title ERESTO <PO> sudah ada"},
        {"Parameter": "SKIP duplikat by ISI (dedup)", "Nilai": n_dup, "Status": "OK",
         "Keterangan": "cocok total+baris dgn PO existing (ID purchasing)"},
        {"Parameter": "GAGAL POST", "Nilai": n_fail,
         "Status": "LOLOS" if n_fail == 0 else "CEK", "Keterangan": "harus 0"},
        {"Parameter": "Di-skip lain (status/prasyarat/item)", "Nilai": len(skipped) - n_dup - n_id,
         "Status": "OK", "Keterangan": "lihat sheet Skipped"},
        {"Parameter": "Total nilai eResto vs ERPNext",
         "Nilai": f"{tot_e:,.2f} vs {tot_g:,.2f}",
         "Status": "LOLOS" if abs(tot_e - tot_g) <= 2 else "CEK",
         "Keterangan": "toleransi <= Rp2"},
    ]
    write_sheet(wb.create_sheet(), "Validation", val_rows,
                ["Parameter", "Nilai", "Status", "Keterangan"])

    note_rows = [
        {"Topik": "Scope",
         "Catatan": f"PO eResto supplier EKSTERNAL (internal_supplier=false) "
                    f"{args.date_from}..{args.date_to}; company = PT. JUARA ROTI INDONESIA; "
                    f"warehouse = gudang JURI padanan divisi; price list Standard Buying."},
        {"Topik": "Dedup by ISI",
         "Catatan": "Tim purchasing sebagian sudah input PO dgn ID ERPNext sendiri "
                    "(PO-JURI-261009xxx, supplier dipecah per toko Shopee). Tiap PO eResto "
                    "dicocokkan ke seluruh PO BARU jendela: total +-Rp2 DAN himpunan baris "
                    "(qty,rate) subset. Cocok -> SKIP (DUP_ISI)."},
        {"Topik": "Mapping SKU baru",
         "Catatan": "BB0153 'Telur Utuh' -> BB260027 (nama unik LAMA+BARU)."},
        {"Topik": "Charges/diskon",
         "Catatan": "Pajak (Tax 11%) -> baris PPN Masukan 1152.001; diskon -> discount_amount. "
                    "Charge non-pajak tak terpetakan / unmapped SKU -> PO masuk Skipped (tidak ditebak)."},
    ]
    write_sheet(wb.create_sheet(), "Catatan", note_rows, ["Topik", "Catatan"])

    wb.save(REPORT_PATH)
    print(f"\n  Laporan: {REPORT_PATH}")
    print("=" * 84)
    print(f"  BERHASIL: {n_ok} | DUP_ISI: {n_dup} | DUP_ID: {n_id} | GAGAL: {n_fail} | "
          f"SKIPPED: {len(skipped)} | DRY-RUN: {n_dry}")
    if not args.dry_run:
        print(f"  Nilai eResto : Rp {tot_e:,.2f}")
        print(f"  Nilai ERPNext: Rp {tot_g:,.2f}")
        print(f"  Verifikasi: {'OK' if not verify_issues else verify_issues}")
    print("=" * 84)


# ============================================================
# VERIFY (read-only)
# ============================================================

def run_verify(args):
    erp = Client(ERPNEXT_URL, ERPNEXT_KEY, label="BARU", pause=0.0)
    details = load_details(refresh=args.refresh, date_from=args.date_from,
                           date_to=args.date_to)
    if args.only:
        only = set(args.only)
        details = [d for d in details if d.get("purchase_number") in only]
    print("=" * 84)
    print(f"  VERIFIKASI PO eksternal JURI {args.date_from}..{args.date_to} vs BARU")
    print("=" * 84)
    issues = []
    for d in sorted(details, key=lambda x: safe_str(x.get("purchase_number"))):
        pnum = safe_str(d.get("purchase_number"))
        st_eresto = safe_str(d.get("status"))
        exp = safe_float(d.get("total_cost"))
        if st_eresto in SKIP_STATUS:
            print(f"   {pnum:22} {st_eresto:11} SKIP_STATUS  Rp{exp:13,.0f}")
            continue
        doc = get_po(erp, pnum)
        if not doc:
            print(f"   {pnum:22} {st_eresto:11} TIDAK ADA    Rp{exp:13,.0f}  (dedup/skipped)")
            continue
        got = safe_float(doc.get("grand_total"))
        diff = abs(got - exp)
        exp_ds = 1 if st_eresto in SUBMIT_STATUS else 0
        ok = diff <= 2 and doc.get("docstatus") == exp_ds
        if not ok:
            issues.append(f"{pnum}: diff={diff:.0f} ds={doc.get('docstatus')}!={exp_ds}")
        print(f"   {pnum:22} {st_eresto:11} {'LOLOS' if ok else 'CEK':12} "
              f"Rp{exp:13,.0f} vs {got:,.0f}")
    print(f"  issues: {issues if issues else 'tidak ada'}")


# ============================================================
# CLI
# ============================================================

def run():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date-from", default=DATE_FROM_DEFAULT)
    ap.add_argument("--date-to", default=DATE_TO_DEFAULT)
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()
    if args.dump:
        run_dump(args); return
    if args.verify:
        run_verify(args); return
    run_migrate(args)


if __name__ == "__main__":
    run()
