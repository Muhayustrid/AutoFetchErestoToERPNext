"""Migrasi penuh Work Order pabrik JURI 1-6 Okt 2026 (replay alur production_app).

Mengikuti alur riil production_app + warehouse_app (bukan sekadar salin field):
  1. Production Plan (4 dokumen PP261001001/002/005/006) dibuat dengan baris
     po_items yang sama seperti site lama, nama dokumen dipertahankan.
  2. Work Order dibuat dari plan (1 WO = 1 baris plan), dipatch dengan seluruh
     field production_app (Persiapan/Pre-Packing/Post-Packing), rename ke ID
     lama (MFG-WO-2026-xxxxx), lalu submit. required_items diekspansi otomatis
     ERPNext dari BOM site baru (BOM-PJ26xxxx-001 = acuan benar).
  3. Material Request serah terima (85 dokumen) dibuat dari MR site lama,
     rename ke ID lama, submit -> hook production_app mengisi
     custom_handover_material_request + custom_handover_status="Diminta Gudang".
  4. Stock Entry direplay kronologis dengan tanggal historis:
     - support: 7 feeder GBB->GP, 5 Material Receipt, 6 Repack (bahan pendukung)
     - 244 Material Transfer for Manufacture (Material stage)
     - 221 Manufacture (Finish stage) — qty hasil mengikuti produced_qty lama,
       process loss mengikuti data lama
     - 85 Material Transfer serah terima CS->GBJ (dari MR) -> status "Terkirim"
     Box 1-3 TIDAK ditulis (sudah dipensiunkan di app; hanya diarsipkan di Excel).
  5. Verifikasi field-per-field vs site lama + laporan Excel.

Idempotency: nama dokumen WO/PP/MR dibuat sama dengan site lama (rename_doc);
Stock Entry memakai marker remarks "ERESTO <nama-lama>" (nama SE ikut seri
site baru). Rerun melanjutkan yang kurang tanpa duplikasi.

Usage:
  python3 pos_sync/migrate_wo_full_okt.py --dump [--refresh]
  python3 pos_sync/migrate_wo_full_okt.py --plans
  python3 pos_sync/migrate_wo_full_okt.py --wos [--only-plan PP...]
  python3 pos_sync/migrate_wo_full_okt.py --mrs
  python3 pos_sync/migrate_wo_full_okt.py --ses [--dry-run]
  python3 pos_sync/migrate_wo_full_okt.py --verify [--repair]
Env: /tmp/eresto_mig.env (ERPNEXT_OLD_API_KEY), /tmp/eresto_prod.env
     (ERPNEXT_URL, ERPNEXT_API_KEY). Jangan commit nilai token.
"""
import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import (JURI, Client, SERVER_FIELDS, fetch_meta,  # noqa: E402
                         load_env, pick, pick_rows)

HERE = os.path.dirname(os.path.abspath(__file__))
DUMP_DIR = os.path.join(HERE, "wo_dump")
MIG_ENV = "/tmp/eresto_mig.env"
PROD_ENV = "/tmp/eresto_prod.env"

OLD_BASE = "https://rotiropi.j.frappe.cloud"
OLD_KEY_FALLBACK = os.environ.get("ERPNEXT_OLD_CLOUD_API_KEY", "")
NEW_BASE_DEFAULT = "https://ropierpnext.frappe.cloud"
WINDOW_FROM = "2026-10-01"
WINDOW_TO = "2026-10-07"  # eksklusif

MARK = "ERESTO"
DESC_MARK = "Migrasi Site Lama | Ref:"

ITEM_MAP = {"BB260057": "BB26001"}
BOM_MAP = {
    "BOM-PJ260010-002": "BOM-PJ260010-001",
    "BOM-PJ260011-002": "BOM-PJ260011-001",
    "BOM-PJ260012-002": "BOM-PJ260012-001",
    "BOM-PJ260013-002": "BOM-PJ260013-001",
    "BOM-PJ260014-002": "BOM-PJ260014-001",
    "BOM-PJ260016-002": "BOM-PJ260016-001",
    "BOM-PJ260016-001": "BOM-PJ260016-001",
}
UOM_MAP = {"Kg": "kg", "KG": "kg"}

# field WO yang tidak boleh disalin apa adanya
WO_DROP = {
    "name", "owner", "creation", "modified", "modified_by", "idx",
    "docstatus", "naming_series", "status", "amended_from",
    "produced_qty", "process_loss_qty",
    "material_transferred_for_manufacturing",
    "actual_start_date", "actual_end_date",
    "planned_operating_cost", "actual_operating_cost",
    "additional_operating_cost", "corrective_operation_cost",
    "total_operating_cost", "disassembled_qty",
    "production_plan", "production_plan_item",
    "production_plan_sub_assembly_item",
    "sales_order", "sales_order_item",
    "material_request", "material_request_item",
    "posa_operator", "posa_pos_profile", "posa_recipe",
    "custom_uom", "custom_handover_material_request",
    "custom_handover_status",
    "custom_box_1", "custom_box_1_qty", "custom_box_2", "custom_box_2_qty",
    "custom_box_3", "custom_box_3_qty",
    "operations", "required_items", "secondary_items", "non_stock_items",
}
BOX_FIELDS = {"custom_box_1", "custom_box_1_qty", "custom_box_2",
              "custom_box_2_qty", "custom_box_3", "custom_box_3_qty"}
LAYOUT_TYPES = {"Section Break", "Column Break", "Tab Break", "Heading"}
SE_DROP = {
    "status", "naming_series", "amended_from", "letter_head", "custom_note",
    "additional_costs", "per_transferred", "total_amount",
    "total_incoming_value", "total_outgoing_value", "value_difference",
    "project", "apply_putaway_rule",
}
MR_DROP = {
    "status", "naming_series", "amended_from", "letter_head",
    "per_ordered", "per_received", "per_transferred",
    "custom_handover_box_plan", "custom_is_form_order",
}
PRIO = {"Material Receipt": 0, "Material Transfer": 1,
        "Material Transfer for Manufacture": 2, "Manufacture": 3,
        "Repack": 4, "Material Issue": 5}

PLAN_ROW_KEEP = {
    "item_code", "bom_no", "planned_qty", "stock_uom", "planned_start_date",
    "custom_item_name_information", "include_exploded_items",
    "fg_warehouse", "operation" "sales_order", "sales_order_item",
}
MR_ITEM_KEEP = {"item_code", "qty", "uom", "from_warehouse", "warehouse",
                "custom_work_order", "schedule_date", "description"}


# ------------------------------------------------------------------ helpers
def jdump(name, obj):
    os.makedirs(DUMP_DIR, exist_ok=True)
    with open(os.path.join(DUMP_DIR, name), "w") as f:
        json.dump(obj, f, indent=1, default=str)


