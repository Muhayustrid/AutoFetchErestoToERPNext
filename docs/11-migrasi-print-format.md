# 11 — Migrasi Print Format: Header Global + Konten Per Format

> **Status: SELESAI dieksekusi 2026-10-07** (site baru `ropierpnext.frappe.cloud`;
> lokal `erp.localhost:8081` sudah lebih dulu). Sumber: `rotiropi.j.frappe.cloud`.
> Script: `pos_sync/migrate_print_formats.py`; artefak: `pos_sync/pf_src/`,
> `pf_dump/`, `pf_build/`, `pf_reports/`.
> Keputusan user 2026-10-07: **hanya format yang jadi default di site lama** yang
> dibawa (10 format); POS Next Receipt / POS Next EOD Report jangan disentuh.

## 1. Hasil akhir

- **10 format default site lama** dimigrasi ke site baru; 7 di antaranya
  di-*split* (header dilepas, lihat §3), 3 disalin apa adanya.
- **Satu header global** hidup di Letter Head yang sudah dipakai semua dokumen
  (`Company Letterhead - Grey`) — isinya diganti dengan header + meta
  kondisional per DocType (§3), tetap `is_default = 1`.
- **10 `default_print_format`** di site baru kini menunjuk format migrasi
  (PO New, Purchase Receipt Format, Purchase Invoice Format, Sales Order
  Format, Delivery Note Format, Material Request Format, Stock Entry Template,
  Format Print Pick List, Batch QRCode Produksi, POS Invoice Format).
- Verifikasi: render parity **10/10 OK** di lokal & cloud; PDF dokumen nyata
  **6/6 OK** lokal (PO/PR/SO/DN/SE/POS Invoice) dan **5/5 OK** cloud
  (PI/SO/DN/Pick List/Batch di-skip: belum ada dokumennya di cloud).
  Laporan: `pos_sync/pf_reports/Migrasi_Print_Format_{local,cloud}.xlsx`.
- POS Next Receipt & POS Next EOD Report **tidak disentuh** (versi app lebih
  baru: logo struk + alokasi paket). POSNext tetap render struk tanpa letter
  head karena template-nya sendiri tidak memanggil `{{ letter_head }}`.

## 2. Temuan kunci (dump + uji + bedah source Frappe v16)

- Semua format A4 site lama menggabung blok `HEADER + TITLE + META` + CSS-nya
  di tiap file (diduplikasi dengan prefix beda: `po-`, `mr-`, `ste-`, …).
- Letter Head dirender server sebagai **Jinja dengan context `{"doc": doc.as_dict()}`**
  + global `frappe.*` → kondisional per `doc.doctype` dan lookup Company
  bisa diandalkan. **Format custom (Jinja) tidak otomatis menampilkan Letter
  Head** — harus memanggil `{{ letter_head }}`; format seri `with Item Image`
  memakai macro `add_header` bawaan yang otomatis memuatnya.
- **Dokumen existing mem-pin `letter_head` eksplisit** (`Company Letterhead -
  Grey`): PO/PR/SE/MR/POS Invoice di lokal (38k+ POS Invoice) & cloud (ratusan
  dokumen). Membuat LH baru bernama lain = tidak muncul di dokumen itu;
  **mengganti konten LH yang sudah dipin** = header baru langsung tampil di
  semua dokumen tanpa menyentuh satu dokumen pun. Karena itu LH lama
  `Company Letterhead - Grey` yang diisi ulang (nama historis dipertahankan).
- `Company Testing` di site lama = embrio header global (baru untuk PO, tampil
  hanya via format standar) — arah desain ini melanjutkannya ke semua DocType.
- PDF: `download_pdf` cloud OK. wkhtmltopdf 0.12.6.1. Logo company `private`
  ternyata **bisa** dirender ke PDF (terbukti di lokal & cloud).
- Kondisi khusus: `Format Print Pick List` mengulang header per halaman
  (24 baris + nomor x/y) → tetap self-contained; `Batch QRCode Produksi`
  (label 50×30mm) & `POS Invoice Format` (struk thermal) tetap self-contained.
- Custom field yang dipakai format lama tapi tidak ada di site baru
  (`custom_note` PO, `custom_nama_customer` POS Invoice) aman: template punya
  fallback `or ""` / `or customer_name` → tidak di-drop, tidak error.

## 3. Arsitektur akhir

