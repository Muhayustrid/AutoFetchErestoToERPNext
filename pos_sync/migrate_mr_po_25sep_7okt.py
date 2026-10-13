#!/usr/bin/env python3
"""pos_sync/migrate_mr_po_25sep_7okt.py — Migrasi Material Request (Purchase) &
Purchase Order PT. JUARA ROTI INDONESIA, window 2026-09-25 s/d 2026-10-07.

Keputusan user (2026-10-12):
  - Scope MR: 140 MR tipe **Purchase** dalam window + 2 MR rujukan di luar
    window (`MAT-MR-2026-00448` 21 Sep, `MAT-MR-2026-00583` 24 Sep) supaya
    link PO -> MR utuh.
  - Scope PO: 140 PO dalam window.
  - **Dokumen cancelled DILEWATI** (11 MR + 1 PO) dan dilaporkan.
  - ID identik (rename_doc), idempotensi `title = "ERESTO <name>"`.
  - Normalisasi gudang '- ROPI' -> '- JURI', UOM 'Kg' -> 'kg'.
  - Relink baris PO -> MR BARU (`material_request` + `material_request_item`).
  - Default dry-run; `--execute` untuk menulis.

Pakai:
  .venv/bin/python pos_sync/migrate_mr_po_25sep_7okt.py            # dry-run
  .venv/bin/python pos_sync/migrate_mr_po_25sep_7okt.py --execute
  .venv/bin/python pos_sync/migrate_mr_po_25sep_7okt.py --verify
  .venv/bin/python pos_sync/migrate_mr_po_25sep_7okt.py --only MAT-MR-2026-00593 --execute
"""
import argparse
import datetime as dt
import json
import os
import sys

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env

COMPANY = "PT. JUARA ROTI INDONESIA"
OLD_BASE = "https://rotiropi.j.frappe.cloud"
START, END = "2026-09-25", "2026-10-07"
EXTRA_MR = ["MAT-MR-2026-00448", "MAT-MR-2026-00583"]   # rujukan PO di luar window
AUDIT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "audit_logs")
REPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "Laporan_Migrasi_MR_PO_25Sep_7Okt2026.xlsx")

UOM_MAP = {"Kg": "kg", "KG": "kg"}
DROP_HDR_COMMON = {
    "name", "owner", "creation", "modified", "modified_by", "idx", "docstatus",
    "naming_series", "status", "amended_from", "_user_tags", "_comments",
    "_assign", "_liked_by", "letter_head", "workflow_state", "title",
    "shipping_address", "shipping_address_display", "billing_address",
    "billing_address_display", "dispatch_address", "dispatch_address_display",
    "contact_person", "contact_display", "contact_email", "contact_mobile",
}
DROP_ROW = {
    "name", "owner", "creation", "modified", "modified_by", "idx", "parent",
    "parentfield", "parenttype", "docstatus", "amended_from",
}


def wh_map(v):
    if not v:
        return v
    if v.endswith(" - ROPI"):
        return v[:-7] + " - JURI"
    return v


def acct_map(v):
    """Akun/gudang lama '- ROPI' -> '- JURI' (mis. 4210.000 - HPP Pembelian)."""
    if not v:
        return v
    return v.replace(" - ROPI", " - JURI")


def tax_map(v):
    """Template pajak pembelian LAMA -> BARU (pola migrate_po_pr_1_7_okt.py).

    LAMA: 'Purchase Tax - ROPI'              -> BARU 'Purchase Tax - JURI'
    LAMA: 'Purchase Tax 11% (Include) - ROPI'-> BARU 'Purchase Tax (Termasuk Pajak) - JURI'
    """
    if not v:
        return v
    if "Include" in v or "Termasuk" in v:
        return "Purchase Tax (Termasuk Pajak) - JURI"
    if "Sales" in v:
        return "Sales Tax - JURI"
    return "Purchase Tax - JURI"


def cc_map(v):
    return "Main - JURI" if v else v


def uom_map(v):
    return UOM_MAP.get(v, v)


