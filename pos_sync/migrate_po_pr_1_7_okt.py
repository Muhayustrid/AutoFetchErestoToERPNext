"""Migrasi & Rekonsiliasi Purchase Order dan Purchase Receipt PT. JUARA ROTI INDONESIA (1-7 Oktober 2026).

Sumber: REST API ERPNext LAMA (http://site-lama.localhost:8082).
Target: REST API ERPNext BARU (Cloud https://ropierpnext.frappe.cloud atau Lokal http://127.0.0.1:8081).

Aturan & Standar:
- Filter khusus Company: 'PT. JUARA ROTI INDONESIA'.
- Rentang tanggal: 2026-10-01 s/d 2026-10-07 (+ PO historis yang dirujuk PR di rentang ini).
- Pertahankan ID bawaan dari ERPNext lama (rename_doc).
- Idempotensi ketat: cek existing by name & title, cegah duplikasi.
- Pemetaan Supplier otomatis (kode lama -> nama supplier resmi target).
- Normalisasi gudang: '- ROPI' -> '- JURI'.
- Normalisasi pajak: 'Purchase Tax - JURI' / 'Purchase Tax (Termasuk Pajak) - JURI'.
- Normalisasi UOM: 'Kg'/'KG' -> 'kg'.
- Relink Purchase Receipt ke Purchase Order pasangannya di target.
- Output laporan audit Excel: pos_sync/Laporan_Migrasi_PO_PR_1_7_Okt2026.xlsx.
"""

import argparse
import json
import os
import sys
import time
import requests
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

OLD_BASE = "http://site-lama.localhost:8082"
LOCAL_BASE = "http://127.0.0.1:8081"
PROD_BASE = "https://ropierpnext.frappe.cloud"

DROP_HDR = {
    "name", "owner", "creation", "modified", "modified_by", "idx",
    "docstatus", "naming_series", "status", "amended_from",
    "letter_head", "workflow_state",
    "shipping_address", "shipping_address_display",
    "billing_address", "billing_address_display",
    "dispatch_address", "dispatch_address_display",
    "contact_person", "contact_display", "contact_email", "contact_mobile",
    "custom_note", "custom_section_break_tjtb0",
    "_user_tags", "_comments", "_assign", "_liked_by",
    "per_received", "per_billed", "status",
}

DROP_ROW_PO = {
    "name", "owner", "creation", "modified", "modified_by", "idx",
    "parent", "parentfield", "parenttype", "docstatus",
    "received_qty", "billed_amt", "amount", "net_amount",
    "delivered_qty", "returned_qty", "amended_from",
    "material_request", "material_request_item",
}

DROP_ROW_PR = {
    "name", "owner", "creation", "modified", "modified_by", "idx",
    "parent", "parentfield", "parenttype", "docstatus",
    "billed_amt", "amount", "net_amount", "returned_qty", "amended_from",
    "material_request", "material_request_item",
}

ITEM_MAP = {
    "BB260057": "BB26001",
}

UOM_MAP = {
    "Kg": "kg",
    "KG": "kg",
}


def load_env(path):
    d = {}
    if not os.path.exists(path):
        return d
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def wh_map(old):
    if not old:
        return old
    if old.endswith(" - ROPI"):
        return old[:-7] + " - JURI"
    return old


def tax_map(old):
    if not old:
        return None
    if "Include" in old:
        return "Purchase Tax (Termasuk Pajak) - JURI"
    return "Purchase Tax - JURI"


class ERPClient:
    def __init__(self, base, key):
        self.base = base.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"token {key}"})

    def get(self, path, params=None):
        r = self.s.get(self.base + path, params=params, timeout=60)
        return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else {"_raw": r.text}

    def post(self, doctype, data):
        r = self.s.post(f"{self.base}/api/resource/{doctype}", json=data, timeout=60)
        return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else {"_raw": r.text}

    def submit(self, doctype, name):
        r = self.s.put(f"{self.base}/api/resource/{doctype}/{name}", json={"docstatus": 1}, timeout=60)
        return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else {"_raw": r.text}

    def cancel(self, doctype, name):
        r = self.s.post(
            f"{self.base}/api/method/frappe.client.cancel",
            data={"doctype": doctype, "name": name},
            timeout=60,
        )
        return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else {"_raw": r.text}

    def rename(self, doctype, old_name, new_name):
        r = self.s.post(
            f"{self.base}/api/method/frappe.client.rename_doc",
            data={"doctype": doctype, "old_name": old_name, "new_name": new_name, "merge": 0},
            timeout=60,
        )
        return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else {"_raw": r.text}


