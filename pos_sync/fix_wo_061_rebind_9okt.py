#!/usr/bin/env python3
"""pos_sync/fix_wo_061_rebind_9okt.py — kembalikan WO-JURI-261009061 ke baris plan 61.

Konteks (temuan 2026-10-09):
  WO-061 asli (baris plan `caj8tpvd7p` idx 61, PJ260016 Krim Kopi) di-cancel
  14:57:42 lalu dihapus 14:57:51. Penggantinya (dibuat 14:59:06) salah nempel
  ke baris 60 (`caj87op4b5`) — baris milik WO-060 (draft).

Akibat (native ERPNext v16 `ProductionPlanWorkOrderQuantities.validate_work_order`):
  - Baris 60 punya 2 WO: WO-060 (draft) + WO-061 (submitted, memegang 25 dari
    allowance 25*1.5 = 37.5).
  - Submit WO-060 ditolak: "Row 60 ... quantity after process loss 25.0 exceeds
    the remaining allowed quantity 12.5" -> di app muncul "Persiapan Gagal".
  - Baris 61 tidak punya WO sama sekali (pending 25 tak akan pernah jalan).

Fix (idempoten, dry-run default):
  1. Rebind `production_plan_item` WO-061: caj87op4b5 -> caj8tpvd7p
     (via Property Setter allow_on_submit sementara — pola `fix_production_plan_09okt.py`).
  2. Luruskan `ordered_qty` baris 60 (-> 0) & 61 (-> 25) sesuai semantik native
     (hanya hitung WO submitted).
  3. Verifikasi: 1 WO aktif per baris plan, allowance submit WO-060 bebas.

CLI: python pos_sync/fix_wo_061_rebind_9okt.py            # dry-run
     python pos_sync/fix_wo_061_rebind_9okt.py --execute  # jalan
"""
import argparse
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env

PLAN = "MFG-PP-2026-00007"
WO_BAD = "WO-JURI-261009061"   # salah baris
WO_KEEP = "WO-JURI-261009060"  # baris 60, draft — jangan disentuh
ROW_60 = "caj87op4b5"          # idx 60
ROW_61 = "caj8tpvd7p"          # idx 61
OVP = 0.5  # overproduction_percentage_for_work_order = 50

SETTERS = [
    ("Work Order", "production_plan_item"),
    ("Production Plan Item", "ordered_qty"),
]
BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "audit_logs", "backup_wo_krim_kopi_rebind_9okt.json")


def get_doc(c, dt, name):
    st, d = c.get("/api/resource/" + urllib.parse.quote(dt) + "/" + urllib.parse.quote(name))
    if st != 200:
        raise SystemExit(f"GAGAL ambil {dt} {name}: HTTP {st} {str(d)[:300]}")
    return d["data"]


