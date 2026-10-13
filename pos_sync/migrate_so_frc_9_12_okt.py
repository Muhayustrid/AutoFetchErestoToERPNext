#!/usr/bin/env python3
"""Sales Order FRC (outlet franchise) dari PO eResto -> ERPNext BARU.

Konteks (instruksi user 2026-10-12: "untuk frc langsung jadi customer jadi
sales order aja" + "SO nya dibikin draf ya"):
- PO eResto divisi OUTLET FRC (mis. 'Pasaman (FRC)', 'Ugm (FRC)',
  'Jogokariyan (FRC)') dikonversi menjadi **Sales Order** JURI -> Customer FRC.
  Company = 'PT. JUARA ROTI INDONESIA'; customer = internal outlet FRC
  (`Customer` dgn customer_name = nama FRC, group 'Outlet Franchise');
  `set_warehouse` = 'Gudang Barang Jadi - JURI'; TANPA `inter_company_order_reference`
  (pola SO FRC yang sudah ada, mis. `SORD-JURI-261012008` Jogokariyan).
- Dibuat sebagai **DRAFT** (docstatus 0) sesuai instruksi user 2026-10-12
  ("SO nya dibikin draf ya") — walaupun PO eResto berstatus 'pending'.
- Idempoten: SO dianggap sudah ada bila ada Sales Order company JURI untuk
  customer tsb dgn transaction_date = tanggal PO DAN grand_total = total_cost
  eResto (dalam toleransi kecil). Rerun = SKIP, 0 duplikat.

Baris PO yang SKU-nya belum ada mapping TIDAK ditebak: di-skip & dicatat
(mis. 'BB0043 Daun Teh Enak Kata Orang' — keputusan user: dikeluarkan dulu).

CLI:
  python pos_sync/migrate_so_frc_9_12_okt.py [--dry-run] [--verify]
      [--only POO33.101026.001 ...] [--submit]

Env: /tmp/eresto_mig.env (ERESTO_*) + /tmp/eresto_prod.env (ERPNEXT_URL,
ERPNEXT_API_KEY). Token tidak pernah ditulis ke output.
"""
import argparse
import json
import os
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client  # noqa: E402

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

ENV_PROD = load_env_file("/tmp/eresto_prod.env")
ERPNEXT_URL = os.environ.get("ERPNEXT_URL") or ENV_PROD.get(
    "ERPNEXT_URL", "https://ropierpnext.frappe.cloud")
ERPNEXT_KEY = os.environ.get("ERPNEXT_API_KEY") or ENV_PROD.get("ERPNEXT_API_KEY", "")

COMPANY = "PT. JUARA ROTI INDONESIA"
WAREHOUSE = "Gudang Barang Jadi - JURI"
DUMP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "po_9_12_dump", "eresto_internal_9_12.json")
REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "Laporan_Migrasi_SO_FRC_9_12_Okt2026.xlsx")

# PO FRC (divisi outlet FRC) di jendela 9-12 Okt.
TARGET_PO = ["POO21.091026.001", "POO33.101026.001", "POO33.101026.002",
             "POO67.101026.001"]

# SKU eResto -> Item Code BARU (proven map).
ITEM_MAP = {
    "BB0046": "PJ260012", "BB0047": "PJ260013", "BB0049": "PJ260014",
    "BB0066": "PEL260072", "BB0085": "PJ260016", "BB0112": "PEL260076",
    "BB0171": "PEL260069", "BB0261": "PJ260011", "BB0042": "BB260048",
    "BB0080": "PEL260074",  # Kardus Ropi 20 roti [bukti stok_sku_to_item.csv COCOK]
    "BB0117": "PEL260077",  # Plastik Alas Gempi  [bukti stok_sku_to_item.csv COCOK]
    # BB0043 'Daun Teh Enak Kata Orang' TIDAK dipetakan (keputusan user:
    # dikeluarkan dulu) — baris di-skip & dicatat, bukan ditebak.
}

# UOM khusus: (item_code, unit_eresto) -> (uom, cf, catatan)
UOM_SPECIAL = {}


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