def jload(name, default=None):
    path = os.path.join(DUMP_DIR, name)
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def wh_map(old):
    if not old:
        return old
    s = str(old)
    if s == "Gudang RnD - ROPI":
        return "Gudang R&D - JURI"
    if s.endswith(" - ROPI"):
        return s[:-7] + " - JURI"
    return s


def item_map(code):
    return ITEM_MAP.get(code, code)


def uom_map(u):
    return UOM_MAP.get(u, u)


def clean_time(t):
    """ERPNext Time field: buang mikrodetik ('8:35:15.269238' -> '8:35:15')."""
    return str(t).split(".")[0] if t else t


def hms(t):
    if not t:
        return (0, 0, 0)
    t = str(t).split(".")[0]
    parts = t.split(":")
    try:
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        s = int(parts[2]) if len(parts) > 2 else 0
        return (h, m, s)
    except (ValueError, IndexError):
        return (0, 0, 0)


def norm_dt(v):
    """Normalisasi datetime utk perbandingan (abaikan mikrodetik)."""
    if not v:
        return ""
    s = str(v)
    if "." in s:
        s = s.split(".")[0]
    return s


def token_of(text):
    if not text:
        return None
    s = str(text)
    i = s.find(MARK + " ")
    if i < 0:
        return None
    rest = s[i + len(MARK) + 1:].strip()
    return rest.split()[0].split("|")[0].strip() if rest else None


class Ctx:
    def __init__(self):
        mig = load_env(MIG_ENV)
        prod = load_env(PROD_ENV)
        old_key = mig.get("ERPNEXT_OLD_API_KEY") or OLD_KEY_FALLBACK
        self.old = Client(OLD_BASE, old_key, label="old", pause=0.02)
        st, _ = self.old.get("/api/method/frappe.auth.get_logged_user")
        if st != 200:
            self.old = Client(OLD_BASE, OLD_KEY_FALLBACK, label="old")
            st, _ = self.old.get("/api/method/frappe.auth.get_logged_user")
        if st != 200:
            raise SystemExit(f"auth site lama gagal: HTTP {st}")
        self.new = Client(prod.get("ERPNEXT_URL", NEW_BASE_DEFAULT).rstrip("/"),
                          prod["ERPNEXT_API_KEY"], label="new", pause=0.05)
        self.meta = {}
        self.meta_types = {}
        self._item_cache = {}
        self._uom_fields_cache = {}
        self._acc_cache = {}

    def acc_exists(self, doctype, name):
        key = (doctype, name)
        if key not in self._acc_cache:
            st, _ = self.new.get(
                "/api/resource/" + doctype + "/" + str(name))
            self._acc_cache[key] = st == 200
        return self._acc_cache[key]

    def load_meta(self, doctypes):
        need = [d for d in doctypes if d not in self.meta]
        if need:
            self.meta.update(fetch_meta(self.new, need))
            for d in need:
                st, r = self.new.get(
                    "/api/resource/DocType/" + d.replace(" ", "%20"),
                    {"limit_page_length": 0})
                types = {}
                if st == 200:
                    for f in r["data"].get("fields", []):
                        types[f["fieldname"]] = f.get("fieldtype")
                # Custom Fields TIDAK ada di child `fields` DocType — merge
                # terpisah supaya custom_* (termasuk stage production_app)
                # ikut lolos filter pick().
                st2, cf = self.new.get("/api/resource/Custom Field", {
                    "filters": json.dumps([["dt", "=", d]]),
                    "fields": json.dumps(["fieldname", "fieldtype"]),
                    "limit_page_length": 0})
                if st2 == 200:
                    for f in cf.get("data", []):
                        fn = f["fieldname"]
                        if fn not in self.meta[d]:
                            self.meta[d].append(fn)
                        types.setdefault(fn, f.get("fieldtype"))
                self.meta_types[d] = types

    def item(self, code):
        if code not in self._item_cache:
            st, d = self.new.get("/api/resource/Item/" + code)
            self._item_cache[code] = d.get("data", {}) if st == 200 else {}
        return self._item_cache[code]

    def stock_uom(self, code):
        it = self.item(code)
        uoms = {u["uom"]: u["conversion_factor"] for u in it.get("uoms", [])}
        return it.get("stock_uom") or "Nos", uoms


def ensure_allow_rename(ctx, doctype):
    st, d = ctx.new.get("/api/resource/Property Setter", {
        "filters": json.dumps([["property", "=", "allow_rename"],
                               ["doc_type", "=", doctype]]),
        "fields": json.dumps(["name", "value"]), "limit_page_length": 1})
    rows = d.get("data", []) if st == 200 else []
    if rows and str(rows[0]["value"]) == "1":
        return True
    st, d = ctx.new.post("Property Setter", {
        "doctype": "Property Setter", "doctype_or_field": "DocType",
        "doc_type": doctype, "property": "allow_rename",
        "property_type": "Check", "value": "1"})
    return st in (200, 201)


def marker_map(ctx, doctype, field):
    out = {}
    for r in ctx.new.list_all(doctype, ["name", field, "docstatus"],
                              [[field, "like", f"%{MARK} MAT-STE-%"]],
                              order="name asc"):
        t = token_of(r.get(field))
        if t:
            out.setdefault(t, {"name": r["name"], "docstatus": r["docstatus"]})
    return out


# ------------------------------------------------------------------ fase 0
def fetch_many(client, path, names, fields="['*']", workers=6):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    out = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(client.get, f"{path}/{n}", {"fields": fields}): n
                for n in names}
        for fu in as_completed(futs):
            n = futs[fu]
            st, d = fu.result()
            if st == 200:
                out[n] = d["data"]
            else:
                print(f"  [!] GET {path}/{n}: HTTP {st} {str(d)[:120]}")
    return out


def phase_dump(ctx):
    print("== FASE 0: DUMP site lama ==")
    st, d = ctx.old.get("/api/resource/Work Order", {
        "filters": json.dumps([["company", "=", JURI],
                               ["planned_start_date", ">=", f"{WINDOW_FROM} 00:00:00"],
                               ["planned_start_date", "<=", f"{WINDOW_TO} 00:00:00"]]),
        "fields": json.dumps(["name"]), "limit_page_length": 500})
    wo_names = sorted(r["name"] for r in d.get("data", []))
    print(f"  WO window: {len(wo_names)}")
    wos = fetch_many(ctx.old, "/api/resource/Work Order", wo_names)
    plans = sorted({w["production_plan"] for w in wos.values()
                    if w.get("production_plan")})
    plan_docs = fetch_many(ctx.old, "/api/resource/Production Plan", plans)
    mr_names = sorted({w["custom_handover_material_request"]
                       for w in wos.values()
                       if w.get("custom_handover_material_request")})
    mrs = fetch_many(ctx.old, "/api/resource/Material Request", mr_names)
    print(f"  plans: {plans}; MR serah terima: {len(mr_names)}")

    rows, start = [], 0
    while True:
        st, d = ctx.old.get("/api/resource/Stock Entry", {
            "filters": json.dumps([["company", "=", JURI],
                                   ["posting_date", ">=", WINDOW_FROM],
                                   ["posting_date", "<", WINDOW_TO]]),
            "fields": json.dumps(["name", "purpose", "stock_entry_type",
                                  "work_order", "docstatus", "posting_date",
                                  "posting_time"]),
            "limit_page_length": 500, "limit_start": start,
            "order_by": "posting_date asc, posting_time asc, name asc"})
        r = d.get("data", []) if st == 200 else []
        if not r:
            break
        rows += r
        start += len(r)
        if len(r) < 500:
            break
    print(f"  SE window: {len(rows)}")
    wo_set = set(wo_names)
    mrs_set = set(mrs)
    need_se = [r["name"] for r in rows
               if r.get("work_order") in wo_set
               or r.get("stock_entry_type") in
               ("Material Transfer", "Material Receipt", "Repack")]
    ses = fetch_many(ctx.old, "/api/resource/Stock Entry", need_se)
    print(f"  SE detail diambil: {len(ses)}")

    jdump("plans.json", plan_docs)
    jdump("wos.json", wos)
    jdump("mrs.json", mrs)
    jdump("se_index.json", rows)
    jdump("ses.json", ses)
    print("  dump tersimpan di pos_sync/wo_dump/")
    return wos, plan_docs, mrs, ses


