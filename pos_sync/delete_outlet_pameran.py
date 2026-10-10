#!/usr/bin/env python3
"""Hapus Company OUTLET PAMERAN dari ERPNext Baru dengan aman.

Alur (semua idempoten, dry-run default):
  --backup    tarik & simpan JSON semua dokumen terkait ke audit_logs/
  --prep      hapus baris 'Allowed To Transact With' PAMERAN di supplier JURI
              + cancel & hapus TDL0003 (Transaction Deletion Record submitted)
  --delete    hapus Company OUTLET PAMERAN (on_trash meng-cascade akun,
              cost center, warehouse, template pajak)
  --verify    sweep 0 sisa di semua doctype terkait

Env: /tmp/eresto_prod.env (ERPNEXT_URL, ERPNEXT_API_KEY) — site BARU.
"""
import json
import os
import sys
from datetime import datetime

import requests

ENV_FILE = "/tmp/eresto_prod.env"

COMPANY = "OUTLET PAMERAN"
SUPPLIER = "PT. JUARA ROTI INDONESIA"
TDL = "TDL0003"

# (doctype, field, value) sweep verifikasi
SWEEP = [
    ("Company", "name", COMPANY),
    ("Warehouse", "company", COMPANY),
    ("Account", "company", COMPANY),
    ("Cost Center", "company", COMPANY),
    ("Item Tax Template", "company", COMPANY),
    ("Sales Taxes and Charges Template", "company", COMPANY),
    ("Purchase Taxes and Charges Template", "company", COMPANY),
    ("Supplier", "Allowed To Transact With", None),  # child filter, di-set runtime
    ("POS Invoice", "company", COMPANY),
    ("Sales Invoice", "company", COMPANY),
    ("GL Entry", "company", COMPANY),
    ("Journal Entry", "company", COMPANY),
    ("Payment Entry", "company", COMPANY),
    ("Stock Entry", "company", COMPANY),
    ("Stock Reconciliation", "company", COMPANY),
    ("Stock Ledger Entry", "company", COMPANY),
    ("Bin", "company", COMPANY),
    ("Material Request", "company", COMPANY),
    ("Work Order", "company", COMPANY),
    ("Production Plan", "company", COMPANY),
    ("Purchase Order", "company", COMPANY),
    ("Purchase Receipt", "company", COMPANY),
    ("Purchase Invoice", "company", COMPANY),
    ("Delivery Note", "company", COMPANY),
    ("Sales Order", "company", COMPANY),
    ("POS Profile", "company", COMPANY),
    ("Asset", "company", COMPANY),
    ("Employee", "company", COMPANY),
    ("Budget", "company", COMPANY),
    ("Transaction Deletion Record", "company", COMPANY),
    ("Bank Account", "company", COMPANY),
]


def load_env():
    for line in open(ENV_FILE):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    return os.environ["ERPNEXT_URL"], os.environ["ERPNEXT_API_KEY"]


URL, KEY = load_env()
H = {"Authorization": f"token {KEY}"}


def get(path, **params):
    return requests.get(f"{URL}{path}", params=params or None, headers=H, timeout=90)


def count(doctype, field, value):
    r = get(f"/api/method/frappe.client.get_count",
            doctype=doctype, filters=json.dumps([[field, "=", value]]))
    if r.status_code != 200:
        return None
    return r.json().get("message")


def list_docs(doctype, field, value, fields=None, limit=1000):
    p = {"filters": json.dumps([[field, "=", value]]), "limit_page_length": limit}
    if fields:
        p["fields"] = json.dumps(fields)
    r = get(f"/api/resource/{doctype}", **p)
    if r.status_code != 200:
        return None
    return r.json().get("data", [])


def get_doc(doctype, name):
    r = get(f"/api/resource/{doctype}/{requests.utils.quote(name)}")
    if r.status_code != 200:
        return None
    return r.json()["data"]


def fetch_full(doctype, rows, name_key="name"):
    out = []
    for row in rows:
        n = row.get(name_key) if isinstance(row, dict) else row
        d = get_doc(doctype, n)
        out.append(d if d else {"name": n, "fetch": "FAILED"})
    return out


def cmd_backup():
    stamp = datetime.now().strftime("%y%m%d_%H%M%S")
    payload = {"_meta": {
        "site": URL, "company": COMPANY, "at": datetime.now().isoformat(),
        "purpose": "Backup sebelum hapus Company OUTLET PAMERAN",
    }}

    payload["company"] = get_doc("Company", COMPANY)
    payload["accounts"] = fetch_full("Account", list_docs("Account", "company", COMPANY, ["name"]))
    payload["warehouses"] = fetch_full("Warehouse", list_docs("Warehouse", "company", COMPANY, ["name"]))
    payload["cost_centers"] = fetch_full("Cost Center", list_docs("Cost Center", "company", COMPANY, ["name"]))
    payload["item_tax_templates"] = fetch_full(
        "Item Tax Template", list_docs("Item Tax Template", "company", COMPANY, ["name"]))
    payload["sales_tax_templates"] = fetch_full(
        "Sales Taxes and Charges Template", list_docs("Sales Taxes and Charges Template", "company", COMPANY, ["name"]))
    payload["purchase_tax_templates"] = fetch_full(
        "Purchase Taxes and Charges Template", list_docs("Purchase Taxes and Charges Template", "company", COMPANY, ["name"]))

    # baris supplier yang menyebut PAMERAN (bukan seluruh supplier)
    sup = get_doc("Supplier", SUPPLIER)
    if sup:
        payload["supplier_rows_pameran"] = [
            {k: v for k, v in row.items() if k != "parent"}
            for row in sup.get("companies", []) if row.get("company") == COMPANY]
        payload["supplier_name"] = SUPPLIER

    payload["tdl"] = get_doc("Transaction Deletion Record", TDL)

    out_dir = os.path.join(os.path.dirname(__file__), "..", "audit_logs")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"backup_OUTLET_PAMERAN_{stamp}.json")
    with open(out, "w") as f:
        json.dump(payload, f, indent=1, default=str, ensure_ascii=False)
    print(f"BACKUP OK -> {out}")
    print(f"  accounts={len(payload['accounts'])} warehouses={len(payload['warehouses'])} "
          f"cost_centers={len(payload['cost_centers'])} "
          f"itt={len(payload['item_tax_templates'])} stt={len(payload['sales_tax_templates'])} "
          f"ptt={len(payload['purchase_tax_templates'])} "
          f"supplier_rows={len(payload.get('supplier_rows_pameran') or [])} tdl={'yes' if payload['tdl'] else 'no'}")
    return out


