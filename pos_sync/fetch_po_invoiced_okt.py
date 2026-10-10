"""Tarik PO eResto yang DIFAKTUR per Oktober 2026 (PO sebelum Okt, faktur Okt).

Sumber: eResto `/v2/purchase_invoices` (jangkarnya tanggal faktur / transaction_date)
  -> ambil `purchase_id` tiap faktur -> `/v2/purchases/{id}/detail` untuk tanggal PO.
Target: daftar PO dengan `date` < 2026-10-01 tetapi punya >=1 faktur bulan Oktober.
Semua supplier/company ikut (bukan hanya outlet -> JURI).

Output: pos_sync/Laporan_PO_Diinvoice_Okt2026.xlsx
  Sheet: Raw_Faktur_Okt (semua faktur Okt), Raw_PO_Sebelum_Okt (PO target),
  Raw_Items (baris item PO target), Raw_PO_Okt (referensi: PO yang lahir Okt),
  Skipped, Validation.
Cache: pos_sync/po_okt_dump/ (--refresh untuk tarik ulang).

eResto READ-ONLY (hanya GET). Kredensial dari /tmp/eresto_mig.env.
"""
import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HERE = os.path.dirname(os.path.abspath(__file__))
DUMP_DIR = os.path.join(HERE, "po_okt_dump")
REPORT = os.path.join(HERE, "Laporan_PO_Diinvoice_Okt2026.xlsx")
ENV_FILE = "/tmp/eresto_mig.env"

BASE = "https://ropi.eresto.id"
PER_PAGE = 200
MAX_WORKERS = 10
TEMP_HTTP = {429, 500, 502, 503, 504}
OKT_FROM, OKT_TO = "2026-10-01", "2026-10-31"

_lock = threading.Lock()


def log(msg):
    with _lock:
        print(msg, flush=True)


def num(v):
    try:
        return float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def load_env(path=ENV_FILE):
    d = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("ERESTO_TOKEN", "ERESTO_EMAIL", "ERESTO_USER_ID"):
        if not d.get(k):
            raise SystemExit(f"env {k} kosong di {path}")
    return d


def jdump(name, obj):
    os.makedirs(DUMP_DIR, exist_ok=True)
    with open(os.path.join(DUMP_DIR, name), "w") as f:
        json.dump(obj, f, default=str)


def jload(name):
    p = os.path.join(DUMP_DIR, name)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


class Eresto:
    def __init__(self, env):
        self.token = env["ERESTO_TOKEN"]
        self.user_id = env["ERESTO_USER_ID"]
        self.s = requests.Session()
        self.s.headers.update({
            "accept": "application/json, text/plain, */*",
            "authorization": f"Token token={self.token}, email={env['ERESTO_EMAIL']}",
            "referer": "https://ropi.eresto.id/manager/v2/index.html",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "cache-control": "no-cache", "pragma": "no-cache",
        })

    def get(self, path, params=None):
        params = dict(params or {})
        params.update({"current_user_id": self.user_id, "domain": "ropi",
                       "token": self.token})
        last = None
        for a in range(1, 4):
            try:
                r = self.s.get(BASE + path, params=params, timeout=90)
                if r.status_code in TEMP_HTTP:
                    last = f"HTTP {r.status_code}"
                    time.sleep(2 ** a)
                    continue
                r.raise_for_status()
                return r.json(), ""
            except (requests.RequestException, ValueError) as e:
                last = str(e)[:150]
                time.sleep(2 ** a)
        return None, last


# ------------------------------------------------------------------ fetch
def fetch_invoices(er, dfrom, dto):
    rows, page = [], 1
    while True:
        d, err = er.get("/v2/purchase_invoices", {
            "transaction_date[geq]": f"{dfrom} 00:00:00.000",
            "transaction_date[leq]": f"{dto} 23:59:59.999",
            "division_id": "", "page": page, "per_page": PER_PAGE,
            "sort[property]": "transaction_date", "sort[order]": "asc",
        })
        if d is None:
            raise SystemExit(f"[faktur] halaman {page} gagal: {err}")
        batch = d.get("purchase_invoices") or []
        rows.extend(batch)
        meta = d.get("meta") or {}
        log(f"[faktur] halaman {page}: {len(batch)} (total {meta.get('total_count')})")
        if not meta.get("next_page") or len(batch) < PER_PAGE:
            break
        page = meta["next_page"]
    seen, dedup = set(), []
    for r in rows:
        if r.get("id") in seen:
            continue
        seen.add(r.get("id"))
        dedup.append(r)
    return dedup


def fetch_po_detail(er, pid, po_number=""):
    for attempt in range(1, 4):
        d, err = er.get(f"/v2/purchases/{pid}/detail")
        if d is not None:
            p = d.get("purchase_detail") or {}
            if p and p.get("id"):
                items = p.get("purchase_items") or []
                if not items and num(p.get("total_cost")) != 0:
                    err = "purchase_items kosong padahal total != 0"
                else:
                    return p, ""
            else:
                err = "payload purchase_detail kosong"
        log(f"  [po] {po_number or pid} percobaan {attempt} gagal: {err}")
        time.sleep(0.8 * attempt)
    return None, err


