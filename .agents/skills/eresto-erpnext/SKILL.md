---
name: eresto-erpnext
description: Ropi's POS system map and hard rules — eResto (ropi.eresto.id) API/UI routes, ERPNext baru (ropierpnext.frappe.cloud) vs lama (rotiropi.j.frappe.cloud), SKU mapping, POS Invoice / Work Order / PO-SO-DN-FRC migration, MR/PO LAMA→BARU, Goods In Transit end-transit, stock chain dough→matang→bundle, RECO/opening stock, stock minus policy. Use whenever the user mentions eResto, ERPNext Ropi, ropi.eresto.id, ropierpnext, rotiropi.j, AutoFetchErestoToERPNext, "inject POS invoice", "migrasi PO/WO/SO/PI/SO FRC", "tarik PO eResto", "input PO ke erpnext", duplikat PO, Olesan Pastry, SKU mapping, POSNext, Stock Reconciliation/RECO, "stock minus", Goodie Bag, "goods in transit", "end transit", "material request", or asks to fetch Ropi sales/production/purchase data — even if they don't name the repo.
---

# eResto ↔ ERPNext (Ropi)

Baca berurutan sebelum menyentuh API apa pun:

1. `KNOWLEDGE.md` (root repo) — peta sistem: URL, endpoint, aturan bisnis, jebakan API.
2. `AGENTS.md` — aturan tetap proyek (style, constraint, alur).
3. `PROJECT_STATE.md` — status terkini: apa yang sudah selesai, task aktif, known issues.

Dokumentasi topik ada di `docs/01..12` (indeks di `KNOWLEDGE.md` §8).
Kode: `pos_sync/` (migrasi & injeksi, idempoten) dan `experiments/` (setup + probe;
`test_*` bukan produksi — jangan di-import).

## Aturan keras (jangan dilanggar)

- **Cek TARGET SITE sebelum menulis apa pun.** Tiga env mudah tertukar:
  `/tmp/eresto_mig.env` → `ERPNEXT_URL` biasanya **LOKAL**
  (`http://127.0.0.1:8081`); `/tmp/eresto_prod.env` → **CLOUD**
  (`https://ropierpnext.frappe.cloud`). Permintaan "site baru / produksi" =
  **CLOUD**. Sebelum eksekusi **cetak `client.base`**; sesudahnya verifikasi
  di site yang dipegang user. (Kasus nyata 2026-10-12: perbaikan tertulis ke
  lokal → user "kok ga ada perubahan".)
- **eResto READ-ONLY** — hanya GET. Jangan POST/PUT/DELETE ke eResto.
- Rahasia hanya dari env (`ERESTO_TOKEN`, `ERESTO_EMAIL`, `ERESTO_USER_ID`,
  `ERPNEXT_URL`, `ERPNEXT_API_KEY`); jangan hardcode/print/commit. File nilai
  biasanya di `/tmp/eresto_mig.env` & `/tmp/eresto_prod.env` (volatile).
- **Jangan pernah kirim ke site yang salah.** Kunci API cloud baru TIDAK
  berlaku di site lama dan sebaliknya. Kunci dari chat = perlu rotasi (catat).
- Rerun wajib idempoten: marker `remarks = "ERESTO <order_no>"`,
  `cheque_no = "ERESTO-<branch>-<date>"`, atau `SKIP_EXISTS` by name/ID lama.
  PO/SO/DN tidak punya field `remarks` — kunci idempotensi di `title`.
- Mapping SKU by **`product_sku`**, bukan nama. Jangan menebak Item Code —
  sumber kebenaran `experiments/sku_to_item_code.csv` & `stok_sku_to_item.csv`;
  bila padanan tak ada, **cari bukti** (PO identik di site LAMA) atau
  **keluarkan & catat** di sheet `Skipped` — jangan tebak.
