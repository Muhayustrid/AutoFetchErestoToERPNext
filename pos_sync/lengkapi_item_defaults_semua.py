#!/usr/bin/env python3
"""Lengkapi item_defaults (expense_account + default_warehouse) per company outlet
di ERPNext BARU (CLOUD). Keputusan user 2026-10-14.

Scope:
- Company target = semua company KECUALI FRC (nama mengandung "(FRC)") dan grup
  (GROUP_COMPANIES). PT. JURI ditunda (CoA-nya tidak punya akun outlet 5220.0xx).
- Item = item aktif di bawah Item Group "Inventories" yang "wajib semua outlet"
  (punya baris di >= WAJIB_MIN company target). Penentu = coverage, bukan nama.
- Akun per ITEM:
  1. Item yang sudah punya akun di company target -> akun terbanyak (mode) item
     itu, suffix abbr diganti ke company tujuan.
  2. Item tanpa akun sama sekali -> EMPTY_RULES (per item_code, lalu per group).
  3. JURI_ONLY -> dilewati (tidak diisi, tidak dibuat barisnya).
  Item tanpa template & tanpa aturan -> dilaporkan TANPA ATURAN, tidak ditebak.
- Baris yang sudah ada dengan akun terisi TIDAK diubah. Hanya: isi expense_account
  kosong, dan tambah baris company yang belum ada (akun + Stores - <ABBR> +
  default_inventory_account mode item tsb).

Keamanan: dry-run default; --execute untuk menulis. Re-GET Item sebelum tiap PUT
(anti lost-update child table), backup JSON tiap item ke audit_logs/. Akun /
warehouse hasil-rename yang tidak ada di company tujuan -> STOP.

CLI:
  python pos_sync/lengkapi_item_defaults_semua.py [--company NAMA ...] [--item CODE ...] [--execute]
"""
import argparse
import collections
import json
import os
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env, PROD_ENV  # noqa: E402

_q = urllib.parse.quote
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(ROOT, "audit_logs", "item_defaults_" + time.strftime("%y%m%d_%H%M%S"))

GROUP_COMPANIES = {"JURI GROUP", "OUTLET", "TRAINING", "Outlet Pameran",
                   "PT. JUARA ROTI INDONESIA"}
WAJIB_MIN = 150

HPP = "4210.000 - HPP Pembelian"
AKTIVA = "1211.004 - Aktiva Tetap - Mesin & Peralatan"
PERLENGKAPAN = "5220.016 - Biaya Perlengkapan Outlet"

# Akun utk item yang akunnya kosong di SEMUA company (tidak ada template).
EMPTY_RULES = {
    # group
    "Peralatan": AKTIVA,
    "Produk Jadi Pabrik": HPP,
    # Bahan Baku yang dipesan outlet (PO outlet >=5x) + bubuk minuman outlet
    **{c: HPP for c in (
        "BB260019", "BB260030", "BB260031", "BB260032", "BB260033", "BB260038",
        "BB260039", "BB260040", "BB260041", "BB260042", "BB260043", "BB260044",
        "BB260045", "BB260046", "BB260047", "BB260048", "BB26009", "BB26012",
        "BB260034", "BB260035", "BB260036", "BB260037", "BB260049", "BB260050",
        "BB260051", "BB260052", "BB260053", "BB260054")},
    # Perlengkapan aset outlet
    **{c: AKTIVA for c in (
        "PEL260004", "PEL260009", "PEL260012", "PEL260046", "PEL260048",
        "PEL260056", "PEL260057", "PEL260059", "PEL260061", "PEL260062",
        "PEL260064", "PEL260065", "PEL260066")},
    # Perlengkapan habis pakai + seragam/sepatu pabrik yang dipakai outlet
    **{c: PERLENGKAPAN for c in (
        "PEL260076", "PEL260077", "SG260005", "SG260006", "SG260007",
        "SG260008", "SG260009", "SG260010", "SG260011")},
}