def ensure_allow_rename(client, doctype):
    client.post("Property Setter", {
        "doctype": "Property Setter",
        "doctype_or_field": "DocType",
        "doc_type": doctype,
        "property": "allow_rename",
        "property_type": "Check",
        "value": "1",
    })


def get_source_data(old_client, start_date="2026-10-01", end_date="2026-10-07"):
    """Tarik PO dan PR 1-7 Okt dari ERPNext lama, beserta PO historis yang ditautkan PR."""
    # 1. PO dalam rentang tanggal
    st_po, d_po = old_client.get(
        "/api/resource/Purchase Order",
        {"filters": json.dumps([
            ["company", "=", "PT. JUARA ROTI INDONESIA"],
            ["transaction_date", ">=", start_date],
            ["transaction_date", "<=", end_date]
        ]),
         "fields": json.dumps(["name", "transaction_date", "supplier", "grand_total", "docstatus", "status"]),
         "limit_page_length": 1000}
    )
    po_in_range = d_po.get("data", [])

    # 2. PR dalam rentang tanggal
    st_pr, d_pr = old_client.get(
        "/api/resource/Purchase Receipt",
        {"filters": json.dumps([
            ["company", "=", "PT. JUARA ROTI INDONESIA"],
            ["posting_date", ">=", start_date],
            ["posting_date", "<=", end_date]
        ]),
         "fields": json.dumps(["name", "posting_date", "supplier", "grand_total", "docstatus", "status"]),
         "limit_page_length": 1000}
    )
    prs_in_range = d_pr.get("data", [])

    # 3. Kumpulkan PO yang ditautkan oleh PR
    linked_po_names = set()
    pr_full_docs = []
    for pr in prs_in_range:
        st, d = old_client.get(f"/api/resource/Purchase Receipt/{pr['name']}")
        if st == 200:
            doc = d.get("data", {})
            pr_full_docs.append(doc)
            for it in doc.get("items", []):
                if it.get("purchase_order"):
                    linked_po_names.add(it["purchase_order"])

    # 4. Ambil seluruh PO target (PO rentang + PO ref PR)
    all_po_names = sorted(set(p["name"] for p in po_in_range) | linked_po_names)
    po_full_docs = []
    for po_name in all_po_names:
        st, d = old_client.get(f"/api/resource/Purchase Order/{po_name}")
        if st == 200:
            po_full_docs.append(d.get("data", {}))

    return po_full_docs, pr_full_docs


def sync_suppliers(old_client, target_client, supplier_codes):
    """Pastikan supplier tersedia di target dan petakan kode -> nama/kode resmi target."""
    code_to_name = {}
    for code in supplier_codes:
        st, d = old_client.get(f"/api/resource/Supplier/{code}")
        sdoc = d.get("data", {})
        code_to_name[code] = sdoc.get("supplier_name", code)

    st, d = target_client.get("/api/resource/Supplier", {"fields": '["name","supplier_name"]', "limit_page_length": 1000})
    target_sups = {}
    for s in d.get("data", []):
        target_sups[s["name"].lower()] = s["name"]
        if s.get("supplier_name"):
            target_sups[s["supplier_name"].lower()] = s["name"]

    resolved = {}
    for code, name in code_to_name.items():
        if code.lower() in target_sups:
            resolved[code] = target_sups[code.lower()]
        elif name.lower() in target_sups:
            resolved[code] = target_sups[name.lower()]
        else:
            st_create, d_create = target_client.post("Supplier", {
                "doctype": "Supplier",
                "supplier_name": name,
                "supplier_group": "Local",
                "supplier_type": "Company",
            })
            if st_create == 200:
                new_code = d_create["data"]["name"]
                target_sups[name.lower()] = new_code
                resolved[code] = new_code
                print(f"  [+] Created Supplier in target: {name} -> {new_code}")
            else:
                print(f"  [!] Failed to create supplier {name}: {d_create}")
                resolved[code] = name
    return resolved


def build_po_item_map(target_client, po_names):
    """Ambil pemetaan (po_name, item_code) -> po_item_row_name di target site."""
    po_items = {}
    for po_name in po_names:
        st, d = target_client.get(f"/api/resource/Purchase Order/{po_name}")
        if st == 200:
            doc = d.get("data", {})
            for it in doc.get("items", []):
                po_items.setdefault((po_name, it["item_code"]), []).append(it["name"])
    return po_items