class Api:
    def __init__(self, base, key, label):
        self.base = base.rstrip("/")
        self.label = label
        self.s = __import__("requests").Session()
        self.s.headers.update({"Authorization": "token " + key})

    def get(self, path, params=None):
        return self._req("GET", path, params=params)

    def post(self, doctype, payload):
        return self._req("POST", "/api/resource/" + doctype, payload=payload)

    def put(self, doctype, name, payload):
        return self._req("PUT", "/api/resource/" + doctype + "/" + name,
                         payload=payload)

    def _req(self, method, path, payload=None, params=None, timeout=90):
        """Retry 3x backoff pada error koneksi / 429 / 5xx (aturan repo)."""
        import time
        last = None
        for attempt in range(1, 4):
            try:
                r = self.s.request(method, self.base + path, json=payload,
                                   params=params, timeout=timeout)
            except Exception as e:                      # ConnectionError, dll
                last = f"{type(e).__name__}: {str(e)[:120]}"
                time.sleep(2 ** attempt)
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code}"
                time.sleep(2 ** attempt)
                continue
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, {"_raw": r.text[:600]}
        print(f"  [!] [{self.label}] {method} {path} gagal 3x: {last}")
        return -1, {"error": last}

    def submit(self, doctype, name):
        return self.put(doctype, name, {"docstatus": 1})

    def cancel(self, doctype, name):
        return self.put(doctype, name, {"docstatus": 2})

    def rename(self, doctype, old, new):
        r = self.s.post(self.base + "/api/method/frappe.client.rename_doc",
                        data={"doctype": doctype, "old_name": old,
                              "new_name": new, "merge": 0}, timeout=90)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"_raw": r.text[:600]}

    def list_all(self, doctype, fields, filters=None, order=None):
        out, start = [], 0
        while True:
            p = {"fields": json.dumps(fields), "limit_page_length": 500,
                 "limit_start": start}
            if filters:
                p["filters"] = json.dumps(filters)
            if order:
                p["order_by"] = order
            st, d = self.get("/api/resource/" + doctype, p)
            rows = d.get("data", []) if st == 200 else []
            if st != 200:
                raise SystemExit(f"[{self.label}] list {doctype} HTTP {st}: "
                                 f"{str(d)[:300]}")
            out += rows
            start += len(rows)
            if len(rows) < 500:
                break
        return out

    def doc(self, doctype, name):
        st, d = self.get("/api/resource/" + doctype + "/" + name)
        if st != 200:
            raise SystemExit(f"[{self.label}] {doctype} {name} HTTP {st}")
        return d["data"]


def ensure_allow_rename(c, doctype):
    c.post("Property Setter", {
        "doctype": "Property Setter", "doctype_or_field": "DocType",
        "doc_type": doctype, "property": "allow_rename",
        "property_type": "Check", "value": "1"})