# Item yang secara riil hanya dipakai pabrik (0 PO outlet) -> tidak diisi utk outlet.
JURI_ONLY = {
    "BB260001", "BB260002", "BB260003", "BB260004", "BB260005", "BB260006",
    "BB260007", "BB260008", "BB260009", "BB26001", "BB260010", "BB260011",
    "BB260012", "BB260013", "BB260014", "BB260015", "BB260016", "BB260017",
    "BB260018", "BB260020", "BB260022", "BB260023", "BB260024", "BB260025",
    "BB260026", "BB260027", "BB260028", "BB260029", "BB260055",
    "PJ260008", "PJ260015",
}


def base_of(name, abbr):
    """'5220.016 - X - RBYMS' -> '5220.016 - X'; None kalau suffix bukan abbr."""
    suf = " - " + abbr
    return name[:-len(suf)] if name and name.endswith(suf) else None


def mode(values):
    vals = [v for v in values if v]
    return collections.Counter(vals).most_common(1)[0][0] if vals else None


def selftest():
    assert base_of("5220.016 - Biaya Perlengkapan Outlet - RBYMS", "RBYMS") == PERLENGKAPAN
    assert base_of("1211.004 - Aktiva Tetap - Mesin & Peralatan - RB", "RB") == AKTIVA
    assert base_of("5220.016 - Biaya - RBYMS", "RB") is None
    assert base_of(None, "RB") is None
    assert mode([None, "a", "b", "a"]) == "a" and mode([None]) is None
    assert not set(EMPTY_RULES) & JURI_ONLY


def under_inventories(group, parents):
    while group:
        if group == "Inventories":
            return True
        group = parents.get(group)
    return False


def load_live(erp):
    rows, start = [], 0
    while True:
        st, d = erp.get("/api/method/frappe.client.get_list", {
            "doctype": "Item Default", "parent": "Item", "limit_page_length": 5000,
            "limit_start": start, "fields": json.dumps([
                "parent", "company", "expense_account", "default_inventory_account"])})
        if st != 200:
            raise SystemExit(f"GAGAL baca Item Default: {json.dumps(d)[:300]}")
        rows += d["message"]
        start += len(d["message"])
        if len(d["message"]) < 5000:
            return rows


def build_plan(erp, only_companies, only_items):
    comps = {c["name"]: c["abbr"] for c in erp.list_all("Company", ["name", "abbr"])}
    targets = {c: a for c, a in comps.items()
               if "(FRC)" not in c and c not in GROUP_COMPANIES}
    for c in only_companies:
        if c not in targets:
            raise SystemExit(f"--company '{c}' bukan company target (FRC/grup/tidak ada)")
    parents = {g["name"]: g["parent_item_group"]
               for g in erp.list_all("Item Group", ["name", "parent_item_group"])}
    items = {i["name"]: i for i in erp.list_all(
        "Item", ["name", "item_name", "item_group"], [["disabled", "=", 0]])
        if under_inventories(i["item_group"], parents)}
    by_item = collections.defaultdict(dict)
    for r in load_live(erp):
        if r["parent"] in items and r["company"] in targets:
            by_item[r["parent"]][r["company"]] = r
    accounts = {a["name"] for a in erp.list_all(
        "Account", ["name"], [["is_group", "=", 0], ["disabled", "=", 0]])}
    warehouses = {w["name"] for w in erp.list_all("Warehouse", ["name"])}

    scope = only_companies or list(targets)
    wajib = sorted(k for k in items if len(by_item[k]) >= WAJIB_MIN
                   and (not only_items or k in only_items))
    plan, skipped, no_rule, missing = {}, [], [], set()
    for code in wajib:
        if code in JURI_ONLY:
            skipped.append(code)
            continue
        rows = by_item[code]
        exp_base = mode(base_of(r["expense_account"], targets[c]) for c, r in rows.items())
        inv_base = mode(base_of(r["default_inventory_account"], targets[c])
                        for c, r in rows.items())
        if not exp_base:
            exp_base = EMPTY_RULES.get(code) or EMPTY_RULES.get(items[code]["item_group"])
        if not exp_base:
            no_rule.append(code)
            continue
        fill, add = [], []
        for c in scope:
            abbr = targets[c]
            exp, wh = f"{exp_base} - {abbr}", f"Stores - {abbr}"
            inv = f"{inv_base} - {abbr}" if inv_base else None
            if c in rows and rows[c]["expense_account"]:
                continue
            for nm in (exp, wh, inv) if c not in rows else (exp,):
                if nm and nm not in accounts and nm not in warehouses:
                    missing.add(f"{c}: {nm}")
            if c in rows:
                fill.append({"company": c, "expense_account": exp})
            else:
                add.append({"company": c, "expense_account": exp,
                            "default_warehouse": wh, "default_inventory_account": inv})
        if fill or add:
            plan[code] = {"fill": fill, "add": add, "exp_base": exp_base}
    if missing:
        raise SystemExit("STOP: akun/warehouse tidak ada di company tujuan:\n  "
                         + "\n  ".join(sorted(missing)[:50]))
    return items, wajib, plan, skipped, no_rule