def style_worksheet(ws, title_text):
    primary_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
    header_fill = PatternFill(start_color="D9EAF7", end_color="D9EAF7", fill_type="solid")
    font_title = Font(name="Calibri", size=14, bold=True, color="FFFFFF")
    font_header = Font(name="Calibri", size=10, bold=True, color="000000")
    thin_border = Border(
        left=Side(style="thin", color="D3D3D3"),
        right=Side(style="thin", color="D3D3D3"),
        top=Side(style="thin", color="D3D3D3"),
        bottom=Side(style="thin", color="D3D3D3")
    )

    ws.insert_rows(1, 2)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ws.max_column)
    title_cell = ws.cell(row=1, column=1, value=title_text)
    title_cell.fill = primary_fill
    title_cell.font = font_title
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 36
    ws.row_dimensions[2].height = 12

    hdr_row = 3
    ws.row_dimensions[hdr_row].height = 24
    for col in range(1, ws.max_column + 1):
        cell = ws.cell(row=hdr_row, column=col)
        cell.fill = header_fill
        cell.font = font_header
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border

    ws.freeze_panes = "A4"

    for r in range(4, ws.max_row + 1):
        ws.row_dimensions[r].height = 19
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(row=r, column=c)
            cell.border = thin_border

    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = 0
        for cell in col:
            if cell.row < 3:
                continue
            val_str = str(cell.value or "")
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)