def load_dump():
    wos = jload("wos.json")
    plans = jload("plans.json")
    mrs = jload("mrs.json")
    ses = jload("ses.json")
    if not (wos and plans and mrs and ses):
        raise SystemExit("dump belum lengkap - jalankan --dump dulu")
    return wos, plans, mrs, ses


# ------------------------------------------------------------------ fase 1
def phase_plans(ctx, dry):
    print("== FASE 1: Production Plan ==")
    ctx.load_meta(["Production Plan", "Production Plan Item"])
    plans = jload("plans.json")
    if not dry:
        ensure_allow_rename(ctx, "Production Plan")
    out = {}
    for name in sorted(plans):
        p = plans[name]
        st, d = ctx.new.get("/api/resource/Production Plan/" + name)
        if st == 200 and d.get("data", {}).get("docstatus") == 1:
            print(f"  [ADA] {name}")
            out[name] = name
            continue
        rows = []
        for r in sorted(p.get("po_items", []), key=lambda x: x.get("idx", 0)):
            q = {}
            for k in ("planned_qty", "stock_uom", "planned_start_date",
                      "custom_item_name_information"):
                if r.get(k) is not None:
                    q[k] = r[k]
            q["item_code"] = item_map(r["item_code"])
            q["bom_no"] = BOM_MAP.get(r.get("bom_no"), r.get("bom_no"))
            rows.append(q)
        payload = {"doctype": "Production Plan", "company": JURI,
                   "posting_date": p.get("posting_date"), "po_items": rows}
        if dry:
            print(f"  [DRY] plan {name}: {len(rows)} baris")
            continue
        st, d = ctx.new.post("Production Plan", payload)
        if st != 200:
            print(f"  [FAIL] POST {name}: {json.dumps(d)[:250]}")
            continue
        temp = d["data"]["name"]
        st_r, d_r = ctx.new.rename("Production Plan", temp, name)
        final = name if st_r == 200 else temp
        if st_r != 200:
            print(f"  [WARN] rename {temp}->{name}: {str(d_r)[:150]}")
        st_s, d_s = ctx.new.submit("Production Plan", final)
        print(f"  [{'OK' if st_s == 200 else 'WARN'}] plan {final} "
              f"(submit HTTP {st_s}, baris={len(rows)})")
        out[name] = final
    jdump("phase_plans.json", out)
    return out


# ------------------------------------------------------------------ fase 2
def wo_payload(ctx, w, plan_name, row_name):
    p = pick(w, ctx.meta["Work Order"], WO_DROP)
    # buang field layout & yang tidak ada di meta
    for k in list(p):
        ft = ctx.meta_types["Work Order"].get(k)
        if ft in LAYOUT_TYPES or ft is None and k not in ctx.meta["Work Order"]:
            p.pop(k, None)
    p["doctype"] = "Work Order"
    p["company"] = JURI
    p["production_item"] = item_map(w["production_item"])
    p["bom_no"] = BOM_MAP.get(w.get("bom_no"), w.get("bom_no"))
    p["production_plan"] = plan_name
    if row_name:
        p["production_plan_item"] = row_name
    for f in ("source_warehouse", "wip_warehouse", "fg_warehouse",
              "scrap_warehouse"):
        if p.get(f):
            p[f] = wh_map(p[f])
    p["description"] = f"{DESC_MARK} {w['name']} | PP: {plan_name}"
    p["operations"] = []
    p["required_items"] = []
    for k, v in w.items():
        if k.startswith("custom_") and k not in WO_DROP and \
                k in ctx.meta["Work Order"] and k not in BOX_FIELDS:
            p[k] = v
    return p


def cleanup_legacy(ctx, dry):
    """Hapus 60 WO lama hasil migrasi parsial (tanpa plan & SE)."""
    st, d = ctx.new.get("/api/resource/Work Order", {
        "filters": json.dumps([["company", "=", JURI],
                               ["description", "like",
                                f"{DESC_MARK}%"]]),
        "fields": json.dumps(["name", "description", "docstatus",
                              "production_plan"]),
        "limit_page_length": 0})
    legacy = [r for r in (d.get("data", []) if st == 200 else [])
              if "PP:" not in (r.get("description") or "")]
    print(f"  legacy WO lama ditemukan: {len(legacy)}")
    n = 0
    for r in legacy:
        if dry:
            print(f"  [DRY] hapus legacy {r['name']}")
            continue
        if r["docstatus"] == 1:
            st2, d2 = ctx.new.cancel("Work Order", r["name"])
            if st2 != 200:
                print(f"  [WARN] cancel {r['name']}: {json.dumps(d2)[:150]}")
        st3, d3 = ctx.new.delete("Work Order", r["name"])
        if st3 in (200, 202):
            n += 1
        else:
            print(f"  [WARN] delete {r['name']}: {json.dumps(d3)[:150]}")
    print(f"  legacy dihapus: {n}")


