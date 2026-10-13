"""Bersama: injeksi site lokal (erp.localhost:8081) -> PRODUCTION
(ropierpnext.frappe.cloud). Pola docs/07-injeksi-production.

Kredensial hanya di env file (jangan tulis ke repo):
  /tmp/eresto_mig.env  (site LOKAL: ERPNEXT_URL, ERPNEXT_API_KEY)
  /tmp/eresto_prod.env (site PROD : ERPNEXT_URL, ERPNEXT_API_KEY)

Idempotency: marker `ERESTO <nama-site-lama>` disalin apa adanya dari lokal;
rerun tidak menduplikasi.
"""
import json
import os
import time
import urllib.parse

import requests

LOCAL_ENV = "/tmp/eresto_mig.env"
PROD_ENV = "/tmp/eresto_prod.env"
SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prod_src")

JURI = "PT. JUARA ROTI INDONESIA"
TEMP_HTTP = {429, 500, 502, 503, 504}
WRITE_PAUSE = 0.04  # jeda kecil antar tulis ke frappe.cloud


def load_env(path):
    d = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("ERPNEXT_URL", "ERPNEXT_API_KEY"):
        if not d.get(k):
            raise SystemExit(f"env {k} kosong di {path}")
    return d


class Client:
    def __init__(self, base, key, label="", pause=0.0):
        self.s = requests.Session()
        self.s.headers.update({"Authorization": "token " + key})
        self.base = base.rstrip("/")
        self.label = label
        self.pause = pause

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
            if r.status_code in TEMP_HTTP:
                last = f"HTTP {r.status_code}"
                time.sleep(2 ** a)
                continue
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, {"_raw": r.text[:1000]}
        return -1, {"error": f"gagal 3x: {last}"}

    def get(self, path, params=None, timeout=90):
        return self.req("GET", path, params=params, timeout=timeout)

    def post(self, doctype, payload):
        st, d = self.req("POST", "/api/resource/" + urllib.parse.quote(doctype),
                         payload)
        if self.pause:
            time.sleep(self.pause)
        return st, d

    def put(self, doctype, name, payload):
        st, d = self.req("PUT", "/api/resource/" + urllib.parse.quote(doctype)
                         + "/" + urllib.parse.quote(name), payload)
        if self.pause:
            time.sleep(self.pause)
        return st, d

    def delete(self, doctype, name):
        return self.req("DELETE", "/api/resource/"
                        + urllib.parse.quote(doctype) + "/"
                        + urllib.parse.quote(name))

    def submit(self, doctype, name):
        return self.put(doctype, name, {"docstatus": 1})

    def cancel(self, doctype, name):
        return self.put(doctype, name, {"docstatus": 2})

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
            if r.status_code in TEMP_HTTP:
                last = f"HTTP {r.status_code}"
                time.sleep(2 ** a)
                continue
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, {"_raw": r.text[:1000]}
        return -1, {"error": f"gagal 3x: {last}"}

    def find(self, doctype, field, value, fields=("name", "docstatus")):
        st, d = self.get("/api/resource/" + urllib.parse.quote(doctype), {
            "filters": json.dumps([[field, "=", value]]),
            "fields": json.dumps(list(fields)), "limit_page_length": 5})
        return d.get("data", []) if st == 200 else []

    def list_all(self, doctype, fields, filters=None, order=None):
        out, start = [], 0
        while True:
            params = {"fields": json.dumps(fields), "limit_page_length": 500,
                      "limit_start": start}
            if filters:
                params["filters"] = json.dumps(filters)
            if order:
                params["order_by"] = order
            st, d = self.get("/api/resource/" + urllib.parse.quote(doctype),
                             params)
            rows = d.get("data", []) if st == 200 else []
            if not rows:
                break
            out += rows
            start += len(rows)
            if len(rows) < 500:
                break
        return out


def fetch_meta(client, doctypes):
    """Meta field per doctype dari site tujuan -> {dt: [fieldnames]}."""
    out = {}
    for dt in doctypes:
        st, d = client.get("/api/resource/DocType/" + urllib.parse.quote(dt),
                           {"limit_page_length": 0})
        if st != 200:
            raise SystemExit(f"meta {dt} gagal: HTTP {st} {str(d)[:200]}")
        out[dt] = [f["fieldname"] for f in d["data"].get("fields", [])]
    return out


# ============================================================
# ATURAN OLESAN PASTRY (keputusan user 2026-10-12)
# ============================================================
# PO ke supplier PT. JUARA ROTI INDONESIA bertanggal > 2026-10-08 memakai
# BB26012 'Olesan Pastry (250 g)'; tanggal <= 2026-10-08 tetap BB260046
# 'Olesan Pastry' (bulk, historis). Lihat KNOWLEDGE.md §5 + AGENTS.md.
OLESAN_PASTRY_CUTOFF = "2026-10-08"   # PO_DATE > cutoff -> BB26012
OLESAN_PASTRY_BULK = "BB260046"       # Olesan Pastry (bulk, kg/ctn)
OLESAN_PASTRY_BOTOL = "BB26012"       # Olesan Pastry (250 g), UOM Botol


def olesan_pastry_item(po_date, default=OLESAN_PASTRY_BULK):
    """Item code Olesan Pastry sesuai tanggal PO (YYYY-MM-DD).

    > 2026-10-08 -> BB26012; <= 2026-10-08 -> BB260046.
    po_date None/kosong -> `default`.
    """
    d = "" if po_date is None else str(po_date)[:10]
    if d and d > OLESAN_PASTRY_CUTOFF:
        return OLESAN_PASTRY_BOTOL
    return default


# field bawaan server — jangan dikirim balik saat POST
SERVER_FIELDS = {
    "name", "owner", "creation", "modified", "modified_by", "idx",
    "docstatus", "doctype", "amended_from",
    "_user_tags", "_comments", "_assign", "_liked_by", "_seen",
    "parent", "parentfield", "parenttype",
}


def pick(doc, allowed, drop=()):
    """Buang field server + field yang tidak ada di meta site tujuan."""
    allow = set(allowed)
    out = {}
    for k, v in doc.items():
        if k in SERVER_FIELDS or k in drop or k.startswith("_"):
            continue
        if k not in allow:
            continue
        out[k] = v
    return out


def pick_rows(rows, allowed, drop=()):
    return [pick(r, allowed, drop) for r in rows or []]


STATE_PATH = os.path.join(SRC_DIR, "state.json")


def load_state():
    try:
        return json.load(open(STATE_PATH))
    except (OSError, ValueError):
        return {}


def save_state(st):
    os.makedirs(SRC_DIR, exist_ok=True)
    json.dump(st, open(STATE_PATH, "w"), indent=1, default=str)


def jload(name):
    return json.load(open(os.path.join(SRC_DIR, name)))
