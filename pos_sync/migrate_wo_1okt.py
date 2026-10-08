"""Tahap 3 Migrasi: Work Order PT. JUARA ROTI INDONESIA via Custom App production_app.

Sumber: REST API site LAMA (http://site-lama.localhost:8082 atau https://rotiropi.j.frappe.cloud).
Target: REST API site BARU (Lokal atau Prod).

Aturan:
- Menggunakan BOM aktif site BARU (BOM-PJ2600xx-001 sebagai acuan benar).
- required_items diekspansi otomatis oleh ERPNext dari BOM baru.
- produced_qty dan material_transferred_for_manufacturing DISERTAKAN saat insert
  agar Work Order berstatus 'Completed' dan memiliki data hasil produksi yang lengkap.
- Menyalin seluruh custom fields yang dipakai production_app:
  adonan_ke, jam_adonan, suhu_adonan, nama_penimbang, kru, leader,
  prepacking & postpacking (good, reject, trial, sisa, confirmed),
  jam pembekuan, jam packing, QC produksi & packing,
  box 1, 2, 3 (kg & qty), custom_handover_status.
- Link custom_handover_material_request dikosongkan & dicatat di description.
- Remarks: description = 'Migrasi Site Lama | Ref: <wo_name> MR-lama:<mr>'.
- ID Dokumen: Dipastikan sama persis dengan site lama via frappe.client.rename_doc.
- Status: Completed (docstatus = 1).
"""
import argparse
import json
import os
import sys
import time
import requests

OLD_CLOUD_BASE = "https://rotiropi.j.frappe.cloud"
OLD_LOCAL_BASE = "http://site-lama.localhost:8082"
LOCAL_BASE = "http://127.0.0.1:8081"
PROD_BASE = "https://ropierpnext.frappe.cloud"

DROP_WO_FIELDS = {
    "name", "owner", "creation", "modified", "modified_by", "idx",
    "docstatus", "naming_series", "status",
    "production_plan", "production_plan_item",
    "production_plan_sub_assembly_item",
    "sales_order", "sales_order_item",
    "material_request", "material_request_item",
    "posa_operator", "posa_pos_profile", "posa_recipe",
    "custom_uom", "custom_handover_material_request",
    "amended_from", "_user_tags", "_comments", "_assign", "_liked_by",
    "operations", "required_items", "secondary_items", "non_stock_items",
}

