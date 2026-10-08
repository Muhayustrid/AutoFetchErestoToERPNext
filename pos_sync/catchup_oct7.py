#!/usr/bin/env python3
"""Catch-up migrasi JURI 1-7 Okt 2026 (docs/10 §9). Fase terpisah, idempoten.

  --dump      tarik data site lama + snapshot site baru -> oct7_dump/
  --reco      RECO-A opening Produksi (telur) + RECO-B WIP (dokumen sendiri)
  --planwo    PP261007001 + 62 WO (urut baris plan) + refresh 8 WO stale
  --mrs       123 Material Request (ID lama)
  --ses       35 Stock Entry (link MR + row MR) — MTFM/MFG dikecualikan
  --polinks   link MR di 57 PO (child row PUT + Property Setter sementara)
  --verify    cek paritas + laporan Excel
  --cleanup   hapus Property Setter sementara (WO + PO Item)

Idempotency: WO/PP/MR rename ke ID lama; RECO marker remarks CATCHUP-OCT7;
SE marker remarks ERESTO <nama-lama>.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from migrate_wo_full_okt import (  # noqa: E402
    BOM_MAP, ITEM_MAP, MR_DROP, MR_ITEM_KEEP, SE_DROP, UOM_MAP, WO_DROP,
    Ctx, clean_time, ensure_allow_rename, hms, wh_map,
)
from prod_common import JURI, pick  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DUMP = os.path.join(HERE, "oct7_dump")
PLAN = "PP261007001"
STALE = ["MFG-WO-2026-04130", "MFG-WO-2026-04131", "MFG-WO-2026-04132",
         "MFG-WO-2026-04133", "MFG-WO-2026-04134", "MFG-WO-2026-04139",
         "MFG-WO-2026-04140", "MFG-WO-2026-04141"]
BACKDATE = ("2026-09-30", "23:30:00")
WO_SET_FIELDS = ["produced_qty", "process_loss_qty",
                 "material_transferred_for_manufacturing", "status"]
PO_LINK_FIELDS = ["material_request", "material_request_item"]
ITEM_MAP.update({"BB260058": "BB26008", "BB260059": "BB26009"})


def jdump(name, obj):
    os.makedirs(DUMP, exist_ok=True)
    with open(os.path.join(DUMP, name), "w") as f:
        json.dump(obj, f, indent=1, default=str)


def jload(name, default=None):
    path = os.path.join(DUMP, name)
    return json.load(open(path)) if os.path.exists(path) else default


def fetch_many(ctx, path, names, workers=6):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    out = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(ctx.old.get, f"{path}/{n}"): n for n in names}
        for fu in as_completed(futs):
            n = futs[fu]
            st, d = fu.result()
            if st == 200:
                out[n] = d["data"]
            else:
                print(f"  [!] OLD GET {path}/{n}: HTTP {st}")
    return out


def resolve_item(ctx, code, old_names, new_names, notes):
    """old code -> new code. Coba kode, ITEM_MAP, lalu nama item unik."""
    if code in ctx._item_cache and ctx._item_cache[code]:
        return code
    st, d = ctx.new.get("/api/resource/Item/" + code)
    if st == 200:
        ctx._item_cache[code] = d["data"]
        return code
    if code in ITEM_MAP:
        return ITEM_MAP[code]
    nm = old_names.get(code)
    cands = new_names.get(nm) or []
    if nm and len(cands) == 1:
        notes.append(f"item_map nama: {code} ({nm}) -> {cands[0]}")
        return cands[0]
    notes.append(f"SKIP item tak ketemu: {code} ({nm})")
    return None


# ---------------------------------------------------------------- fase 0
def phase_dump(ctx):
    print("== DUMP ==")
    old = ctx.old
    # item meta kedua site utk item yang terlibat
    mrs_old = jload("mrs_old", {}) or {}
    plan = old.get(f"/api/resource/Production Plan/{PLAN}")[1]["data"]
    wos = fetch_many(ctx, "/api/resource/Work Order",
                     [r["name"] for r in old.get(
                         "/api/resource/Work Order",
                         {"filters": json.dumps([["production_plan", "=", PLAN]]),
                          "fields": json.dumps(["name"]),
                          "limit_page_length": 300})[1]["data"]])
    stale = fetch_many(ctx, "/api/resource/Work Order", STALE)
    mr_names = jload("mr_names", [])
    if not mr_names:
        rows = old.get("/api/resource/Material Request", {
            "filters": json.dumps([["company", "=", JURI],
                                   ["transaction_date", ">=", "2026-10-01"],
                                   ["transaction_date", "<=", "2026-10-07"],
                                   ["docstatus", "=", 1]]),
            "fields": json.dumps(["name"]), "limit_page_length": 500,
            "order_by": "name asc"})[1]["data"]
        mr_names = [r["name"] for r in rows]
    mrs = fetch_many(ctx, "/api/resource/Material Request", mr_names)
    se_names = jload("se_names", [])
    if not se_names:
        rows = old.get("/api/resource/Stock Entry", {
            "filters": json.dumps([["company", "=", JURI],
                                   ["posting_date", ">=", "2026-10-01"],
                                   ["posting_date", "<=", "2026-10-07"],
                                   ["docstatus", "=", 1]]),
            "fields": json.dumps(["name", "purpose"]), "limit_page_length": 800,
            "order_by": "name asc"})[1]["data"]
        mig = set(jload("migrated_se", []) or [])
        if not mig and os.path.exists("/tmp/migrated_se.json"):
            mig = set(json.load(open("/tmp/migrated_se.json")))
            jdump("migrated_se", sorted(mig))
        excl = {"Material Transfer for Manufacture", "Manufacture"}
        se_names = [r["name"] for r in rows
                    if r["purpose"] not in excl and r["name"] not in mig]
    ses = fetch_many(ctx, "/api/resource/Stock Entry", se_names)

    # WIP saldo site lama per 30 Sep EOD (SLE terakhir per item)
    wip = {}
    start = 0
    while True:
        st, d = old.get("/api/resource/Stock Ledger Entry", {
            "filters": json.dumps([
                ["warehouse", "=", "Work In Progress - ROPI"],
                ["posting_date", "<=", "2026-09-30"],
                ["is_cancelled", "=", 0]]),
            "fields": json.dumps(["item_code", "qty_after_transaction",
                                  "valuation_rate", "posting_date",
                                  "posting_time", "creation"]),
            "limit_page_length": 500, "limit_start": start,
            "order_by": "posting_date asc, posting_time asc, creation asc"})
        rows = d.get("data", []) if st == 200 else []
        for r in rows:
            wip[r["item_code"]] = r  # terakhir menang
        start += len(rows)
        if len(rows) < 500:
            break
    jdump("wip_sep30.json", wip)

    # PO old + new (57 dgn link MR)
    with_links = jload("po_with_links", [])
    if not with_links:
        pos = old.get("/api/resource/Purchase Order", {
            "filters": json.dumps([["company", "=", JURI],
                                   ["transaction_date", ">=", "2026-10-01"],
                                   ["transaction_date", "<=", "2026-10-07"]]),
            "fields": json.dumps(["name"]), "limit_page_length": 200})[1]["data"]
        for p in pos:
            d = old.get(f"/api/resource/Purchase Order/{p['name']}")[1]["data"]
            if any(i.get("material_request") for i in d.get("items", [])):
                with_links.append(p["name"])
    old_pos = fetch_many(ctx, "/api/resource/Purchase Order", with_links)
    new_pos = {}
    for n in with_links:
        st, d = ctx.new.get("/api/resource/Purchase Order/" + n)
        if st == 200:
            new_pos[n] = d["data"]

    # item meta kedua site
    codes = set()
    for coll in (mrs, ses):
        for doc in coll.values():
            for it in doc.get("items", []):
                codes.add(it["item_code"])
    for doc in list(wos.values()) + list(stale.values()):
        codes.add(doc["production_item"])
    codes |= set(wip)
    old_items = {}
    for c in sorted(codes):
        d = old.get("/api/resource/Item/" + c)[1].get("data")
        if d:
            old_items[c] = {k: d.get(k) for k in
                            ("item_name", "stock_uom", "is_stock_item",
                             "uoms")}
    new_items, new_names = {}, {}
    for r in ctx.new.list_all("Item", ["name", "item_name", "stock_uom",
                                       "is_stock_item"]):
        new_names.setdefault(r["item_name"], []).append(r["name"])
    for c in sorted(codes):
        for cand in [ITEM_MAP.get(c), c]:
            if not cand:
                continue
            d = ctx.new.get("/api/resource/Item/" + cand)[1].get("data")
            if d:
                new_items[c] = {k: d.get(k) for k in
                                ("name", "item_name", "stock_uom",
                                 "is_stock_item", "uoms")}
                break
        else:
            nm = (old_items.get(c) or {}).get("item_name")
            for cand in new_names.get(nm, []):
                d = ctx.new.get("/api/resource/Item/" + cand)[1].get("data")
                new_items[c] = {k: d.get(k) for k in
                                ("name", "item_name", "stock_uom",
                                 "is_stock_item", "uoms")}
                break

    # RECO referensi (expense account/cost center/purpose)
    reco_ref = {}
    st, d = ctx.new.get("/api/resource/Stock Reconciliation/"
                        "RECO-JURI-261006003")
    if st == 200:
        dd = d["data"]
        reco_ref = {"expense_account": dd.get("expense_account"),
                    "cost_center": dd.get("cost_center"),
                    "purpose": dd.get("purpose")}

    jdump("plan007.json", {PLAN: plan})
    jdump("wos_new.json", wos)
    jdump("wos_stale.json", stale)
    jdump("mr_names", mr_names)
    jdump("mrs.json", mrs)
    jdump("se_names", se_names)
    jdump("ses.json", ses)
    jdump("po_with_links", with_links)
    jdump("old_po_docs.json", old_pos)
    jdump("new_po_docs.json", new_pos)
    jdump("old_items.json", old_items)
    jdump("new_items.json", new_items)
    jdump("reco_ref.json", reco_ref)
    print(f"  plan={len(plan.get('po_items', []))} WO baru={len(wos)} "
          f"stale={len(stale)} MR={len(mrs)} SE={len(ses)} "
          f"PO link={len(with_links)} WIP items={len(wip)}")
    print(f"  reco_ref={reco_ref}")


# ---------------------------------------------------------------- fase 1
def _post_reco(ctx, warehouse, items, remarks, tag):
    # RECO tidak punya field remarks -> idempotency via state file nama dok.
    docs = jload("reco_docs.json", {}) or {}
    if docs.get(tag):
        st, d = ctx.new.get("/api/resource/Stock Reconciliation/"
                            + docs[tag])
        if st == 200 and d.get("data", {}).get("docstatus") == 1:
            print(f"  [{tag}] ADA: {docs[tag]}")
            return docs[tag]
    if not items:
        print(f"  [{tag}] tidak ada baris, skip")
        return None
    ref = jload("reco_ref.json", {})
    payload = {
        "doctype": "Stock Reconciliation",
        "company": JURI,
        "purpose": ref.get("purpose") or "Opening Stock",
        "set_posting_time": 1,
        "posting_date": BACKDATE[0], "posting_time": BACKDATE[1],
        "set_warehouse": warehouse,
        "expense_account": ref.get("expense_account"),
        "cost_center": ref.get("cost_center"),
        "items": items,
        "docstatus": 1,
    }
    st, d = ctx.new.post("Stock Reconciliation", payload)
    ok = st == 200
    print(f"  [{'OK' if ok else 'FAIL'}] {tag} {warehouse} "
          f"items={len(items)} {'' if ok else json.dumps(d)[:300]}")
    if ok:
        docs[tag] = d.get("data", {}).get("name")
        jdump("reco_docs.json", docs)
        return docs[tag]
    return None


def phase_reco(ctx):
    print("== RECO: opening Produksi + WIP ==")
    old_items = jload("old_items.json", {})
    new_items = jload("new_items.json", {})
    new_names = {}
    for r in ctx.new.list_all("Item", ["name", "item_name"]):
        new_names.setdefault(r["item_name"], []).append(r["name"])
    notes = []

    def row(code, qty, rate):
        ni = new_items.get(code) or {}
        new = ni.get("name")
        if not new:
            st, d = ctx.new.get("/api/resource/Item/" + code)
            if st == 200:
                d0 = d["data"]
                ni = {k: d0.get(k) for k in
                      ("name", "item_name", "stock_uom", "is_stock_item")}
                new_items[code] = ni
                new = ni.get("name")
        if not new:
            notes.append(f"SKIP {code}: item tak ada di site baru")
            return None
        if not ni.get("is_stock_item"):
            notes.append(f"SKIP {code}: non-stock di site baru")
            return None
        return {"item_code": new, "warehouse": None, "qty": qty,
                "valuation_rate": rate, "uom": ni.get("stock_uom"),
                "allow_zero_valuation_rate": 1}

    # A. Produksi — item recount ADJ260930005 yang belum masuk opening
    a_rows = []
    for code, qty, rate in [("BB260055", 32460.0, 28.801486556)]:
        r = row(code, qty, rate)
        if r:
            r["warehouse"] = "Gudang Produksi - JURI"
            a_rows.append(r)
    _post_reco(ctx, "Gudang Produksi - JURI", a_rows,
               "CATCHUP-OCT7 opening Produksi (telur) dari ADJ260930005",
               "RECO-A")

    # A2. Produksi — BHP260022 (Kertas Alas) dari RECO lama yang sama
    a2_rows = []
    for code, qty, rate in [("BHP260022", 53.0, 59000.0)]:
        r = row(code, qty, rate)
        if r:
            r["warehouse"] = "Gudang Produksi - JURI"
            a2_rows.append(r)
    if a2_rows:
        _post_reco(ctx, "Gudang Produksi - JURI", a2_rows,
                   "CATCHUP-OCT7 opening Produksi (kertas alas) "
                   "dari ADJ260930005",
                   "RECO-A2")

    # C. PEL260087 (Tutup Pet Strawless) — belum opening, saldo ROPI 30 Sep
    #    EOD: GBJ 201.000 + Jakarta 34.000 (dokumen sendiri per gudang).
    for tag, wh, qty in [("RECO-C1", "Gudang Barang Jadi - JURI", 201000.0),
                         ("RECO-C2", "Gudang Jakarta - JURI", 34000.0)]:
        c_rows = []
        r = row("PEL260087", qty, 124.0)
        if r:
            r["warehouse"] = wh
            c_rows.append(r)
        _post_reco(ctx, wh, c_rows,
                   f"CATCHUP-OCT7 opening {wh.split(' - ')[0]} (PEL260087)",
                   tag)

    # D. Cold Storage — FG dari serah terima 7 Okt (MFG dikecualikan) supaya
    #    Bin tidak negatif; target netto = site lama (0).
    d_rows = []
    for code, qty, rate in [("PJ260010", 1542.0, 1957.326158417),
                            ("PJ260011", 1020.0, 2489.304882431),
                            ("PJ260012", 9096.0, 803.524552437),
                            ("PJ260013", 10500.0, 834.404097942),
                            ("PJ260014", 1176.0, 940.309029801),
                            ("PJ260016", 870.0, 15347.862030132)]:
        r = row(code, qty, rate)
        if r:
            r["warehouse"] = "Cold Storage Produksi - JURI"
            d_rows.append(r)
    if d_rows:
        _post_reco(ctx, "Cold Storage Produksi - JURI", d_rows,
                   "CATCHUP-OCT7 FG serah terima (MFG dikecualikan)", "RECO-D")

    # E. Gula Cair (BB26008) — sumber Repack 09527 yang belum ber-opening.
    e_rows = []
    r = row("BB260058", 200.0, 12432.43245)
    if r:
        r["warehouse"] = "Gudang Barang Jadi - JURI"
        e_rows.append(r)
    if e_rows:
        _post_reco(ctx, "Gudang Barang Jadi - JURI", e_rows,
                   "CATCHUP-OCT7 sumber Repack gula BB260058", "RECO-E")

    # B. WIP — saldo site lama 30 Sep EOD, dokumen sendiri
    wip = jload("wip_sep30.json", {})
    b_rows = []
    for code, r in sorted(wip.items()):
        qty = float(r.get("qty_after_transaction") or 0)
        if abs(qty) < 1e-6:
            continue
        rate = float(r.get("valuation_rate") or 0)
        rw = row(code, qty, rate)
        if rw:
            rw["warehouse"] = "Work In Progress - JURI"
            b_rows.append(rw)
    _post_reco(ctx, "Work In Progress - JURI", b_rows,
               "CATCHUP-OCT7 opening WIP dari saldo ROPI 30 Sep EOD",
               "RECO-B")
    for n in notes:
        print("   ", n)
    jdump("reco_notes.json", notes)


# ---------------------------------------------------------------- fase 2
def _client_set(ctx, doctype, name, values):
    import urllib.parse
    return ctx.new.req("POST", "/api/method/frappe.client.set_value",
                       payload={"doctype": doctype, "name": name,
                                "fieldname": json.dumps(values)})


def _ensure_wo_setters(ctx):
    made = []
    for field in WO_SET_FIELDS:
        st, d = ctx.new.get("/api/resource/Property Setter", {
            "filters": json.dumps([
                ["doc_type", "=", "Work Order"], ["field_name", "=", field],
                ["property", "=", "allow_on_submit"]]),
            "fields": json.dumps(["name", "value"]), "limit_page_length": 1})
        rows = d.get("data", []) if st == 200 else []
        if rows and str(rows[0]["value"]) == "1":
            continue
        st, d = ctx.new.post("Property Setter", {
            "doctype": "Property Setter", "doctype_or_field": "DocField",
            "doc_type": "Work Order", "field_name": field,
            "property": "allow_on_submit", "property_type": "Check",
            "value": "1"})
        made.append(field)
    print(f"  setter WO dibuat: {made or '(sudah ada)'}")


def phase_planwo(ctx, dry=False):
    print("== PLAN + WO ==")
    ctx.load_meta(["Production Plan", "Production Plan Item", "Work Order",
                   "Work Order Item"])
    if not dry:
        ensure_allow_rename(ctx, "Production Plan")
        ensure_allow_rename(ctx, "Work Order")
    # 1. plan
    plan = jload("plan007.json")[PLAN]
    st, d = ctx.new.get(f"/api/resource/Production Plan/{PLAN}")
    if st == 200 and d.get("data", {}).get("docstatus") == 1:
        print(f"  [ADA] plan {PLAN}")
    elif not dry:
        rows = []
        for r in sorted(plan.get("po_items", []), key=lambda x: x.get("idx", 0)):
            q = {k: r[k] for k in ("planned_qty", "stock_uom",
                                   "planned_start_date",
                                   "custom_item_name_information")
                 if r.get(k) is not None}
            q["item_code"] = r["item_code"]
            q["bom_no"] = BOM_MAP.get(r.get("bom_no"), r.get("bom_no"))
            rows.append(q)
        payload = {"doctype": "Production Plan", "company": JURI,
                   "posting_date": plan.get("posting_date"), "po_items": rows}
        st, d = ctx.new.post("Production Plan", payload)
        temp = d["data"]["name"]
        st_r, _ = ctx.new.rename("Production Plan", temp, PLAN)
        final = PLAN if st_r == 200 else temp
        st_s, d_s = ctx.new.submit("Production Plan", final)
        print(f"  [{'OK' if st_s == 200 else 'WARN'}] plan {final} "
              f"rows={len(rows)} submit={st_s} {'' if st_s == 200 else str(d_s)[:200]}")

    # 2. WO baru (urut baris plan)
    st, d = ctx.new.get(f"/api/resource/Production Plan/{PLAN}")
    plan_doc = d["data"]
    row_names = [r["name"] for r in
                 sorted(plan_doc.get("po_items", []),
                        key=lambda x: x.get("idx", 0))]
    wos = jload("wos_new.json")
    old_list = sorted(wos.values(), key=lambda x: x["name"])
    made, failed = [], []
    for i, w in enumerate(old_list):
        st, d = ctx.new.get("/api/resource/Work Order/" + w["name"])
        if st == 200 and d.get("data", {}).get("docstatus") == 1:
            made.append(w["name"])
            continue
        if dry:
            print(f"  [DRY] {w['name']} idx={i} row={row_names[i]}")
            continue
        from migrate_wo_full_okt import wo_payload
        payload = wo_payload(ctx, w, PLAN, row_names[i])
        st, d = ctx.new.post("Work Order", payload)
        if st != 200:
            print(f"  [FAIL] WO {w['name']}: {json.dumps(d)[:250]}")
            failed.append(w["name"])
            continue
        temp = d["data"]["name"]
        st_r, _ = ctx.new.rename("Work Order", temp, w["name"])
        final = w["name"] if st_r == 200 else temp
        st_s, d_s = ctx.new.submit("Work Order", final)
        ok = st_s == 200
        if not ok:
            failed.append(w["name"])
        made.append(final)
        print(f"  [{'OK' if ok else 'FAIL'}] {final} {w['production_item']} "
              f"{w['qty']} {'' if ok else str(d_s)[:200]}")
    print(f"  WO baru: {len(made)} dibuat, gagal {len(failed)}")

    # 3. set nilai pasca-submit (62 + 8 stale)
    if dry:
        return
    _ensure_wo_setters(ctx)
    wos_stale = jload("wos_stale.json")
    all_old = dict(wos)
    all_old.update(wos_stale)
    changed, bad = [], []
    for name in sorted(all_old):
        st, d = ctx.new.get("/api/resource/Work Order/" + name)
        if st != 200:
            bad.append((name, "tidak ada"))
            continue
        cur = d["data"]
        src = all_old[name]
        values = {}
        for f in ("produced_qty", "process_loss_qty",
                  "material_transferred_for_manufacturing", "status",
                  "actual_start_date", "actual_end_date"):
            sv = src.get(f)
            if f in ("actual_start_date", "actual_end_date"):
                sv = None if not sv else str(sv).replace(" ", " ")
                cv = cur.get(f)
                if (sv or None) != (cv or None):
                    values[f] = sv
                continue
            if f == "status":
                if (cur.get(f) or "") != (sv or ""):
                    values[f] = sv or "Not Started"
                continue
            sv = float(sv or 0)
            cv = float(cur.get(f) or 0)
            if abs(sv - cv) > 0.001:
                values[f] = sv
        if not values:
            continue
        if name not in made and name not in STALE:
            continue
        st, d = _client_set(ctx, "Work Order", name, values)
        ok = st in (200, 201)
        if ok:
            changed.append((name, values))
        else:
            bad.append((name, str(d)[:200]))
    print(f"  WO nilai diset: {len(changed)}, gagal: {len(bad)}")
    for b in bad[:10]:
        print("    ", b)
    jdump("wo_set.json", {"changed": changed, "bad": bad})


# ---------------------------------------------------------------- fase 3
def _mr_payload(ctx, m):
    p = pick(m, ctx.meta["Material Request"], MR_DROP)
    for k in list(p):
        if ctx.meta_types["Material Request"].get(k) == "Table":
            p.pop(k, None)
    p["doctype"] = "Material Request"
    p["company"] = JURI
    for f in ("set_from_warehouse", "set_warehouse"):
        if p.get(f):
            p[f] = wh_map(p[f])
    bp = p.get("custom_handover_box_plan")
    if bp:
        st, _ = ctx.new.get("/api/resource/Handover Box Plan/" + bp)
        if st != 200:
            p.pop("custom_handover_box_plan", None)
    rows = []
    for it in m.get("items", []):
        q = {k: v for k, v in it.items() if k in MR_ITEM_KEEP and v is not None}
        q["item_code"] = it["item_code"]
        if q.get("uom"):
            q["uom"] = UOM_MAP.get(q["uom"], q["uom"])
        for f in ("from_warehouse", "warehouse"):
            if q.get(f):
                q[f] = wh_map(q[f])
        rows.append(q)
    p["items"] = rows
    return p


def phase_mrs(ctx, dry=False):
    print("== MR ==")
    ctx.load_meta(["Material Request", "Material Request Item"])
    if not dry:
        ensure_allow_rename(ctx, "Material Request")
    mrs = jload("mrs.json")
    out, items_map, fails = {}, {}, []
    for name in sorted(mrs):
        st, d = ctx.new.get("/api/resource/Material Request/" + name)
        if st == 200 and d.get("data", {}).get("docstatus") == 1:
            doc = d["data"]
            items_map[name] = {r["item_code"]: r["name"]
                               for r in doc.get("items", [])}
            print(f"  [ADA] MR {name}")
            out[name] = name
            continue
        payload = _mr_payload(ctx, mrs[name])
        if dry:
            print(f"  [DRY] MR {name}: {len(payload['items'])} item")
            continue
        st, d = ctx.new.post("Material Request", payload)
        if st != 200:
            print(f"  [FAIL] MR {name}: {json.dumps(d)[:250]}")
            fails.append(name)
            continue
        temp = d["data"]["name"]
        st_r, _ = ctx.new.rename("Material Request", temp, name)
        final = name if st_r == 200 else temp
        st_s, d_s = ctx.new.submit("Material Request", final)
        ok = st_s == 200
        if not ok:
            fails.append(name)
        print(f"  [{'OK' if ok else 'FAIL'}] MR {final} "
              f"{'' if ok else str(d_s)[:200]}")
        out[name] = final
        st_g, d_g = ctx.new.get("/api/resource/Material Request/" + final)
        if st_g == 200:
            items_map[name] = {r["item_code"]: r["name"]
                               for r in d_g["data"].get("items", [])}
    print(f"  MR: {len(out)} siap, gagal {len(fails)}")
    jdump("mr_map.json", {"map": out, "items": items_map, "fails": fails})


# ---------------------------------------------------------------- fase 4
def _old_item_uom(old_items, code):
    return ((old_items.get(code) or {}).get("stock_uom") or "").lower()


def _se_payload(ctx, s, old_items, new_items, mr_map, notes):
    p = pick(s, ctx.meta["Stock Entry"], SE_DROP)
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
    p["remarks"] = f"ERESTO {s['name']} | Migrasi Site Lama"
    rows = []
    for it in s.get("items", []):
        code = it["item_code"]
        ni = new_items.get(code) or {}
        new_code = ni.get("name")
        if not new_code or not ni.get("is_stock_item"):
            notes.append(f"{s['name']}: skip row {code} "
                         f"({'non-stock' if new_code else 'tak ada'} di baru)")
            continue
        cf = float(it.get("conversion_factor") or 1)
        old_su = _old_item_uom(old_items, code)
        new_su = (ni.get("stock_uom") or "").lower()
        if old_su == new_su:
            qty = float(it.get("qty") or 0) * cf
        elif (it.get("uom") or "").lower() == new_su:
            qty = float(it.get("qty") or 0)
        else:
            fac = None
            for u in ni.get("uoms", []):
                if (u.get("uom") or "").lower() == old_su:
                    fac = float(u.get("conversion_factor") or 0)
            if fac:
                qty = float(it.get("qty") or 0) * cf / fac
            else:
                qty = float(it.get("qty") or 0)
                notes.append(f"{s['name']}: {code} uom {old_su}->{new_su} "
                             f"tanpa tabel konversi, qty as-is")
        q = {"item_code": new_code, "qty": qty, "uom": ni.get("stock_uom")}
        for f in ("s_warehouse", "t_warehouse"):
            if it.get(f):
                q[f] = wh_map(it[f])
        if it.get("material_request") and it["material_request"] in mr_map["map"]:
            q["material_request"] = mr_map["map"][it["material_request"]]
            old_mri = it.get("material_request_item")
            if old_mri:
                # old row id -> item_code (dari dok MR lama) -> row baru
                src = jload("mrs.json")[it["material_request"]]
                hit = next((r for r in src.get("items", [])
                            if r.get("name") == old_mri), None)
                if hit:
                    new_mri = mr_map["items"].get(
                        it["material_request"], {}).get(hit["item_code"])
                    if new_mri:
                        q["material_request_item"] = new_mri
        if it.get("is_finished_item"):
            q["is_finished_item"] = it["is_finished_item"]
        rate = float(it.get("basic_rate") or it.get("valuation_rate") or 0)
        if rate > 0:
            q["basic_rate"] = round(rate, 6)
            q["set_basic_rate_manually"] = 1
        # gudang sumber bisa 0 stok/nilai di site baru (pola docs/09):
        # izinkan rate 0 bila valuation tak ketemu, rate manual menang bila ada
        q["allow_zero_valuation_rate"] = 1
        rows.append(q)
    if not rows:
        notes.append(f"{s['name']}: semua row dilewati, dokumen tidak dibuat")
        return None
    if notes:
        p["remarks"] += " | " + "; ".join(
            n.split(": ", 1)[1] for n in notes if n.startswith(s["name"]))
    p["items"] = rows
    p["docstatus"] = 1
    return p


def phase_ses(ctx, dry=False):
    print("== SE ==")
    ctx.load_meta(["Stock Entry", "Stock Entry Detail"])
    ses = jload("ses.json")
    old_items = jload("old_items.json", {})
    new_items = jload("new_items.json", {})
    mr_map = jload("mr_map.json", {"map": {}, "items": {}})
    out, fails, notes = {}, [], []
    for name in sorted(ses):
        st, d = ctx.new.get("/api/resource/Stock Entry", {
            "filters": json.dumps([["remarks", "like",
                                    f"%ERESTO {name} |%"]]),
            "fields": json.dumps(["name", "docstatus"]),
            "limit_page_length": 1})
        if st == 200 and d.get("data"):
            print(f"  [ADA] SE {name} -> {d['data'][0]['name']}")
            out[name] = d["data"][0]["name"]
            continue
        payload = _se_payload(ctx, ses[name], old_items, new_items,
                              mr_map, notes)
        if payload is None:
            print(f"  [SKIP] SE {name}")
            continue
        if dry:
            print(f"  [DRY] SE {name}: {len(payload['items'])} row "
                  f"mrs={[r.get('material_request') for r in payload['items']]}")
            continue
        st, d = ctx.new.post("Stock Entry", payload)
        ok = st == 200
        if ok:
            out[name] = d["data"]["name"]
        else:
            fails.append((name, json.dumps(d)[:250]))
        print(f"  [{'OK' if ok else 'FAIL'}] SE {name} "
              f"{'' if ok else str(d)[:250]}")
    print(f"  SE: {len(out)} dibuat, gagal {len(fails)}, catatan {len(notes)}")
    for n in notes:
        print("    ", n)
    jdump("se_result.json", {"ok": out, "fails": fails, "notes": notes})


# ---------------------------------------------------------------- fase 5
def _ensure_po_setters(ctx):
    made = []
    for field in PO_LINK_FIELDS:
        st, d = ctx.new.get("/api/resource/Property Setter", {
            "filters": json.dumps([
                ["doc_type", "=", "Purchase Order Item"],
                ["field_name", "=", field],
                ["property", "=", "allow_on_submit"]]),
            "fields": json.dumps(["name", "value"]), "limit_page_length": 1})
        rows = d.get("data", []) if st == 200 else []
        if rows and str(rows[0]["value"]) == "1":
            continue
        st, d = ctx.new.post("Property Setter", {
            "doctype": "Property Setter", "doctype_or_field": "DocField",
            "doc_type": "Purchase Order Item", "field_name": field,
            "property": "allow_on_submit", "property_type": "Check",
            "value": "1"})
        made.append(field)
    print(f"  setter PO Item dibuat: {made or '(sudah ada)'}")


def phase_polinks(ctx, dry=False):
    print("== PO LINK ==")
    old_pos = jload("old_po_docs.json", {})
    new_pos = jload("new_po_docs.json", {})
    mrs = jload("mrs.json", {})
    mr_map = jload("mr_map.json", {"items": {}})
    if not dry:
        _ensure_po_setters(ctx)
    done, fails = [], []
    for name, old in sorted(old_pos.items()):
        new = new_pos.get(name)
        if not new:
            fails.append((name, "PO tidak ada di site baru"))
            continue
        new_rows = {r["item_code"]: r for r in new.get("items", [])}
        for oi in old.get("items", []):
            mr = oi.get("material_request")
            if not mr or mr not in mr_map.get("map", {}):
                continue
            new_row = new_rows.get(oi["item_code"])
            if not new_row:
                fails.append((name, f"row {oi['item_code']} tak ada"))
                continue
            want = {"material_request": mr}
            omri = oi.get("material_request_item")
            if omri:
                src = mrs.get(mr, {})
                hit = next((r for r in src.get("items", [])
                            if r.get("name") == omri), None)
                if hit:
                    nmri = mr_map["items"].get(mr, {}).get(hit["item_code"])
                    if nmri:
                        want["material_request_item"] = nmri
            if (new_row.get("material_request") == want.get("material_request")
                    and new_row.get("material_request_item")
                    == want.get("material_request_item")):
                done.append(name)
                continue
            if dry:
                print(f"  [DRY] {name} row {oi['item_code']} <- {want}")
                continue
            st, d = ctx.new.req(
                "PUT", "/api/resource/Purchase Order Item/" + new_row["name"],
                payload=want)
            ok = st == 200
            print(f"  [{'OK' if ok else 'FAIL'}] {name} "
                  f"{oi['item_code']} <- {mr} {'' if ok else str(d)[:200]}")
            if ok:
                done.append(name)
            else:
                fails.append((name, str(d)[:200]))
    print(f"  PO link: {len(set(done))} ok, gagal {len(fails)}")
    jdump("po_link_result.json", {"done": sorted(set(done)), "fails": fails})


# ---------------------------------------------------------------- fase 5b
MR_QTY_FIELDS = [("Material Request Item", "ordered_qty"),
                 ("Material Request Item", "received_qty"),
                 ("Material Request", "per_ordered"),
                 ("Material Request", "per_received"),
                 ("Material Request", "status")]


def _ensure_mr_setters(ctx, fields):
    made = []
    for dt, field in fields:
        st, d = ctx.new.get("/api/resource/Property Setter", {
            "filters": json.dumps([
                ["doc_type", "=", dt], ["field_name", "=", field],
                ["property", "=", "allow_on_submit"]]),
            "fields": json.dumps(["name", "value"]), "limit_page_length": 1})
        rows = d.get("data", []) if st == 200 else []
        if rows and str(rows[0]["value"]) == "1":
            continue
        st, d = ctx.new.post("Property Setter", {
            "doctype": "Property Setter", "doctype_or_field": "DocField",
            "doc_type": dt, "field_name": field,
            "property": "allow_on_submit", "property_type": "Check",
            "value": "1"})
        made.append(f"{dt}.{field}")
    print(f"  setter MR dibuat: {made or '(sudah ada)'}")


def phase_mrstatus(ctx, dry=False):
    """Replikasi ordered/received_qty MR Purchase dari dokumen lama.
    PO↔MR link sudah terpasang; field turunan (ordered_qty/per_ordered/
    received_qty/per_received) + status harus ikut benar supaya MR tidak
    selamanya 'Pending' (derived murni — sumber otoritatif dokumen lama)."""
    print("== MR STATUS ==")
    mrs = jload("mrs.json", {})
    mr_map = jload("mr_map.json", {"map": {}})
    if not dry:
        _ensure_mr_setters(ctx, MR_QTY_FIELDS)
    done, fails = [], []
    for name in sorted(mr_map.get("map", {})):
        src = mrs.get(name)
        if not src:
            continue
        st, d = ctx.new.get("/api/resource/Material Request/" + name)
        if st != 200:
            fails.append((name, "tidak ada"))
            continue
        cur = d["data"]
        src_rows = src.get("items", [])
        cur_rows = cur.get("items", [])
        if len(src_rows) != len(cur_rows):
            fails.append((name, "jumlah row beda"))
            continue
        changed = 0
        for sr, cr in zip(src_rows, cur_rows):
            if sr.get("item_code") != cr.get("item_code"):
                fails.append((name, f"row beda {sr.get('item_code')}"))
                break
            want = {}
            for f in ("ordered_qty", "received_qty"):
                sv = float(sr.get(f) or 0)
                cv = float(cr.get(f) or 0)
                if abs(sv - cv) > 0.001:
                    want[f] = sv
            if not want:
                continue
            if dry:
                print(f"  [DRY] {name} row {sr.get('item_code')} {want}")
                continue
            st, d2 = _client_set(ctx, "Material Request Item", cr["name"],
                                 want)
            if st in (200, 201):
                changed += 1
            else:
                fails.append((name, str(d2)[:200]))
        want_p = {}
        for f in ("per_ordered", "per_received"):
            sv = float(src.get(f) or 0)
            cv = float(cur.get(f) or 0)
            if abs(sv - cv) > 0.001:
                want_p[f] = sv
        # status juga derived (dari per_ordered/per_received yg sudah disamakan);
        # hook before_save TIDAK jalan pada jalur update_after_submit, jadi
        # status disalin eksplisit dari dokumen lama yang otoritatif.
        if (cur.get("status") or "") != (src.get("status") or ""):
            want_p["status"] = src.get("status")
        if want_p and not dry:
            st, d3 = _client_set(ctx, "Material Request", name, want_p)
            if st in (200, 201):
                changed += 1
            else:
                fails.append((name, str(d3)[:200]))
        if changed:
            done.append(name)
    print(f"  MR status: {len(done)} diperbarui, gagal {len(fails)}")
    for f in fails[:10]:
        print("    ", f)
    jdump("mr_status_result.json", {"done": done, "fails": fails})


def phase_cleanup(ctx):
    print("== CLEANUP setter ==")
    for field in WO_SET_FIELDS:
        _del_setter(ctx, "Work Order", field)
    for field in PO_LINK_FIELDS:
        _del_setter(ctx, "Purchase Order Item", field)
    for dt, field in MR_QTY_FIELDS:
        _del_setter(ctx, dt, field)


def _del_setter(ctx, dt, field):
    st, d = ctx.new.get("/api/resource/Property Setter", {
        "filters": json.dumps([
            ["doc_type", "=", dt], ["field_name", "=", field],
            ["property", "=", "allow_on_submit"]]),
        "fields": json.dumps(["name", "value"]), "limit_page_length": 1})
    rows = d.get("data", []) if st == 200 else []
    if not rows:
        print(f"  {dt}.{field}: tidak ada")
        return
    if str(rows[0]["value"]) == "1":
        st, d = ctx.new.put("Property Setter", rows[0]["name"],
                            {"value": "0"})
        print(f"  {dt}.{field}: value -> 0 ({st})")


# ---------------------------------------------------------------- fase 6
def phase_verify(ctx):
    print("== VERIFY ==")
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    lines = []

    # RECO
    docs = jload("reco_docs.json", {}) or {}
    for tag in ("RECO-A", "RECO-A2", "RECO-B", "RECO-C1", "RECO-C2",
                "RECO-D", "RECO-E"):
        nm = docs.get(tag)
        if not nm:
            lines.append(("RECO", tag, "TIDAK ADA", "-"))
            continue
        st, d = ctx.new.get("/api/resource/Stock Reconciliation/" + nm)
        ok = st == 200
        lines.append(("RECO", tag, nm,
                      d.get("data", {}).get("docstatus") if ok else "MISSING"))

    # bins spot
    for code in ["BB260055", "BHP260022"]:
        st, d = ctx.new.get("/api/resource/Bin", {
            "filters": json.dumps([["item_code", "=", code]]),
            "fields": json.dumps(["warehouse", "actual_qty"]),
            "limit_page_length": 50})
        for b in d.get("data", []):
            if b["actual_qty"]:
                lines.append(("BIN", code, b["warehouse"], b["actual_qty"]))

    # WO: 62 + 8 vs old
    wos = dict(jload("wos_new.json", {}))
    wos.update(jload("wos_stale.json", {}))
    ok = 0
    for name, src in sorted(wos.items()):
        st, d = ctx.new.get("/api/resource/Work Order/" + name)
        cur = d.get("data", {}) if st == 200 else {}
        same = (abs(float(cur.get("produced_qty") or 0)
                    - float(src.get("produced_qty") or 0)) < 0.001
                and (cur.get("status") or "") == (src.get("status") or ""))
        if same:
            ok += 1
        else:
            lines.append(("WO_BEDA", name,
                          f"{cur.get('produced_qty')}/{cur.get('status')}",
                          f"{src.get('produced_qty')}/{src.get('status')}"))
    lines.append(("WO", "paritas 62+8", f"{ok}/{len(wos)}", "OK"))

    # MR
    mr_map = jload("mr_map.json", {"map": {}, "fails": []})
    lines.append(("MR", "dibuat", len(mr_map.get("map", {})),
                  f"gagal {len(mr_map.get('fails', []))}"))

    # SE
    se_res = jload("se_result.json", {"ok": {}, "fails": []})
    lines.append(("SE", "dibuat", len(se_res.get("ok", {})),
                  f"gagal {len(se_res.get('fails', []))}"))

    # PO link
    po = jload("po_link_result.json", {"done": [], "fails": []})
    lines.append(("PO", "link ok", len(po.get("done", [])),
                  f"gagal {len(po.get('fails', []))}"))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Verifikasi"
    ws.append(["Bagian", "Kunci", "Nilai", "Catatan"])
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="D9EAF7")
    for row in lines:
        ws.append(list(row))
    ws.freeze_panes = "A2"
    out = os.path.join(HERE, "Laporan_Catchup_7Okt2026.xlsx")
    wb.save(out)
    for row in lines:
        if row[0] in ("WO_BEDA",):
            print("  BEDA:", row)
    print(f"  laporan: {out}")
    for row in lines:
        print("   ", row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--reco", action="store_true")
    ap.add_argument("--planwo", action="store_true")
    ap.add_argument("--mrs", action="store_true")
    ap.add_argument("--ses", action="store_true")
    ap.add_argument("--polinks", action="store_true")
    ap.add_argument("--mrstatus", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--cleanup", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    ctx = Ctx()
    if args.dump:
        phase_dump(ctx)
    if args.reco:
        phase_reco(ctx)
    if args.planwo:
        phase_planwo(ctx, args.dry_run)
    if args.mrs:
        phase_mrs(ctx, args.dry_run)
    if args.ses:
        phase_ses(ctx, args.dry_run)
    if args.polinks:
        phase_polinks(ctx, args.dry_run)
    if args.mrstatus:
        phase_mrstatus(ctx, args.dry_run)
    if args.verify:
        phase_verify(ctx)
    if args.cleanup:
        phase_cleanup(ctx)
    if not any([args.dump, args.reco, args.planwo, args.mrs, args.ses,
                args.polinks, args.mrstatus, args.verify, args.cleanup]):
        ap.print_help()


if __name__ == "__main__":
    main()