def phase_wos(ctx, dry, only_plan=None):
    print("== FASE 2: Work Order (dari Production Plan) ==")
    ctx.load_meta(["Work Order", "Work Order Item"])
    wos = jload("wos.json")
    plans = jload("plans.json")
    if not dry:
        ensure_allow_rename(ctx, "Work Order")
        cleanup_legacy(ctx, dry)
    out, fails = {}, []
    for plan_name in sorted(plans):
        if only_plan and plan_name != only_plan:
            continue
        st, d = ctx.new.get("/api/resource/Production Plan/" + plan_name)
        if st != 200 or d.get("data", {}).get("docstatus") != 1:
            print(f"  [!] plan {plan_name} belum ada/submitted - skip")
            continue
        plan_doc = d["data"]
        row_names = [r["name"] for r in
                     sorted(plan_doc.get("po_items", []),
                            key=lambda x: x.get("idx", 0))]
        old_wos = sorted([w for w in wos.values()
                          if w.get("production_plan") == plan_name],
                         key=lambda x: x["name"])
        if len(row_names) != len(old_wos):
            print(f"  [!] {plan_name}: baris plan={len(row_names)} "
                  f"WO lama={len(old_wos)} - skip")
            continue
        existing = {}
        for i in range(0, len(old_wos), 50):
            chunk = [w["name"] for w in old_wos[i:i + 50]]
            st, d = ctx.new.get("/api/resource/Work Order", {
                "filters": json.dumps([["name", "in", chunk]]),
                "fields": json.dumps(["name", "docstatus"]),
                "limit_page_length": 0})
            for r in (d.get("data", []) if st == 200 else []):
                existing[r["name"]] = r
        todo = [w for w in old_wos
                if existing.get(w["name"], {}).get("docstatus") != 1]
        if not todo:
            print(f"  [SKIP] {plan_name}: {len(old_wos)} WO sudah ada")
            out.update({w["name"]: w["name"] for w in old_wos})
            continue
        print(f"  {plan_name}: buat {len(todo)} WO")
        for w in todo:
            idx = old_wos.index(w)
            row_name = row_names[idx]
            payload = wo_payload(ctx, w, plan_name, row_name)
            if dry:
                print(f"    [DRY] {w['name']} {w['production_item']} "
                      f"qty={w['qty']} row={row_name}")
                continue
            st, d = ctx.new.post("Work Order", payload)
            if st != 200:
                print(f"    [FAIL] POST {w['name']}: {json.dumps(d)[:220]}")
                fails.append(w["name"])
                continue
            temp = d["data"]["name"]
            st_r, d_r = ctx.new.rename("Work Order", temp, w["name"])
            final = w["name"] if st_r == 200 else temp
            if st_r != 200:
                print(f"    [WARN] rename {temp}->{w['name']}: "
                      f"{str(d_r)[:150]}")
            st_s, d_s = ctx.new.submit("Work Order", final)
            ok = st_s == 200
            if not ok:
                fails.append(w["name"])
            print(f"    [{'OK' if ok else 'FAIL'}] {final} "
                  f"({w['production_item']} qty={w['qty']})")
            out[w["name"]] = final
    jdump("phase_wos.json", out)
    print(f"  WO selesai: {len(out)}, gagal: {len(fails)}")
    return out


# ------------------------------------------------------------------ fase 3
def mr_payload(ctx, m):
    p = pick(m, ctx.meta["Material Request"], MR_DROP)
    p["doctype"] = "Material Request"
    p["company"] = JURI
    for f in ("set_from_warehouse", "set_warehouse"):
        if p.get(f):
            p[f] = wh_map(p[f])
    for k in list(p):
        if ctx.meta_types["Material Request"].get(k) in LAYOUT_TYPES:
            p.pop(k, None)
    rows = []
    for it in m.get("items", []):
        q = {k: v for k, v in it.items() if k in MR_ITEM_KEEP and v is not None}
        q["item_code"] = item_map(it["item_code"])
        for f in ("from_warehouse", "warehouse"):
            if q.get(f):
                q[f] = wh_map(q[f])
        rows.append(q)
    p["items"] = rows
    for k, v in m.items():
        if k.startswith("custom_") and k in ctx.meta["Material Request"] \
                and k not in BOX_FIELDS and k != "custom_handover_box_plan":
            p[k] = v
    return p


def phase_mrs(ctx, dry):
    print("== FASE 3: Material Request serah terima ==")
    ctx.load_meta(["Material Request", "Material Request Item"])
    mrs = jload("mrs.json")
    if not dry:
        ensure_allow_rename(ctx, "Material Request")
    out, items_map = {}, {}
    for name in sorted(mrs):
        m = mrs[name]
        st, d = ctx.new.get("/api/resource/Material Request/" + name)
        if st == 200 and d.get("data", {}).get("docstatus") == 1:
            print(f"  [ADA] MR {name}")
            out[name] = name
            items_map[name] = {r["item_code"]: r["name"]
                               for r in d["data"].get("items", [])}
            continue
        payload = mr_payload(ctx, m)
        if dry:
            print(f"  [DRY] MR {name}: {len(payload['items'])} item")
            continue
        st, d = ctx.new.post("Material Request", payload)
        if st != 200:
            print(f"  [FAIL] POST MR {name}: {json.dumps(d)[:250]}")
            continue
        temp = d["data"]["name"]
        st_r, d_r = ctx.new.rename("Material Request", temp, name)
        final = name if st_r == 200 else temp
        if st_r != 200:
            print(f"  [WARN] rename {temp}->{name}: {str(d_r)[:150]}")
        st_s, d_s = ctx.new.submit("Material Request", final)
        ok = st_s == 200
        print(f"  [{'OK' if ok else 'WARN'}] MR {final} "
              f"(submit {st_s})")
        out[name] = final
        st_g, d_g = ctx.new.get("/api/resource/Material Request/" + final)
        if st_g == 200:
            items_map[name] = {r["item_code"]: r["name"]
                               for r in d_g["data"].get("items", [])}
    jdump("phase_mrs.json", {"map": out, "items": items_map})
    return out, items_map


# ------------------------------------------------------------------ fase 4
def se_from_old(ctx, s, extra_drop=()):
    """Payload SE salinan dari site lama (item dikonversi ke stock UOM).

    - Item non-stock di site baru (mis. BHP260028 Tisu) dilewati barisnya.
    - Link work_order dibuang (SE pendukung: WO September / tanpa WO).
    - Link material_request dibuang bila MR-nya tidak ikut dimigrasi.
    - Rate diambil dari data lama bila gudang sumber kosong di site baru.
    """
    p = pick(s, ctx.meta["Stock Entry"], SE_DROP | set(extra_drop))
    p.pop("work_order", None)
    p["doctype"] = "Stock Entry"
    p["company"] = JURI
    p["set_posting_time"] = 1
    p["posting_date"] = s.get("posting_date")
    p["posting_time"] = clean_time(s.get("posting_time"))
    for f in ("from_warehouse", "to_warehouse"):
        if p.get(f):
            p[f] = wh_map(p[f])
    if p.get("bom_no"):
        p["bom_no"] = BOM_MAP.get(p["bom_no"], p["bom_no"])
        if not ctx.acc_exists("BOM", p["bom_no"]):
            p.pop("bom_no", None)
    p["remarks"] = f"{MARK} {s['name']} | Migrasi Site Lama"
    rows, skipped = [], []
    is_receipt = s.get("stock_entry_type") == "Material Receipt"
    for it in s.get("items", []):
        code = item_map(it["item_code"])
        if not ctx.item(code).get("is_stock_item"):
            skipped.append(code)
            continue
        suom, uoms = ctx.stock_uom(code)
        cf = float(it.get("conversion_factor") or 1)
        qty = float(it.get("qty") or 0) * cf
        q = {"item_code": code, "qty": qty, "uom": suom}
        for f in ("s_warehouse", "t_warehouse"):
            if it.get(f):
                q[f] = wh_map(it[f])
        # link MR dibuang di jalur support (handover punya jalur sendiri)
        if it.get("is_finished_item"):
            q["is_finished_item"] = it["is_finished_item"]
        if it.get("allow_zero_valuation_rate"):
            q["allow_zero_valuation_rate"] = 1
        if is_receipt:
            rate = float(it.get("basic_rate") or it.get("valuation_rate") or 0)
            rate = rate / cf if cf else rate
            q["basic_rate"] = rate
            q["valuation_rate"] = rate
            if not rate:
                q["allow_zero_valuation_rate"] = 1
        rows.append(q)
    if skipped:
        p["remarks"] += f" | non-stock dilewati: {','.join(sorted(set(skipped)))}"
    p["items"] = rows
    p["docstatus"] = 1
    patch_rates(p, s)
    return p