BOM_MAP = {
    "BOM-PJ260010-002": "BOM-PJ260010-001",
    "BOM-PJ260011-002": "BOM-PJ260011-001",
    "BOM-PJ260012-002": "BOM-PJ260012-001",
    "BOM-PJ260013-002": "BOM-PJ260013-001",
    "BOM-PJ260014-002": "BOM-PJ260014-001",
    "BOM-PJ260016-001": "BOM-PJ260016-001",
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
        r = self.s.put(f"{self.base}/api/resource/{doctype}/{name}", json={"docstatus": 2}, timeout=60)
        return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else {"_raw": r.text}

    def delete(self, doctype, name):
        r = self.s.delete(f"{self.base}/api/resource/{doctype}/{name}", timeout=60)
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


def get_target_wos(old_client, date_filter=None, all_october=False):
    filters = [["company", "=", "PT. JUARA ROTI INDONESIA"]]
    if all_october:
        filters.extend([
            ["creation", ">=", "2026-10-01 00:00:00"],
            ["creation", "<=", "2026-10-31 23:59:59"],
        ])
    elif date_filter:
        filters.extend([
            ["planned_start_date", ">=", f"{date_filter} 00:00:00"],
            ["planned_start_date", "<=", f"{date_filter} 23:59:59"],
        ])
    else:
        filters.extend([
            ["planned_start_date", ">=", "2026-10-01 00:00:00"],
            ["planned_start_date", "<=", "2026-10-01 23:59:59"],
        ])

    st, d = old_client.get(
        "/api/resource/Work Order",
        {"filters": json.dumps(filters), "limit_page_length": 500, "fields": '["name"]'}
    )
    return [r["name"] for r in d.get("data", [])]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", choices=["local", "prod"], default="prod")
    parser.add_argument("--date", default="2026-10-01")
    parser.add_argument("--all-october", action="store_true")
    parser.add_argument("--force-refresh", action="store_true", help="Hapus dan buat ulang jika status Not Started")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    mig_env = load_env("/tmp/eresto_mig.env")
    old_key = mig_env.get("ERPNEXT_OLD_API_KEY") or os.environ.get("ERPNEXT_OLD_CLOUD_API_KEY", "")

    # Prefer local old site if reachable, else cloud
    old_client = ERPClient(OLD_LOCAL_BASE, old_key)
    st, _ = old_client.get("/api/method/frappe.auth.get_logged_user")
    if st != 200:
        old_client = ERPClient(OLD_CLOUD_BASE, os.environ.get("ERPNEXT_OLD_CLOUD_API_KEY", ""))

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

    scope_desc = "Semua Oktober (1, 2, 5, 6 Okt)" if args.all_october else f"Tanggal {args.date}"
    print(f"=== MIGRASI TAHAP 3: WORK ORDER ({scope_desc}) -> {args.site} ===")
    if args.dry_run:
        print(">>> MODE: DRY-RUN (tidak melakukan penulisan ke target) <<<")

    if not args.dry_run:
        ensure_allow_rename(target_client, "Work Order")

    target_wos = get_target_wos(old_client, date_filter=args.date, all_october=args.all_october)
    print(f"Total target Work Order yang diproses: {len(target_wos)}")

    # Cek yang sudah ada di target
    st, d = target_client.get("/api/resource/Work Order",
                             {"fields": '["name","description","status","docstatus","produced_qty"]', "limit_page_length": 500})
    existing = {r["name"]: r for r in d.get("data", [])}

    migrated, skipped, failed = [], [], []

    for idx, wo_name in enumerate(sorted(target_wos), 1):
        cur = existing.get(wo_name)
        # Jika sudah ada dan sudah Completed (produced_qty > 0), lewati
        if cur and cur.get("docstatus") == 1 and cur.get("status") == "Completed" and float(cur.get("produced_qty", 0)) > 0:
            print(f"  [{idx}/{len(target_wos)}] [SKIP] {wo_name} sudah Completed & lengkap.")
            skipped.append(wo_name)
            continue

        # Jika sudah ada tapi Not Started / produced_qty == 0, dan force-refresh aktif:
        if cur and args.force_refresh:
            print(f"  [{idx}/{len(target_wos)}] [REFRESH] Menghapus {wo_name} (status lama: {cur.get('status')}) untuk dibuat ulang lengkap...")
            if not args.dry_run:
                target_client.cancel("Work Order", wo_name)
                target_client.delete("Work Order", wo_name)
        elif cur:
            print(f"  [{idx}/{len(target_wos)}] [SKIP] {wo_name} sudah ada di target (gunakan --force-refresh untuk update).")
            skipped.append(wo_name)
            continue

        st, d = old_client.get(f"/api/resource/Work Order/{wo_name}")
        if st != 200:
            print(f"  [!] Gagal mengambil {wo_name}: {d}")
            failed.append({"wo": wo_name, "step": "get_old", "err": d})
            continue
        old_wo = d.get("data", {})

        # Mapping payload
        payload = {"doctype": "Work Order"}
        for k, v in old_wo.items():
            if k in DROP_WO_FIELDS or k.startswith("_"):
                continue
            payload[k] = v

        payload["company"] = "PT. JUARA ROTI INDONESIA"
        payload["production_item"] = old_wo["production_item"]

        # BOM Mapping (acuan site baru)
        old_bom = old_wo.get("bom_no")
        payload["bom_no"] = BOM_MAP.get(old_bom, old_bom)

        # Warehouse mapping
        if payload.get("source_warehouse"):
            payload["source_warehouse"] = wh_map(payload["source_warehouse"])
        if payload.get("wip_warehouse"):
            payload["wip_warehouse"] = wh_map(payload["wip_warehouse"])
        if payload.get("fg_warehouse"):
            payload["fg_warehouse"] = wh_map(payload["fg_warehouse"])
        if payload.get("scrap_warehouse"):
            payload["scrap_warehouse"] = wh_map(payload["scrap_warehouse"])

        # Produced qty & material transferred (kunci agar status Completed dan ada isinya)
        payload["produced_qty"] = old_wo.get("produced_qty", 0.0)
        payload["material_transferred_for_manufacturing"] = old_wo.get("material_transferred_for_manufacturing", 0.0)
        payload["process_loss_qty"] = old_wo.get("process_loss_qty", 0.0)
        payload["actual_start_date"] = old_wo.get("actual_start_date")
        payload["actual_end_date"] = old_wo.get("actual_end_date")

        payload["operations"] = []
        payload["required_items"] = []

        # Remarks & Audit Trail
        old_mr = old_wo.get("custom_handover_material_request") or ""
        payload["description"] = f"Migrasi Site Lama | Ref: {wo_name}" + (f" MR-lama:{old_mr}" if old_mr else "")

        # Custom fields production_app
        for k in old_wo.keys():
            if k.startswith("custom_") and k not in DROP_WO_FIELDS:
                payload[k] = old_wo[k]

        if args.dry_run:
            print(f"  [{idx}/{len(target_wos)}] [DRY-RUN] {wo_name} (Item: {payload['production_item']}, Qty: {payload['qty']}, Produced: {payload['produced_qty']})")
            migrated.append(wo_name)
            continue

        st_post, d_post = target_client.post("Work Order", payload)
        if st_post != 200:
            print(f"  [{idx}/{len(target_wos)}] [FAIL] POST {wo_name} gagal ({st_post}): {json.dumps(d_post)[:200]}")
            failed.append({"wo": wo_name, "step": "post", "err": d_post})
            continue

        temp_name = d_post["data"]["name"]
        st_ren, d_ren = target_client.rename("Work Order", temp_name, wo_name)
        if st_ren != 200:
            print(f"  [{idx}/{len(target_wos)}] [WARN] Rename {temp_name} -> {wo_name} gagal ({st_ren}): {d_ren}")
            final_name = temp_name
        else:
            final_name = wo_name

        if old_wo.get("docstatus") == 1:
            st_sub, d_sub = target_client.submit("Work Order", final_name)
            if st_sub != 200:
                print(f"  [{idx}/{len(target_wos)}] [WARN] Submit {final_name} gagal ({st_sub}): {json.dumps(d_sub)[:200]}")
            else:
                d_sub_data = d_sub.get("data", {})
                print(f"  [{idx}/{len(target_wos)}] [OK] {final_name} -> Completed (Produced: {payload['produced_qty']}/{payload['qty']}, BOM: {payload['bom_no']})")
        else:
            print(f"  [{idx}/{len(target_wos)}] [OK] {final_name} (Draft)")

        migrated.append(final_name)

    print("\n=== RINGKASAN TAHAP 3 ===")
    print(f"Total target: {len(target_wos)}")
    print(f"Berhasil: {len(migrated)}")
    print(f"Skipped: {len(skipped)}")
    print(f"Gagal: {len(failed)}")


if __name__ == "__main__":
    main()