- Rate limit API: maks 10 worker, 3 retry backoff (429/5xx), timeout 90s.
- Jangan menyentuh `Backup SIte Production/`.
- **Audit read-only dulu, tanya user sebelum aksi destruktif/ambigu.** Sebelum
  hapus/cancel/ubah dokumen milik pihak lain: tarik & bandingkan dulu, tunjukkan
  temuan, minta konfirmasi (mis. "PO mana yang dipertahankan"). Jangan tebak
  maksud user; banyak kasus nyata ambigu (duplikat vs PO beda outlet, item tanpa
  padanan, draft vs submit).
- Setiap akhir sesi kerja: update `PROJECT_STATE.md`.

## Keputusan user yang dikunci (2026-10-09/10) — jangan langgar

- **Stock minus DILARANG**: `Stock Settings.allow_negative_stock = 0`
  permanen di cloud baru. Jangan nyalakan tanpa izin user; bila terpaksa
  utk backfill, hanya sementara + restore di `finally`. Kekurangan stok
  = catat pergerakan riil (repack/receipt/transfer), bukan buka izin minus.
- **PI site LAMA = trial saja, JANGAN dimigrasi** (audit 2026-10-09:
  5 PI lama, 0 di BARU). Faktur riil = PI di site BARU dari eResto.
- **Dokumen cancelled DIHAPUS, bukan dibiarkan menumpuk** — pakai
  `pos_sync/bersih_dokumen_cancelled.py` (dry-run default, `--execute`,
  guard backup + link-check + ledger sweep).
- **Duplikat DIHAPUS, bukan dibiarkan** (keputusan user 2026-10-12):
  audit lalu hapus sisi Draft (guard ds=0 + cek rujukan PR/PI + backup JSON +
  verifikasi 404; lihat `pos_sync/hapus_po_juri_duplikat.py`). **Kunci audit
  duplikat = company + supplier + tanggal + signature item (qty,rate)** —
  BUKAN total saja (banyak PO beda outlet nominalnya kembar → bukan duplikat).
- **Olesan Pastry (keputusan user 2026-10-12):** PO ke **PT. JUARA ROTI
  INDONESIA** bertanggal **> 2026-10-08** → item `BB26012` "Olesan Pastry
  (250 g)", BUKAN `BB260046`. PO ≤ 2026-10-08 tetap `BB260046`. SKU eResto
  `BB0174`/`BB0352` ikut aturan. Helper: `prod_common.olesan_pastry_item(po_date)`.
- **FRC (outlet franchise):** PO outlet FRC → **Sales Order** JURI → Customer
  FRC (group `Outlet Franchise`), `set_warehouse` = `Gudang Barang Jadi -
  JURI`, TANPA `inter_company_order_reference`; default **DRAFT**
  (`pos_sync/migrate_so_frc_9_12_okt.py`). Cek dulu SO existing per customer
  (jangan bikin dobel).
- **RECO kanonik**: opening = `1171.000 Pembukaan sementara`, satu dokumen
  per gudang @ 30 Sep 23:00; penyesuaian operasional = `5110.020 Penyesuaian
  Stock`. Cancel RECO v16 menggeser trail — jangan cancel/recreate asal;
  zero-out di atas minus → substitusi Material Receipt.
- **Warehouse testing DIHAPUS di kedua site** (LAMA `- ROPI` & BARU
  `- JURI`) — jangan dibuat ulang di script migrasi/opening.
- **Goodie Bag = `PEL260072`** (legacy `PG001` di-merge & dihapus;
  jangan pakai `PG001` lagi).
- **FRC tetap FRC di jendela mana pun** (2026-10-13): company FRC tidak
  di-onboard; PO outlet FRC → Sales Order JURI → Customer FRC, DRAFT, via
  `migrate_so_frc_9_12_okt.py --only <PO...>`.