def find_setter(c, dt, field):
    st, d = c.get("/api/resource/Property Setter", {
        "filters": json.dumps([
            ["Property Setter", "doc_type", "=", dt],
            ["Property Setter", "field_name", "=", field],
            ["Property Setter", "property", "=", "allow_on_submit"],
        ]),
        "fields": json.dumps(["name", "value"]),
    })
    return (d.get("data") or [None])[0] if st == 200 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    prod = load_env("/tmp/eresto_prod.env")
    c = Client(prod["ERPNEXT_URL"], prod["ERPNEXT_API_KEY"], "BARU")

    plan = get_doc(c, "Production Plan", PLAN)
    wo060 = get_doc(c, "Work Order", WO_KEEP)
    wo061 = get_doc(c, "Work Order", WO_BAD)
    rows = {r["name"]: r for r in plan["po_items"]}

    # ---------- pre-checks ----------
    print("== PRE-CHECK ==")
    print(f"  {WO_KEEP}: ds={wo060['docstatus']} row={wo060['production_plan_item']}")
    print(f"  {WO_BAD} : ds={wo061['docstatus']} row={wo061['production_plan_item']}")
    if wo060["production_plan_item"] != ROW_60 or wo060["docstatus"] != 0:
        raise SystemExit("STOP: WO-060 tidak di baris 60 / bukan draft — periksa manual.")
    if wo061["docstatus"] != 1:
        raise SystemExit("STOP: WO-061 bukan submitted — periksa manual.")

    # safety: WO-061 tidak boleh punya SE/MR/Job Card
    for dt, fld in (("Stock Entry", "work_order"),
                    ("Material Request", "custom_work_order"),
                    ("Job Card", "work_order")):
        st, d = c.get("/api/resource/" + urllib.parse.quote(dt), {
            "filters": json.dumps([[dt, fld, "=", WO_BAD]]),
            "fields": json.dumps(["name"]), "limit_page_length": 5})
        if st == 200 and d.get("data"):
            raise SystemExit(f"STOP: {WO_BAD} direferensikan {dt}: {d['data']}")

    row61 = rows[ROW_61]
    row60 = rows[ROW_60]
    need_rebind = wo061["production_plan_item"] != ROW_61
    need_order61 = abs(float(row61.get("ordered_qty") or 0) - 25.0) > 0.001
    need_order60 = abs(float(row60.get("ordered_qty") or 0) - 0.0) > 0.001
    print(f"  rebind {WO_BAD} -> {ROW_61}: {need_rebind}")
    print(f"  ordered_qty row61 {ROW_61}: {row61.get('ordered_qty')} -> 25 ({need_order61})")
    print(f"  ordered_qty row60 {ROW_60}: {row60.get('ordered_qty')} -> 0 ({need_order60})")

    if not (need_rebind or need_order61 or need_order60):
        print("[SKIP] Sudah benar semua — tidak ada yang perlu diubah.")
        verify(c)
        return

    if not args.execute:
        print("\n[DRY-RUN] Jalankan ulang dengan --execute untuk menulis.")
        return

    # ---------- backup ----------
    os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
    with open(BACKUP, "w") as f:
        json.dump({"plan_row_60": row60, "plan_row_61": row61,
                   WO_KEEP: wo060, WO_BAD: wo061}, f, indent=2, default=str)
    print(f"\n[OK] Backup -> {os.path.abspath(BACKUP)}")

    # ---------- property setters sementara ----------
    created = []
    for dt, fld in SETTERS:
        existing = find_setter(c, dt, fld)
        if existing and str(existing.get("value")) == "1":
            print(f"  [setter] {dt}.{fld} sudah allow_on_submit=1")
            continue
        if existing:
            raise SystemExit(f"STOP: property setter {dt}.{fld} ada tapi value={existing.get('value')}")
        st, d = c.post("Property Setter", {
            "doctype": "Property Setter", "doctype_or_field": "DocField",
            "doc_type": dt, "field_name": fld,
            "property": "allow_on_submit", "property_type": "Check", "value": "1",
        })
        if st not in (200, 201):
            raise SystemExit(f"GAGAL buat setter {dt}.{fld}: HTTP {st} {str(d)[:300]}")
        created.append(d["data"]["name"])
        print(f"  [setter] buat {dt}.{fld} allow_on_submit=1 ({d['data']['name']})")

    try:
        # ---------- rebind ----------
        if need_rebind:
            st, d = c.put("Work Order", WO_BAD, {"production_plan_item": ROW_61})
            if st != 200:
                raise SystemExit(f"GAGAL rebind {WO_BAD}: HTTP {st} {str(d)[:500]}")
            print(f"[OK] {WO_BAD}.production_plan_item -> {ROW_61}")

        # ---------- ordered_qty ----------
        for name, target in ((ROW_60, 0.0), (ROW_61, 25.0)):
            if name == ROW_60 and not need_order60:
                continue
            if name == ROW_61 and not need_order61:
                continue
            st, d = c.req("POST", "/api/method/frappe.client.set_value", {
                "doctype": "Production Plan Item", "name": name,
                "fieldname": "ordered_qty", "value": target})
            if st != 200:
                raise SystemExit(f"GAGAL set ordered_qty {name}: HTTP {st} {str(d)[:500]}")
            print(f"[OK] ordered_qty {name} -> {target}")
    finally:
        # ---------- bersihkan setter ----------
        for sname in created:
            st, _ = c.req("DELETE", "/api/resource/Property%20Setter/" + urllib.parse.quote(sname))
            print(f"  [setter] hapus {sname}: status {st}")

    verify(c)


def verify(c):
    print("\n== VERIFIKASI ==")
    plan = get_doc(c, "Production Plan", PLAN)
    wo061 = get_doc(c, "Work Order", WO_BAD)
    wo060 = get_doc(c, "Work Order", WO_KEEP)
    rows = list(plan["po_items"])
    by_name = {r["name"]: r for r in rows}

    # 1. binding
    ok = wo061["production_plan_item"] == ROW_61 and wo060["production_plan_item"] == ROW_60
    print(f"  [{'LOLOS' if ok else 'GAGAL'}] binding: WO-061->{wo061['production_plan_item']} WO-060->{wo060['production_plan_item']}")

    # 2. 1 WO aktif per baris
    st, d = c.get("/api/resource/Work Order", {
        "filters": json.dumps([["Work Order", "production_plan", "=", PLAN],
                               ["Work Order", "docstatus", "<", 2]]),
        "fields": json.dumps(["name", "production_plan_item", "docstatus"]),
        "limit_page_length": 0})
    per_row = {}
    for w in d["data"]:
        per_row.setdefault(w["production_plan_item"], []).append(w)
    dup = {k: [x["name"] for x in v] for k, v in per_row.items() if len(v) > 1}
    missing = [r["name"] for r in rows if r["name"] not in per_row]
    ok = not dup and not missing
    print(f"  [{'LOLOS' if ok else 'GAGAL'}] 1 WO per baris: dup={dup or '-'} kosong={missing or '-'}")

    # 3. allowance submit WO-060: committed(others) baris 60 = WO submitted selain WO-060
    committed = sum(25.0 for w in per_row.get(ROW_60, [])
                    if w["name"] != WO_KEEP and w["docstatus"] == 1)
    planned = float(by_name[ROW_60]["planned_qty"])
    maximum = planned * (1 + OVP) - committed
    ok = 25.0 <= maximum
    print(f"  [{'LOLOS' if ok else 'GAGAL'}] allowance baris 60: qty 25.0 <= max {maximum} "
          f"(planned {planned} x 1.5 - committed {committed})")

    # 4. ordered_qty
    r60, r61 = float(by_name[ROW_60].get("ordered_qty") or 0), float(by_name[ROW_61].get("ordered_qty") or 0)
    ok = r60 == 0.0 and r61 == 25.0
    print(f"  [{'LOLOS' if ok else 'GAGAL'}] ordered_qty: row60={r60} row61={r61}")

    print("\n[SELESAI] WO-060 kini bisa di-submit dari app; WO-061 kembali ke baris 61.")


if __name__ == "__main__":
    main()