def classify(ses, wo_set, mr_set):
    """Kembalikan (support, tfm, mfg, handover, skip)."""
    support, tfm, mfg, hand, skip = [], {}, {}, {}, []
    for s in ses.values():
        if s.get("docstatus") != 1:
            skip.append((s["name"], "cancelled/unsaved", s.get("stock_entry_type")))
            continue
        t = s.get("stock_entry_type")
        wo = s.get("work_order")
        refs = {it.get("material_request") for it in s.get("items", [])
                if it.get("material_request")} & mr_set
        if t == "Material Transfer for Manufacture" and wo in wo_set:
            tfm[wo] = s
        elif t == "Manufacture" and wo in wo_set:
            mfg[wo] = s
        elif t == "Manufacture":
            # WO di luar jendela (Sep) yang selesai 1-6 Okt: tetap direplay
            # tanpa link work_order (WO-nya tidak ada di site baru).
            support.append(s)
        elif t == "Material Transfer" and refs:
            hand[s["name"]] = s
        elif t == "Material Transfer" and not wo:
            support.append(s)
        elif t in ("Material Receipt", "Repack", "Material Issue"):
            support.append(s)
        else:
            skip.append((s["name"], "di luar scope", t))
    return support, tfm, mfg, hand, skip


def patch_rates(doc, old):
    """Isi rate baris dari SE lama bila rate target tidak diketahui.

    BB260055 dkk bisa 0-stock di gudang sumber site baru (opening belum
    lengkap) -> ERPNext minta valuation rate. Pakai basic_rate lama bila ada.
    """
    rates = {}
    for it in old.get("items", []):
        r = float(it.get("basic_rate") or it.get("valuation_rate") or 0)
        if r > 0:
            rates[item_map(it["item_code"])] = r
    for row in doc.get("items", []):
        code = row.get("item_code")
        r = float(row.get("basic_rate") or row.get("valuation_rate") or 0)
        if r <= 0 and rates.get(code):
            row["basic_rate"] = rates[code]
            row["valuation_rate"] = rates[code]
            row["set_basic_rate_manually"] = 1
            row["allow_zero_valuation_rate"] = 1
        elif r <= 0:
            row["allow_zero_valuation_rate"] = 1
    return doc


def gen_se(ctx, wo, purpose, qty):
    st, d = ctx.new.req(
        "POST",
        "/api/method/erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry",
        {"work_order_id": wo, "purpose": purpose, "qty": qty})
    if st != 200:
        return None, d
    doc = d.get("message") or {}
    for k in ("name", "owner", "creation", "modified", "modified_by", "idx",
              "__islocal", "__unsaved", "_user_tags", "_comments", "_assign",
              "_liked_by"):
        doc.pop(k, None)
    return doc, None