- **Keputusan mapping user 2026-10-13** (SKU keperluan outlet, sudah di
  ITEM_MAP `migrate_po_juri_9_12_okt.py`): BB0263→ATK260041, BB0131→PEL260038,
  BB0136→PEL260041, BB0082 Lakban Besar→BHP260023, BB0087 Lakban
  Kecil→BHP260020 (Selotip), BB0230 Sticker Label→ATK260038,
  BB0267 Tinta Isi Ulang→BHP260033.

## Migrasi PO dari eResto — dua lane + anti-duplikat

eResto `/v2/purchases`: flag benar = **`internal_supplier` (boolean di root)**,
BUKAN `supplier.is_internal`. Jendela tarik = union `date[]` DAN `created_at[]`.

| Lane | Siapa | Company | Supplier | Warehouse | Price List |
|---|---|---|---|---|---|
| Internal gudang | PO outlet → PT. JURI | divisi outlet pemesan | `PT. JUARA ROTI INDONESIA` | `Stores - <ABBR>` | `Harga Outlet` |
| Eksternal | JURI beli supplier luar | `PT. JUARA ROTI INDONESIA` | nama supplier eResto | gudang JURI padanan divisi | `Standard Buying` |

Lane eksternal wajib **dedup by ISI** sebelum POST (tim purchasing sering input
manual dgn ID ERPNext sendiri, mis. `PO-JURI-261009xxx`, supplier dipecah per
toko Shopee). Skrip: `pos_sync/migrate_po_juri_eksternal_9_12_okt.py`
(total ±Rp100 + tanggal ±1 hari + multiset qty, alias supplier).

## Jebakan wajib ingat (dari sesi terakhir)

- **Trap baca API Frappe:** `client.get()` mengembalikan body UTUH; field
  anak ada di `body["data"]` (mis. `grand_total`, `items`, `companies`
  supplier). Salah baca → UOM/CF `None` & verifikasi "Rp 0". **Selalu unwrap
  `body.get("data", body)`.**
- **`rename_doc` wajib form-encoded** (bukan JSON) → kalau salah, server 417.
- **Status eResto → docstatus:** `processing`/`completed` → submit; `pending`
  → draft; `rejected`/`canceled` → **skip** (keputusan user 2026-10-12).
- **Klaim dari pekerjaan paralel:** operator lain bisa mengubah dokumen di
  tengah sesi (kasus: 3 draft jadi submitted; batch SO dibuat 10:05–11:11).
  **Rekonsiliasi live sebelum & sesudah**, jangan asumsi kondisi awal.
  Kasus lain (13 Okt): company yang diasumsikan "belum ada" ternyata SUDAH ADA
  dibuat pihak lain sejak 29 Sep (abbr beda dari rencana) — **selalu GET dulu
  sebelum membuat**, dan pakai abbr existing, jangan paksa abbr baru.

## Jebakan nama company eResto vs ERPNext (kasus 2026-10-13)

Nama divisi eResto TIDAK SELALU identik dengan nama Company ERPNext. Lookup
exact-match akan menyalahkan company "belum ada" padahal ada:

- `RSUD PROF H MUHAMMAD YAMIN SH` (eResto) vs `RSUD PROF H MUHAMMADIYAH
  YAMIN SH` (ERPNext) — beda ejaan, bukan cuma kapital.
- `RSUD HJ. ANNA LASMANAH BANJARNEGARA` (eResto) vs `RSUD Hj. ANNA LASMANAH
  BANJARNEGARA` (ERPNext) — beda kapitalisasi saja.

Perlakuan wajib:
1. Resolver **case-insensitive** (`_by_lower`) + **alias eksplisit** di skrip
   migrasi (lihat `resolve_company()` di `migrate_po_juri_9_12_okt.py`).
2. Guard prasyarat & `payload["company"]` memakai nama ERPNext aktual hasil
   resolve, bukan nama mentah eResto.
3. Bila "lower match" juga gagal, bandingkan per karakter (`repr`/`zip`) —
   bisa beda ejaan sungguhan (MUHAMMAD vs MUHAMMADIYAH), bukan sekadar case.

## Jebakan PUT child-table = lost-update race (kasus 2026-10-13)

