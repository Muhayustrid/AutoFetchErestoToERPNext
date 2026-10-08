"""Tambah Mode of Payment ke SEMUA POS Profile (pola SHIFT 1 Delanggu):
  Cash (default, allow returns) + Debit Card + Credit Card + QRIS.
Sumber pola: profil SHIFT 1 - RS PKU MUHAMMADIYAH DELANGGU.
Idempoten: skip profil yg sudah persis 4 metode itu.
Khusus: profil dgn pos_profile_group yg dokumennya hilang (mis. "SHIFT 2")
direstorasi grupnya dulu (jadwal disalin dari profil) supaya bisa disimpan.
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

CANON = [
    {"mode_of_payment": "Cash", "default": 1, "allow_in_returns": 1},
    {"mode_of_payment": "Debit Card", "default": 0, "allow_in_returns": 0},
    {"mode_of_payment": "Credit Card", "default": 0, "allow_in_returns": 0},
    {"mode_of_payment": "QRIS", "default": 0, "allow_in_returns": 0},
]


def get(path, params=None):
    r = S.get(BASE + path, params=params, timeout=90)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:300]}


def post(path, payload):
    r = S.post(BASE + path, json=payload, timeout=180)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:300]}


def put(path, payload):
    r = S.put(BASE + path, json=payload, timeout=180)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"_raw": r.text[:300]}


def same(cur):
    if len(cur) != len(CANON):
        return False
    for a, b in zip(cur, CANON):
        if (a.get("mode_of_payment") != b["mode_of_payment"]
                or bool(a.get("default")) != bool(b["default"])
                or bool(a.get("allow_in_returns")) != bool(b["allow_in_returns"])):
            return False
    return True


def main():
    rep = {"updated": [], "skip": [], "fail": [],
           "group_restored": [], "group_restore_fail": []}

    st, d = get("/api/resource/POS Profile", params={
        "fields": '["name"]', "limit_page_length": 2000, "order_by": "name"})
    names = [x["name"] for x in d.get("data", [])] if st == 200 else []
    print(f"POS Profile: {len(names)}")

    # grup yang ada (utk deteksi link hilang)
    st, d = get("/api/resource/POS Profile Group", params={
        "fields": '["name"]', "limit_page_length": 200})
    groups = {x["name"] for x in d.get("data", [])} if st == 200 else set()
    print(f"POS Profile Group: {sorted(groups)}")

    for nm in names:
        st, d = get("/api/resource/POS Profile/" + urllib.parse.quote(nm))
        if st != 200:
            rep["fail"].append({"profile": nm, "err": f"GET HTTP {st}"})
            continue
        doc = d["data"]
        cur = doc.get("payments") or []
        if same(cur):
            rep["skip"].append(nm)
            continue

        # restorasi grup hilang dulu (kalau ada)
        grp = (doc.get("pos_profile_group") or "").strip()
        if grp and grp not in groups:
            payload = {
                "group_name": grp,
                "pos_schedule_enabled": doc.get("pos_schedule_enabled") or 0,
                "pos_schedule_start": doc.get("pos_schedule_start"),
                "pos_schedule_end": doc.get("pos_schedule_end"),
                "pos_schedule_warning_minutes":
                    doc.get("pos_schedule_warning_minutes") or 0,
                "pos_schedule_enforce_closing":
                    doc.get("pos_schedule_enforce_closing") or 0,
                "profiles": [{"pos_profile": nm,
                              "company": doc.get("company") or ""}],
            }
            st2, d2 = post("/api/resource/POS Profile Group", payload)
            if st2 in (200, 201):
                groups.add(grp)
                rep["group_restored"].append(
                    {"profile": nm, "group": grp,
                     "schedule": f"{doc.get('pos_schedule_start')}-"
                                 f"{doc.get('pos_schedule_end')}"})
                print(f"OK restore grup {grp!r} utk {nm}")
            else:
                rep["group_restore_fail"].append(
                    {"profile": nm, "group": grp, "http": st2,
                     "body": str(d2)[:200]})
                print(f"GAGAL restore grup {grp!r}: HTTP {st2} "
                      f"{str(d2)[:150]}")

        st2, d2 = put("/api/resource/POS Profile/" + urllib.parse.quote(nm),
                      {"payments": CANON})
        if st2 == 200:
            rep["updated"].append(nm)
            print(f"OK payments {nm}")
        else:
            rep["fail"].append({"profile": nm, "http": st2,
                                "body": str(d2)[:250]})
            print(f"GAGAL {nm}: HTTP {st2} {str(d2)[:180]}")
        time.sleep(0.08)

    json.dump(rep, open("experiments/pos_payments_report.json", "w"),
              ensure_ascii=False, indent=1)
    print(f"\nupdated: {len(rep['updated'])} | skip: {len(rep['skip'])} "
          f"| fail: {len(rep['fail'])}")
    print("report: experiments/pos_payments_report.json")


if __name__ == "__main__":
    main()
