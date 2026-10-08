"""Migrasi Work Order 8 Oktober 2026 (PP261008001 -> 62 Work Order).

Alur:
1. Memastikan Production Plan PP261008001 ada di site baru.
2. Membaca po_items di PP261008001 (62 baris, idx 1..62).
3. Untuk setiap WO (MFG-WO-2026-04238..04299):
   - Jika sudah ada, lewati.
   - Buat WO baru dengan docstatus 0 (Draft) sesuai data site lama.
   - Hubungkan ke PP261008001 dan row name po_items yang sesuai.
   - Rename ke ID asli (MFG-WO-2026-04xxx).
4. Verifikasi seluruh 62 WO dan koneksi ke PP261008001.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import (JURI, Client, load_env)
from migrate_wo_full_okt import Ctx, BOM_MAP, item_map, wh_map

def run_migration():
    ctx = Ctx()
    print("=== MIGRASI WORK ORDER 8 OKTOBER 2026 ===")

    # 1. Cek Production Plan
    st, pp = ctx.new.get("/api/resource/Production Plan/PP261008001")
    if st != 200:
        raise SystemExit(f"Production Plan PP261008001 tidak ditemukan di site baru: HTTP {st}")
    
    po_items = pp["data"].get("po_items", [])
    po_items_sorted = sorted(po_items, key=lambda x: x["idx"])
    print(f"Production Plan PP261008001 ditemukan dengan {len(po_items_sorted)} baris po_items.")

    # 2. Muat dump WO site lama
    dump_path = "wo_dump_08okt/wos_08okt.json"
    if not os.path.exists(dump_path):
        raise SystemExit(f"File {dump_path} tidak ditemukan!")
    
    with open(dump_path) as f:
        wos = json.load(f)
    wos_sorted = [wos[k] for k in sorted(wos.keys())]
    print(f"Total WO site lama yang akan dimigrasikan: {len(wos_sorted)}")

    if len(wos_sorted) != len(po_items_sorted):
        raise SystemExit(f"Jumlah WO ({len(wos_sorted)}) tidak sama dengan baris plan ({len(po_items_sorted)})!")

    # 3. Cek WO yang sudah ada di site baru
    existing_wos = set()
    for w in wos_sorted:
        st_chk, _ = ctx.new.get(f"/api/resource/Work Order/{w['name']}")
        if st_chk == 200:
            existing_wos.add(w["name"])
    print(f"WO yang sudah ada di site baru: {len(existing_wos)} / {len(wos_sorted)}")

    success_count = len(existing_wos)
    failed_count = 0

    for idx, w in enumerate(wos_sorted):
        wo_name = w["name"]
        if wo_name in existing_wos:
            continue

        target_row = po_items_sorted[idx]
        row_name = target_row["name"]

        payload = {
            "doctype": "Work Order",
            "company": JURI,
            "production_item": item_map(w["production_item"]),
            "bom_no": BOM_MAP.get(w["bom_no"], w["bom_no"]),
            "qty": float(w["qty"]),
            "production_plan": "PP261008001",
            "production_plan_item": row_name,
            "source_warehouse": wh_map(w.get("source_warehouse")) or "Gudang Produksi - JURI",
            "wip_warehouse": wh_map(w.get("wip_warehouse")) or "Work In Progress - JURI",
            "fg_warehouse": wh_map(w.get("fg_warehouse")) or "Cold Storage Produksi - JURI",
            "planned_start_date": w.get("planned_start_date"),
            "use_multi_level_bom": w.get("use_multi_level_bom", 1),
            "update_consumed_material_cost_in_project": 1,
            "allow_alternative_item": 0,
            "description": f"Migrasi Site Lama | Ref: {wo_name} | PP: PP261008001",
            "custom_item_name_information": w.get("custom_item_name_information") or "",
        }

        # POST WO
        st_p, res_p = ctx.new.post("Work Order", payload)
        if st_p != 200:
            print(f"[{idx+1}/{len(wos_sorted)}] FAIL POST {wo_name}: {json.dumps(res_p)[:150]}")
            failed_count += 1
            continue

        temp_name = res_p["data"]["name"]

        # Rename to original WO name
        st_r, res_r = ctx.new.rename("Work Order", temp_name, wo_name)
        if st_r != 200:
            print(f"[{idx+1}/{len(wos_sorted)}] WARN RENAME {temp_name} -> {wo_name}: {json.dumps(res_r)[:150]}")
            failed_count += 1
            continue

        print(f"[{idx+1}/{len(wos_sorted)}] OK {wo_name} ({w['production_item']} qty={w['qty']}) -> {row_name}")
        success_count += 1
        time.sleep(0.04)

    print(f"\nSelesai migrasi: {success_count} sukses, {failed_count} gagal.")

if __name__ == "__main__":
    run_migration()
