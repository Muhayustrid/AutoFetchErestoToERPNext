#!/usr/bin/env python3
"""Perbaikan item_defaults Item Group 'Barang Habis Pakai' (keputusan user 14 Okt).

1. 33 item outlet: buat baris item_defaults utk 6 company non-FRC yang 0 baris
   (RSMS, RSPY, RSUKJ, RRSC, RFB, RSUPP) dgn akun 5220.016 + Stores - <ABBR>.
   FRC tidak dibuatkan (keputusan user). Grup (JURI GROUP/OUTLET/TRAINING/Pameran) skip.
2. 11 baris kosong di PT. JURI: diisi akun pabrik sesuai pola nama item
   (pabrik: ATK -> 5130.005, perlengkapan/sabun/tinta/plastik -> 5130.010).
   Air Galon (BHP260021) -> 5130.010.
Idempoten: baris company yang sudah ada tidak disentuh (kecuali JURI kosong).
"""
import json, os, sys, urllib.parse
env = dict(l.strip().split("=",1) for l in open("/tmp/eresto_prod.env") if "=" in l)
sys.path.insert(0,"pos_sync")
from prod_common import Client
erp = Client(env["ERPNEXT_URL"], env["ERPNEXT_API_KEY"], label="BARU")
_q = urllib.parse.quote

DRY = "--execute" not in sys.argv
print("Mode:", "DRY-RUN (tambahkan --execute)" if DRY else "EXECUTE")

JURI = "PT. JUARA ROTI INDONESIA"
EXP_PABRIK_ATK = "5130.005 - Biaya Alat Tulis Kantor - JURI"
EXP_PABRIK_LNG = "5130.010 - Biaya Perlengkapan Pabrik - JURI"

# company non-FRC non-grup yang 0 baris
TARGET_COMPANIES = {
    "RS MUHAMMADIYAH SELOGIRI": "RSMS",
    "RSUD PROF H MUHAMMADIYAH YAMIN SH": "RSPY",
    "RSUD KRAMAT JATI": "RSUKJ",
    "RS RIDHOKA SALMA CIKARANG": "RRSC",
    "RSI FATIMAH BANYUWANGI": "RFB",
    "RSUP Palembang": "RSUPP",
}

items = json.load(open("/tmp/bhp_items.json"))
actives = [(c, n, d) for c, n, dis, d in items if not dis]
outlet_items = [c for c, n, d in actives if len([x for x in d if x.get("company")]) > 5]
pabrik_items = [c for c, n, d in actives if c not in outlet_items]
print(f"item outlet: {len(outlet_items)} | item pabrik: {len(pabrik_items)}")

# pola akun outlet per item: lihat akun teratas item tsb antar company (semua 5220.016 pola sama)
report = []

def existing_row(item_doc, company):
    for d in item_doc.get("item_defaults") or []:
        if d.get("company") == company:
            return d
    return None

def save_item(item_doc):
    name = item_doc["name"]
    payload = {"item_defaults": item_doc["item_defaults"]}
    st, r = erp.put("Item", name, payload)
    if st != 200:
        raise SystemExit(f"GAGAL PUT Item {name}: {json.dumps(r)[:300]}")

def juri_expense_for(item_code, item_name):
    # pola pabrik: ATK/office -> 5130.005; lainnya -> 5130.010
    atk_codes = {"BHP26002"}  # Gunting
    if item_code in atk_codes:
        return EXP_PABRIK_ATK
    return EXP_PABRIK_LNG

# ---------- 1) company 0 baris ----------
print("\n[1] Buat baris utk company non-FRC yang 0 baris")
for code, name, defaults in actives:
    if code not in outlet_items:
        continue  # item pabrik tidak ikut outlet
    st, b = erp.get(f"/api/resource/Item/{_q(code)}")
    doc = b.get("data") or {}
    changed = False
    for company, abbr in TARGET_COMPANIES.items():
        if existing_row(doc, company):
            continue
        doc.setdefault("item_defaults", []).append({
            "company": company,
            "expense_account": f"5220.016 - Biaya Perlengkapan Outlet - {abbr}",
            "default_warehouse": f"Stores - {abbr}",
        })
        changed = True
        report.append(f"  + {code:10} -> {company} (5220.016 - {abbr})")
    if changed and not DRY:
        save_item(doc)
print(f"  {len(report)} baris baru" if report else "  semua sudah ada")

# ---------- 2) isi 11 baris kosong JURI ----------
print("\n[2] Isi baris kosong PT. JURI")
n_juri = 0
for code, name, defaults in actives:
    st, b = erp.get(f"/api/resource/Item/{_q(code)}")
    doc = b.get("data") or {}
    row = existing_row(doc, JURI)
    if row and not row.get("expense_account"):
        exp = juri_expense_for(code, name)
        print(f"  ~ {code:10} {str(name)[:32]:32} -> {exp}")
        row["expense_account"] = exp
        n_juri += 1
        if not DRY:
            save_item(doc)
print(f"  {n_juri} baris JURI diisi" if n_juri else "  baris JURI sudah terisi semua")

print("\nSelesai." + (" (DRY-RUN, belum ditulis)" if DRY else ""))