def build_jobs(ctx, existing=None, dry=False):
    """Bangun seluruh job SE. `existing` = marker map {'ERESTO <old>': ...}.

    Job untuk dokumen yang sudah ter-posting (docstatus=1) dilewati sejak awal
    supaya rerun murah dan tidak memanggil make_stock_entry yang sudah ada.
    """
    existing = existing or {}
    wos, plans, mrs, ses = load_dump()
    wo_set, mr_set = set(wos), set(mrs)
    support, tfm, mfg, hand, skip = classify(ses, wo_set, mr_set)
    mrs_map = jload("phase_mrs.json", {}) or {}
    mr_items_map = mrs_map.get("items", {})
    jobs, notes = [], []

    def done(old_name):
        cur = existing.get(old_name)
        return bool(cur and cur.get("docstatus") == 1)

    if not dry:
        support = [s for s in support if not done(s["name"])]
        tfm = {k: v for k, v in tfm.items() if not done(v["name"])}
        mfg = {k: v for k, v in mfg.items() if not done(v["name"])}
        hand = {k: v for k, v in hand.items() if not done(k)}

    for s in support:
        payload = se_from_old(ctx, s)
        if not payload.get("items"):
            notes.append(f"{s['name']} dilewati: semua item non-stock di site "
                         f"baru (tanpa efek ledger)")
            continue
        jobs.append({"old": s["name"], "kind": "support",
                     "date": s.get("posting_date"), "time": s.get("posting_time"),
                     "prio": PRIO.get(s.get("stock_entry_type"), 9),
                     "payload": payload})

    wo_docs = {}
    names = sorted(wos)
    for i in range(0, len(names), 50):
        chunk = names[i:i + 50]
        st, d = ctx.new.get("/api/resource/Work Order", {
            "filters": json.dumps([["name", "in", chunk]]),
            "fields": json.dumps(["name", "qty", "produced_qty",
                                  "production_item"]),
            "limit_page_length": 0})
        for r in (d.get("data", []) if st == 200 else []):
            wo_docs[r["name"]] = r

    for wo_name in sorted(tfm):
        old = tfm[wo_name]
        wq = float(wos[wo_name]["qty"])
        doc, err = gen_se(ctx, wo_name, "Material Transfer for Manufacture", wq)
        if not doc:
            notes.append(f"TFM gagal dibuat {wo_name}: {str(err)[:150]}")
            continue
        doc["posting_date"] = old.get("posting_date")
        doc["posting_time"] = clean_time(old.get("posting_time"))
        doc["set_posting_time"] = 1
        doc["remarks"] = f"{MARK} {old['name']} | Migrasi Site Lama"
        doc["company"] = JURI
        doc["docstatus"] = 1
        patch_rates(doc, old)
        jobs.append({"old": old["name"], "kind": "tfm", "wo": wo_name,
                     "date": old.get("posting_date"),
                     "time": clean_time(old.get("posting_time")),
                     "prio": PRIO["Material Transfer for Manufacture"],
                     "payload": doc})

    for wo_name in sorted(mfg):
        old = mfg[wo_name]
        wq = float(wos[wo_name]["qty"])
        produced = float(wos[wo_name].get("produced_qty") or 0)
        loss_old = float(old.get("process_loss_qty") or 0)
        q = max(produced, wq)
        doc, err = gen_se(ctx, wo_name, "Manufacture", q)
        fallback = False
        if not doc and q > wq:
            doc, err2 = gen_se(ctx, wo_name, "Manufacture", wq)
            fallback = True
            if not doc:
                notes.append(f"MFG gagal dibuat {wo_name}: {str(err)[:150]}")
                continue
        elif not doc:
            notes.append(f"MFG gagal dibuat {wo_name}: {str(err)[:150]}")
            continue
        for row in doc.get("items", []):
            if row.get("is_finished_item") and row.get("t_warehouse"):
                row["qty"] = produced
                if "transfer_qty" in row:
                    row["transfer_qty"] = produced
        doc["process_loss_qty"] = loss_old if not fallback else max(q - produced, 0)
        doc["fg_completed_qty"] = produced + (loss_old if not fallback
                                              else max(q - produced, 0))
        doc["posting_date"] = old.get("posting_date")
        doc["posting_time"] = clean_time(old.get("posting_time"))
        doc["set_posting_time"] = 1
        doc["remarks"] = f"{MARK} {old['name']} | Migrasi Site Lama"
        doc["company"] = JURI
        doc["docstatus"] = 1
        patch_rates(doc, old)
        if fallback:
            notes.append(f"MFG {wo_name}: fallback qty={wq} (minta {q})")
        jobs.append({"old": old["name"], "kind": "mfg", "wo": wo_name,
                     "date": old.get("posting_date"),
                     "time": clean_time(old.get("posting_time")),
                     "prio": PRIO["Manufacture"],
                     "payload": doc})

    for old_name, s in sorted(hand.items()):
        mr_old = next((it["material_request"] for it in s["items"]
                       if it.get("material_request")), None)
        mr_new = mr_items_map and mr_old or mr_old
        row_ids = mr_items_map.get(mr_old, {})
        rows = []
        ok = True
        for it in s["items"]:
            code = item_map(it["item_code"])
            suom, _ = ctx.stock_uom(code)
            row = {"item_code": code, "qty": float(it.get("qty") or 0),
                   "uom": suom,
                   "s_warehouse": wh_map(it.get("s_warehouse")),
                   "t_warehouse": wh_map(it.get("t_warehouse")),
                   "material_request": mr_new}
            if row_ids.get(code):
                row["material_request_item"] = row_ids[code]
            else:
                ok = False
            rows.append(row)
        if not ok:
            notes.append(f"handover {old_name}: row MR tidak ketemu "
                         f"({mr_old})")
        payload = {"doctype": "Stock Entry",
                   "stock_entry_type": "Material Transfer",
                   "purpose": "Material Transfer", "company": JURI,
                   "from_warehouse": wh_map(s.get("from_warehouse")),
                   "to_warehouse": wh_map(s.get("to_warehouse")),
                   "posting_date": s.get("posting_date"),
                   "posting_time": clean_time(s.get("posting_time")),
                   "set_posting_time": 1,
                   "remarks": f"{MARK} {old_name} | Migrasi Site Lama",
                   "items": rows, "docstatus": 1}
        jobs.append({"old": old_name, "kind": "handover", "mr": mr_new,
                     "date": s.get("posting_date"),
                     "time": clean_time(s.get("posting_time")),
                     "prio": PRIO["Material Transfer"],
                     "payload": payload})

    jobs.sort(key=lambda j: (str(j["date"]), hms(j["time"]), j["prio"],
                             j["old"]))
    return jobs, skip, notes


def simulate(ctx, jobs):
    """Simulasi saldo berjalan dari Bin target + job yang akan diposting."""
    bins, start = {}, 0
    while True:
        st, d = ctx.new.get("/api/resource/Bin", {
            "filters": json.dumps([["warehouse", "like", "%- JURI"]]),
            "fields": json.dumps(["item_code", "warehouse", "actual_qty"]),
            "limit_page_length": 500, "limit_start": start})
        rows = d.get("data", []) if st == 200 else []
        if not rows:
            break
        for r in rows:
            bins[(r["item_code"], r["warehouse"])] = float(r["actual_qty"])
        start += len(rows)
        if len(rows) < 500:
            break
    bal = dict(bins)
    mins = {}
    for j in jobs:
        for it in j["payload"].get("items", []):
            code = it["item_code"]
            for f, sg in (("s_warehouse", -1), ("t_warehouse", 1)):
                wh = it.get(f)
                if not wh or wh not in ("Gudang Barang Jadi - JURI", "Gudang Bahan Baku - JURI",
                                        "Gudang Produksi - JURI", "Work In Progress - JURI",
                                        "Cold Storage Produksi - JURI"):
                    pass
                if not wh:
                    continue
                k = (code, wh)
                bal[k] = bal.get(k, 0.0) + sg * float(it.get("qty") or 0)
                if k not in mins or bal[k] < mins[k]:
                    mins[k] = bal[k]
    neg = sorted([(k, v) for k, v in mins.items() if v < -0.01],
                 key=lambda x: x[1])
    return neg


def phase_ses(ctx, dry):
    print("== FASE 4: Stock Entry (kronologis) ==")
    ctx.load_meta(["Stock Entry", "Stock Entry Detail"])
    existing = marker_map(ctx, "Stock Entry", "remarks")
    print(f"  marker SE existing di target: {len(existing)}")
    jobs, skip, notes = build_jobs(ctx, existing=existing, dry=dry)
    print(f"  job baru: {len(jobs)} (support/tfm/mfg/handover), "
          f"di luar scope: {len(skip)}")
    for n in notes:
        print(f"  [!] {n}")
    if dry:
        for j in jobs[:5]:
            print(f"  [DRY] {j['old']} -> {j['kind']} {j['date']} {j['time']}")
        print(f"  [DRY] total job: {len(jobs)}")
        return

    pending = jobs
    result = {"ok": [], "fail": []}
    for rnd in range(1, 4):
        if not pending:
            break
        nxt = []
        print(f"  -- ronde {rnd}: {len(pending)} --")
        for j in pending:
            st, d = ctx.new.post("Stock Entry", j["payload"])
            if st != 200:
                msg = json.dumps(d, default=str)
                result["fail"].append({"old": j["old"], "kind": j["kind"],
                                       "err": msg[:300]})
                print(f"    [FAIL] {j['old']} ({j['kind']}): {msg[:180]}")
                if rnd < 3 and re.search(r"negative|insufficient|stock|"
                                         r"not enough|less than|required|"
                                         r"reserved|available|overproduc|"
                                         r"valuation",
                                         msg, re.I):
                    nxt.append(j)
                continue
            new_name = d.get("data", {}).get("name")
            result["ok"].append({"old": j["old"], "kind": j["kind"],
                                 "new": new_name, "date": j["date"]})
            print(f"    [OK] {j['old']} -> {new_name} ({j['kind']})")
        pending = nxt
    if pending:
        for j in pending:
            result["fail"].append({"old": j["old"], "kind": j["kind"],
                                   "err": "defer habis"})
    jdump("phase_ses.json", result)
    print(f"  SE posted: {len(result['ok'])}, gagal: "
          f"{len(result['fail'])}")
    for f in result["fail"][:20]:
        print("    GAGAL", f)
    return result


