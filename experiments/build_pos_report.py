"""Excel ringkasan hasil bulk POS setup (dari API + report JSON).
Output: experiments/POS_Setup_Report.xlsx
Sheet: Ringkasan, POS_Profile, Price_Group, Unmapped_SKU, Catatan.
Env: ERPNEXT_URL, ERPNEXT_API_KEY."""
import json
import os
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

BASE = os.getenv("ERPNEXT_URL", "http://127.0.0.1:8081").rstrip("/")
KEY = os.getenv("ERPNEXT_API_KEY", "").strip()

S = requests.Session()
S.headers.update({"Authorization": "token " + KEY})


def g(path, params=None):
    r = S.get(BASE + path, params=params, timeout=90)
    return r.status_code, (r.json() if r.status_code == 200 else {})


rep = json.load(open("experiments/pos_bulk_report.json"))
m = pd.read_excel("experiments/Company_POS_Setup.xlsx",
                  sheet_name="Company_Tier")

# POS Profile sheet
st, d = g("/api/resource/POS Profile", params={
    "fields": '["name","company","selling_price_list",'
              '"custom_pos_next_price_group","warehouse","disabled"]',
    "limit_page_length": 2000})
prof = pd.DataFrame(d.get("data", []))


def payments_of(nm):
    st, dd = g("/api/resource/POS Profile/" + urllib.parse.quote(nm))
    if st != 200:
        return nm, ""
    pays = dd.get("data", {}).get("payments", []) or []
    parts = []
    for x in pays:
        lab = x.get("mode_of_payment", "")
        if x.get("default"):
            lab += " (default)"
        parts.append(lab)
    return nm, ", ".join(parts)


if not prof.empty:
    pay_map = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        for fu in as_completed({pool.submit(payments_of, nm): nm
                                for nm in prof["name"]}):
            nm, txt = fu.result()
            pay_map[nm] = txt
    prof["payments_txt"] = prof["name"].map(pay_map)
    tier_of = dict(zip(m["company"].astype(str),
                       m["tier_takeaway"].astype(str)))
    prof["tier_eResto"] = prof["company"].map(tier_of)
    prof = prof[["name", "company", "tier_eResto", "selling_price_list",
                 "custom_pos_next_price_group", "payments_txt",
                 "warehouse", "disabled"]]
    prof.columns = ["POS Profile", "Company", "Tier eResto", "Price List",
                    "Price Group", "Metode Bayar", "Warehouse", "Disabled"]
    prof = prof.sort_values("Company").reset_index(drop=True)

# Price Group sheet
rows = []
st, d = g("/api/resource/Price Group", params={
    "fields": '["name","price_list"]', "limit_page_length": 300})
for pg in d.get("data", []):
    st2, d2 = g("/api/resource/Price Group/" + urllib.parse.quote(pg["name"]))
    doc = d2.get("data", {})
    st3, d3 = g("/api/resource/Item Price", params={
        "fields": '["name"]',
        "filters": json.dumps([["price_list", "=", pg["price_list"]]]),
        "limit_page_length": 500})
    rows.append({
        "Price Group": pg["name"],
        "Price List": pg["price_list"],
        "Jumlah Item": len(doc.get("items", [])),
        "Jumlah Item Price": len(d3.get("data", [])) if st3 == 200 else -1,
        "Jumlah Outlet": len(doc.get("outlets", [])),
        "Enabled": doc.get("enabled"),
    })
pgdf = pd.DataFrame(rows).sort_values("Jumlah Outlet", ascending=False)

# Unmapped SKU sheet
un = []
for tier, skus in (rep.get("unmapped") or {}).items():
    seen = []
    for s_ in skus:
        if s_ not in seen:
            seen.append(s_)
    for s_ in seen:
        un.append({"Tier": tier, "SKU eResto": s_})
undf = pd.DataFrame(un).drop_duplicates() if un else pd.DataFrame(
    columns=["Tier", "SKU eResto"])

# Catatan sheet
cat = [
    ["Alur POSNext", "Price Group memiliki Price List (PG-<nama>), "
     "Item Price, dan mengklaim semua POS Profile company-nya"],
    ["Urutan apply", "prep -> pg -> prof -> claim -> group (Shift Group) "
     "-> verify"],
    ["Shift Group", "ALL TIME (00:00-23:59:59, tanpa enforcement); "
     "membership lewat tabel Members, bukan field di profil"],
    ["POS Profile", "nama 'SHIFT 1 - <company>', Cash, Warehouse "
     "Stores - <abbr>, item group Products, print POS Next Receipt"],
    ["Metode Bayar", "semua profil: Cash (default, allow returns), "
     "Debit Card, Credit Card, QRIS - pola SHIFT 1 Delanggu "
     "(update_pos_payments.py)"],
    ["Harga", "rate dari sampling transaksi eResto per tier "
     "(window 1-4 Okt, fallback 15 Sep-4 Okt utk tier sepi)"],
    ["Profile tanpa PG", "tinggal RSUD Taman Husada Bontang (tidak ada di "
     "eResto). 6 profil duplikat ejaan sudah dihapus 2026-10-04 "
     "(delete_duplicate_profiles.py); company-nya dibiarkan "
     "(data backup, nol riwayat transaksi)"],
    ["Company grup", "JURI GROUP / OUTLET / PT. JUARA ROTI INDONESIA / "
     "TRAINING tidak dibuatkan profil (bukan outlet)"],
    ["Unmapped SKU", "SKU belum ada di sku_to_item_code.csv; price group "
     "berisi item yang sudah terpetakan saja"],
]
catdf = pd.DataFrame(cat, columns=["Topik", "Keterangan"])

with pd.ExcelWriter("experiments/POS_Setup_Report.xlsx",
                    engine="openpyxl") as w:
    prof.to_excel(w, sheet_name="POS_Profile", index=False)
    pgdf.to_excel(w, sheet_name="Price_Group", index=False)
    undf.to_excel(w, sheet_name="Unmapped_SKU", index=False)
    catdf.to_excel(w, sheet_name="Catatan", index=False)
    for ws in w.sheets.values():
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        fill = PatternFill("solid", fgColor="D9EAF7")
        for c in ws[1]:
            c.fill, c.font = fill, Font(bold=True)
            c.alignment = Alignment(horizontal="center", vertical="center")
        for col in ws.columns:
            wdt = max(len(str(c.value or "")) for c in col)
            ws.column_dimensions[get_column_letter(
                col[0].column)].width = min(wdt + 2, 52)
print("POS_Setup_Report.xlsx ditulis:")
print(f"  POS_Profile : {len(prof)}")
print(f"  Price_Group : {len(pgdf)}")
print(f"  Unmapped_SKU: {len(undf)}")