def sync_suppliers(old, new, codes):
    code_to_name = {}
    for code in codes:
        try:
            code_to_name[code] = old.doc("Supplier", code).get("supplier_name", code)
        except SystemExit:
            code_to_name[code] = code
    target = {}
    for s in new.list_all("Supplier", ["name", "supplier_name"]):
        target[s["name"].lower()] = s["name"]
        if s.get("supplier_name"):
            target[s["supplier_name"].lower()] = s["name"]
    resolved = {}
    for code, name in code_to_name.items():
        if code.lower() in target:
            resolved[code] = target[code.lower()]
        elif name.lower() in target:
            resolved[code] = target[name.lower()]
        else:
            st, d = new.post("Supplier", {
                "doctype": "Supplier", "supplier_name": name,
                "supplier_group": "Local", "supplier_type": "Company"})
            if st == 200:
                resolved[code] = d["data"]["name"]
                target[name.lower()] = d["data"]["name"]
                print(f"  [+] supplier dibuat: {name} -> {d['data']['name']}")
            else:
                print(f"  [!] supplier gagal {name}: {str(d)[:150]}")
                resolved[code] = name
    return resolved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--only", default="", help="satu dokumen (MR atau PO) untuk uji")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    mig = load_env("/tmp/eresto_mig.env")
    new = Api(mig["ERPNEXT_URL"], mig["ERPNEXT_API_KEY"], "BARU")
    old = Api(OLD_BASE, mig["ERPNEXT_OLD_CLOUD_API_KEY"], "LAMA")

    mode = "VERIFY" if args.verify else ("EXECUTE" if args.execute else "DRY-RUN")
    print("=" * 78)
    print(f"MIGRASI MATERIAL REQUEST (PURCHASE) & PURCHASE ORDER — {START} s/d {END}")
    print(f"company: {COMPANY}")
    print(f"BARU: {new.base}  |  LAMA: {OLD_BASE}")
    print(f"mode: {mode}  |  cancelled DILEWATI  |  ID identik  |  idempotensi title=ERESTO <name>")
    print("=" * 78)

    # ---------- tarik sumber
    mr_rows = old.list_all(
        "Material Request",
        ["name", "transaction_date", "material_request_type", "docstatus"],
        [["company", "=", COMPANY],
         ["material_request_type", "=", "Purchase"],
         ["transaction_date", ">=", START],
         ["transaction_date", "<=", END]],
        order="transaction_date asc, name asc")
    po_rows = old.list_all(
        "Purchase Order",
        ["name", "transaction_date", "supplier", "docstatus"],
        [["company", "=", COMPANY],
         ["transaction_date", ">=", START],
         ["transaction_date", "<=", END]],
        order="transaction_date asc, name asc")
    for m in EXTRA_MR:
        try:
            doc = old.doc("Material Request", m)
            if doc.get("material_request_type") == "Purchase":
                mr_rows.append({"name": m,
                                "transaction_date": doc["transaction_date"],
                                "material_request_type": "Purchase",
                                "docstatus": doc.get("docstatus")})
        except SystemExit:
            print(f"  [!] MR rujukan {m} tidak ditemukan di LAMA")

    mr_skip_ds = [r for r in mr_rows if r["docstatus"] != 1]
    po_skip_ds = [r for r in po_rows if r["docstatus"] != 1]
    mr_todo = [r for r in mr_rows if r["docstatus"] == 1]
    po_todo = [r for r in po_rows if r["docstatus"] == 1]
    print(f"\n[1] Sumber: MR Purchase {len(mr_rows)} (submitted {len(mr_todo)}, "
          f"cancelled {len(mr_skip_ds)}) | PO {len(po_rows)} "
          f"(submitted {len(po_todo)}, cancelled {len(po_skip_ds)})")

    # ---------- target existing
    ex_mr = {}
    for r in new.list_all("Material Request", ["name", "title", "docstatus"]):
        ex_mr[r["name"]] = r
        if r.get("title"):
            ex_mr[r["title"]] = r
    ex_po = {}
    for r in new.list_all("Purchase Order", ["name", "title", "docstatus"]):
        ex_po[r["name"]] = r
        if r.get("title"):
            ex_po[r["title"]] = r
    print(f"[2] Target existing: MR {len(ex_mr)} key | PO {len(ex_po)} key")

    # ---------- supplier
    sup_codes = {r["supplier"] for r in po_todo if r.get("supplier")}
    if args.execute and not args.verify:
        print(f"[3] Sync {len(sup_codes)} supplier...")
        sup_map = sync_suppliers(old, new, sup_codes)
    else:
        sup_map = {c: c for c in sup_codes}
        print(f"[3] (dry-run) {len(sup_codes)} supplier akan dipetakan")

    if args.execute and not args.verify:
        ensure_allow_rename(new, "Material Request")
        ensure_allow_rename(new, "Purchase Order")

    # ---------- migrasi MR
    print(f"\n[4] MIGRASI MATERIAL REQUEST ({len(mr_todo)} dokumen)")
    mr_ok, mr_skip, mr_fail = [], [], []
    missing_items = set()
    for idx, r in enumerate(mr_todo, 1):
        name = r["name"]
        if args.only and name != args.only:
            continue
        if args.limit and len(mr_ok) >= args.limit:
            break
        ident = f"ERESTO {name}"
        if name in ex_mr or ident in ex_mr:
            t = ex_mr.get(name) or ex_mr.get(ident)
            mr_skip.append({"name": name, "target": t["name"],
                            "docstatus": t.get("docstatus")})
            continue
        doc = old.doc("Material Request", name)
        payload = {"doctype": "Material Request", "company": COMPANY,
                   "title": ident,
                   "material_request_type": doc.get("material_request_type")}
        for k, v in doc.items():
            if k in DROP_HDR_COMMON or k.startswith("_") or k == "items":
                continue
            payload[k] = v
        if payload.get("set_warehouse"):
            payload["set_warehouse"] = wh_map(payload["set_warehouse"])
        items = []
        for it in doc.get("items", []):
            row = {k: v for k, v in it.items()
                   if k not in DROP_ROW and not k.startswith("_")}
            row["item_code"] = it["item_code"]
            row["uom"] = uom_map(it.get("uom"))
            row["stock_uom"] = uom_map(it.get("stock_uom"))
            if row.get("warehouse"):
                row["warehouse"] = wh_map(row["warehouse"])
            if row.get("cost_center"):
                row["cost_center"] = cc_map(row["cost_center"])
            if row.get("expense_account"):
                row["expense_account"] = acct_map(row["expense_account"])
            for f in ("ordered_qty", "received_qty", "picked_qty",
                      "stock_qty", "actual_qty", "projected_qty",
                      "projected_on_hand", "amount", "page_break",
                      "min_order_qty", "reorder_level", "reorder_qty",
                      "price_list_rate", "image"):
                row.pop(f, None)
            items.append(row)
        payload["items"] = items

        # guard: item master harus ada di BARU
        hilang = [i["item_code"] for i in items
                  if new.get("/api/resource/Item/" + i["item_code"])[0] != 200]
        if hilang:
            print(f"  [SKIP] {name}: item belum ada di BARU -> {sorted(set(hilang))}")
            mr_fail.append({"name": name,
                            "err": f"item belum ada: {sorted(set(hilang))}"})
            for h in hilang:
                missing_items.add(("ITEM", h, name))
            continue

        if not args.execute:
            print(f"  [{idx}/{len(mr_todo)}] DRY-RUN {name:<26} "
                  f"{doc['transaction_date']} {len(items)} baris "
                  f"wh={payload.get('set_warehouse')}")
            mr_ok.append({"name": name, "final": name, "status": "DRY-RUN"})
            continue

        st, d = new.post("Material Request", payload)
        if st != 200:
            print(f"  [FAIL] {name}: HTTP {st} {str(d)[:200]}")
            mr_fail.append({"name": name, "err": str(d)[:300]})
            continue
        tmp = d["data"]["name"]
        st_r, d_r = new.rename("Material Request", tmp, name)
        final = name if st_r == 200 else tmp
        if st_r != 200:
            print(f"  [WARN] rename {tmp} -> {name}: {str(d_r)[:150]}")
        st_s, d_s = new.submit("Material Request", final)
        stat = "Submitted" if st_s == 200 else f"SubmitFail({st_s})"
        print(f"  [OK] MR {final:<26} {stat} ({len(items)} baris)")
        mr_ok.append({"name": name, "final": final, "status": stat})
        ex_mr[final] = {"name": final, "docstatus": 1}

    # ---------- migrasi PO
    print(f"\n[5] MIGRASI PURCHASE ORDER ({len(po_todo)} dokumen)")
    # map MR target: (mr_name, item_code) -> mr item row name
    mr_item_map = {}
    mr_names_used = set()
    for r in po_todo:
        doc = old.doc("Purchase Order", r["name"])
        for it in doc.get("items", []):
            if it.get("material_request"):
                mr_names_used.add(it["material_request"])
    for m in mr_names_used:
        tgt = ex_mr.get(m) or ex_mr.get(f"ERESTO {m}")
        if not tgt:
            continue
        try:
            td = new.doc("Material Request", tgt["name"])
        except SystemExit:
            continue
        for it in td.get("items", []):
            mr_item_map.setdefault((m, it["item_code"]), []).append(it["name"])
    print(f"      indeks MR item: {len(mr_item_map)} pasangan "
          f"({len(mr_names_used)} MR dirujuk)")

    po_ok, po_skip, po_fail = [], [], []
    for idx, r in enumerate(po_todo, 1):
        name = r["name"]
        if args.only and name != args.only:
            continue
        if args.limit and len(po_ok) >= args.limit:
            break
        ident = f"ERESTO {name}"
        if name in ex_po or ident in ex_po:
            t = ex_po.get(name) or ex_po.get(ident)
            po_skip.append({"name": name, "target": t["name"],
                            "docstatus": t.get("docstatus")})
            continue
        doc = old.doc("Purchase Order", name)
        payload = {"doctype": "Purchase Order", "company": COMPANY,
                   "title": ident}
        for k, v in doc.items():
            if k in DROP_HDR_COMMON or k.startswith("_") or k == "items":
                continue
            payload[k] = v
        payload["supplier"] = sup_map.get(doc.get("supplier"), doc.get("supplier"))
        if payload.get("set_warehouse"):
            payload["set_warehouse"] = wh_map(payload["set_warehouse"])
        if payload.get("taxes_and_charges"):
            payload["taxes_and_charges"] = tax_map(payload["taxes_and_charges"])
        payload["taxes"] = []
        items = []
        for it in doc.get("items", []):
            row = {k: v for k, v in it.items()
                   if k not in DROP_ROW and not k.startswith("_")}
            row["item_code"] = it["item_code"]
            row["uom"] = uom_map(it.get("uom"))
            row["stock_uom"] = uom_map(it.get("stock_uom"))
            if row.get("warehouse"):
                row["warehouse"] = wh_map(row["warehouse"])
            if row.get("cost_center"):
                row["cost_center"] = cc_map(row["cost_center"])
            if row.get("expense_account"):
                row["expense_account"] = acct_map(row["expense_account"])
            old_mr = it.get("material_request")
            if old_mr:
                row["material_request"] = old_mr          # nama identik
                cand = mr_item_map.get((old_mr, it["item_code"]), [])
                if cand:
                    row["material_request_item"] = cand[0]
                else:
                    # MR ada tapi barisnya tidak ketemu -> jangan kirim ref patah
                    row.pop("material_request", None)
                    missing_items.add(("MR_ITEM", old_mr, it["item_code"]))
            for f in ("received_qty", "billed_amt", "delivered_qty",
                      "returned_qty", "amount", "net_amount"):
                row.pop(f, None)
            items.append(row)
        payload["items"] = items

        # guard: item master harus ada di BARU (jangan biarkan LinkError di tengah)
        hilang = [i["item_code"] for i in items
                  if new.get("/api/resource/Item/" + i["item_code"])[0] != 200]
        if hilang:
            print(f"  [SKIP] {name}: item belum ada di BARU -> {sorted(set(hilang))}")
            po_fail.append({"name": name,
                            "err": f"item belum ada: {sorted(set(hilang))}"})
            for h in hilang:
                missing_items.add(("ITEM", h, name))
            continue

        if not args.execute:
            linked = sum(1 for i in items if i.get("material_request"))
            print(f"  [{idx}/{len(po_todo)}] DRY-RUN {name:<22} "
                  f"{doc['transaction_date']} {payload['supplier'][:24]:<24} "
                  f"{len(items)} baris, MR-linked {linked}")
            po_ok.append({"name": name, "final": name, "status": "DRY-RUN"})
            continue

        st, d = new.post("Purchase Order", payload)
        if st != 200:
            print(f"  [FAIL] {name}: HTTP {st} {str(d)[:200]}")
            po_fail.append({"name": name, "err": str(d)[:300]})
            continue
        tmp = d["data"]["name"]
        st_r, d_r = new.rename("Purchase Order", tmp, name)
        final = name if st_r == 200 else tmp
        if st_r != 200:
            print(f"  [WARN] rename {tmp} -> {name}: {str(d_r)[:150]}")
        st_s, d_s = new.submit("Purchase Order", final)
        stat = "Submitted" if st_s == 200 else f"SubmitFail({st_s})"
        print(f"  [OK] PO {final:<22} {stat} ({len(items)} baris)")
        po_ok.append({"name": name, "final": final, "status": stat})
        ex_po[final] = {"name": final, "docstatus": 1}

    # ---------- laporan
    print(f"\n[6] Ringkasan: MR ok {len(mr_ok)} skip {len(mr_skip)} "
          f"fail {len(mr_fail)} | PO ok {len(po_ok)} skip {len(po_skip)} "
          f"fail {len(po_fail)}")
    if missing_items:
        print(f"\n    !! {len(missing_items)} item/relasi belum siap di BARU:")
        for kind, a, b in sorted(missing_items):
            print(f"       {kind:<8} {a:<26} {b}")
    if mr_skip_ds or po_skip_ds:
        print(f"    dilewati karena cancelled: MR {len(mr_skip_ds)} "
              f"({[r['name'] for r in mr_skip_ds]})")
        print(f"                                 PO {len(po_skip_ds)} "
              f"({[r['name'] for r in po_skip_ds]})")

    if args.execute:
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        fill = PatternFill("solid", start_color="D9EAF7")
        bold = Font(bold=True)
        for sheet, rows, cols in (
            ("Rekap_MR", mr_ok + mr_skip + mr_fail, ["name", "final", "status"]),
            ("Rekap_PO", po_ok + po_skip + po_fail, ["name", "final", "status"]),
            ("Skipped_Cancelled", mr_skip_ds + po_skip_ds, ["name"]),
            ("Failed", mr_fail + po_fail, ["name", "err"]),
        ):
            ws = wb.create_sheet(sheet)
            ws.append(cols)
            for c in range(1, len(cols) + 1):
                ws.cell(1, c).fill = fill
                ws.cell(1, c).font = bold
            for r in rows:
                ws.append([r.get(c) for c in cols])
            ws.freeze_panes = "A2"
            for i, c in enumerate(cols, 1):
                ws.column_dimensions[get_column_letter(i)].width = 34
        wb.save(REPORT)
        print(f"    laporan -> {REPORT}")

    if args.execute and not (mr_fail or po_fail):
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs(AUDIT_DIR, exist_ok=True)
        with open(os.path.join(AUDIT_DIR, f"backup_mr_po_25sep_7okt_{ts}.json"), "w") as f:
            json.dump({"ts": ts, "mr_ok": mr_ok, "po_ok": po_ok,
                       "mr_skip": mr_skip, "po_skip": po_skip}, f, indent=1,
                      default=str)

    if not args.execute:
        print("\n# DRY-RUN — tidak ada yang ditulis. Tambah --execute.")


if __name__ == "__main__":
    main()
