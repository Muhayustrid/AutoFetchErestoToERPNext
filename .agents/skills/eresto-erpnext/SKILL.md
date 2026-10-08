---
name: eresto-erpnext
description: Ropi's POS system map and hard rules — eResto (ropi.eresto.id) API/UI routes, ERPNext baru (ropierpnext.frappe.cloud) vs lama (rotiropi.j.frappe.cloud), SKU mapping, POS Invoice / Work Order / PO-SO-DN migration, stock chain dough→matang→bundle. Use whenever the user mentions eResto, ERPNext Ropi, ropi.eresto.id, ropierpnext, rotiropi.j, AutoFetchErestoToERPNext, "inject POS invoice", "migrasi PO/WO/SO", SKU mapping, POSNext, or asks to fetch Ropi sales/production/purchase data — even if they don't name the repo.
---

# eResto ↔ ERPNext (Ropi)

Baca berurutan sebelum menyentuh API apa pun:

1. `KNOWLEDGE.md` (root repo) — peta sistem: URL, endpoint, aturan bisnis, jebakan API.
2. `AGENTS.md` — aturan tetap proyek (style, constraint, alur).
3. `PROJECT_STATE.md` — status terkini: apa yang sudah selesai, task aktif, known issues.

Dokumentasi topik ada di `docs/01..11` (indeks di `KNOWLEDGE.md` §8).
Kode: `pos_sync/` (migrasi & injeksi, idempoten) dan `experiments/` (setup + probe;
`test_*` bukan produksi — jangan di-import).

## Aturan keras (jangan dilanggar)

- **eResto READ-ONLY** — hanya GET. Jangan POST/PUT/DELETE ke eResto.
- Rahasia hanya dari env (`ERESTO_TOKEN`, `ERESTO_EMAIL`, `ERESTO_USER_ID`,
  `ERPNEXT_URL`, `ERPNEXT_API_KEY`); jangan hardcode/print/commit. File nilai
  biasanya di `/tmp/eresto_mig.env` & `/tmp/eresto_prod.env` (volatile).
- Rerun wajib idempoten: marker `remarks = "ERESTO <order_no>"`,
  `cheque_no = "ERESTO-<branch>-<date>"`, atau `SKIP_EXISTS` by name/ID lama.
  PO/SO/DN tidak punya field `remarks` — kunci idempotensi di `title`.
- Mapping SKU by **`product_sku`**, bukan nama. Jangan menebak Item Code —
  sumber kebenaran `experiments/sku_to_item_code.csv` & `stok_sku_to_item.csv`.
- Rate limit API: maks 10 worker, 3 retry backoff (429/5xx), timeout 90s.
- Jangan menyentuh `Backup SIte Production/`.
- Setiap akhir sesi kerja: update `PROJECT_STATE.md`.

## Peta cepat

| Butuh | Tempat |
|---|---|
| URL & endpoint eResto (API v3/v2 + route Manager) | `KNOWLEDGE.md` §2–4 |
| Jebakan Frappe/ERPNext (rename_doc, posting_date, mlb=0, dst) | `KNOWLEDGE.md` §6 |
| Rantai produk dough→matang→bundle + resep yield | `docs/05-alur-dough-ke-bundle.md` |
| Mapping SKU/outlet/payment/void/refund | `docs/02-erpnext-mapping.md` |
| Alur kasir POSNext | `docs/04-posnext-cara-kerja-penjualan.md` |
| Cara menjalankan lane migrasi (flag CLI) | `PROJECT_STATE.md` §Cara jalanin |