def cmd_prep(execute):
    # 1) supplier row 'Allowed To Transact With' — satu-satunya link statis
    # yang TIDAK di-cascade Company.on_trash.
    sup = get_doc("Supplier", SUPPLIER)
    if not sup:
        print("PREP: supplier tidak ditemukan — SKIP")
    else:
        rows = sup.get("companies", [])
        keep = [{"company": r["company"]} for r in rows if r.get("company") != COMPANY]
        removed = len(rows) - len(keep)
        if removed == 0:
            print("PREP: baris supplier PAMERAN sudah tidak ada — SKIP")
        elif not execute:
            print(f"PREP(dry): akan hapus {removed} baris dari {len(rows)} di supplier {SUPPLIER}")
        else:
            r = requests.put(f"{URL}/api/resource/Supplier/{requests.utils.quote(SUPPLIER)}",
                             json={"companies": keep}, headers=H, timeout=90)
            print(f"PREP: supplier update -> {r.status_code} ({removed} baris dihapus, sisa {len(keep)})")
            if r.status_code != 200:
                print(r.text[:400])
                return False

    # 2) TDL0003 — TIDAK perlu di-cancel manual: Company.on_trash sudah
    #    `frappe.db.delete("Transaction Deletion Record", {"company": ...})`
    #    dan link-check jalan SETELAH on_trash. (Cancel manual ditolak 403 —
    #    DocPerm TDL hanya read+write.)
    tdl = get_doc("Transaction Deletion Record", TDL)
    print(f"PREP: TDL0003 {'ada — akan ikut terhapus oleh cascade Company.on_trash' if tdl else 'sudah tidak ada'}")

    # 3) Expense Claim Type.accounts — child 'Expense Claim Account' TIDAK
    #    di-cascade on_trash (link-check statis membacanya sebagai blocker).
    r = get("/api/resource/Expense Claim Type", fields=json.dumps(["name"]), limit_page_length=100)
    ects = [x["name"] for x in r.json().get("data", [])] if r.status_code == 200 else []
    for t in ects:
        d = get_doc("Expense Claim Type", t)
        if not d:
            continue
        rows = d.get("accounts", [])
        rows_pam = [x for x in rows if x.get("company") == COMPANY]
        if not rows_pam:
            continue
        if not execute:
            print(f"PREP(dry): Expense Claim Type '{t}' — hapus 1 baris akun PAMERAN")
            continue
        keep = [x for x in rows if x.get("company") != COMPANY]
        rr = requests.put(f"{URL}/api/resource/Expense Claim Type/{requests.utils.quote(t)}",
                          json={"accounts": keep}, headers=H, timeout=90)
        print(f"PREP: Expense Claim Type '{t}' update -> {rr.status_code}: {len(rows_pam)} baris dihapus")
        if rr.status_code != 200:
            print(rr.text[:400])
            return False
    return True


def cmd_delete(execute):
    if get_doc("Company", COMPANY) is None:
        print("DELETE: Company sudah tidak ada — SKIP")
        return True
    if not execute:
        print("DELETE(dry): akan hapus Company OUTLET PAMERAN")
        return True
    r = requests.delete(f"{URL}/api/resource/Company/{requests.utils.quote(COMPANY)}",
                        headers=H, timeout=180)
    print(f"DELETE Company -> {r.status_code}")
    if r.status_code not in (200, 202):
        print(r.text[:800])
        return False
    return True


def cmd_verify():
    fails = []
    for doctype, field, value in SWEEP:
        if value is None:  # entry yang di-scan terpisah di bawah
            continue
        c = count(doctype, field, value)
        status = "OK(0)" if c == 0 else f"!! {c}"
        if c != 0:
            fails.append(doctype)
        print(f"  {doctype:36s} {status}")
    # supplier scan terpisah (child filter butuh format khusus)
    r = get("/api/resource/Supplier",
            filters=json.dumps([["Allowed To Transact With", "company", "=", COMPANY]]),
            fields=json.dumps(["name"]), limit_page_length=10)
    sup_hits = r.json().get("data", []) if r.status_code == 200 else [f"ERR{r.status_code}"]
    print(f"  Supplier allowed-list PAMERAN          {'OK(0)' if not sup_hits else '!! ' + str(sup_hits)}")
    if sup_hits:
        fails.append("Supplier")
    print("VERIFY:", "SEMUA BERSIH" if not fails else f"SISA -> {fails}")
    return not fails


def main():
    args = sys.argv[1:]
    if not args:
        args = ["--backup", "--prep", "--delete", "--verify"]
    execute = "--execute" in args
    if "--backup" in args:
        cmd_backup()
    if "--prep" in args:
        if not cmd_prep(execute):
            sys.exit(1)
    if "--delete" in args:
        if not cmd_delete(execute):
            sys.exit(1)
    if "--verify" in args:
        ok = cmd_verify()
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
