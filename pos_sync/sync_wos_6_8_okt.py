#!/usr/bin/env python3
"""Sinkronisasi & Migrasi Work Order 6-8 Oktober 2026 (PT. JURI).

Fitur:
1. Idempoten & Zero-duplicate: Dokumen yang sudah ada di-update/ditimpa jika ada perubahan data.
2. Production Plan: PP261006001, PP261007001, PP261008001 disinkronkan status & total_produced_qty.
3. Work Order (186 WO):
   - Submit WO Draft (PP261008001).
   - Sinkronkan seluruh field 5 tahapan (Persiapan, Material, Pre-Packing, Post-Packing, Finish).
   - Sinkronkan child table required_items[].transferred_qty = required_qty.
4. Form Order (MR + SE):
   - MAT-MR-2026-01016 dan SE-nya sudah aktif.
5. Serah Terima Barang Jadi (Warehouse App & Production App):
   - Migrasi 27 MR serah terima (MAT-MR-2026-01017..01046).
   - Replay SE Material Transfer CS -> GBJ yang ber-link MR.
6. Revert Property Setter allow_on_submit ke 0.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import JURI, Client, load_env
from migrate_wo_full_okt import Ctx, BOM_MAP, item_map, wh_map

WO_SETTERS = [
    "produced_qty", "process_loss_qty", "status",
    "material_transferred_for_manufacturing",
    "actual_start_date", "actual_end_date",
    "custom_handover_status", "custom_handover_material_request", "custom_item_name_information"
]

SYNC_FIELDS = [
    # 1. Persiapan
    "custom_adonan_ke", "custom_adonan", "custom_jam_adonan", "custom_suhu_adonan",
    "custom_nama_penimbang", "custom_leader_produksi", "custom_jumlah_kru",
    "custom_qc_produksi", "custom_item_name_information",
    # 2. Material
    "material_transferred_for_manufacturing",
    # 3. Pre-Packing
    "custom_good_qty_prepacking", "custom_reject_qty_prepacking",
    "custom_trial_qty_prepacking", "custom_sisa_qty_prepacking",
    "custom_jam_pembekuan", "custom_prepacking_confirmed",
    # 4. Post-Packing
    "custom_good_qty_postpacking", "custom_reject_qty_postpacking",
    "custom_trial_qty_postpacking", "custom_sisa_qty_postpacking",
    "custom_jam_packing", "custom_qc_packing", "custom_postpacking_confirmed",
    # 5. Finish
    "produced_qty", "process_loss_qty", "status", "actual_start_date", "actual_end_date",
    # 6. Handover
    "custom_handover_material_request", "custom_item_name_information", "custom_handover_status"
]


def ensure_setters(ctx):
    print("Mengaktifkan Property Setter sementara...")
    for f in WO_SETTERS:
        ctx.new.post("Property Setter", {
            "doctype": "Property Setter", "doctype_or_field": "DocField",
            "doc_type": "Work Order", "field_name": f,
            "property": "allow_on_submit", "property_type": "Check", "value": "1"
        })
    ctx.new.post("Property Setter", {
        "doctype": "Property Setter", "doctype_or_field": "DocField",
        "doc_type": "Work Order Item", "field_name": "transferred_qty",
        "property": "allow_on_submit", "property_type": "Check", "value": "1"
    })
    for mf in ["custom_is_form_order", "per_ordered", "status"]:
        ctx.new.post("Property Setter", {
            "doctype": "Property Setter", "doctype_or_field": "DocField",
            "doc_type": "Material Request", "field_name": mf,
            "property": "allow_on_submit", "property_type": "Check", "value": "1"
        })
    for mrif in ["custom_work_order", "ordered_qty"]:
        ctx.new.post("Property Setter", {
            "doctype": "Property Setter", "doctype_or_field": "DocField",
            "doc_type": "Material Request Item", "field_name": mrif,
            "property": "allow_on_submit", "property_type": "Check", "value": "1"
        })
    for ppf in ["status", "total_produced_qty"]:
        ctx.new.post("Property Setter", {
            "doctype": "Property Setter", "doctype_or_field": "DocField",
            "doc_type": "Production Plan", "field_name": ppf,
            "property": "allow_on_submit", "property_type": "Check", "value": "1"
        })


def cleanup_setters(ctx):
    print("Mengembalikan Property Setter ke 0...")
    for f in WO_SETTERS:
        ctx.new.put("Property Setter", f"Work Order-{f}-allow_on_submit", {"value": "0"})
    ctx.new.put("Property Setter", "Work Order Item-transferred_qty-allow_on_submit", {"value": "0"})
    for mf in ["custom_is_form_order", "per_ordered", "status"]:
        ctx.new.put("Property Setter", f"Material Request-{mf}-allow_on_submit", {"value": "0"})
    for mrif in ["custom_work_order", "ordered_qty"]:
        ctx.new.put("Property Setter", f"Material Request Item-{mrif}-allow_on_submit", {"value": "0"})
    for ppf in ["status", "total_produced_qty"]:
        ctx.new.put("Property Setter", f"Production Plan-{ppf}-allow_on_submit", {"value": "0"})


def sync_production_plans(ctx):
    print("\n" + "=" * 80)
    print("1. SINKRONISASI PRODUCTION PLAN (PP261006001, PP261007001, PP261008001)")
    print("=" * 80)
    for p in ["PP261006001", "PP261007001", "PP261008001"]:
        st_o, d_o = ctx.old.get(f"/api/resource/Production Plan/{p}")
        st_n, d_n = ctx.new.get(f"/api/resource/Production Plan/{p}")
        if st_o != 200 or st_n != 200:
            print(f"  [WARN] {p} gagal dibaca (old={st_o}, new={st_n})")
            continue
        old_p, new_p = d_o["data"], d_n["data"]
        updates = {}
        if old_p.get("status") != new_p.get("status"):
            updates["status"] = old_p.get("status")
        if abs(float(old_p.get("total_produced_qty") or 0) - float(new_p.get("total_produced_qty") or 0)) > 0.001:
            updates["total_produced_qty"] = float(old_p.get("total_produced_qty") or 0)
        
        if updates:
            st_up, _ = ctx.new.req(
                "POST", "/api/method/frappe.client.set_value",
                payload={"doctype": "Production Plan", "name": p,
                         "fieldname": json.dumps(updates)})
            print(f"  [UPDATED] {p}: {updates} (HTTP {st_up})")
        else:
            print(f"  [OK] {p}: status={new_p.get('status')}, produced_qty={new_p.get('total_produced_qty')}")


def sync_work_orders(ctx):
    print("\n" + "=" * 80)
    print("2. SINKRONISASI WORK ORDERS 6-8 OKTOBER (186 WOs)")
    print("=" * 80)

    # 1. Pastikan seluruh WO 8 Okt yang masih Draft di-submit
    st_w, wos_draft = ctx.new.get("/api/resource/Work Order", params={
        "filters": json.dumps([["production_plan", "=", "PP261008001"], ["docstatus", "=", 0]]),
        "fields": json.dumps(["name"]), "limit_page_length": 100
    })
    drafts = [w["name"] for w in wos_draft.get("data", [])]
    if drafts:
        print(f"Submitting {len(drafts)} WO Draft pada PP261008001...")
        for name in sorted(drafts):
            st_s, res_s = ctx.new.submit("Work Order", name)
            if st_s != 200:
                print(f"  [WARN] Submit {name} gagal: {json.dumps(res_s)[:150]}")
            else:
                print(f"  [SUBMITTED] {name}")
            time.sleep(0.02)

    # 2. Fetch seluruh WO 6-8 Okt dari site lama & baru
    st_o, wos_o = ctx.old.get("/api/resource/Work Order", params={
        "filters": json.dumps([
            ["company", "=", JURI],
            ["production_plan", "in", ["PP261006001", "PP261007001", "PP261008001"]]
        ]),
        "fields": json.dumps(["name", "production_plan"]),
        "limit_page_length": 300, "order_by": "name asc"
    })
    all_names = [w["name"] for w in wos_o.get("data", [])]
    print(f"Memproses {len(all_names)} Work Order...")

    updated_count = 0
    clean_count = 0

    for name in all_names:
        st_od, od = ctx.old.get(f"/api/resource/Work Order/{name}")
        st_nd, nd = ctx.new.get(f"/api/resource/Work Order/{name}")
        if st_od != 200 or st_nd != 200:
            print(f"  [FAIL] {name}: Old HTTP {st_od}, New HTTP {st_nd}")
            continue

        doc_o = od["data"]
        doc_n = nd["data"]

        updates = {}
        for f in SYNC_FIELDS:
            ov = doc_o.get(f)
            nv = doc_n.get(f)
            if f.endswith("_qty") or f in ("material_transferred_for_manufacturing", "custom_suhu_adonan", "custom_adonan_ke", "custom_adonan", "custom_jumlah_kru", "custom_prepacking_confirmed", "custom_postpacking_confirmed"):
                if abs(float(ov or 0) - float(nv or 0)) > 0.001:
                    updates[f] = float(ov or 0) if not f.endswith("_confirmed") and not f in ("custom_adonan_ke", "custom_adonan", "custom_jumlah_kru") else int(float(ov or 0))
            elif f in ("custom_jam_adonan", "custom_jam_pembekuan", "custom_jam_packing"):
                so = str(ov or "").split(".")[0]
                sn = str(nv or "").split(".")[0]
                if so != sn:
                    updates[f] = so or None
            elif f in ("actual_start_date", "actual_end_date"):
                so = str(ov or "").split(".")[0]
                sn = str(nv or "").split(".")[0]
                if so != sn:
                    updates[f] = so or None
            else:
                if (ov or "") != (nv or ""):
                    updates[f] = ov or ""

        # Update child table required_items[].transferred_qty
        req_items_updated = 0
        req_trans = float(doc_o.get("material_transferred_for_manufacturing") or 0)
        if req_trans > 0:
            for r in doc_n.get("required_items", []):
                req = float(r.get("required_qty") or 0)
                trans = float(r.get("transferred_qty") or 0)
                if abs(req - trans) > 0.001:
                    st_up, _ = ctx.new.req(
                        "POST", "/api/method/frappe.client.set_value",
                        payload={"doctype": "Work Order Item", "name": r["name"],
                                 "fieldname": json.dumps({"transferred_qty": req})})
                    if st_up in (200, 201):
                        req_items_updated += 1

        if updates:
            st_up, res_up = ctx.new.req(
                "POST", "/api/method/frappe.client.set_value",
                payload={"doctype": "Work Order", "name": name,
                         "fieldname": json.dumps(updates)})
            if st_up in (200, 201):
                updated_count += 1
                fields_str = ", ".join(updates.keys())
                print(f"  [UPDATED] {name}: status={doc_o.get('status')}, produced={doc_o.get('produced_qty')}, fields=[{fields_str}], items_synced={req_items_updated}")
            else:
                print(f"  [FAIL] {name} update gagal: {json.dumps(res_up)[:150]}")
        else:
            clean_count += 1

    print(f"Hasil WO: {updated_count} diupdate/disinkronkan, {clean_count} sudah cocok.")


def sync_handover_mrs_and_ses(ctx):
    print("\n" + "=" * 80)
    print("3. SINKRONISASI SERAH TERIMA BARANG JADI (WAREHOUSE & PRODUCTION APP)")
    print("=" * 80)

    # 1. Cari MR Serah Terima yang ada di Old
    st_o, wos_o = ctx.old.get("/api/resource/Work Order", params={
        "filters": json.dumps([
            ["company", "=", JURI],
            ["production_plan", "in", ["PP261006001", "PP261007001", "PP261008001"]]
        ]),
        "fields": json.dumps(["name", "custom_handover_material_request", "custom_item_name_information"]),
        "limit_page_length": 300
    })
    mr_names = sorted({w.get("custom_handover_material_request") for w in wos_o.get("data", []) if w.get("custom_handover_material_request")})
    print(f"Total Handover MRs di Old site: {len(mr_names)}")

    # 2. Cek MR di New site, buat yang belum ada
    mrs_created = 0
    mr_items_map = {} # mr_name -> {item_code: row_name}
    for mr_name in mr_names:
        st_n, d_n = ctx.new.get(f"/api/resource/Material Request/{mr_name}")
        if st_n == 200:
            mr_items_map[mr_name] = {it["item_code"]: it["name"] for it in d_n["data"].get("items", [])}
            continue

        # Fetch from old site
        st_old_mr, d_omr = ctx.old.get(f"/api/resource/Material Request/{mr_name}")
        if st_old_mr != 200:
            continue
        old_mr = d_omr["data"]

        items = []
        for it in old_mr.get("items", []):
            items.append({
                "item_code": item_map(it["item_code"]),
                "qty": float(it["qty"]),
                "uom": it.get("uom") or "Pcs",
                "stock_uom": it.get("stock_uom") or "Pcs",
                "from_warehouse": "Cold Storage Produksi - JURI",
                "warehouse": "Gudang Barang Jadi - JURI",
                "custom_work_order": it.get("custom_work_order"),
                "schedule_date": it.get("schedule_date") or "2026-10-08",
                "description": it.get("description") or it["item_code"]
            })

        payload = {
            "doctype": "Material Request",
            "company": JURI,
            "material_request_type": "Material Transfer",
            "transaction_date": old_mr.get("transaction_date"),
            "schedule_date": old_mr.get("schedule_date"),
            "set_from_warehouse": "Cold Storage Produksi - JURI",
            "set_warehouse": "Gudang Barang Jadi - JURI",
            "items": items
        }
        st_p, res_p = ctx.new.post("Material Request", payload)
        if st_p == 200:
            temp = res_p["data"]["name"]
            st_r, _ = ctx.new.rename("Material Request", temp, mr_name)
            final_name = mr_name if st_r == 200 else temp
            st_s, _ = ctx.new.submit("Material Request", final_name)
            # Update per_ordered = 100, status = Transferred
            ctx.new.req("POST", "/api/method/frappe.client.set_value",
                        payload={"doctype": "Material Request", "name": final_name,
                                 "fieldname": json.dumps({"per_ordered": 100.0, "status": "Transferred"})})
            print(f"  [CREATED MR] {final_name} (HTTP submit {st_s})")
            mrs_created += 1

            # reload new items map
            st_n_reload, d_nr = ctx.new.get(f"/api/resource/Material Request/{final_name}")
            if st_n_reload == 200:
                mr_items_map[final_name] = {it["item_code"]: it["name"] for it in d_nr["data"].get("items", [])}
        else:
            print(f"  [FAIL MR] {mr_name}: {json.dumps(res_p)[:150]}")

    print(f"MR Serah Terima baru dibuat: {mrs_created}")

    # 3. Replay Stock Entry CS -> GBJ yang memindahkan hasil serah terima
    st_se_old, ses_old = ctx.old.get("/api/resource/Stock Entry", params={
        "filters": json.dumps([
            ["company", "=", JURI],
            ["posting_date", "in", ["2026-10-06", "2026-10-07", "2026-10-08"]],
            ["purpose", "=", "Material Transfer"],
            ["from_warehouse", "=", "Cold Storage Produksi - ROPI"],
            ["to_warehouse", "=", "Gudang Barang Jadi - ROPI"]
        ]),
        "fields": json.dumps(["name", "posting_date", "posting_time"]),
        "limit_page_length": 200, "order_by": "posting_date asc, posting_time asc"
    })
    old_ses = ses_old.get("data", [])
    print(f"Total CS->GBJ SEs di Old: {len(old_ses)}")

    # Cek SE di New site via marker remarks
    st_se_new, ses_new = ctx.new.get("/api/resource/Stock Entry", params={
        "filters": json.dumps([
            ["company", "=", JURI],
            ["posting_date", "in", ["2026-10-06", "2026-10-07", "2026-10-08"]],
            ["purpose", "=", "Material Transfer"]
        ]),
        "fields": json.dumps(["name", "remarks"]), "limit_page_length": 200
    })
    existing_markers = set()
    for s in ses_new.get("data", []):
        rem = s.get("remarks") or ""
        if "ERESTO" in rem:
            existing_markers.add(rem.split("ERESTO")[1].strip().split()[0])

    ses_created = 0
    for s in old_ses:
        se_name = s["name"]
        if se_name in existing_markers:
            continue

        st_sdoc, sdoc = ctx.old.get(f"/api/resource/Stock Entry/{se_name}")
        if st_sdoc != 200:
            continue
        se_data = sdoc["data"]

        items = []
        for it in se_data.get("items", []):
            code = item_map(it["item_code"])
            mr_ref = it.get("material_request")
            mr_item_ref = mr_items_map.get(mr_ref, {}).get(code)
            items.append({
                "item_code": code,
                "qty": float(it["qty"]),
                "uom": it.get("uom") or "Pcs",
                "stock_uom": it.get("stock_uom") or "Pcs",
                "conversion_factor": float(it.get("conversion_factor") or 1.0),
                "s_warehouse": "Cold Storage Produksi - JURI",
                "t_warehouse": "Gudang Barang Jadi - JURI",
                "material_request": mr_ref,
                "material_request_item": mr_item_ref,
                "basic_rate": float(it.get("basic_rate") or 0.0)
            })

        payload = {
            "doctype": "Stock Entry",
            "company": JURI,
            "purpose": "Material Transfer",
            "stock_entry_type": "Material Transfer",
            "posting_date": se_data.get("posting_date"),
            "posting_time": se_data.get("posting_time"),
            "from_warehouse": "Cold Storage Produksi - JURI",
            "to_warehouse": "Gudang Barang Jadi - JURI",
            "remarks": f"ERESTO {se_name}",
            "items": items
        }
        st_p, res_p = ctx.new.post("Stock Entry", payload)
        if st_p == 200:
            created_se_name = res_p["data"]["name"]
            st_sub, _ = ctx.new.submit("Stock Entry", created_se_name)
            print(f"  [CREATED SE] {created_se_name} (Ref: {se_name}, items={len(items)}, HTTP submit {st_sub})")
            ses_created += 1
            existing_markers.add(se_name)
        else:
            print(f"  [FAIL SE] {se_name}: {json.dumps(res_p)[:150]}")

    print(f"SE Serah Terima baru dibuat: {ses_created}")


class SafeCtx:
    def __init__(self):
        mig = load_env('/tmp/eresto_mig.env')
        prod = load_env('/tmp/eresto_prod.env')
        old_key = mig.get('ERPNEXT_OLD_CLOUD_API_KEY') or mig.get('ERPNEXT_OLD_API_KEY')
        self.old = Client('https://rotiropi.j.frappe.cloud', old_key, label='old', pause=0.02)
        self.new = Client(prod.get('ERPNEXT_URL').rstrip('/'), prod['ERPNEXT_API_KEY'], label='new', pause=0.04)

def main():
    ctx = SafeCtx()
    print("Mulai sinkronisasi data produksi 6-8 Oktober 2026...")
    try:
        ensure_setters(ctx)
        sync_production_plans(ctx)
        sync_work_orders(ctx)
        sync_handover_mrs_and_ses(ctx)
    finally:
        cleanup_setters(ctx)
    print("\nSemua tahapan sinkronisasi selesai.")


if __name__ == "__main__":
    main()