def apply_item(erp, code, p):
    st, d = erp.get("/api/resource/Item/" + _q(code))
    if st != 200:
        raise SystemExit(f"GAGAL GET Item {code}: HTTP {st}")
    doc = d["data"]
    rows = doc.get("item_defaults") or []
    have = {r["company"]: r for r in rows}
    changed = 0
    for f in p["fill"]:
        r = have.get(f["company"])
        if r and not r.get("expense_account"):
            r["expense_account"] = f["expense_account"]
            changed += 1
    for a in p["add"]:
        if a["company"] not in have:
            rows.append({k: v for k, v in a.items() if v})
            changed += 1
    if not changed:
        return 0
    os.makedirs(BACKUP_DIR, exist_ok=True)
    with open(os.path.join(BACKUP_DIR, code.replace("/", "_") + ".json"), "w") as f:
        json.dump(d["data"], f)
    st, r = erp.put("Item", code, {"item_defaults": rows})
    if st != 200:
        raise SystemExit(f"GAGAL PUT Item {code}: {json.dumps(r)[:300]}")
    return changed


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--company", action="append", default=[])
    ap.add_argument("--item", action="append", default=[])
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    selftest()

    env = load_env(PROD_ENV)
    erp = Client(env["ERPNEXT_URL"], env["ERPNEXT_API_KEY"], label="BARU", pause=0.15)
    print(f"TARGET SITE: {erp.base}")
    print("Mode:", "EXECUTE" if args.execute else "DRY-RUN (tambahkan --execute)")

    items, wajib, plan, skipped, no_rule = build_plan(erp, args.company, set(args.item))
    n_fill = sum(len(p["fill"]) for p in plan.values())
    n_add = sum(len(p["add"]) for p in plan.values())
    print(f"item wajib: {len(wajib)} | JURI_ONLY dilewati: {len(skipped)} | "
          f"TANPA ATURAN: {len(no_rule)} {no_rule}")
    print(f"rencana: {len(plan)} item | isi akun kosong {n_fill} baris | "
          f"baris baru {n_add}")
    summ = collections.Counter()
    for code, p in plan.items():
        summ[(items[code]["item_group"], p["exp_base"])] += len(p["fill"]) + len(p["add"])
    for (g, acc), n in sorted(summ.items()):
        print(f"  {g:20} {acc:48} {n:6} baris")

    if not args.execute:
        return
    done = 0
    for i, (code, p) in enumerate(sorted(plan.items()), 1):
        done += apply_item(erp, code, p)
        if i % 20 == 0:
            print(f"  .. {i}/{len(plan)} item")
    print(f"SELESAI: {done} baris ditulis di {len(plan)} item. Backup: {BACKUP_DIR}")


if __name__ == "__main__":
    main()