Menambah 1 izin company ke supplier dengan pola
`GET companies → append → PUT full list` itu **tidak atomik**: PUT beruntun
utk company berbeda bisa saling menimpa (lost update) dan menghasilkan
**baris child-table DUPLIKAT** (kasus nyata: 2 baris `Allowed To Transact With`
kembar di supplier JURI, total 178 padahal harus 176).

- Sesudah PUT child-table, **verifikasi ulang**: bandingkan total vs unik by
  key (`company`); kalau ada duplikat, PUT ulang dengan daftar dedup
  (`seen` by key) — idempoten dan aman diulang.
- Baca balik dengan GET penuh (tanpa filter `fields` sempit) agar bentuk
  child rows terlihat (tiap row punya `name`, `company`, `parent`, ...).
- Onboarding beruntun utk banyak company: re-GET fresh sebelum tiap PUT,
  jangan cache daftar companies dari awal loop.

## Onboarding company baru di site BARU (pola terbukti)

`pos_sync/onboard_company_rs_12okt.py` (pola Selogiri, idempoten, dry-run
default). Checklist idempoten per company:

1. **Company** — GET dulu; kalau sudah ada pakai `abbr` existing (JANGAN
   gagalkan karena abbr rencana beda). Kalau baru: POST anak `OUTLET`, COA
   `Existing Company = OUTLET`, lalu wajib cek master turunan:
   `Stores - <ABBR>`, `4210.000 - HPP Pembelian - <ABBR>`, `Main - <ABBR>`
   (kurang = gagalkan keras, jangan POST PO tanpa itu).
2. **Fiscal Year 2026** — append company ke `companies`.
3. **Allowed To Transact With** di supplier JURI (lihat jebakan PUT di atas).
4. **Customer internal** (`is_internal_customer=1`,
   `represents_company=<company>`, companies `[JURI]`).
5. Baru jalankan lane PO internal; company FRC **tidak** di-onboard —
   PO-nya masuk lane SO FRC (keputusan user 2026-10-13).

## Mapping SKU tanpa bukti: alur keputusan (kasus 2026-10-13)

Saat banyak SKU keperluan outlet belum termapping (kasus: 28 SKU di PO 12 Okt
— sabun, lakban, kuas, ATK, dll.):

1. Sumber bukti berurutan: `experiments/stok_sku_to_item.csv` (COCOK) →
   nama item master BARU exact-match → padanan nama jelas (mis. `Kuas Oles
   Loyang 1,5'` → `Kuas Oles Loyang (1,5 inch)`) → **tanya user** utk sisanya.
2. Pencarian nama di BARU: filter API `like` sering gagal utk varian ejaan —
   dump semua Item (`limit_page_length: 0`) lalu filter substring lowercase
   lokal; jangan berhenti di hasil kosong API `like`.
3. Item ambigu (banyak varian, mis. 3 Lakban) & tanpa padanan (mis. Sticker
   Label) = **wajib tanya user**; catat keputusannya sebagai komentar mapping
   `[BARU <tgl>, mapping user]` di ITEM_MAP.
4. Mapping yang disetujui user ditaruh di ITEM_MAP skrip lane (bukan CSV
   terpisah) supaya rerun lane tetap idempoten.

## Playbook: perbaikan stok & migrasi dokumen (kasus terbukti 2026-10-12)

### A. Barang "nyangkut" di `Goods In Transit` (belum end-transit)

Gejala: user bilang stok di Goods In Transit belum sampai tujuan / "targetnya
gudang Jakarta". **Selalu audit dua site dulu** — jangan asumsikan.

1. **Cek GIT di site yang user periksa** (bukan yang mudah):
   `audit_cloud_jakarta_git.py` (cloud) / `audit_goodintransit_juri.py` (lokal).
   Lihat Bin ber-qty, SLE, dan **voucher pembentuknya**.
