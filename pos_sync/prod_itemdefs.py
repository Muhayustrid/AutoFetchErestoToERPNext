"""Lengkapi item_defaults + samakan flag stok di PROD (docs/07).

Kenapa: company di prod mengaktifkan `enable_item_wise_inventory_account`,
jadi setiap baris stok butuh default inventory account per (item, company).
Site lokal sudah valid; prod belum lengkap:

1. JURI (PT. JUARA ROTI INDONESIA): baris Item Default belum ada -> ambil
   akun dari site lokal (per item), fallback pola per item_group.
2. RPMD/RQLY: baris ada tapi beberapa akunnya kosong -> isi dari pola
   prod yang sudah terisi (item_group + abbr).
3. Tabrakan model: 11 item yang di local NON-STOCK masih stock di prod
   (ATK*/BHP*/PEL260025/PEL260047) -> set is_stock_item=0 agar DN tidak
   menuntut stok. Aman: prod belum punya transaksi stok (SLE=0).

Idempoten: skip yang sudah benar.
Usage: python3 prod_itemdefs.py [--dry-run]
Env: /tmp/eresto_mig.env (lokal), /tmp/eresto_prod.env (prod).
"""
import argparse
import json
import os
import sys
import urllib.parse
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import (JURI, LOCAL_ENV, PROD_ENV, SRC_DIR, Client,  # noqa: E402
                         jload, load_env)

DIVERGENT_NONSTOCK = [
    "ATK260001", "ATK260027", "ATK260038", "ATK260041", "ATK260046",
    "BHP260004", "BHP260020", "BHP260023", "BHP260028", "PEL260025",
    "PEL260047",
]
GROUPS = ("RS PKU MUHAMMADIYAH DELANGGU", "RSU QUEEN LATIFA YOGYAKARTA")


