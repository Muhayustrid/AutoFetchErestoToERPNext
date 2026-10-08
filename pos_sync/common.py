"""Migrasi dokumen site-lama -> site-baru (Oktober 2026). Lihat docs/06.

Tahap 0: fondasi — klien REST site baru, dump baca site lama, tabel pemetaan.

Env (/tmp/eresto_mig.env, nama saja, jangan tulis nilai ke repo):
  ERPNEXT_URL, ERPNEXT_API_KEY  (site BARU — dari file env yang sudah ada)
  ERPNEXT_OLD_API_KEY           (site LAMA — user simpan sendiri di env-nya)

Kunci idempotency: remarks/description = "ERESTO <nama-lama>".
"""
import json
import time
import urllib.parse

import requests

NEW_BASE = "http://erp.localhost:8081"
OLD_BASE = "http://site-lama.localhost:8082"

TEMP_HTTP_CODES = {429, 500, 502, 503, 504}

# Item lama -> baru (pengecualian saja; kode sama dipakai langsung).
ITEM_MAP = {
    "BB260057": "BB26001",   # lama Botol 250ml; BB260057 baru = bubuk minuman
}

# BOM WO lama -> baru.
BOM_MAP = {
    "BOM-PJ260010-002": "BOM-PJ260010-001",
    "BOM-PJ260014-002": "BOM-PJ260014-001",
    "BOM-PJ260016-001": "BOM-PJ260016-001",  # dibuat di tahap master
}

# Pajak PO lama -> pola baru (per abbr company).
def tax_map(old, abbr):
    if not old:
        return None
    if "Include" in old:
        return f"Purchase Tax (Termasuk Pajak) - {abbr}"
    return f"Purchase Tax - {abbr}"


def wh_map(old):
    """Gudang lama -> baru: akhiran ' - ROPI' menjadi ' - JURI'."""
    if not old:
        return old
    if old.endswith(" - ROPI"):
        return old[:-7] + " - JURI"
    return old


def eresto_key(old_name):
    return f"ERESTO {old_name}"


class ERP:
    """Klien REST tulis ke satu site (pola inject_sales_aggregate.py)."""

    def __init__(self, base, key):
        self.s = requests.Session()
        self.s.headers.update({"Authorization": "token " + key})
        self.base = base.rstrip("/")

    def req(self, method, path, payload=None, params=None, timeout=90):
        last = None
        for a in range(1, 4):
            try:
                r = self.s.request(method, self.base + path, json=payload,
                                   params=params, timeout=timeout)
            except requests.RequestException as e:
                last = str(e)[:200]
                time.sleep(2 ** a)
                continue
            if r.status_code in TEMP_HTTP_CODES:
                last = f"HTTP {r.status_code}"
                time.sleep(2 ** a)
                continue
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, {"_raw": r.text[:1000]}
        return -1, {"error": f"gagal 3x: {last}"}

    def get(self, path, params=None):
        return self.req("GET", path, params=params, timeout=60)

    def post(self, doctype, payload):
        return self.req("POST", "/api/resource/" + urllib.parse.quote(doctype),
                        payload)

    def put(self, doctype, name, payload):
        return self.req("PUT", "/api/resource/" + urllib.parse.quote(doctype)
                        + "/" + urllib.parse.quote(name), payload)

    def delete(self, doctype, name):
        return self.req("DELETE", "/api/resource/"
                        + urllib.parse.quote(doctype) + "/"
                        + urllib.parse.quote(name))

    def rename(self, doctype, old_name, new_name):
        """frappe.client.rename_doc — harus form-encoded (bukan JSON)."""
        last = None
        for a in range(1, 4):
            try:
                r = self.s.post(
                    self.base + "/api/method/frappe.client.rename_doc",
                    data={"doctype": doctype, "old_name": old_name,
                          "new_name": new_name, "merge": 0}, timeout=90)
            except requests.RequestException as e:
                last = str(e)[:200]
                time.sleep(2 ** a)
                continue
            if r.status_code in TEMP_HTTP_CODES:
                last = f"HTTP {r.status_code}"
                time.sleep(2 ** a)
                continue
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, {"_raw": r.text[:1000]}
        return -1, {"error": f"gagal 3x: {last}"}

    def find_by_remark(self, doctype, remark_field, key):
        """Cek idempotency: dokumen dengan remarks/description = key."""
        st, d = self.get("/api/resource/" + urllib.parse.quote(doctype), {
            "filters": json.dumps([[remark_field, "=", key]]),
            "fields": '["name","docstatus"]', "limit_page_length": 5})
        return d.get("data", []) if st == 200 else []

    def submit(self, doctype, name):
        return self.put(doctype, name, {"docstatus": 1})

    def cancel(self, doctype, name):
        return self.put(doctype, name, {"docstatus": 2})