2. **Tentukan jalur yang benar** — ada dua bentuk yang sering tertukar:

   | Kondisi GIT | Tindakan |
   |---|---|
   | Barang **ADA di GIT** (`SE-MTF-*` dengan `to_warehouse = GIT`) | **end-transit**: `GIT → Gudang Jakarta`, satu Stock Entry. GBJ **tidak disentuh** (barang sudah keluar dari GBJ). |
   | GIT **kosong** (Baru belum punya jejak sama sekali) | kompensasi dulu: RECO penyesuaian (`5110.020`) ke GBJ, lalu transfer GBJ → Jakarta. |

3. **Jangan lewat transit dua kali.** Jalur `GBJ → GIT → Jakarta` membuat GBJ
   keluar **2× qty** → minus besar (terukur: `PJ260013` −17.832,
   `PJ260012` −13.716, `PJ260014` −20.856, `PJ260010` −2.958 Pcs). Kalau bisa
   langsung, langsung.
4. **Konversi `Pack` → `Pcs`**: dokumen LAMA memakai UOM baris (Pack), site
   BARU `stock_uom = Pcs` dengan konversi berbeda per item (`PJ260010` cf=6,
   `PJ260011` cf=3, `PJ26001x` lain cf=12). Ambil `conversion_factor` dari
   **master Item site BARU**, jangan asumsikan 1:1.
5. **UOM LAMA `Kg` (K besar) ≠ BARU `kg`** — master BARU lowercase; map
   eksplisit, jangan tebak.
6. Skrip: `pos_sync/endtransit_cloud_jakarta.py` (cloud, `--execute/--verify`),
   `pos_sync/fix_git_jakarta_ke_gbj_transfer.py` (lokal, `--plan/--reco/--transfer`).

### B. Migrasi dokumen pembelian (MR / PO) dari site LAMA

Pola: `pos_sync/migrate_mr_po_25sep_7okt.py` — parameterisasi window tanggal,
ID identik (`rename_doc`), idempotensi `title = "ERESTO <name>"`, dry-run
default. Checklist sebelum eksekusi:

- [ ] **Normalisasi berlapis**: `set_warehouse`, `warehouse` baris,
      **`expense_account`** (`4210.000 - HPP Pembelian - ROPI` → `- JURI`),
      **`cost_center`** (`Main - ROPI` → `- JURI`). Lewat akun → 417
      `LinkValidationError: Could not find Row #1: Expense Account`.
- [ ] **Template pajak**: LAMA `Purchase Tax - ROPI` → BARU `Purchase Tax -
      JURI`; LAMA `Purchase Tax 11% (Include) - ROPI` → BARU
      `Purchase Tax (Termasuk Pajak) - JURI`. Template **Include tidak butuh
      baris pajak** (grand = net sudah benar).
- [ ] **Guard item master**: cek `/api/resource/Item/<code>` ada di target
      **sebelum** POST; kalau tidak, SKIP + laporkan (jangan biarkan LinkError
      di tengah batch).
- [ ] **Relink**: baris PO `material_request` + `material_request_item` harus
      menunjuk MR BARU → buat **MR dulu, PO kemudian**.
- [ ] **Cari by name DAN title** sebelum menyimpulkan "belum ada" (dokumen
      lama bisa bernama `PO-JURI-261004xxx` dengan title `ERESTO <id-lama>`).

### C. Menambahkan baris pajak ke dokumen yang sudah submitted

`pos_sync/fix_tax_rows_po_25sep_7okt.py`:

1. Property Setter `allow_on_submit=1` sementara untuk **8 field PO**:
   `taxes`, `total_taxes_and_charges`, `grand_total`, `rounded_total`,
   `base_grand_total`, `base_rounded_total`, `in_words`, `taxes_and_charges`.
   Satu saja kurang → `UpdateAfterSubmitError`.
2. **PUT tidak memicu recalc pajak v16** — isi manual `tax_amount`, `total`,
   `base_tax_amount`, `base_total`, `net_amount`, dan field grand di header.
   Kalau tidak: baris pajak masuk tapi `tax_amount = 0`.