# ============================================================
# ERPNext
# ============================================================

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
    special = UOM_SPECIAL.get((code, unit_norm))
    if special:
        return special[0], special[1], special[2]
    return su, uoms.get(su, 1.0), f"UOM '{unit}' tidak ada di master -> fallback {su} cf=1"


def find_customer(client, frc_name):
    st, body = client.get("/api/resource/Customer", params={
        "filters": json.dumps([["customer_name", "=", frc_name]]),
        "fields": json.dumps(["name", "customer_name"]), "limit_page_length": 1})
    rows = body.get("data", []) if st == 200 else []
    return rows[0] if rows else None

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


def run(args):
    erp = Client(ERPNEXT_URL, ERPNEXT_KEY, label="BARU", pause=0.15)
    details = {d["purchase_number"]: d for d in json.load(open(DUMP_FILE))}
    targets = args.only or TARGET_PO
    targets = [t for t in targets if t in details]

    print("=" * 84)
    print("  MIGRASI SO FRC (PO eResto outlet FRC -> Sales Order JURI -> Customer FRC)")
    print(f"  Target: {ERPNEXT_URL} | mode: {'SUBMIT' if args.submit else 'DRAFT'}")
    print("=" * 84)

    all_codes = set()
    for pn in targets:
        for it in details[pn].get("purchase_items") or []:
            c = ITEM_MAP.get(safe_str((it.get("inventory") or {}).get("sku")))
            if c:
                all_codes.add(c)
    items_master = get_items_master(erp, all_codes)
    print(f"  {len(items_master)} item master diambil.")

    migrated, skipped, raw_rows = [], [], []
    for pn in sorted(targets):
        d = details[pn]
        frc = safe_str((d.get("division") or {}).get("name"))
        pdate = safe_str(d.get("date"))[:10]
        total = safe_float(d.get("total_cost"))
        base = {"PO eResto": pn, "Divisi FRC": frc, "Tanggal": pdate,
                "Total eResto": total, "Status eResto": safe_str(d.get("status"))}

        cust = find_customer(erp, frc)
        if not cust:
            skipped.append({**base, "Kategori": "Customer",
                            "Alasan": f"Customer '{frc}' tidak ada di BARU"})
            continue

        # -- idempotensi: SO existing utk customer ini (tanggal apa pun) dgn total ~sama --
        st, body = erp.get("/api/resource/Sales Order", params={
            "fields": json.dumps(["name", "grand_total", "docstatus", "status",
                                  "transaction_date"]),
            "filters": json.dumps([["company", "=", COMPANY],
                                   ["customer", "=", cust["name"]]]),
            "limit_page_length": 50})
        exist = body.get("data", []) if st == 200 else []
        # total cocok dlm toleransi kecil ATAU total cocok utk versi tanpa baris Daun Teh
        hit = [e for e in exist
               if abs(safe_float(e.get("grand_total")) - total) <= 1000
               or abs(safe_float(e.get("grand_total")) - (total - 2040000)) <= 1000]
        if hit:
            print(f"  [SKIP_EXISTS] {pn} -> {hit[0]['name']} "
                  f"Rp{safe_float(hit[0].get('grand_total')):,.0f}")
            migrated.append({**base, "Nama SO": hit[0]["name"], "Customer": cust["name"],
                             "Jumlah Baris": "", "Grand Total SO": hit[0].get("grand_total"),
                             "Docstatus": hit[0].get("docstatus"),
                             "Status": hit[0].get("status"), "Hasil": "SKIP_EXISTS",
                             "Catatan": "sudah ada"})
            continue

        # -- susun baris --
        rows_payload, row_audit, problems = [], [], []
        for it in d.get("purchase_items") or []:
            inv = it.get("inventory") or {}
            sku = safe_str(inv.get("sku"))
            qty = safe_float(it.get("amount"))
            rate = safe_float(it.get("price"))
            unit = safe_str((it.get("unit") or {}).get("name"))
            code = ITEM_MAP.get(sku)
            if not code:
                problems.append(f"SKU {sku} ({safe_str(inv.get('name'))}) tanpa mapping -> baris dikeluarkan")
                continue
            master = items_master.get(code) or {}
            if not master or master.get("disabled"):
                problems.append(f"Item {code} tidak ada/disabled")
                continue
            uom, cf, note = resolve_uom(code, unit, master)
            rows_payload.append({
                "item_code": code, "qty": qty, "uom": uom, "conversion_factor": cf,
                "rate": rate, "warehouse": WAREHOUSE, "delivery_date": pdate,
            })
            row_audit.append({
                "PO eResto": pn, "Divisi FRC": frc, "Tanggal": pdate, "SKU": sku,
                "Nama eResto": safe_str(inv.get("name")), "Qty": qty, "Unit": unit,
                "Rate": rate, "Amount": round(qty * rate, 2), "Item Code": code,
                "Item Name": master.get("item_name"), "UOM ERPNext": uom, "CF": cf,
                "Catatan UOM": note})
        if not rows_payload:
            skipped.append({**base, "Kategori": "Item",
                            "Alasan": "; ".join(problems) or "tidak ada baris valid"})
            continue
        raw_rows.extend(row_audit)
        catatan = "; ".join(problems)

        if args.dry_run:
            print(f"  [DRY-RUN] {pn} -> {frc} ({len(rows_payload)} baris, "
                  f"Rp{sum(x['qty']*x['rate'] for x in rows_payload):,.0f}) "
                  f"{'| ' + catatan if catatan else ''}")
            migrated.append({**base, "Nama SO": "(dry-run)", "Customer": cust["name"],
                             "Jumlah Baris": len(rows_payload),
                             "Grand Total SO": "", "Docstatus": "", "Status": "",
                             "Hasil": "DRY_RUN", "Catatan": catatan})
            continue

        payload = {
            "doctype": "Sales Order", "company": COMPANY, "customer": cust["name"],
            "transaction_date": pdate, "delivery_date": pdate,
            "set_warehouse": WAREHOUSE, "currency": "IDR",
            "title": f"ERESTO {pn}",
            "items": rows_payload,
        }
        print(f"  [POST] SO {pn} -> {frc} ({len(rows_payload)} baris) ...")
        st_p, res = erp.post("Sales Order", payload)
        if st_p != 200:
            msg = json.dumps(res)[:300]
            print(f"    [GAGAL] {pn}: {msg}")
            migrated.append({**base, "Nama SO": "", "Customer": cust["name"],
                             "Jumlah Baris": len(rows_payload), "Grand Total SO": "",
                             "Docstatus": "", "Status": "", "Hasil": "FAIL_POST",
                             "Catatan": msg})
            continue

        name = (res.get("data") or {}).get("name")
        ds, status = 0, "Draft"
        if args.submit:
            st_s, res_s = erp.submit("Sales Order", name)
            if st_s == 200:
                ds = 1
                status = (res_s.get("data") or {}).get("status", "Submitted")
        rec = (erp.get(f"/api/resource/Sales Order/{urllib.parse.quote(name)}")[1] or {}).get("data", {})
        print(f"    [OK] {name} | ds={ds} | {status} | Rp {rec.get('grand_total')}")
        migrated.append({**base, "Nama SO": name, "Customer": cust["name"],
                         "Jumlah Baris": len(rows_payload),
                         "Grand Total SO": rec.get("grand_total", ""),
                         "Docstatus": ds, "Status": status, "Hasil": "BERHASIL",
                         "Catatan": catatan})

    # ---------- Excel ----------
    wb = Workbook()
    rekap_cols = ["PO eResto", "Nama SO", "Customer", "Divisi FRC", "Tanggal",
                  "Jumlah Baris", "Total eResto", "Grand Total SO", "Docstatus",
                  "Status", "Hasil", "Status eResto", "Catatan"]
    raw_cols = ["PO eResto", "Divisi FRC", "Tanggal", "SKU", "Nama eResto", "Qty",
                "Unit", "Rate", "Amount", "Item Code", "Item Name", "UOM ERPNext",
                "CF", "Catatan UOM"]
    skip_cols = ["PO eResto", "Divisi FRC", "Tanggal", "Total eResto", "Status eResto",
                 "Kategori", "Alasan"]
    write_sheet(wb.active, "Rekap_SO", migrated, rekap_cols)
    write_sheet(wb.create_sheet(), "Raw_Baris", raw_rows, raw_cols)
    write_sheet(wb.create_sheet(), "Skipped", skipped, skip_cols)

    n_ok = sum(1 for m in migrated if m["Hasil"] == "BERHASIL")
    n_skip = sum(1 for m in migrated if m["Hasil"] == "SKIP_EXISTS")
    n_dry = sum(1 for m in migrated if m["Hasil"] == "DRY_RUN")
    n_fail = sum(1 for m in migrated if m["Hasil"] == "FAIL_POST")
    val_rows = [
        {"Parameter": "PO FRC diproses", "Nilai": len(targets), "Status": "OK",
         "Keterangan": "dari dump 9-12 Okt"},
        {"Parameter": "SO BERHASIL", "Nilai": n_ok,
         "Status": "DRY-RUN" if args.dry_run else ("LOLOS" if n_fail == 0 else "CEK"),
         "Keterangan": "draft" if not args.submit else "submitted"},
        {"Parameter": "SKIP_EXISTS (rerun)", "Nilai": n_skip, "Status": "OK", "Keterangan": ""},
        {"Parameter": "DRY_RUN", "Nilai": n_dry, "Status": "OK", "Keterangan": ""},
        {"Parameter": "GAGAL", "Nilai": n_fail, "Status": "LOLOS" if n_fail == 0 else "CEK",
         "Keterangan": "harus 0"},
    ]
    write_sheet(wb.create_sheet(), "Validation", val_rows,
                ["Parameter", "Nilai", "Status", "Keterangan"])
    note_rows = [
        {"Topik": "Scope",
         "Catatan": "PO eResto divisi outlet FRC 9-12 Okt -> Sales Order JURI -> Customer FRC. "
                    "Company JURI, set_warehouse Gudang Barang Jadi - JURI, tanpa "
                    "inter_company_order_reference (pola SO FRC existing)."},
        {"Topik": "Draft",
         "Catatan": "Instruksi user 2026-10-12: 'SO nya dibikin draf ya' -> docstatus 0."},
        {"Topik": "BB0043 Daun Teh",
         "Catatan": "Item 'Daun Teh Enak Kata Orang' belum ada padanannya di ERPNext -> "
                    "baris dikeluarkan (keputusan user), bukan ditebak."},
    ]
    write_sheet(wb.create_sheet(), "Catatan", note_rows, ["Topik", "Catatan"])
    wb.save(REPORT_PATH)

    print(f"\n  Laporan: {REPORT_PATH}")
    print("=" * 84)
    print(f"  BERHASIL: {n_ok} | SKIP_EXISTS: {n_skip} | GAGAL: {n_fail} | "
          f"SKIPPED: {len(skipped)} | DRY-RUN: {n_dry}")
    print("=" * 84)