```
Letter Head "Company Letterhead - Grey" (is_default=1) — KONTEN BARU
├─ kiri : logo company_logo + nama + Phone/Email/WWW (frappe.db.get_value Company)
└─ kanan: judul + meta rows KONDISIONAL per doc.doctype
          (PO 6 row, PR/PI 8-9 row incl. Against PO/PR, SO 6, DN 6, MR 5,
           STE 4, SI 10 incl. Against SO/DN) — fallback generik: No. + Date.
          Row kosong otomatis hilang (loop `{% if value %}`).
Konten format (site baru) = body lama TANPA blok header + `{{ letter_head }}`
├─ Purchase Order New / Purchase Receipt Format / Purchase Invoice Format /
│  Sales Order Format / Delivery Note Format / Material Request Format /
│  Stock Entry Template  → split (15 rule CSS header + blok header + var set
│  dibuang; sisa body + CSS body identik byte-per-byte dgn render lama,
│  diverifikasi via diff HTML ternormalisasi)
├─ Format Print Pick List → verbatim (header lokal per halaman dipertahankan)
├─ Batch QRCode Produksi  → verbatim
└─ POS Invoice Format     → verbatim
```

Mapping detail baris meta per DocType: lihat `pos_sync/pf_src/letterhead.html`
(sisa persis dari format lama; judul = nama dokumen).

## 4. Cara pakai / rerun

```bash
python3 pos_sync/migrate_print_formats.py --dump   --stage local|cloud
python3 pos_sync/migrate_print_formats.py --build  --stage local|cloud
python3 pos_sync/migrate_print_formats.py --push   --stage local|cloud [--dry-run]
python3 pos_sync/migrate_print_formats.py --verify --stage local|cloud
python3 pos_sync/migrate_print_formats.py --revert --stage local|cloud   # rollback
```

Env (nama saja): `/tmp/eresto_mig.env` (lokal: `ERPNEXT_URL`,
`ERPNEXT_API_KEY`, `ERPNEXT_OLD_API_KEY` 8082), `/tmp/eresto_print_env`
(cloud lama: `ERPNEXT_OLD_CLOUD_URL`, `ERPNEXT_OLD_CLOUD_API_KEY`),
`/tmp/eresto_prod.env` (cloud baru). Semua idempoten (upsert cek live state);
`--dump` menyimpan state sebelum push untuk `--revert`.

Edit header = ubah `pos_sync/pf_src/letterhead.html` → `--build` → `--push`.

## 5. Jebakan lokal (dev-only, bukan isu produksi)

- **wkhtmltopdf dalam container tidak bisa resolve `erp.localhost`** (Qt tak
  pakai resolver Docker) dan aset `/assets/frappe/dist/*` hanya disajikan
  container frontend (nginx :8080), bukan gunicorn (:8000).
  Solusi dev yang dipakai: `site_config.json` lokal `host_name =
  "erp.localhost:8080"` + entry `/etc/hosts` di container backend:
  `172.18.0.10 erp.localhost` (IP container frontend).
  **/etc/hosts hilang saat container restart** → PDF lokal gagal lagi sampai
  entry ditambahkan ulang (IP frontend bisa berubah, cek
  `docker inspect frappe-frontend-1`).
- Di cloud tidak ada masalah ini (wkhtmltopdf satu host dengan server).

## 6. Keputusan yang diminta user (semua TERJAWAB oleh pesan 2026-10-07)

1. Scope → **hanya 10 format default** (sisanya tidak dibawa). ✔
2. Repointing default → dilakukan (10 setter). ✔
3. Sales Invoice & Stock Reconciliation → tidak jadi default di site lama →
   tidak diambil (SI tetap `Sales Invoice with Item Image`); Stock
   Reconciliation tanpa format custom (standar). ✔
4. Letter Head default → dipakai LH lama yang sudah default & sudah dipin
   dokumen (`Company Letterhead - Grey`), bukan membuat LH baru. ✔
5. Nama LH → tidak relevan lagi (pakai yang lama); file sumber tetap
   `pf_src/letterhead.html`. ✔
6. `custom_note`/`custom_nama_customer` → dibiarkan dengan fallback template
   (tidak perlu buat field). ✔

## 7. Risiko / catatan operasional

- Format seri `with Item Image` (Quotation, RFQ, Sales Invoice) ikut memakai
  Letter Head global (macro add_header) → print standar mereka kini menampilkan
  header baru + fallback generik (judul + No. + Date). Diterima sebagai efek
  desain (header global), bukan bug.
- Rollback penuh tersedia: `--revert --stage cloud` (konten LH Grey, 10 format,
  setter dipulihkan dari dump).