3. Hapus semua setter di `finally` (verifikasi 0 sisa di akhir).

### D. Jebakan baca/tulis yang menelan error

- **Field tak dikenal menggagalkan SELURUH query**, bukan diabaikan: contoh
  `Material Request` menolak `custom_department` di `fields` → 417
  `Field not permitted in query`. Helper `list_all` yang menelan error lalu
  mengembalikan `[]` → data terlihat "kosong" tanpa jejak. **Wajib cek status
  HTTP di list helper.**
- **`list_all` harus jalan sampai batch < limit**; kalau ada error, **raise**,
  jangan return list parsial/kosong.

## Peta cepat

| Butuh | Tempat |
|---|---|
| URL & endpoint eResto (API v3/v2 + route Manager) | `KNOWLEDGE.md` §2–4 |
| Jebakan Frappe/ERPNext (rename_doc, posting_date, mlb=0, dst) | `KNOWLEDGE.md` §6 |
| Ganti WO & error "Persiapan Gagal" (gate qty baris plan, rebind) | `KNOWLEDGE.md` §5 "Work Order & Production Plan" |
| Alur repack bahan baku (Gula Cair & **Olesan Pastry**) | `KNOWLEDGE.md` §5 "Alur repack bahan baku" |
| Konsolidasi RECO/opening (akun, cancel v16, substitusi MR) | `docs/12-konsolidasi-reco-opening.md` |
| Rantai produk dough→matang→bundle + resep yield | `docs/05-alur-dough-ke-bundle.md` |
| Mapping SKU/outlet/payment/void/refund | `docs/02-erpnext-mapping.md` |
| Alur kasir POSNext | `docs/04-posnext-cara-kerja-penjualan.md` |
| Cara menjalankan lane migrasi (flag CLI) | `PROJECT_STATE.md` §Cara jalanin |

Lane migrasi PO/SO terbaru (semua idempoten, dry-run default bila destruktif):

| Lane | Skrip |
|---|---|
| PO outlet → JURI (9–13 Okt, window bisa diatur) | `pos_sync/migrate_po_juri_9_12_okt.py` |
| PO JURI ↔ supplier eksternal (anti-duplikat ISI) | `pos_sync/migrate_po_juri_eksternal_9_12_okt.py` |
| PO Gudang Jakarta per hari | `pos_sync/migrate_po_gudang_jakarta_9okt.py` |
| SO FRC (PO FRC → Sales Order) | `pos_sync/migrate_so_frc_9_12_okt.py` |
| Onboard company outlet + PO | `pos_sync/migrate_po_selogiri_9okt.py` |
| Onboard company saja (tanpa PO) | `pos_sync/onboard_company_rs_12okt.py` |
| Hapus duplikat PO PT. JURI | `pos_sync/hapus_po_juri_duplikat.py` |
| Bersih dokumen cancelled | `pos_sync/bersih_dokumen_cancelled.py` |
| **MR (Purchase) + PO 25 Sep–7 Okt LAMA→BARU** | `pos_sync/migrate_mr_po_25sep_7okt.py` |
| **Tambah baris pajak PPN ke PO submitted** | `pos_sync/fix_tax_rows_po_25sep_7okt.py` |
| **Verifikasi dua sisi MR/PO** | `pos_sync/verify_mr_po_25sep_7okt.py` |
| **Audit scope MR/PO LAMA** | `pos_sync/audit_mr_mp_25sep_7okt.py` |
| **End-transit GIT → Gudang Jakarta (CLOUD)** | `pos_sync/endtransit_cloud_jakarta.py` |
| **Audit GIT cloud vs LAMA** | `pos_sync/audit_cloud_jakarta_git.py` |
| **Perbaikan GIT → GBJ → Jakarta (LOKAL)** | `pos_sync/fix_git_jakarta_ke_gbj_transfer.py` |
