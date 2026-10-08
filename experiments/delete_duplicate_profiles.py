"""Hapus 6 POS Profile duplikat (ejaan beda dari outlet eResto).
Urutan aman:
  1. Cek tiap target: profil ada, tanpa Price Group, company-nya tidak
     dipakai di Price Group manapun, dan tanpa dokumen transaksi
     (POS Invoice / Sales Invoice / POS Opening Shift / POS Closing Entry).
  2. Keluarkan ke-6nya dari Shift Group 'ALL TIME' (satu save).
  3. Hapus profil satu per satu.
  4. Verifikasi: profil 404, member group tinggal 161.
Company TIDAK dihapus (data dari backup produksi, bukan buatan kita).
Idempoten: target yang sudah 404 = skip.
Env: ERPNEXT_URL, ERPNEXT_API_KEY."""
import json
import os
import sys
import time
import urllib.parse

import requests

BASE = os.getenv("ERPNEXT_URL", "http://127.0.0.1:8081").rstrip("/")
KEY = os.getenv("ERPNEXT_API_KEY", "").strip()
if not KEY:
    sys.exit("ERROR: env ERPNEXT_API_KEY kurang")

S = requests.Session()
S.headers.update({"Authorization": "token " + KEY})

TARGETS = [
    ("SHIFT 1 - RS KARTIKA ASIH SUKABUMI", "RS KARTIKA ASIH SUKABUMI"),
    ("SHIFT 1 - RS MEDIROSSA - CIKARANG", "RS MEDIROSSA - CIKARANG"),
    ("SHIFT 1 - RS MUHAMMADIYAH MARDATILAH PEMALANG",
     "RS MUHAMMADIYAH MARDATILAH PEMALANG"),
    ("SHIFT 1 - RS RAHMAN RAHIM", "RS RAHMAN RAHIM"),
    ("SHIFT 1 - RS RAHMAN RAHIM SIDOREJO", "RS RAHMAN RAHIM SIDOREJO"),
    ("SHIFT 1 - RSI MUH. KENDAL", "RSI MUH. KENDAL"),
]

# doctype + field yg bisa memblokir delete
TRANSAKSI = [
    ("POS Invoice", "pos_profile"),
    ("Sales Invoice", "pos_profile"),
    ("POS Opening Shift", "pos_profile"),
    ("POS Closing Entry", "pos_profile"),
]
# cek riwayat company (utk laporan; bukan target hapus)
RIWAYAT_COMPANY = ["GL Entry", "Sales Invoice", "Purchase Invoice",
                   "Stock Ledger Entry", "POS Invoice"]


def get(path, params=None):
    r = S.get(BASE + path, params=params, timeout=90)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:300]}


def delete(path):
    r = S.delete(BASE + path, timeout=90)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, r.text[:300]


def count_links(doctype, field, value):
    """0 kalau tidak ada/bukan doctype; None kalau query error lain."""
    st, d = get(f"/api/resource/{urllib.parse.quote(doctype)}", params={
        "fields": '["name"]',
        "filters": json.dumps([[field, "=", value]]),
        "limit_page_length": 1})
    if st == 200:
        return len(d.get("data", []))
    msg = str(d)
    if "not found" in msg or "DoesNotExist" in msg or "Unknown column" in msg:
        return 0
    return None


rep = {"checked": [], "group": {}, "deleted": [], "skipped": [],
       "failed": [], "company_history": {}}

# ---------- 1. pre-check ----------
ok_targets = []
for prof, comp in TARGETS:
    st, d = get("/api/resource/POS Profile/" + urllib.parse.quote(prof))
    if st != 200:
        rep["skipped"].append({"profile": prof, "reason": f"HTTP {st} (sudah tidak ada?)"})
        print(f"SKIP {prof}: sudah tidak ada")
        continue
    doc = d["data"]
    pg = doc.get("custom_pos_next_price_group") or ""
    if pg:
        rep["skipped"].append({"profile": prof, "reason": f"punya Price Group {pg}"})
        print(f"SKIP {prof}: punya PG {pg}")
        continue
    # company dipakai di PG manapun?
    st2, d2 = get("/api/resource/Price Group", params={
        "fields": '["name"]', "limit_page_length": 300})
    used = []
    for x in d2.get("data", []):
        st3, d3 = get("/api/resource/Price Group/" + urllib.parse.quote(x["name"]))
        if st3 == 200 and any(o.get("company") == comp
                              for o in d3["data"].get("outlets", [])):
            used.append(x["name"])
    if used:
        rep["skipped"].append({"profile": prof,
                               "reason": f"company dipakai PG {used}"})
        print(f"SKIP {prof}: company dipakai di {used}")
        continue
    # dokumen transaksi?
    blockers = []
    for dt, field in TRANSAKSI:
        n = count_links(dt, field, prof)
        if n is None:
            blockers.append(f"{dt}: query error")
        elif n > 0:
            blockers.append(f"{dt}: {n} dokumen")
    if blockers:
        rep["skipped"].append({"profile": prof, "reason": "; ".join(blockers)})
        print(f"SKIP {prof}: {blockers}")
        continue
    ok_targets.append((prof, comp))
    rep["checked"].append({"profile": prof, "company": comp, "clean": True})
    print(f"SIAP hapus {prof}")

