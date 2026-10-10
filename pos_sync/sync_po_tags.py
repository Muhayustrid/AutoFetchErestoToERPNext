"""Sinkronisasi Tag Purchase Order PT. JUARA ROTI INDONESIA: LAMA -> BARU.

Mengambil semua tag dari Tag Link / _user_tags di site lama untuk Purchase Order
perusahaan PT. JUARA ROTI INDONESIA, kemudian memasangkannya ke Purchase Order
yang sesuai di site baru via frappe.desk.doctype.tag.tag.add_tag.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env  # noqa: E402

OLD_BASE = "https://rotiropi.j.frappe.cloud"
MIG_ENV = "/tmp/eresto_mig.env"
PROD_ENV = "/tmp/eresto_prod.env"
COMPANY = "PT. JUARA ROTI INDONESIA"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="eksekusi penambahan tag")
    args = ap.parse_args()

    mig_env = load_env(MIG_ENV)
    prod_env = load_env(PROD_ENV)

    c_lama = Client(OLD_BASE, mig_env["ERPNEXT_OLD_CLOUD_API_KEY"], "lama")
    c_baru = Client(prod_env["ERPNEXT_URL"], prod_env["ERPNEXT_API_KEY"], "baru", pause=0.05)

    print(f"[1/4] Mengambil daftar Tag Link untuk Purchase Order di site LAMA...")
    links_lama = c_lama.list_all("Tag Link", ["name", "document_type", "document_name", "tag", "title"],
                                 filters=[["document_type", "=", "Purchase Order"]])
    print(f"      Total Tag Link Purchase Order di LAMA: {len(links_lama)}")

    print(f"[2/4] Mengambil Purchase Order PT. JURI di site BARU...")
    pos_baru = {r["name"]: r for r in c_baru.list_all("Purchase Order", ["name", "supplier", "status"],
                                                       filters=[["company", "=", COMPANY]])}
    print(f"      Total PO JURI di BARU: {len(pos_baru)}")

    # Pasangkan PO yang ada di site BARU
    matched = []
    skipped_no_po = []
    for l in links_lama:
        po_name = l["document_name"]
        tag = l["tag"]
        if po_name in pos_baru:
            matched.append((po_name, tag, pos_baru[po_name].get("supplier")))
        else:
            skipped_no_po.append((po_name, tag))

    print(f"[3/4] Ditemukan {len(matched)} PO yang memiliki tag dan ada di site BARU.")
    print(f"      ({len(skipped_no_po)} PO tidak ada di site BARU karena di luar rentang migrasi)")

    if not args.execute:
        print("\n--- RENCANA SINKRONISASI (DRY RUN) ---")
        for po_name, tag, sup in matched:
            print(f"  {po_name} ({sup}): '{tag}'")
        print("\nJalankan dengan flag --execute untuk memasang tag.")
        return

    print("\n--- EKSEKUSI PENAMBAHAN TAG KE SITE BARU ---")
    success = 0
    failed = 0
    for po_name, tag, sup in matched:
        st, res = c_baru.req("POST", "/api/method/frappe.desk.doctype.tag.tag.add_tag", {
            "tag": tag,
            "dt": "Purchase Order",
            "dn": po_name
        })
        if st == 200:
            print(f"  [OK] {po_name} ({sup}) -> '{tag}'")
            success += 1
        else:
            print(f"  [GAGAL {st}] {po_name} -> {res}")
            failed += 1
        time.sleep(0.05)

    print(f"\n[4/4] Selesai: {success} berhasil, {failed} gagal.")

    # Verifikasi akhir
    print("\n--- VERIFIKASI AKHIR DI SITE BARU ---")
    verify_links = c_baru.list_all("Tag Link", ["document_name", "tag"],
                                   filters=[["document_type", "=", "Purchase Order"]])
    print(f"Total Tag Link Purchase Order di site BARU sekarang: {len(verify_links)}")
    for vl in verify_links[:10]:
        print(f"  {vl['document_name']} -> {vl['tag']}")


if __name__ == "__main__":
    main()