# ------------------------------------------------------------------ fase 5
def phase_verify(ctx, repair=False):
    print("== FASE 5: VERIFIKASI ==")
    import pandas as pd
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    wos, plans, mrs, ses = load_dump()
    wo_set, mr_set = set(wos), set(mrs)
    names = sorted(wos)

    new_wos = {}
    for i in range(0, len(names), 40):
        chunk = names[i:i + 40]
        st, d = ctx.new.get("/api/resource/Work Order", {
            "filters": json.dumps([["name", "in", chunk]]),
            "fields": json.dumps(["*"]), "limit_page_length": 0})
        for r in (d.get("data", []) if st == 200 else []):
            new_wos[r["name"]] = r

    se_map = {}
    for r in ctx.new.list_all("Stock Entry",
                              ["name", "remarks", "stock_entry_type",
                               "work_order", "docstatus", "posting_date"],
                              [["remarks", "like", f"%{MARK} MAT-STE-%"]],
                              order="name asc"):
        t = token_of(r.get("remarks"))
        if t:
            se_map[t] = r

    def old_se_count(wo, kind):
        n = 0
        for s in ses.values():
            if s.get("work_order") == wo and s.get("docstatus") == 1:
                if s.get("stock_entry_type") == kind:
                    n += 1
        return n

    def new_se_count(wo, kind):
        n = 0
        for r in se_map.values():
            if r.get("work_order") == wo and r.get("stock_entry_type") == kind \
                    and r.get("docstatus") == 1:
                n += 1
        return n

    tags = ["adonan_ke", "jam_adonan", "suhu_adonan", "nama_penimbang",
            "jumlah_kru", "leader_produksi", "qc_produksi", "jam_pembekuan",
            "good_qty_prepacking", "reject_qty_prepacking",
            "trial_qty_prepacking", "sisa_qty_prepacking",
            "prepacking_confirmed", "jam_packing", "qc_packing",
            "good_qty_postpacking", "reject_qty_postpacking",
            "trial_qty_postpacking", "sisa_qty_postpacking",
            "postpacking_confirmed"]
    def canon(v):
        if v is None:
            return ""
        if isinstance(v, float):
            return round(v, 4)
        s = str(v).strip()
        try:
            return round(float(s), 4)
        except ValueError:
            return s

    rows, arsip, n_fail = [], [], 0
    for n in names:
        o, w = wos[n], new_wos.get(n, {})
        pr = []
        if not w:
            pr.append("TIDAK ADA")
        else:
            if w.get("docstatus") != 1:
                pr.append("docstatus!=1")
            if (w.get("status") or "") != (o.get("status") or ""):
                pr.append(f"status {w.get('status')}!={o.get('status')}")
            for f in ("qty", "produced_qty", "process_loss_qty",
                      "material_transferred_for_manufacturing"):
                if canon(w.get(f)) != canon(o.get(f)):
                    pr.append(f"{f} {w.get(f)}!={o.get(f)}")
            for t in tags:
                if canon(w.get("custom_" + t)) != canon(o.get("custom_" + t)):
                    pr.append(f"custom_{t}")
            if w.get("production_plan") != o.get("production_plan"):
                pr.append("production_plan")
            if (w.get("custom_handover_material_request") or "") != \
                    (o.get("custom_handover_material_request") or ""):
                pr.append("handover_mr")
            if (w.get("custom_handover_status") or "") != \
                    (o.get("custom_handover_status") or ""):
                pr.append("handover_status")
            if norm_dt(w.get("actual_start_date")) != \
                    norm_dt(o.get("actual_start_date")):
                pr.append("actual_start")
            if norm_dt(w.get("actual_end_date")) != \
                    norm_dt(o.get("actual_end_date")):
                pr.append("actual_end")
            if new_se_count(n, "Material Transfer for Manufacture") != \
                    old_se_count(n, "Material Transfer for Manufacture"):
                pr.append("jml_SE_tfm")
            if new_se_count(n, "Manufacture") != old_se_count(n, "Manufacture"):
                pr.append("jml_SE_mfg")
        if pr:
            n_fail += 1
        rows.append({
            "Work Order": n, "Plan": o.get("production_plan"),
            "Item": o.get("production_item"), "Qty": o.get("qty"),
            "Status Lama": o.get("status"), "Status Baru": w.get("status"),
            "Produced Lama": o.get("produced_qty"),
            "Produced Baru": w.get("produced_qty"),
            "Loss Lama": o.get("process_loss_qty"),
            "Loss Baru": w.get("process_loss_qty"),
            "Transfer Lama": o.get("material_transferred_for_manufacturing"),
            "Transfer Baru": w.get("material_transferred_for_manufacturing"),
            "Adonan Ke": o.get("custom_adonan_ke"),
            "Jam Adonan": o.get("custom_jam_adonan"),
            "Suhu": o.get("custom_suhu_adonan"),
            "Penimbang": o.get("custom_nama_penimbang"),
            "Kru": o.get("custom_jumlah_kru"),
            "Leader": o.get("custom_leader_produksi"),
            "QC Produksi": o.get("custom_qc_produksi"),
            "Jam Beku": o.get("custom_jam_pembekuan"),
            "Prepack Good": o.get("custom_good_qty_prepacking"),
            "Postpack Good": o.get("custom_good_qty_postpacking"),
            "MR Lama": o.get("custom_handover_material_request") or "",
            "MR Baru": w.get("custom_handover_material_request") or "",
            "Handover Lama": o.get("custom_handover_status") or "",
            "Handover Baru": w.get("custom_handover_status") or "",
            "SE TFM lama/baru": f"{old_se_count(n, 'Material Transfer for Manufacture')}"
                                f"/{new_se_count(n, 'Material Transfer for Manufacture')}",
            "SE MFG lama/baru": f"{old_se_count(n, 'Manufacture')}"
                                f"/{new_se_count(n, 'Manufacture')}",
            "Actual Start Lama": norm_dt(o.get("actual_start_date")),
            "Actual Start Baru": norm_dt(w.get("actual_start_date")),
            "Actual End Lama": norm_dt(o.get("actual_end_date")),
            "Actual End Baru": norm_dt(w.get("actual_end_date")),
            "Hasil": "LOLOS" if not pr else "SELISIH",
            "Catatan": "; ".join(pr)})
        arsip.append({"Work Order": n, "Item": o.get("production_item"),
                      "Box 1 (kg)": o.get("custom_box_1"),
                      "Box 1 Qty": o.get("custom_box_1_qty"),
                      "Box 2 (kg)": o.get("custom_box_2"),
                      "Box 2 Qty": o.get("custom_box_2_qty"),
                      "Box 3 (kg)": o.get("custom_box_3"),
                      "Box 3 Qty": o.get("custom_box_3_qty")})

    if repair:
        fixed = 0
        for n in names:
            o, w = wos[n], new_wos.get(n, {})
            if not w:
                continue
            vals = {}
            for t in tags:
                if canon(w.get("custom_" + t)) != canon(o.get("custom_" + t)):
                    vals["custom_" + t] = o.get("custom_" + t)
            if (w.get("custom_handover_material_request") or "") != \
                    (o.get("custom_handover_material_request") or ""):
                vals["custom_handover_material_request"] = \
                    o.get("custom_handover_material_request")
            if (w.get("custom_handover_status") or "") != \
                    (o.get("custom_handover_status") or ""):
                vals["custom_handover_status"] = o.get("custom_handover_status")
            if norm_dt(w.get("actual_start_date")) != \
                    norm_dt(o.get("actual_start_date")):
                vals["actual_start_date"] = o.get("actual_start_date")
            if norm_dt(w.get("actual_end_date")) != \
                    norm_dt(o.get("actual_end_date")):
                vals["actual_end_date"] = o.get("actual_end_date")
            if vals:
                st, d = ctx.new.req(
                    "POST", "/api/method/frappe.client.set_value",
                    {"doctype": "Work Order", "name": n,
                     "fieldname": json.dumps(vals)})
                if st == 200:
                    fixed += 1
                else:
                    print(f"  [!] repair {n}: {str(d)[:150]}")
        print(f"  repair: {fixed} WO diperbaiki")

    # ---------------- Excel
    plan_rows = []
    for pn in sorted(plans):
        o = plans[pn]
        st, d = ctx.new.get("/api/resource/Production Plan/" + pn)
        w = d.get("data", {}) if st == 200 else {}
        o_cnt = len(o.get("po_items", []))
        n_cnt = len(w.get("po_items", [])) if w else 0
        plan_rows.append({
            "Plan": pn, "Docstatus Baru": w.get("docstatus"),
            "Status Lama": o.get("status"), "Status Baru": w.get("status"),
            "Planned Lama": o.get("total_planned_qty"),
            "Planned Baru": w.get("total_planned_qty"),
            "Produced Lama": o.get("total_produced_qty"),
            "Produced Baru": w.get("total_produced_qty"),
            "Jml Baris Lama": o_cnt, "Jml Baris Baru": n_cnt})

    se_rows = []
    for en, r in sorted(se_map.items()):
        se_rows.append({"Jenis": r.get("stock_entry_type"), "SE Lama": en,
                        "SE Baru": r.get("name"),
                        "Posting": r.get("posting_date"),
                        "Docstatus": r.get("docstatus")})
    mr_rows = []
    for mn in sorted(mrs):
        st, d = ctx.new.get("/api/resource/Material Request/" + mn)
        w = d.get("data", {}) if st == 200 else {}
        mr_rows.append({"MR Lama": mn, "MR Baru": w.get("name"),
                        "Docstatus": w.get("docstatus"),
                        "Status": w.get("status"),
                        "Item": mrs[mn]["items"][0]["item_code"] if mrs[mn].get("items") else "",
                        "Qty": mrs[mn]["items"][0]["qty"] if mrs[mn].get("items") else "",
                        "WO": mrs[mn]["items"][0].get("custom_work_order", "") if mrs[mn].get("items") else ""})

    jobs_json = jload("phase_ses.json", {}) or {}
    done = {x["old"] for x in jobs_json.get("ok", [])}
    fail = jobs_json.get("fail", [])

    ringkas = [
        {"Kunci": "Total WO target", "Nilai": len(names)},
        {"Kunci": "WO LOLOS", "Nilai": len(names) - n_fail},
        {"Kunci": "WO SELISIH", "Nilai": n_fail},
        {"Kunci": "Total SE diposting (marker)", "Nilai": len(se_map)},
        {"Kunci": "SE gagal", "Nilai": len(fail)},
        {"Kunci": "MR serah terima", "Nilai": len(mr_rows)},
        {"Kunci": "Tanggal migrasi", "Nilai": time.strftime("%Y-%m-%d %H:%M:%S")},
    ]

    out_path = os.path.join(HERE, "Laporan_Migrasi_WO_1_6_Okt2026.xlsx")
    with pd.ExcelWriter(out_path, engine="openpyxl") as xw:
        pd.DataFrame(rows).to_excel(xw, sheet_name="Hasil_WO", index=False)
        pd.DataFrame(arsip).to_excel(xw, sheet_name="Arsip_Box_Lama", index=False)
        pd.DataFrame(plan_rows).to_excel(xw, sheet_name="Production_Plan", index=False)
        pd.DataFrame(se_rows).to_excel(xw, sheet_name="SE_Mapping", index=False)
        pd.DataFrame(mr_rows).to_excel(xw, sheet_name="MR_Mapping", index=False)
        if fail:
            pd.DataFrame(fail).to_excel(xw, sheet_name="SE_Gagal", index=False)
    wb = openpyxl.load_workbook(out_path)
    fill = PatternFill("solid", start_color="D9EAF7")
    ok_fill = PatternFill("solid", start_color="E2EFDA")
    bad_fill = PatternFill("solid", start_color="FCE4E4")
    for ws in wb.worksheets:
        ws.freeze_panes = "A2"
        for c in ws[1]:
            c.fill = fill
            c.font = Font(bold=True)
            c.alignment = Alignment(horizontal="center")
    if "Hasil_WO" in wb.sheetnames:
        ws = wb["Hasil_WO"]
        col = [c.value for c in ws[1]].index("Hasil") + 1
        for r in range(2, ws.max_row + 1):
            c = ws.cell(row=r, column=col)
            c.fill = ok_fill if c.value == "LOLOS" else bad_fill
    wb.save(out_path)
    print(f"  total WO: {len(names)}, LOLOS: {len(names) - n_fail}, "
          f"SELISIH: {n_fail}")
    print(f"  laporan: {out_path}")
    return n_fail


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--plans", action="store_true")
    ap.add_argument("--wos", action="store_true")
    ap.add_argument("--mrs", action="store_true")
    ap.add_argument("--ses", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--repair", action="store_true")
    ap.add_argument("--only-plan", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    ctx = Ctx()
    if args.dump:
        phase_dump(ctx)
    if args.plans:
        phase_plans(ctx, args.dry_run)
    if args.wos:
        phase_wos(ctx, args.dry_run, only_plan=args.only_plan or None)
    if args.mrs:
        phase_mrs(ctx, args.dry_run)
    if args.ses:
        phase_ses(ctx, args.dry_run)
    if args.verify:
        phase_verify(ctx, repair=args.repair)
    if not any([args.dump, args.plans, args.wos, args.mrs, args.ses,
                args.verify]):
        ap.print_help()


if __name__ == "__main__":
    main()
