"""Tahap 2 Migrasi: Purchase Receipt PT. JUARA ROTI INDONESIA (Relink ke PO).

Sumber: REST API site LAMA (http://site-lama.localhost:8082).
Target: REST API site BARU (Lokal atau Prod).

Aturan:
- Hanya PR bertanggal 2026-10-01 untuk PT. JUARA ROTI INDONESIA (total 22 PR).
- Relink ke Purchase Order yang sudah dimigrasikan di Tahap 1.
- Gudang dinormalisasi: ' - ROPI' -> ' - JURI'.
- UOM dinormalisasi: 'Kg' -> 'kg'.
- Remarks: 'Migrasi Site Lama | Ref: <pr_name>'.
- Idempotency marker: title = 'ERESTO <pr_name>'.
- ID Dokumen: Dipastikan sama persis dengan site lama via frappe.client.rename_doc.
- Status: Disubmit di target (docstatus = 1).
"""
import argparse
import json
import os
import sys
import time
import requests

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
    "per_billed", "status",
}

DROP_ROW = {
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


def tax_map(old):
    if not old:
        return None
    if "Include" in old:
        return "Purchase Tax (Termasuk Pajak) - JURI"
    return "Purchase Tax - JURI"


def wh_map(old):
    if not old:
        return old
    if old.endswith(" - ROPI"):
        return old[:-7] + " - JURI"
    return old


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


def get_target_prs(old_client):
    st, d = old_client.get(
        "/api/resource/Purchase Receipt",
        {"filters": '[["company","=","PT. JUARA ROTI INDONESIA"],["posting_date","=","2026-10-01"]]',
         "limit_page_length": 500}
    )
    return [r["name"] for r in d.get("data", [])]


def sync_suppliers(old_client, target_client, supplier_codes):
    code_to_name = {}
    for code in supplier_codes:
        st, d = old_client.get(f"/api/resource/Supplier/{code}")
        sdoc = d.get("data", {})
        code_to_name[code] = sdoc.get("supplier_name", code)

    st, d = target_client.get("/api/resource/Supplier", {"fields": '["name","supplier_name"]', "limit_page_length": 1000})
    target_sups = {s["supplier_name"].lower(): s["name"] for s in d.get("data", [])}
    for s in d.get("data", []):
        target_sups[s["name"].lower()] = s["name"]

    resolved = {}
    for code, name in code_to_name.items():
        if name.lower() in target_sups:
            resolved[code] = target_sups[name.lower()]
        else:
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", choices=["local", "prod"], default="local")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    mig_env = load_env("/tmp/eresto_mig.env")
    old_key = mig_env.get("ERPNEXT_OLD_API_KEY")
    if not old_key:
        print("ERROR: ERPNEXT_OLD_API_KEY tidak ditemukan di /tmp/eresto_mig.env")
        sys.exit(1)

    old_client = ERPClient(OLD_BASE, old_key)

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

    print(f"=== MIGRASI TAHAP 2: PURCHASE RECEIPT (Target: {args.site} @ {target_base}) ===")
    if args.dry_run:
        print(">>> MODE: DRY-RUN (tidak melakukan penulisan ke target) <<<")

    if not args.dry_run:
        ensure_allow_rename(target_client, "Purchase Receipt")

    target_prs = get_target_prs(old_client)
    print(f"Total target PR yang diproses: {len(target_prs)}")

    # Ambil semua data PR lama
    pr_docs = []
    sup_codes = set()
    po_names = set()
    for pr_name in target_prs:
        st, d = old_client.get(f"/api/resource/Purchase Receipt/{pr_name}")
        if st != 200:
            print(f"Gagal mengambil {pr_name}: {d}")
            continue
        doc = d.get("data", {})
        pr_docs.append(doc)
        if doc.get("supplier"):
            sup_codes.add(doc["supplier"])
        for it in doc.get("items", []):
            if it.get("purchase_order"):
                po_names.add(it["purchase_order"])

    sup_map = sync_suppliers(old_client, target_client, sup_codes)
    po_item_map = build_po_item_map(target_client, po_names)
    print(f"PO item mapping terdeteksi untuk {len(po_names)} Purchase Order.")

    # Cek yang sudah ada di target
    st, d = target_client.get("/api/resource/Purchase Receipt", {"fields": '["name","title","docstatus"]', "limit_page_length": 500})
    existing = {r["name"]: r for r in d.get("data", [])}
    for r in d.get("data", []):
        if r.get("title"):
            existing[r["title"]] = r

    migrated, skipped, failed = [], [], []

    for doc in pr_docs:
        pr_name = doc["name"]
        idemp_title = f"ERESTO {pr_name}"

        if pr_name in existing or idemp_title in existing:
            print(f"  [SKIP] {pr_name} sudah ada di target.")
            skipped.append(pr_name)
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

        payload["posting_date"] = "2026-10-01"
        payload["set_posting_time"] = 1
        payload["remarks"] = f"Migrasi Site Lama | Ref: {pr_name}"
        payload["title"] = idemp_title
        payload["taxes"] = []

        items = []
        for it in doc.get("items", []):
            row = {}
            for k, v in it.items():
                if k in DROP_ROW or k.startswith("_"):
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

            # Relink ke PO di target
            old_po = it.get("purchase_order")
            if old_po:
                row["purchase_order"] = old_po
                # Cocokkan purchase_order_item
                target_po_items = po_item_map.get((old_po, new_item_code), [])
                if target_po_items:
                    row["purchase_order_item"] = target_po_items[0]
            items.append(row)

        payload["items"] = items

        if args.dry_run:
            print(f"  [DRY-RUN] Siap migrasi {pr_name} (Supplier: {payload['supplier']}, Items: {len(items)}, Grand Total: {doc.get('grand_total')})")
            migrated.append(pr_name)
            continue

        st_post, d_post = target_client.post("Purchase Receipt", payload)
        if st_post != 200:
            print(f"  [FAIL] POST {pr_name} gagal ({st_post}): {json.dumps(d_post)[:200]}")
            failed.append({"pr": pr_name, "step": "post", "err": d_post})
            continue

        temp_name = d_post["data"]["name"]
        st_ren, d_ren = target_client.rename("Purchase Receipt", temp_name, pr_name)
        if st_ren != 200:
            print(f"  [WARN] Rename {temp_name} -> {pr_name} gagal ({st_ren}): {d_ren}")
            final_name = temp_name
        else:
            final_name = pr_name

        if doc.get("docstatus") == 1:
            st_sub, d_sub = target_client.submit("Purchase Receipt", final_name)
            if st_sub != 200:
                print(f"  [WARN] Submit {final_name} gagal ({st_sub}): {json.dumps(d_sub)[:200]}")
            else:
                print(f"  [OK] {final_name} berhasil dibuat & disubmit (ID sama, total Rp{doc.get('grand_total'):,.0f})")
        else:
            print(f"  [OK] {final_name} berhasil dibuat (Draft)")

        migrated.append(final_name)

    print("\n=== RINGKASAN TAHAP 2 ===")
    print(f"Total target: {len(target_prs)}")
    print(f"Berhasil: {len(migrated)}")
    print(f"Skipped: {len(skipped)}")
    print(f"Gagal: {len(failed)}")


if __name__ == "__main__":
    main()