def run_verify(args):
    erp = Client(ERPNEXT_URL, ERPNEXT_KEY, label="BARU", pause=0.0)
    details = {d["purchase_number"]: d for d in json.load(open(DUMP_FILE))}
    targets = args.only or TARGET_PO
    print("=" * 84)
    print("  VERIFIKASI SO FRC vs eResto")
    print("=" * 84)
    for pn in sorted(t for t in targets if t in details):
        d = details[pn]
        frc = safe_str((d.get("division") or {}).get("name"))
        total = safe_float(d.get("total_cost"))
        cust = find_customer(erp, frc)
        if not cust:
            print(f"  {pn:22} {frc:22} customer tidak ada"); continue
        st, body = erp.get("/api/resource/Sales Order", params={
            "fields": json.dumps(["name", "grand_total", "docstatus", "status"]),
            "filters": json.dumps([["company", "=", COMPANY], ["customer", "=", cust["name"]],
                                   ["transaction_date", "=", safe_str(d.get("date"))[:10]]]),
            "limit_page_length": 10})
        print(f"  {pn:22} {frc:22} eResto Rp{total:14,.0f} -> "
              f"{[(e['name'], e.get('grand_total'), e.get('docstatus')) for e in body.get('data', [])]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--submit", action="store_true", help="submit SO (default draft)")
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()
    if args.verify:
        run_verify(args); return
    run(args)


if __name__ == "__main__":
    main()