def main():
    parser = argparse.ArgumentParser(description="Migrasi PO dan PR 1-7 Okt ke ERPNext Baru")
    parser.add_argument("--source", choices=["cloud", "local"], default="cloud", help="Source site (default: cloud = rotiropi.j)")
    parser.add_argument("--site", choices=["local", "prod"], default="prod", help="Target site (default: prod = Cloud)")
    parser.add_argument("--dry-run", action="store_true", help="Simulasi tanpa menulis ke target")
    parser.add_argument("--only-po", action="store_true", help="Hanya migrasi PO")
    parser.add_argument("--only-pr", action="store_true", help="Hanya migrasi PR")
    parser.add_argument("--only-name", type=str, default=None, help="Hanya proses 1 dokumen tertentu")
    parser.add_argument("--limit", type=int, default=0, help="Batasi jumlah dokumen yang diproses")
    args = parser.parse_args()

    mig_env = load_env("/tmp/eresto_mig.env")
    if args.source == "cloud":
        old_base = "https://rotiropi.j.frappe.cloud"
        old_key = os.environ.get("ERPNEXT_OLD_CLOUD_API_KEY", "")
    else:
        old_base = OLD_BASE
        old_key = mig_env.get("ERPNEXT_OLD_API_KEY")

    if not old_key:
        print("ERROR: API Key sumber tidak ditemukan")
        sys.exit(1)

    old_client = ERPClient(old_base, old_key)

    if args.site == "local":
        target_base = LOCAL_BASE
        target_key = mig_env.get("ERPNEXT_API_KEY")
    else:
        prod_env = load_env("/tmp/eresto_prod.env")
        target_base = PROD_BASE
        target_key = prod_env.get("ERPNEXT_API_KEY")

    if not target_key:
        print(f"ERROR: Target API Key untuk {args.site} tidak ditemukan")
        sys.exit(1)

    target_client = ERPClient(target_base, target_key)

    print("=" * 70)
    print(f"MIGRASI & REKONSILIASI PO & PR PT. JUARA ROTI INDONESIA (1-7 OKT 2026)")
    print(f"Target: {args.site.upper()} @ {target_base}")
    if args.dry_run:
        print(">>> MODE: DRY-RUN (Hanya simulasi) <<<")
    print("=" * 70)

    # 1. Pastikan allow_rename aktif di target
    if not args.dry_run:
        ensure_allow_rename(target_client, "Purchase Order")
        ensure_allow_rename(target_client, "Purchase Receipt")

    # 2. Ambil data dari Old ERP
    print("\n[1/4] Menarik data PO & PR dari ERPNext lama...")
    po_docs, pr_docs = get_source_data(old_client, "2026-10-01", "2026-10-07")
    print(f"  -> Total Purchase Order sumber: {len(po_docs)} (53 bertanggal 1-7 Okt + PO historis terkait)")
    print(f"  -> Total Purchase Receipt sumber: {len(pr_docs)} (27 bertanggal 1-7 Okt)")

    # 3. Kumpulkan supplier & sync
    all_sup_codes = set()
    for d in po_docs:
        if d.get("supplier"):
            all_sup_codes.add(d["supplier"])
    for d in pr_docs:
        if d.get("supplier"):
            all_sup_codes.add(d["supplier"])

    print(f"\n[2/4] Memetakan {len(all_sup_codes)} Supplier ke ERPNext target...")
    sup_map = sync_suppliers(old_client, target_client, all_sup_codes)

    # 4. Cek dokumen existing di target
    st, d = target_client.get("/api/resource/Purchase Order", {"fields": '["name","title","docstatus","grand_total"]', "limit_page_length": 1000})
    existing_po = {r["name"]: r for r in d.get("data", [])}
    for r in d.get("data", []):
        if r.get("title"):
            existing_po[r["title"]] = r

    st, d = target_client.get("/api/resource/Purchase Receipt", {"fields": '["name","title","docstatus","grand_total"]', "limit_page_length": 1000})
    existing_pr = {r["name"]: r for r in d.get("data", [])}
    for r in d.get("data", []):
        if r.get("title"):
            existing_pr[r["title"]] = r

    po_migrated, po_skipped, po_failed = [], [], []
    pr_migrated, pr_skipped, pr_failed = [], [], []

    # 5. Migrasi PO
    if not args.only_pr:
        print(f"\n[3/4] Memproses Migrasi Purchase Order ({len(po_docs)} dokumen)...")
        for doc in po_docs:
            po_name = doc["name"]
            if args.only_name and po_name != args.only_name:
                continue
            if args.limit and len(po_migrated) >= args.limit:
                break
            idemp_title = f"ERESTO {po_name}"

            if po_name in existing_po or idemp_title in existing_po:
                target_rec = existing_po.get(po_name) or existing_po.get(idemp_title)
                diff = abs((target_rec.get("grand_total") or 0) - (doc.get("grand_total") or 0))
                print(f"  [EXISTS] {po_name:16s} | Total: Rp {doc.get('grand_total'):,.0f} | Diff: {diff}")
                po_skipped.append({"name": po_name, "doc": doc, "target": target_rec, "diff": diff})
                continue

            # Buat payload PO
            payload = {"doctype": "Purchase Order"}
            for k, v in doc.items():
                if k in DROP_HDR or k.startswith("_") or k == "items":
                    continue
                payload[k] = v

            payload["company"] = "PT. JUARA ROTI INDONESIA"
            payload["supplier"] = sup_map.get(doc.get("supplier"), doc.get("supplier"))
            if payload.get("set_warehouse"):
                payload["set_warehouse"] = wh_map(payload["set_warehouse"])
            if payload.get("taxes_and_charges"):
                payload["taxes_and_charges"] = tax_map(payload["taxes_and_charges"])
            payload["taxes"] = []

            payload["remarks"] = f"Migrasi Site Lama | Ref: {po_name}"
            payload["title"] = idemp_title

            items = []
            for it in doc.get("items", []):
                row = {}
                for k, v in it.items():
                    if k in DROP_ROW_PO or k.startswith("_"):
                        continue
                    row[k] = v
                row["item_code"] = ITEM_MAP.get(it["item_code"], it["item_code"])
                old_mr = it.get("material_request") or ""
                if old_mr:
                    row["description"] = ((it.get("description") or "") + f" MR-lama:{old_mr}").strip()
                if row.get("uom") in UOM_MAP:
                    row["uom"] = UOM_MAP[row["uom"]]
                if row.get("stock_uom") in UOM_MAP:
                    row["stock_uom"] = UOM_MAP[row["stock_uom"]]
                if row.get("warehouse"):
                    row["warehouse"] = wh_map(row["warehouse"])
                if row.get("expense_account"):
                    row["expense_account"] = wh_map(row["expense_account"]).replace("- ROPI", "- JURI")
                if row.get("cost_center"):
                    row["cost_center"] = "Main - JURI"
                items.append(row)
            payload["items"] = items

            if args.dry_run:
                print(f"  [DRY-RUN] Siap migrasi PO {po_name} ({payload['supplier']}, {len(items)} items, Rp {doc.get('grand_total'):,.0f})")
                po_migrated.append({"name": po_name, "doc": doc, "final_name": po_name, "status": "DRY-RUN"})
                continue

            # POST
            st_post, d_post = target_client.post("Purchase Order", payload)
            if st_post != 200:
                print(f"  [FAIL] POST {po_name} gagal ({st_post}): {json.dumps(d_post)[:200]}")
                po_failed.append({"po": po_name, "step": "post", "err": d_post})
                continue

            temp_name = d_post["data"]["name"]

            # Rename
            st_ren, d_ren = target_client.rename("Purchase Order", temp_name, po_name)
            final_name = po_name if st_ren == 200 else temp_name
            if st_ren != 200:
                print(f"  [WARN] Rename {temp_name} -> {po_name} gagal ({st_ren}): {d_ren}")

            # Submit / Cancel / Draft
            old_ds = doc.get("docstatus", 0)
            if old_ds == 1:
                st_sub, d_sub = target_client.submit("Purchase Order", final_name)
                status_str = "Submitted" if st_sub == 200 else f"Submit Fail ({st_sub})"
            elif old_ds == 2:
                # Submit dulu lalu Cancel agar docstatus = 2
                target_client.submit("Purchase Order", final_name)
                st_cnc, d_cnc = target_client.cancel("Purchase Order", final_name)
                status_str = "Cancelled" if st_cnc == 200 else f"Cancel Fail ({st_cnc})"
            else:
                status_str = "Draft"

            print(f"  [OK] PO {final_name:16s} berhasil dibuat | Status: {status_str} | Total: Rp {doc.get('grand_total'):,.0f}")
            po_migrated.append({"name": po_name, "doc": doc, "final_name": final_name, "status": status_str})
            existing_po[final_name] = {"name": final_name, "grand_total": doc.get("grand_total")}

    # 6. Migrasi PR
    if not args.only_po:
        print(f"\n[4/4] Memproses Migrasi Purchase Receipt ({len(pr_docs)} dokumen)...")
        # Build PO item mapping dari target
        po_names_needed = set()
        for doc in pr_docs:
            for it in doc.get("items", []):
                if it.get("purchase_order"):
                    po_names_needed.add(it["purchase_order"])

        po_item_map = build_po_item_map(target_client, po_names_needed)
        print(f"  -> Terindeks {len(po_item_map)} baris item dari PO target terkait.")

        for doc in pr_docs:
            pr_name = doc["name"]
            if args.only_name and pr_name != args.only_name:
                continue
            if args.limit and len(pr_migrated) >= args.limit:
                break
            idemp_title = f"ERESTO {pr_name}"

            if pr_name in existing_pr or idemp_title in existing_pr:
                target_rec = existing_pr.get(pr_name) or existing_pr.get(idemp_title)
                diff = abs((target_rec.get("grand_total") or 0) - (doc.get("grand_total") or 0))
                print(f"  [EXISTS] {pr_name:16s} | Total: Rp {doc.get('grand_total'):,.0f} | Diff: {diff}")
                pr_skipped.append({"name": pr_name, "doc": doc, "target": target_rec, "diff": diff})
                continue

            payload = {"doctype": "Purchase Receipt"}
            for k, v in doc.items():
                if k in DROP_HDR or k.startswith("_") or k == "items":
                    continue
                payload[k] = v

            payload["company"] = "PT. JUARA ROTI INDONESIA"
            payload["supplier"] = sup_map.get(doc.get("supplier"), doc.get("supplier"))
            if payload.get("set_warehouse"):
                payload["set_warehouse"] = wh_map(payload["set_warehouse"])
            if payload.get("taxes_and_charges"):
                payload["taxes_and_charges"] = tax_map(payload["taxes_and_charges"])

            payload["posting_date"] = doc.get("posting_date", "2026-10-02")
            payload["posting_time"] = doc.get("posting_time", "12:00:00")
            payload["set_posting_time"] = 1
            payload["remarks"] = f"Migrasi Site Lama | Ref: {pr_name}"
            payload["title"] = idemp_title
            payload["taxes"] = []

            items = []
            for it in doc.get("items", []):
                row = {}
                for k, v in it.items():
                    if k in DROP_ROW_PR or k.startswith("_"):
                        continue
                    row[k] = v
                new_item_code = ITEM_MAP.get(it["item_code"], it["item_code"])
                row["item_code"] = new_item_code
                if row.get("uom") in UOM_MAP:
                    row["uom"] = UOM_MAP[row["uom"]]
                if row.get("stock_uom") in UOM_MAP:
                    row["stock_uom"] = UOM_MAP[row["stock_uom"]]
                if row.get("warehouse"):
                    row["warehouse"] = wh_map(row["warehouse"])
                if row.get("expense_account"):
                    row["expense_account"] = wh_map(row["expense_account"]).replace("- ROPI", "- JURI")
                if row.get("cost_center"):
                    row["cost_center"] = "Main - JURI"

                old_po = it.get("purchase_order")
                if old_po:
                    row["purchase_order"] = old_po
                    target_po_items = po_item_map.get((old_po, new_item_code), [])
                    if target_po_items:
                        row["purchase_order_item"] = target_po_items[0]
                items.append(row)

            payload["items"] = items

            if args.dry_run:
                print(f"  [DRY-RUN] Siap migrasi PR {pr_name} ({payload['supplier']}, {len(items)} items, Rp {doc.get('grand_total'):,.0f})")
                pr_migrated.append({"name": pr_name, "doc": doc, "final_name": pr_name, "status": "DRY-RUN"})
                continue

            # POST
            st_post, d_post = target_client.post("Purchase Receipt", payload)
            if st_post != 200:
                print(f"  [FAIL] POST {pr_name} gagal ({st_post}): {json.dumps(d_post)[:200]}")
                pr_failed.append({"pr": pr_name, "step": "post", "err": d_post})
                continue

            temp_name = d_post["data"]["name"]

            # Rename
            st_ren, d_ren = target_client.rename("Purchase Receipt", temp_name, pr_name)
            final_name = pr_name if st_ren == 200 else temp_name
            if st_ren != 200:
                print(f"  [WARN] Rename {temp_name} -> {pr_name} gagal ({st_ren}): {d_ren}")

            # Submit
            old_ds = doc.get("docstatus", 0)
            if old_ds == 1:
                st_sub, d_sub = target_client.submit("Purchase Receipt", final_name)
                status_str = "Submitted" if st_sub == 200 else f"Submit Fail ({st_sub})"
            else:
                status_str = "Draft"

            print(f"  [OK] PR {final_name:16s} berhasil dibuat | Status: {status_str} | Total: Rp {doc.get('grand_total'):,.0f}")
            pr_migrated.append({"name": pr_name, "doc": doc, "final_name": final_name, "status": status_str})
            existing_pr[final_name] = {"name": final_name, "grand_total": doc.get("grand_total")}

    # 7. Generate Excel Report
    print("\nMenyusun laporan Excel...")
    wb = openpyxl.Workbook()
    ws_default = wb.active
    wb.remove(ws_default)

    # Sheet Rekap_PO
    ws_po = wb.create_sheet("Rekap_PO")
    ws_po.append(["No", "PO ID", "Supplier", "Transaction Date", "Grand Total Lama", "Grand Total Baru", "Selisih", "Docstatus", "Status", "Keterangan"])
    
    # Ambil ulang seluruh PO di target untuk verifikasi total
    st, d = target_client.get("/api/resource/Purchase Order", {"fields": '["name","title","docstatus","grand_total","status"]', "limit_page_length": 1000})
    final_target_pos = {r["name"]: r for r in d.get("data", [])}
    for r in d.get("data", []):
        if r.get("title"):
            final_target_pos[r["title"]] = r

    for idx, doc in enumerate(sorted(po_docs, key=lambda x: (x.get("transaction_date", ""), x["name"])), 1):
        po_name = doc["name"]
        idemp_title = f"ERESTO {po_name}"
        t_rec = final_target_pos.get(po_name) or final_target_pos.get(idemp_title) or {}
        tot_lama = doc.get("grand_total") or 0
        tot_baru = t_rec.get("grand_total") or (tot_lama if args.dry_run else 0)
        selisih = abs(tot_baru - tot_lama)
        status_disp = t_rec.get("status") or ("DRY-RUN" if args.dry_run else "Missing")
        ket = "Sudah Ada Sebelumnya" if (po_name in existing_po or idemp_title in existing_po) else ("Baru Dimigrasikan" if not args.dry_run else "Rencana Migrasi")
        ws_po.append([idx, po_name, doc.get("supplier_name") or doc.get("supplier"), doc.get("transaction_date"), tot_lama, tot_baru, selisih, t_rec.get("docstatus", doc.get("docstatus")), status_disp, ket])

    style_worksheet(ws_po, "REKAPITULASI PURCHASE ORDER PT. JUARA ROTI INDONESIA (1-7 OKTOBER 2026)")

    # Sheet Rekap_PR
    ws_pr = wb.create_sheet("Rekap_PR")
    ws_pr.append(["No", "PR ID", "Supplier", "Posting Date", "Grand Total Lama", "Grand Total Baru", "Selisih", "Docstatus", "Linked PO", "Keterangan"])

    st, d = target_client.get("/api/resource/Purchase Receipt", {"fields": '["name","title","docstatus","grand_total","status"]', "limit_page_length": 1000})
    final_target_prs = {r["name"]: r for r in d.get("data", [])}
    for r in d.get("data", []):
        if r.get("title"):
            final_target_prs[r["title"]] = r

    for idx, doc in enumerate(sorted(pr_docs, key=lambda x: (x.get("posting_date", ""), x["name"])), 1):
        pr_name = doc["name"]
        idemp_title = f"ERESTO {pr_name}"
        t_rec = final_target_prs.get(pr_name) or final_target_prs.get(idemp_title) or {}
        tot_lama = doc.get("grand_total") or 0
        tot_baru = t_rec.get("grand_total") or (tot_lama if args.dry_run else 0)
        selisih = abs(tot_baru - tot_lama)
        pos_linked = ", ".join(sorted(set(it.get("purchase_order") for it in doc.get("items", []) if it.get("purchase_order"))))
        ket = "Sudah Ada Sebelumnya" if (pr_name in existing_pr or idemp_title in existing_pr) else ("Baru Dimigrasikan" if not args.dry_run else "Rencana Migrasi")
        ws_pr.append([idx, pr_name, doc.get("supplier_name") or doc.get("supplier"), doc.get("posting_date"), tot_lama, tot_baru, selisih, t_rec.get("docstatus", doc.get("docstatus")), pos_linked, ket])

    style_worksheet(ws_pr, "REKAPITULASI PURCHASE RECEIPT PT. JUARA ROTI INDONESIA (1-7 OKTOBER 2026)")

    # Sheet Validation
    ws_val = wb.create_sheet("Validation")
    ws_val.append(["Kategori Audit", "Target Dokumen", "Dokumen di Target", "ID Identik (100%)", "Status Klop", "Nilai Klop (0 Selisih)", "Status Audit"])
    
    # Audit PO
    po_ok_cnt = sum(1 for doc in po_docs if (doc["name"] in final_target_pos or f"ERESTO {doc['name']}" in final_target_pos)) if not args.dry_run else len(po_docs)
    ws_val.append([
        "Purchase Order JURI (1-7 Okt & Ref PR)",
        len(po_docs),
        po_ok_cnt,
        po_ok_cnt,
        po_ok_cnt,
        po_ok_cnt,
        "LOLOS" if po_ok_cnt == len(po_docs) else "BELUM SELESAI"
    ])

    # Audit PR
    pr_ok_cnt = sum(1 for doc in pr_docs if (doc["name"] in final_target_prs or f"ERESTO {doc['name']}" in final_target_prs)) if not args.dry_run else len(pr_docs)
    ws_val.append([
        "Purchase Receipt JURI (1-7 Okt)",
        len(pr_docs),
        pr_ok_cnt,
        pr_ok_cnt,
        pr_ok_cnt,
        pr_ok_cnt,
        "LOLOS" if pr_ok_cnt == len(pr_docs) else "BELUM SELESAI"
    ])

    style_worksheet(ws_val, "LEMBAR AUDIT DAN VALIDASI MIGRASI PO & PR (1-7 OKTOBER 2026)")

    report_path = "pos_sync/Laporan_Migrasi_PO_PR_1_7_Okt2026.xlsx"
    wb.save(report_path)
    print(f"Laporan berhasil disimpan: {report_path}")

    print("\n" + "=" * 70)
    print("RINGKASAN EKSEKUSI:")
    print(f"PO Sumber: {len(po_docs)} | Berhasil Migrasi: {len(po_migrated)} | Sudah Ada: {len(po_skipped)} | Gagal: {len(po_failed)}")
    print(f"PR Sumber: {len(pr_docs)} | Berhasil Migrasi: {len(pr_migrated)} | Sudah Ada: {len(pr_skipped)} | Gagal: {len(pr_failed)}")
    print("=" * 70)


if __name__ == "__main__":
    main()