if not ok_targets:
    print("tidak ada target yang bisa dihapus")
    json.dump(rep, open("experiments/delete_duplicates_report.json", "w"),
              ensure_ascii=False, indent=1)
    sys.exit(0)

# ---------- 2. keluarkan dari Shift Group ALL TIME ----------
st, d = get("/api/resource/POS Profile Group/ALL TIME")
if st != 200:
    sys.exit("ERROR: grup ALL TIME tidak ada")
grp = d["data"]
drop = {p for p, _c in ok_targets}
members = [{"pos_profile": x["pos_profile"], "company": x.get("company")}
           for x in grp.get("profiles", [])
           if x["pos_profile"] not in drop]
n_before = len(grp.get("profiles", []))
r = S.put(BASE + "/api/resource/POS Profile Group/ALL TIME", json={
    "group_name": "ALL TIME", "pos_schedule_enabled": 1,
    "pos_schedule_start": grp.get("pos_schedule_start") or "0:00:00",
    "pos_schedule_end": grp.get("pos_schedule_end") or "23:59:59",
    "pos_schedule_warning_minutes": grp.get("pos_schedule_warning_minutes") or 0,
    "pos_schedule_enforce_closing": grp.get("pos_schedule_enforce_closing") or 0,
    "profiles": members}, timeout=240)
rep["group"] = {"members_before": n_before, "members_after": len(members),
                "http": r.status_code, "body": r.text[:200]}
print(f"grup ALL TIME: {n_before} -> {len(members)} member, HTTP {r.status_code}")
if r.status_code != 200:
    sys.exit("GAGAL update grup; hentikan sebelum hapus")

# ---------- 3. hapus profil ----------
for prof, comp in ok_targets:
    st, d = delete("/api/resource/POS Profile/" + urllib.parse.quote(prof))
    if st == 202 or st == 200:
        rep["deleted"].append(prof)
        print(f"OK hapus {prof}")
    else:
        rep["failed"].append({"profile": prof, "http": st, "body": str(d)[:200]})
        print(f"GAGAL hapus {prof}: HTTP {st} {str(d)[:150]}")
    time.sleep(0.15)

# ---------- 4. verifikasi + riwayat company (utk laporan) ----------
for prof, comp in TARGETS:
    st, _ = get("/api/resource/POS Profile/" + urllib.parse.quote(prof))
    rep.setdefault("verify_after", []).append(
        {"profile": prof, "http": st, "hilang": st == 404})
    hist = {}
    for dt in RIWAYAT_COMPANY:
        n = count_links(dt, "company", comp)
        if n is None:
            hist[dt] = "err"
        elif n > 0:
            hist[dt] = n
    rep["company_history"][comp] = hist
st, d = get("/api/resource/POS Profile Group/ALL TIME")
if st == 200:
    rep["group"]["final_members"] = len(d["data"].get("profiles", []))
st, d = get("/api/resource/POS Profile", params={
    "fields": '["name"]', "limit_page_length": 2000})
rep["profiles_total"] = len(d.get("data", [])) if st == 200 else -1

json.dump(rep, open("experiments/delete_duplicates_report.json", "w"),
          ensure_ascii=False, indent=1)
print(f"\nhapus: {len(rep['deleted'])} | gagal: {len(rep['failed'])} "
      f"| skip: {len(rep['skipped'])}")
print(f"profil total sekarang: {rep['profiles_total']} | "
      f"member ALL TIME: {rep['group'].get('final_members')}")
print("riwayat company:", json.dumps(rep["company_history"],
                                      ensure_ascii=False))
print("report: experiments/delete_duplicates_report.json")