# ------------------------------------------------------------------ excel
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
    for col in ws.columns:
        w = max(len(str(c.value or "")) for c in col)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(w + 2, 45)


def write_report(faktur_rows, po_target, po_okt, item_rows, skipped, checks):
    wb = Workbook()
    s = wb.active
    s.title = "Raw_Faktur_Okt"
    s.append(["invoice_number", "transaction_date", "status", "total_amount",
              "balance_due", "po_number", "po_id", "division", "supplier",
              "vendor_ref_no"])
    for r in faktur_rows:
        s.append([r["transaction_number"], str(r.get("transaction_date"))[:10],
                  r.get("status"), num(r.get("total_amount")),
                  num(r.get("balance_due")), r["po_number"], r["purchase_id"],
                  r.get("division"), r.get("supplier"), r.get("vendor_ref_no")])

    s2 = wb.create_sheet("Raw_PO_Sebelum_Okt")
    s2.append(["po_number", "po_id", "tanggal_po", "status", "invoice_status",
               "payment_status", "total_cost", "division", "supplier",
               "faktur_okt_count", "faktur_okt_numbers", "faktur_okt_dates",
               "faktur_okt_total", "faktur_pertama_po"])
    for p in po_target:
        s2.append([p["po_number"], p["po_id"], p["date"], p["status"],
                   p["invoice_status"], p["payment_status"], p["total_cost"],
                   p["division"], p["supplier"], p["faktur_okt_count"],
                   p["faktur_okt_numbers"], p["faktur_okt_dates"],
                   p["faktur_okt_total"], p["faktur_pertama"]])

    it = wb.create_sheet("Raw_Items")
    it.append(["po_number", "tanggal_po", "sku", "item_name", "qty", "unit",
               "price", "total_price", "supplier", "division"])
    for r in item_rows:
        it.append([r["po_number"], r["tanggal_po"], r["sku"], r["item_name"],
                   r["qty"], r["unit"], r["price"], r["total_price"],
                   r["supplier"], r["division"]])

    s3 = wb.create_sheet("Raw_PO_Okt")
    s3.append(["po_number", "po_id", "tanggal_po", "status", "invoice_status",
               "total_cost", "division", "faktur_okt_numbers"])
    for p in po_okt:
        s3.append([p["po_number"], p["po_id"], p["date"], p["status"],
                   p["invoice_status"], p["total_cost"], p["division"],
                   p["faktur_okt_numbers"]])

    s4 = wb.create_sheet("Skipped")
    s4.append(["jenis", "kunci", "alasan"])
    for r in skipped:
        s4.append([r["jenis"], r["kunci"], r["alasan"]])

    s5 = wb.create_sheet("Validation")
    s5.append(["check", "hasil", "status"])
    for c in checks:
        s5.append(list(c))

    for ws in (s, s2, it, s3, s4, s5):
        style(ws)
    wb.save(REPORT)


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date-from", default=OKT_FROM)
    ap.add_argument("--date-to", default=OKT_TO)
    ap.add_argument("--refresh", action="store_true",
                    help="abaikan cache dump, tarik ulang dari eResto")
    args = ap.parse_args()

    env = load_env()
    er = Eresto(env)

    # 1. faktur bulan Oktober
    invoices = None if args.refresh else jload("invoices_okt.json")
    if invoices is None:
        print(f"[faktur] tarik /v2/purchase_invoices {args.date_from}..{args.date_to}")
        invoices = fetch_invoices(er, args.date_from, args.date_to)
        jdump("invoices_okt.json", invoices)
    print(f"[faktur] total {len(invoices)} faktur "
          f"(Rp{sum(num(r.get('total_amount')) for r in invoices):,.0f})")

    # 2. PO unik + grupkan faktur
    skipped = []
    by_po = {}
    for r in invoices:
        pid = r.get("purchase_id")
        if not pid:
            skipped.append({"jenis": "faktur_tanpa_po",
                            "kunci": r.get("transaction_number", r.get("id")),
                            "alasan": "quick purchase / tanpa referensi PO"})
            continue
        by_po.setdefault(pid, []).append(r)
    print(f"[po] {len(by_po)} PO unik dirujuk faktur Okt; "
          f"{len(skipped)} faktur tanpa PO")

    # 3. detail PO (paralel, cache)
    details = {} if args.refresh else (jload("po_details.json") or {})
    todo = [pid for pid in by_po if pid not in details]
    if todo:
        print(f"[po] ambil detail {len(todo)} PO (paralel {MAX_WORKERS}) ...")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = {ex.submit(fetch_po_detail, er, pid,
                              by_po[pid][0].get("purchase", {}).get("purchase_number", "")): pid
                    for pid in todo}
            done = 0
            for f in as_completed(futs):
                pid = futs[f]
                p, err = f.result()
                done += 1
                if p is None:
                    skipped.append({"jenis": "po_detail_gagal", "kunci": pid,
                                    "alasan": err})
                else:
                    details[pid] = p
                if done % 20 == 0 or done == len(todo):
                    log(f"  [po] {done}/{len(todo)}")
        jdump("po_details.json", details)
    else:
        print(f"[po] pakai cache: {len(details)} detail PO")

    # 4. klasifikasi: PO sebelum Okt vs PO lahir Okt (referensi)
    po_okt_from = args.date_from  # 2026-10-01
    po_target, po_okt = [], []
    for pid, invs in sorted(by_po.items()):
        p = details.get(pid)
        if not p:
            continue
        invs_sorted = sorted(invs, key=lambda x: str(x.get("transaction_date")))
        row = {
            "po_number": p.get("purchase_number", ""),
            "po_id": pid,
            "date": str(p.get("date", ""))[:10],
            "status": p.get("status", ""),
            "invoice_status": p.get("invoice_status", ""),
            "payment_status": p.get("payment_status", ""),
            "total_cost": num(p.get("total_cost")),
            "division": (p.get("division") or {}).get("name", ""),
            "supplier": (p.get("supplier") or {}).get("name", ""),
            "faktur_okt_count": len(invs_sorted),
            "faktur_okt_numbers": ", ".join(x.get("transaction_number", "") for x in invs_sorted),
            "faktur_okt_dates": ", ".join(str(x.get("transaction_date", ""))[:10] for x in invs_sorted),
            "faktur_okt_total": sum(num(x.get("total_amount")) for x in invs_sorted),
            "faktur_pertama": "",
        }
        all_inv = p.get("purchase_invoices") or []
        if all_inv:
            first = min(all_inv, key=lambda x: str(x.get("transaction_date")))
            row["faktur_pertama"] = (f"{first.get('transaction_number', '')}"
                                     f" ({str(first.get('transaction_date', ''))[:10]})")
        if row["date"] and row["date"] < po_okt_from:
            po_target.append(row)
        else:
            po_okt.append(row)

    # 5. baris item PO target
    item_rows = []
    for p in po_target:
        det = details[p["po_id"]]
        for it in det.get("purchase_items") or []:
            inv = it.get("inventory") or {}
            unit = it.get("unit") or {}
            item_rows.append({
                "po_number": p["po_number"], "tanggal_po": p["date"],
                "sku": inv.get("sku") or it.get("sku") or "",
                "item_name": inv.get("name") or it.get("name") or "",
                "qty": num(it.get("amount")),
                "unit": unit.get("name") or it.get("unit_name") or "",
                "price": num(it.get("price")),
                "total_price": num(it.get("total_price")),
                "supplier": p["supplier"], "division": p["division"],
            })

    # 6. faktur sheet + validasi
    faktur_rows = []
    for r in invoices:
        pur = r.get("purchase") or {}
        faktur_rows.append({
            "transaction_number": r.get("transaction_number", ""),
            "transaction_date": r.get("transaction_date", ""),
            "status": r.get("status", ""),
            "total_amount": r.get("total_amount"),
            "balance_due": r.get("balance_due"),
            "po_number": pur.get("purchase_number", ""),
            "purchase_id": r.get("purchase_id", ""),
            "division": (r.get("division") or {}).get("name", ""),
            "supplier": (r.get("supplier") or {}).get("name", ""),
            "vendor_ref_no": r.get("vendor_ref_no", ""),
        })

    n_po_target = len(po_target)
    sum_po = sum(p["total_cost"] for p in po_target)
    sum_faktur = sum(p["faktur_okt_total"] for p in po_target)
    n_no_items = sum(1 for p in po_target
                     if not (details[p["po_id"]].get("purchase_items") or []))
    checks = [
        ("Faktur Okt ditarik", f"{len(invoices)} faktur", "OK"),
        ("PO unik dirujuk", f"{len(by_po)} PO", "OK"),
        ("PO target (sebelum Okt, difaktur Okt)", f"{n_po_target} PO",
         "OK" if n_po_target else "KOSONG"),
        ("PO target punya baris item", f"{n_no_items} tanpa item",
         "OK" if n_no_items == 0 else "CATATAN"),
        ("Total PO target", f"Rp{sum_po:,.0f}", "OK"),
        ("Total faktur Okt atas PO target", f"Rp{sum_faktur:,.0f}", "OK"),
        ("Faktur tanpa PO (quick purchase)", f"{len(skipped)}", "CATATAN"),
        ("PO lahir Okt (referensi, bukan target)", f"{len(po_okt)} PO", "CATATAN"),
    ]
    write_report(faktur_rows, po_target, po_okt, item_rows, skipped, checks)

    print()
    for c in checks:
        print(f"  {c[2]}: {c[0]} ({c[1]})")
    print(f"\n[done] {n_po_target} PO sebelum Okt difaktur Okt; laporan: {REPORT}")


if __name__ == "__main__":
    main()
