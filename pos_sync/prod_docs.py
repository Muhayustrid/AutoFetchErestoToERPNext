"""Tahap dokumen PROD (docs/07): WO -> PO -> SO -> PR -> SE -> DN.

Sumber: pos_sync/prod_src/*.json (state final site lokal). Marker idempotency
`ERESTO <nama-lama>` disalin apa adanya. Relink antar dokumen:
SE.work_order, PR.purchase_order, DN.against_sales_order via map lokal->prod.

Keputusan tanggal: dokumen stok (PR/SE/DN) disubmit TANPA posting_date/
set_posting_time -> ERPNext mencap waktu submit. Validasi stok ERPNext
berjalan per titik waktu ("current datetime onwards", stock_ledger.py), jadi
urutan submit = urutan waktu = rantai yang valid. Dokumen non-stok (PO/SO/WO)
tetap memakai tanggal aslinya.

SE Manufacture dengan company != PT. JUARA ROTI INDONESIA dilewati (aturan
user). Kegagalan stok ditunda (defer) sampai 5 ronde.

Usage:
  python3 prod_docs.py --dry-run
  python3 prod_docs.py --only-wo WO-JURI-261004199   (smoke: WO + SE-nya)
  python3 prod_docs.py
Env: /tmp/eresto_mig.env (lokal), /tmp/eresto_prod.env (prod).
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import (JURI, LOCAL_ENV, PROD_ENV, SRC_DIR, Client,  # noqa: E402
                         jload, load_env, load_state, pick, pick_rows,
                         save_state)

# ---------- field drop sets (mengikuti skrip migrate_* yang sudah terbukti) ----
WO_DROP = {
    "production_plan", "production_plan_item",
    "production_plan_sub_assembly_item",
    "sales_order", "sales_order_item",
    "material_request", "material_request_item",
    "posa_operator", "posa_pos_profile", "posa_recipe",
    "custom_uom", "custom_handover_material_request",
    "operations", "required_items", "secondary_items", "non_stock_items",
    "status", "produced_qty", "material_transferred_for_manufacturing",
    "naming_series", "actual_start_date", "actual_end_date",
    "planned_operating_cost", "actual_operating_cost",
    "additional_operating_cost", "corrective_operation_cost",
    "total_operating_cost", "disassembled_qty",
}
SE_DROP = {
    "letter_head", "custom_note", "status", "naming_series",
    "total_amount", "total_incoming_value", "total_outgoing_value",
    "value_difference", "per_transferred", "additional_costs",
    # tanggal: pakai waktu submit (lihat docstring)
    "posting_date", "posting_time", "set_posting_time",
}
PO_DROP = {
    "letter_head", "workflow_state", "status", "naming_series",
    "shipping_address", "shipping_address_display",
    "billing_address", "billing_address_display",
    "dispatch_address", "dispatch_address_display",
    "contact_person", "contact_display", "contact_email", "contact_mobile",
    "custom_note", "custom_section_break_tjtb0",
    "taxes", "payment_schedule", "pricing_rules", "supplied_items",
    "item_wise_tax_details", "advance_payment_status",
}
PR_DROP = PO_DROP | {"posting_date", "posting_time", "set_posting_time"}
SO_DROP = {
    "letter_head", "pos_profile", "posa_pos_opening_shift",
    "inter_company_order_reference",
    "company_address", "company_address_display",
    "shipping_address", "shipping_address_display", "shipping_address_name",
    "billing_address", "billing_address_display",
    "dispatch_address", "dispatch_address_display", "dispatch_address_name",
    "customer_address", "address_display",
    "contact_person", "contact_display", "contact_email", "contact_mobile",
    "status", "naming_series", "taxes", "payment_schedule",
    "pricing_rules", "sales_team", "advance_payment_status",
    "item_wise_tax_details",
}
DN_DROP = SO_DROP | {"posting_date", "posting_time", "set_posting_time"}
ROW_DROP = {
    "naming_series", "against_sales_order", "so_detail", "sales_order",
    "sales_order_item", "purchase_order", "purchase_order_item",
    "material_request", "material_request_item", "amended_from",
    "delivery_note_item", "dn_detail", "bom_no", "pricing_rules",
    "item_wise_tax_details", "purchase_receipt",
}

SE_TYPE_ORDER = ["Material Receipt", "Material Transfer for Manufacture",
                 "Manufacture", "Material Transfer", "Repack",
                 "Material Issue"]
DEFER_PAT = re.compile(
    r"NegativeStock|negative stock|Insufficient|not enough|less than|"
    r"needed in|allowed only|reserved", re.I)


def token(text):
    if not text:
        return None
    i = text.find("ERESTO ")
    if i < 0:
        return None
    rest = text[i + 7:].strip()
    return rest.split()[0] if rest else None


def load_existing(pc, doctype, field):
    """{token: {'name':..,'docstatus':..}} utk dokumen marker ERESTO di prod."""
    out = {}
    for r in pc.list_all(doctype, ["name", field, "docstatus"],
                         [[field, "like", "ERESTO%"]], order="name asc"):
        t = token(str(r.get(field) or ""))
        if t:
            out.setdefault(t, {"name": r["name"], "docstatus": r["docstatus"]})
    return out


class Runner:
    def __init__(self, pc, meta, dry):
        self.pc = pc
        self.meta = meta
        self.dry = dry
        self.fails = []
        self.result = {"created": [], "submitted_draft": [], "skipped": [],
                       "deferred_final": []}

    def fail(self, dt, ref, msg):
        self.fails.append({"doctype": dt, "ref": ref, "err": str(msg)[:300]})
        print(f"    FAIL {dt} {ref}: {str(msg)[:180]}")

    def ensure(self, doctype, src, marker, payload_fn, submit, exists):
        """Buat/submit satu dokumen. Return nama prod, 'DEFER', atau None."""
        t = token(marker)
        cur = exists.get(t)
        created_now = False
        if cur is None and not self.dry:
            payload = payload_fn()
            st, d = self.pc.post(doctype, payload)
            if st != 200:
                msg = json.dumps(d)
                if DEFER_PAT.search(msg):
                    return "DEFER"
                self.fail(doctype, src, msg)
                return None
            name = d["data"]["name"]
            cur = {"name": name, "docstatus": 0}
            exists[t] = cur
            created_now = True
        elif cur is None and self.dry:
            self.result["created"].append({"doctype": doctype, "lama": src,
                                           "baru": "DRY"})
            return "DRY"
        if submit and cur["docstatus"] == 0 and not self.dry:
            st, d = self.pc.submit(doctype, cur["name"])
            if st != 200:
                msg = json.dumps(d)
                if DEFER_PAT.search(msg):
                    return "DEFER"
                self.fail(doctype, src, f"submit: {msg}")
                return None
            cur["docstatus"] = 1
            if not created_now:
                self.result["submitted_draft"].append(
                    {"doctype": doctype, "name": cur["name"]})
        if created_now:
            self.result["created"].append({"doctype": doctype, "lama": src,
                                           "baru": cur["name"]})
        elif cur["docstatus"] == 1:
            self.result["skipped"].append({"doctype": doctype,
                                           "name": cur["name"]})
        return cur["name"]

    def summary(self):
        for k, v in self.result.items():
            print(f"  {k}: {len(v)}")
        print(f"  fails: {len(self.fails)}")
        for f in self.fails[:30]:
            print("   ", f)


def run_round(runner, jobs, round_no):
    defer = []
    for job in jobs:
        doctype, src = job[0], job[1]
        print(f"  [r{round_no}] {doctype} {src}")
        name = runner.ensure(*job)
        if name == "DEFER":
            print("    -> tunda (stok)")
            defer.append(job)
    return defer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only-wo", default="")
    ap.add_argument("--max-rounds", type=int, default=5)
    args = ap.parse_args()

    le, pe = load_env(LOCAL_ENV), load_env(PROD_ENV)
    pc = Client(pe["ERPNEXT_URL"], pe["ERPNEXT_API_KEY"], label="prod",
                pause=0.05)
    meta = json.load(open(os.path.join(SRC_DIR, "prod_meta.json")))
    state = load_state()
    cust_alias = state.get("customer_alias", {})
    runner = Runner(pc, meta, args.dry_run)

    wos = jload("work_order.json")
    pos = jload("purchase_order.json")
    sos = jload("sales_order.json")
    prs = jload("purchase_receipt.json")
    ses = [s for s in jload("stock_entry.json")
           if (s.get("remarks") or "").startswith("ERESTO MAT-STE-")]
    dns = jload("delivery_note.json")

    # --- resume maps (idempotensi antar-run): token -> prod name
    wo_ex = load_existing(pc, "Work Order", "description")
    po_ex = load_existing(pc, "Purchase Order", "title")
    so_ex = load_existing(pc, "Sales Order", "title")
    pr_ex = load_existing(pc, "Purchase Receipt", "title")
    se_ex = load_existing(pc, "Stock Entry", "remarks")
    dn_ex = load_existing(pc, "Delivery Note", "title")
    print(f"existing prod: WO={len(wo_ex)} PO={len(po_ex)} SO={len(so_ex)} "
          f"PR={len(pr_ex)} SE={len(se_ex)} DN={len(dn_ex)}")

    wo_map = {}
    for w in wos:
        t = token(w.get("description"))
        wo_map[w["name"]] = (wo_ex[t]["name"] if t and t in wo_ex
                             else w["name"])

    def wo_payload(w):
        p = pick(w, meta["Work Order"], WO_DROP)
        p["doctype"] = "Work Order"
        p["operations"] = []
        p["required_items"] = []
        return p

    # ---------- fase 1: WO ----------
    print("== fase 1: Work Order ==")
    for w in sorted(wos, key=lambda x: x["name"]):
        if w["docstatus"] != 1:
            continue
        if args.only_wo and w["name"] != args.only_wo:
            continue
        name = runner.ensure("Work Order", w["name"],
                             w.get("description") or "",
                             lambda w=w: wo_payload(w), True, wo_ex)
        if name and name not in ("DEFER", "DRY"):
            wo_map[w["name"]] = name
    print(f"  WO map: {len([1 for k, v in wo_map.items() if v])}")

    smoke = bool(args.only_wo)

    # ---------- fase 2: PO ----------
    po_map = {}
    for h in sorted(pos, key=lambda x: x["name"]):
        t = token(h.get("title"))
        if t and t in po_ex:
            po_map[h["name"]] = (po_ex[t]["name"], po_ex[t]["docstatus"])
    if not smoke:
        print("== fase 2: Purchase Order ==")
        jobs = []
        for h in sorted(pos, key=lambda x: x["name"]):
            if h["name"] in po_map:
                continue
            submit = h["docstatus"] in (1, 2)

            def po_payload(h):
                return {**pick(h, meta["Purchase Order"], PO_DROP),
                        "doctype": "Purchase Order",
                        "title": h.get("title") or "",
                        "items": pick_rows(h.get("items"),
                                           meta["Purchase Order Item"],
                                           ROW_DROP)}
            jobs.append(("Purchase Order", h["name"], h.get("title") or "",
                         lambda h=h: po_payload(h), submit, po_ex))
        run_round(runner, jobs, 0)
        po_ex.update(load_existing(pc, "Purchase Order", "title"))
        for h in sorted(pos, key=lambda x: x["name"]):
            if h["name"] in po_map:
                continue
            t = token(h.get("title"))
            cur = po_ex.get(t)
            if cur:
                po_map[h["name"]] = (cur["name"], cur["docstatus"])
        for h in sorted(pos, key=lambda x: x["name"]):
            if h["docstatus"] != 2 or h["name"] not in po_map:
                continue
            nm, ds = po_map[h["name"]]
            if ds == 1 and not args.dry_run:
                st, d = pc.cancel("Purchase Order", nm)
                print(f"  cancel {nm}: HTTP {st}")
                po_map[h["name"]] = (nm, 2)

    # ---------- fase 3: SO ----------
    so_map = {}
    if not smoke:
        print("== fase 3: Sales Order ==")
        jobs = []
        for h in sorted(sos, key=lambda x: x["name"]):
            p = {**pick(h, meta["Sales Order"], SO_DROP),
                 "doctype": "Sales Order", "title": h.get("title") or "",
                 "items": pick_rows(h.get("items"), meta["Sales Order Item"],
                                    ROW_DROP)}
            cus = h.get("customer")
            if cus in cust_alias:
                p["customer"] = cust_alias[cus]
            submit = h["docstatus"] == 1
            jobs.append(("Sales Order", h["name"], h.get("title") or "",
                         lambda p=p: p, submit, so_ex))
        run_round(runner, jobs, 0)
        so_ex.update(load_existing(pc, "Sales Order", "title"))
        for h in sorted(sos, key=lambda x: x["name"]):
            t = token(h.get("title"))
            cur = so_ex.get(t)
            if cur:
                so_map[h["name"]] = cur["name"]

    # ---------- fase 4: PR ----------
    if not smoke:
        print("== fase 4: Purchase Receipt ==")

        def pr_payload(h):
            p = {**pick(h, meta["Purchase Receipt"], PR_DROP),
                 "doctype": "Purchase Receipt",
                 "items": pick_rows(h.get("items"),
                                    meta["Purchase Receipt Item"], ROW_DROP)}
            for row_src, row_p in zip(h.get("items", []), p["items"]):
                old_po = row_src.get("purchase_order")
                if old_po and old_po in po_map and po_map[old_po][1] == 1:
                    row_p["purchase_order"] = po_map[old_po][0]
            return p

        jobs = []
        for h in sorted(prs, key=lambda x: x["name"]):
            if h["docstatus"] != 1:
                continue
            jobs.append(("Purchase Receipt", h["name"], h.get("title") or "",
                         lambda h=h: pr_payload(h), True, pr_ex))
        run_round(runner, jobs, 0)

    if smoke:
        print(f"== SMOKE (--only-wo {args.only_wo}): SE terkait ==")
        ses_smoke = [s for s in ses if s.get("work_order") == args.only_wo]

        def se_payload(s):
            p = {**pick(s, meta["Stock Entry"], SE_DROP),
                 "doctype": "Stock Entry",
                 "items": pick_rows(s.get("items"), meta["Stock Entry Detail"],
                                    ROW_DROP)}
            old_wo = s.get("work_order")
            if old_wo:
                p["work_order"] = wo_map.get(old_wo)
            return p
        for s in sorted(ses_smoke, key=lambda x: x["name"]):
            name = runner.ensure("Stock Entry", s["name"],
                                 s.get("remarks") or "",
                                 lambda s=s: se_payload(s), True, se_ex)
            print(f"    {s['name']} -> {name}")
        runner.summary()
        return

    # ---------- fase 5: SE (kronologis sumber) ----------
    print("== fase 5: Stock Entry (kronologis) ==")
    ses_sorted = []
    for s in ses:
        if (s.get("stock_entry_type") == "Manufacture"
                and s.get("company") != JURI):
            print(f"  SKIP {s['name']}: manufacture non-JURI "
                  f"({s.get('company')})")
            continue
        ty = (SE_TYPE_ORDER.index(s["stock_entry_type"])
              if s.get("stock_entry_type") in SE_TYPE_ORDER else 9)
        key = (s.get("posting_date") or "", s.get("posting_time") or "",
               ty, s["name"])
        ses_sorted.append((key, s))
    ses_sorted.sort(key=lambda x: x[0])

    def se_payload(s):
        p = {**pick(s, meta["Stock Entry"], SE_DROP),
             "doctype": "Stock Entry",
             "items": pick_rows(s.get("items"), meta["Stock Entry Detail"],
                                ROW_DROP)}
        old_wo = s.get("work_order")
        if old_wo:
            p["work_order"] = wo_map.get(old_wo)
        return p

    pending = [("Stock Entry", s["name"], s.get("remarks") or "",
                lambda s=s: se_payload(s), True, se_ex)
               for _k, s in ses_sorted]
    for rnd in range(1, args.max_rounds + 1):
        if not pending:
            break
        print(f"-- ronde SE {rnd}: {len(pending)} dokumen --")
        pending = run_round(runner, pending, rnd)
    runner.result["deferred_final"] += [{"doctype": d[0], "ref": d[1]}
                                        for d in pending]

    # ---------- fase 6: DN ----------
    print("== fase 6: Delivery Note ==")

    def dn_payload(h):
        p = {**pick(h, meta["Delivery Note"], DN_DROP),
             "doctype": "Delivery Note", "title": h.get("title") or "",
             "items": pick_rows(h.get("items"), meta["Delivery Note Item"],
                                ROW_DROP)}
        cus = h.get("customer")
        if cus in cust_alias:
            p["customer"] = cust_alias[cus]
        for row_src, row_p in zip(h.get("items", []), p["items"]):
            old_so = row_src.get("against_sales_order")
            if old_so and old_so in so_map:
                row_p["against_sales_order"] = so_map[old_so]
        return p

    pending = []
    for h in sorted(dns, key=lambda x: x["name"]):
        if h["docstatus"] != 1:
            continue
        pending.append(("Delivery Note", h["name"], h.get("title") or "",
                        lambda h=h: dn_payload(h), True, dn_ex))
    for rnd in range(1, args.max_rounds + 1):
        if not pending:
            break
        print(f"-- ronde DN {rnd}: {len(pending)} dokumen --")
        pending = run_round(runner, pending, rnd)
    runner.result["deferred_final"] += [{"doctype": d[0], "ref": d[1]}
                                        for d in pending]

    runner.summary()
    state["docs_run"] = {k: len(v) for k, v in runner.result.items()}
    state["docs_fails"] = runner.fails[:200]
    save_state(state)
    if runner.fails or pending:
        sys.exit(1)
    print("DOCS OK")


if __name__ == "__main__":
    main()