def get_item(client, code, cache):
    if code not in cache:
        st, d = client.get("/api/resource/Item/" + urllib.parse.quote(code))
        cache[code] = d.get("data") if st == 200 else None
    return cache[code]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    le, pe = load_env(LOCAL_ENV), load_env(PROD_ENV)
    lc = Client(le["ERPNEXT_URL"], le["ERPNEXT_API_KEY"], label="local")
    pc = Client(pe["ERPNEXT_URL"], pe["ERPNEXT_API_KEY"], label="prod",
                pause=0.04)

    # ---------- himpunan item yang dibutuhkan ----------
    need = defaultdict(set)
    for grp in jload("opening.json"):
        for it in grp["items"]:
            need[grp["company"]].add(it["item_code"])
    for f, dt in (("stock_entry.json", None), ("purchase_receipt.json", None),
                  ("delivery_note.json", None)):
        for d in jload(f):
            for it in d.get("items", []):
                need[d["company"]].add(it["item_code"])
    all_items = sorted(set().union(*need.values()))
    print(f"item dibutuhkan: {len(all_items)} "
          f"({', '.join(f'{k[:24]}={len(v)}' for k, v in need.items())})")

    lcache, pcache = {}, {}
    created, updated, fails, skipped = [], [], [], 0

    # ---------- 1. flag non-stock untuk 11 item tabrakan ----------
    print("== 1. samakan flag non-stock (11 item) ==")
    for code in DIVERGENT_NONSTOCK:
        it = get_item(pc, code, pcache)
        if not it:
            print(f"  {code}: tidak ada di prod")
            continue
        if not it.get("is_stock_item"):
            skipped += 1
            continue
        if args.dry_run:
            print(f"  DRY-RUN {code}: is_stock_item -> 0")
            continue
        st, d = pc.req("POST", "/api/method/frappe.client.set_value", {
            "doctype": "Item", "name": code, "fieldname": "is_stock_item",
            "value": 0})
        ok = st == 200 and d.get("message", {}).get("is_stock_item") in (0, "0")
        print(f"  {code}: set non-stock {'OK' if ok else 'GAGAL '+str(d)[:120]}")
        if not ok:
            fails.append({"item": code, "aksi": "non-stock", "err": str(d)[:200]})
        else:
            pcache.pop(code, None)

    # ---------- 2. pola akun terpasang di prod (per group/company) ----------
    pat = defaultdict(Counter)
    for code in all_items:
        it = get_item(pc, code, pcache)
        if not it:
            continue
        for row in it.get("item_defaults") or []:
            co, a = row.get("company"), row.get("default_inventory_account")
            if co in (JURI,) + GROUPS and a:
                pat[(it.get("item_group"), co)][a] += 1

    # ---------- 3. JURI: tambah baris dari data lokal ----------
    print("== 2. baris JURI (dari lokal) ==")
    for code in sorted(need.get(JURI, ())):
        it = get_item(pc, code, pcache)
        if not it:
            fails.append({"item": code, "aksi": "ADD-JURI",
                          "err": "item tidak ada di prod"})
            continue
        juri_row = next((r for r in it.get("item_defaults") or []
                         if r.get("company") == JURI), None)
        if juri_row and juri_row.get("default_inventory_account"):
            skipped += 1
            continue
        if not it.get("is_stock_item"):
            skipped += 1
            print(f"  {code}: non-stock, tidak perlu akun")
            continue
        lit = get_item(lc, code, lcache)
        acc = None
        if lit:
            lrow = next((r for r in lit.get("item_defaults") or []
                         if r.get("company") == JURI), None)
            acc = lrow.get("default_inventory_account") if lrow else None
        if not acc:
            acc = (pat[(it.get("item_group"), JURI)].most_common(1)[0][0]
                   if pat[(it.get("item_group"), JURI)] else None)
        if not acc:
            fails.append({"item": code, "aksi": "ADD-JURI",
                          "err": "tanpa acuan akun"})
            print(f"  {code}: GAGAL tanpa acuan akun")
            continue
        if args.dry_run:
            print(f"  DRY-RUN ADD JURI {code} -> {acc}")
            continue
        if juri_row:  # baris ada tapi akun kosong -> set_value
            st, d = pc.req("POST", "/api/method/frappe.client.set_value", {
                "doctype": "Item Default", "name": juri_row["name"],
                "fieldname": "default_inventory_account", "value": acc})
            ok = st == 200
            act = "SET-JURI"
        else:
            st, d = pc.post("Item Default", {
                "parent": code, "parenttype": "Item",
                "parentfield": "item_defaults", "company": JURI,
                "default_inventory_account": acc})
            ok = st == 200
            act = "ADD-JURI"
        if not ok:
            fails.append({"item": code, "aksi": act, "err": str(d)[:200]})
            print(f"  {code}: {act} GAGAL {str(d)[:120]}")
        else:
            created.append({"item": code, "aksi": act, "akun": acc})
            pcache.pop(code, None)

    # ---------- 4. RPMD/RQLY: isi akun kosong / baris hilang ----------
    print("== 3. baris RPMD/RQLY ==")
    for co in GROUPS:
        for code in sorted(need.get(co, ())):
            it = get_item(pc, code, pcache)
            if not it:
                fails.append({"item": code, "aksi": "FIX-" + co[:16],
                              "err": "item tidak ada di prod"})
                continue
            row = next((r for r in it.get("item_defaults") or []
                        if r.get("company") == co), None)
            if row and row.get("default_inventory_account"):
                skipped += 1
                continue
            if not it.get("is_stock_item"):
                skipped += 1
                continue
            accs = pat[(it.get("item_group"), co)]
            acc = accs.most_common(1)[0][0] if accs else None
            if not acc:
                fails.append({"item": code, "aksi": "FIX-" + co[:16],
                              "err": "tanpa acuan akun"})
                print(f"  {code} {co}: GAGAL tanpa acuan akun")
                continue
            if args.dry_run:
                print(f"  DRY-RUN {co[:20]} {code} -> {acc}")
                continue
            if row:
                st, d = pc.req("POST", "/api/method/frappe.client.set_value", {
                    "doctype": "Item Default", "name": row["name"],
                    "fieldname": "default_inventory_account", "value": acc})
                act = "SET"
            else:
                st, d = pc.post("Item Default", {
                    "parent": code, "parenttype": "Item",
                    "parentfield": "item_defaults", "company": co,
                    "default_inventory_account": acc})
                act = "ADD"
            ok = st == 200
            if not ok:
                fails.append({"item": code, "aksi": act + "-" + co[:16],
                              "err": str(d)[:200]})
                print(f"  {code}: {act} GAGAL {str(d)[:120]}")
            else:
                created.append({"item": code, "aksi": act, "company": co,
                                "akun": acc})
                pcache.pop(code, None)

    json.dump({"created": created, "fails": fails},
              open(os.path.join(SRC_DIR, "itemdefs_run.json"), "w"),
              indent=1, default=str)
    print(f"== ringkasan: perubahan={len(created)} skip={skipped} "
          f"gagal={len(fails)} ==")
    for f in fails[:20]:
        print("   ", f)

    # ---------- 5. clear cache dokumen Item ----------
    # Validasi stok memakai frappe.get_cached_doc("Item") (TTL 1 jam). Insert
    # child row lewat REST tidak memicu doc.save() sehingga cache lama masih
    # terpakai. set_value pada parent memicu save -> clear_document_cache.
    print("== 4. clear cache Item (touch via set_value) ==")
    touched_items = sorted(set().union(*need.values()))
    n_touch, touch_fail = 0, 0
    for code in touched_items:
        it = get_item(pc, code, pcache)
        if not it:
            continue
        if args.dry_run:
            continue
        st, d = pc.req("POST", "/api/method/frappe.client.set_value", {
            "doctype": "Item", "name": code,
            "fieldname": {"is_stock_item": int(it.get("is_stock_item") or 0)}})
        if st != 200:
            touch_fail += 1
            print(f"  touch {code} GAGAL: {str(d)[:120]}")
        else:
            n_touch += 1
    print(f"  touched: {n_touch}; gagal: {touch_fail}")
    if touch_fail:
        fails.append({"aksi": "cache-touch", "err": f"{touch_fail} gagal"})
    if fails and not args.dry_run:
        sys.exit(1)
    print("ITEMDEFS OK")


if __name__ == "__main__":
    main()
