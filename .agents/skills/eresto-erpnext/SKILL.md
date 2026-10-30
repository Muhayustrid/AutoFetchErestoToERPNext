---
name: eresto-erpnext
description: Use when working with Ropi eResto or ERPNext (ropi.co.id, ropi.eresto.id, ropierpnext, rotiropi.j), POSNext, SKU mapping, POS invoices, WO, MR, PO/SO/PR/PI/DN migration, duplicate documents, Stock Reconciliation/RECO, opening stock, SO opname, SA stock adjustment, auto stock balancing, negative stock, Goods In Transit/end-transit, Olesan Pastry, Goodie Bag, or Ropi sales, production, purchase and inventory data.
---

# eResto ↔ ERPNext (Ropi)

Baca berurutan sebelum menyentuh API apa pun:

1. `KNOWLEDGE.md` (root repo) — peta sistem: URL, endpoint, aturan bisnis, jebakan API.
2. `AGENTS.md` — aturan tetap proyek (style, constraint, alur).
3. `PROJECT_STATE.md` — status terkini: apa yang sudah selesai, task aktif, known issues.

Dokumentasi topik ada di `docs/01..13` (indeks di `KNOWLEDGE.md` §8).
Kode: `pos_sync/` (migrasi & injeksi, idempoten) dan `experiments/` (setup + probe;
`test_*` bukan produksi — jangan di-import).

## Aturan keras (jangan dilanggar)

- **Cek TARGET SITE sebelum menulis apa pun.** Tiga env mudah tertukar:
  `/tmp/eresto_mig.env` → `ERPNEXT_URL` biasanya **LOKAL**
  (`http://127.0.0.1:8081`); `/tmp/eresto_prod.env` → **CLOUD**
  (`https://ropi.co.id`, dulu `ropierpnext.frappe.cloud`). Permintaan "site baru / produksi" =
  **CLOUD**. Sebelum eksekusi **cetak `client.base`**; sesudahnya verifikasi
  di site yang dipegang user. (Kasus nyata 2026-10-12: perbaikan tertulis ke
  lokal → user "kok ga ada perubahan".)
- **eResto READ-ONLY** — hanya GET. Jangan POST/PUT/DELETE ke eResto.
- Rahasia hanya dari env (`ERESTO_TOKEN`, `ERESTO_EMAIL`, `ERESTO_USER_ID`,
  `ERPNEXT_URL`, `ERPNEXT_API_KEY`); jangan hardcode/print/commit. File nilai
  biasanya di `/tmp/eresto_mig.env` & `/tmp/eresto_prod.env` (volatile).
- **Jangan pernah kirim ke site yang salah.** Kunci API cloud baru TIDAK
  berlaku di site lama dan sebaliknya. Kunci dari chat = perlu rotasi (catat).
- Reruns must be idempotent: `remarks = "ERESTO <order_no>"`,
  `cheque_no = "ERESTO-<branch>-<date>"`, or `SKIP_EXISTS` by existing name/ID.
  Check doctype metadata before querying marker fields. Use `title` only when
  available; if neither `remarks` nor `title` exists, use native Comments with
  reference doctype/name plus timestamp/item signatures.
- Mapping SKU by **`product_sku`**, bukan nama. Jangan menebak Item Code —
  sumber kebenaran `docs/02-erpnext-mapping.md` (CSV experiments hanya arsip);
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
- **RECO opening:** account `1171.000 - Pembukaan sementara`; operational
  adjustment: `5110.020 - Penyesuaian Stock`. For eResto SO-derived opening,
  use the source SO timestamp and one RECO per SO per warehouse. Non-eResto
  opening remains at 23:00 on its approved date. The older blanket 30 Sep
  23:00 convention does not override a source SO timestamp. Cancel RECO v16
  shifts later ledger balances; follow the replacement procedure below.
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

## Purchase Request retrieval (eResto)

- **GET `/v2/purchase_requests`** lists Purchase Requests, not PO records or
  ERPNext Purchase Receipts. Read `purchase_requests[]`; confirmed header keys
  are `id` (UUID) and `request_no` (for example `PRGBJ.281026.004`).
- Use `created_at[geq]` / `created_at[leq]` in day-name format, `division_id`,
  `po_status=uncreated`, `page`, `per_page`, `sort[property]=updated_at`,
  `sort[order]=desc`, plus the standard env-based query/header authentication.
  Exact sanitized parameters: `docs/01-eresto-api.md` §Purchase Requests.
  Pass decoded values to the HTTP client's query encoder; do not double-encode
  `%5B`/`%5D` or copy a credential-bearing browser URL into code or logs.
- `po_status=uncreated` restricts the result to the uncreated-PO view, not all
  PRs. Other filter values and removal semantics need verification. Empty
  `division_id` is the captured all-division scope; use an explicit division
  when a single outlet is requested. `created_at` is not the document date.
- Follow `meta.next_page` to null, deduplicate headers by `id` and reconcile
  unique counts against `meta.total_count`; report live drift rather than
  claiming completeness from one page. The capture used `per_page=20`;
  larger page sizes are unverified for this endpoint.
- **Item rows remain unverified:** the supplied list capture collapses each
  PR object. Inspect a complete object or capture the GET triggered by opening
  a PR before specifying its item field, detail endpoint, SKU, qty or UOM.
  Do not guess `/purchase_request_items` or reuse the PO detail contract.
  Missing item evidence is not an empty item list. Retrieve only; no ERPNext
  creation or stock movement is authorized by this reference update.

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

## Stock adjustment eResto (SA) → dokumen stok ERPNext

Dua endpoint **READ-ONLY**: `/v2/stock_adjustments` (daftar dokumen) +
`/v2/stock_adjustment_items?stock_adjustment_id={id}` (baris item).
Detail `/v2/stock_adjustments/{id}` **tidak menambah apa pun** — hanya jurnal agregat.

**Parameter list (terverifikasi live 21 Okt 2026):**
`date[geq]`/`date[leq]` format **day-name** (`Wed, 21 Oct 2026 00:00:00.000`),
`division_id=` kosong = semua divisi, `page`, `per_page=200`,
`sort[property]=updated_at` + `sort[order]=desc` (catch-up incrementally),
plus `domain=ropi`, `current_user_id`, `token`. **Jangan kirim
`If-None-Match`** (balas 304, bukan 200).

**Kontrak baris list** (root `{"stock_adjustments": [...], "meta": {...}}`):

| Field | Isi |
|---|---|
| `number` | `SA<branch>.<DDMMYY>.<seq>` — branch **alnum** (`SA220.`, `SAO77.`), bukan angka saja |
| `reason` | **teks bebas** (tidak seragam): `Auto stock balancing` (sistem), `SO Monthly September` / `SO MID SEPTEMBER` / `Periode 1 Bulan September` (opname), `PENGAMBILAN HARIAN ...`, `From RSIA Nganjuk`, `BAJB-213 ...` |
| `division` | embed outlet: `name`, `branch_number`, `category: outlet`, `parent_division.name` |
| `stock_adjustment_type` | embed: `name` (9 tipe — lihat katalog di bawah), **`adjustment_type`** ("adjustment" \| "loss" \| "add" \| "new"), `account_id` = akun lawan di jurnal otomatis |
| `transaction_group` | jurnal otomatis: `automatic: true`, `number` `R…`, `note` "auto journal posting for inventory stock adjustment SA…", `transactions[]` = kaki jurnal (`account_number`, `account_name`, `debit_amount`, `credit_amount`) |
| `deleted_at` / `synced_at` | filter `deleted_at` null |

**Jebakan utama:** field root `adjustment_type` **selalu `null`** — penentunya
`stock_adjustment_type.adjustment_type` (nilai: `adjustment` | `loss` | `add` |
`new`). Memakai field root = salah klasifikasi.
Kaki jurnal otomatis amounts-nya bisa `"0.0"` (untuk auto-balancing) — jangan
dibaca sebagai "tidak ada nilai".

**Kontrak item:** `current_quantity` (sistem), `real_quantity` (fisik hasil
opname), `adjustment_quantity` = real − current, `adjustment_value` (Rp),
`reason` **per item** (hanya terisi pada auto-balancing: "Auto stock balancing
- inbound"/"- outbound"; dokumen lain `null` — catatan ada di `reason` header),
`unit.name`, `inventory.sku`/`inventory.name`, `stock_card`
(`initial_stock`/`stock_in`/`stock_out`/`stock_balance`), `meta.total_value`
(checksum). Item ber-selisih 0 tetap termuat → `real_quantity` = stok fisik utuh.

**Checksum:** `Σ adjustment_value` item vs `meta.total_value`. **Hanya sah untuk
tipe `adjustment`/`add`/`new`** (contoh: `SA116.300926.006` sum −1.325.788 =
meta −1.325.788 COCOK). Pada tipe **`loss`** meta = **0** walau Σ item ≠ 0
(contoh `SA208.300926.006` sum −58.900 vs meta 0) → jangan gagalkan batch
hanya karena selisih checksum di tipe loss. SA "Auto stock balancing" 0 = COCOK
(inbound & outbound saling meniadakan), bukan "kosong".

### SO opening source selection

When the user requests SO-prefixed opname, select non-deleted headers with
`stock_adjustment_type.name == "Stock Opname"` and
`reason.strip().upper().startswith("SO")`. The note is header **`reason`**,
not the SA number or the automatically generated journal note. Always exclude
auto-balancing, including item reasons `Auto stock balancing - inbound/outbound`.
Daily withdrawals (`PENGAMBILAN HARIAN ...`) are not SO opening sources.
The broader non-auto Stock Opname filter remains valid for requests explicitly
covering all opname reasons; do not silently broaden an SO-only request.

Use **`real_quantity`**, including unchanged and zero-count items, not
`adjustment_quantity`. Map by SKU and verified UOM factor. Report unmapped
positive quantities explicitly; never call a partial mapping "all items imported".
Keep non-eResto opening at 23:00 and later operational adjustments separate.

### Counted rows versus correction rows

Report source rows, mapped unique items, exclusions, and changed rows separately.
A count of 10 differences does not mean an SO contains only 10 items. Trace each
mapped SKU to its document and ledger balance at the SO timestamp, not to today's
Bin or EOD alone. Existing split RECOs may overlap; deduplicate by warehouse/item.
**Zero targets may have no new SLE** when book quantity is already zero; verify
their effective balance rather than requiring one SLE per document row.

### Safe replacement of split RECOs

1. Audit live target, exact inclusive date range, dependencies, source rows,
   existing RECOs, future SLE, Bin quantities and stock values. Backup first.
2. Prepare the full mapped payload with custom UOM fields and obtain exact
   replacement-scope approval before cancellation/deletion/submission. Read
   back native drafts/submissions; submitting over old anchors can drop rows.
3. Scope deletion to approved names, not every RECO in the date range. Preserve
   non-eResto opening, operational adjustments, and rows belonging to other
   warehouses in mixed documents. Preserve their timestamp, qty and valuation
   in warehouse-specific replacements; verify counted-data invariants after
   repost, not byte-equality of server-recomputed current/difference fields.
4. Submitted zero-difference rows can be removed by server validation. Do not
   submit over old layers, delete those layers, and assume full SO coverage.
   Validate replacement order; cancelling oldest-created layers first preserves
   next-RECO boundaries but can still raise **NegativeStockError**.
5. If cancellation fails, stop and read back documents/Bin to verify rollback.
   Approval to replace RECOs is NOT approval to enable negative stock. Obtain
   explicit permission for that specific temporary exception; restore
   `allow_negative_stock=0` in `finally`, even if replacement fails.
6. After approved cancellation, preserve cross-warehouse rows and submit the
   consolidated draft before permanently deleting originals. If deletion is
   blocked by **Workflow Action**, backup and remove only actions whose
   `reference_doctype/reference_name` match the approved cancelled voucher.
   Restore `delete_linked_ledger_entries` in `finally`.
7. Verify submitted row signatures and SO-time balances; protected counted data;
   approved projected quantities and expected EOD; report valuation changes;
   balanced GL (an empty journal may be valid for a same-account transfer);
   old names 404 and GL/SLE residue 0; no negative target Bin; restored settings;
   repost pending/failed 0. Do not claim success while repost remains pending.

Evidence, execution history and current document IDs belong in `docs/13` and
`PROJECT_STATE.md`, not in permanent skill rules.

### Stock audit and repost edge cases

Before a stock audit or backdated correction, read
[Stock audit safety](references/stock-audit-safety.md): stable ERP pagination,
native omitted-row proof, counted-versus-derived fields, scoped historical
negatives, safe no-op decisions, metadata, precision and asynchronous deletion.

### Katalog tipe SA (9 tipe, terukur 1–30 Sep 2026: 11.319 SA) → dokumen ERPNext

| Tipe eResto (`stock_adjustment_type.name`) | `adjustment_type` | Arti | Dokumen ERPNext (cloud baru) |
|---|---|---|---|
| `Stock Opname` (reason opname: `SO Monthly …`, `SO MID …`, `Periode 1 Bulan …`) | `adjustment` | opname fisik outlet | `Stock Reconciliation` qty absolut → `5110.020 - Penyesuaian Stock` |
| `Stock Opname` (reason `Auto stock balancing`) | `adjustment` | koreksi delta sistem (~10,8k/bulan) | **jangan post** — jejak audit saja (praktik proyek: skip di `fetch_so_monthly.py`) |
| `Opening Stock` | `new` | stok awal | `Stock Reconciliation` opening → `1171.000 - Pembukaan sementara` |
| `Adjusmen Beli Inventory outlet` | `add` | sisi **terima** transfer antar outlet (mis. "From RSIA Nganjuk") | `Stock Entry` transfer masuk ke outlet penerima |
| `Adjusment Jual Inventory Outlet` | `loss` | sisi **keluar** transfer antar outlet ("To RSUP Surakarta") | `Stock Entry` transfer keluar dari outlet pengirim |
| `Adjustment Stock Out` | `loss` | pengambilan harian dari gudang | `Stock Entry` (Material Transfer/Repack) gudang → outlet |
| `Reject Outlet` | `loss` | barang reject/expired outlet | `Stock Reconciliation` penyesuaian (`5110.020`) atau Waste |
| `Keperluan Produksi` | `loss` | bahan untuk produksi | `Stock Entry` Manufacture / Material Transfer |
| `Cangkang Telur` | `loss` | cangkang telur (limbah) | `Stock Reconciliation` penyesuaian / Waste |
| `Keperluan RnD` | `loss` | uji coba R&D | `Stock Reconciliation` penyesuaian (beban R&D) |

Pasangan transfer antar outlet ("Beli" & "Jual") nilainya **sama** berlawanan
(±694.148 pada pasangan 30 Sep) → **satu** Stock Entry transfer, jangan dua RECO.
Akun kaki jurnal eResto: `1 1 03 01` Persediaan Raw Matterial, `1 1 03 02`
Semi Finished, `1 1 03 03` Pesediaan Finished Good, `2 1 01 07` Hutang
Lain-lain, `5 2 00 01` HPP Produksi, `6 1 01 25` Beban Operasional, Piutang
Outlet, Opening Balance. Peta ke akun ERPNext **ikut master item/company**
(`docs/02` + `lengkapi_item_defaults_semua.py`) — jangan menebak.

**Pemetaan umum ke ERPNext (baru/cloud):** SA opname → `Stock Reconciliation`
(RECO) **qty absolut**: opening → `1171.000 - Pembukaan sementara`; penyesuaian
operasional → `5110.020 - Penyesuaian Stock` (jangan campur). Idempotensi:
marker `remarks = "ERESTO SA<number>"` where metadata permits; otherwise use
`title` if available, or native Comments plus timestamp/item signatures when
both fields are absent. Check before writing. `allow_negative_stock = 0` terkunci: RECO backdated di atas
saldo minus ditolak `NegativeStockError` → catat pergerakan riil
(receipt/repack/transfer).

### Jebakan SA yang sudah terbukti

1. `adjustment_type` root selalu `null` → pakai `stock_adjustment_type.adjustment_type`.
2. `meta.total_value` = 0 pada tipe `loss` → bukan error.
3. **Pagination: andalkan `meta.total_count`/`meta.next_page`, JANGAN stop saat
   `len(batch) < per_page`** — angka lama 4.645 SA (1–30 Sep, terukur 4 Okt)
   **terpotong**; terukur ulang 21 Okt = **11.319 SA / 57 halaman**
   (`meta.total_count` 11.319). `total_count` bisa bergerak (data live).
4. `reason` = **teks bebas**, opname tidak seragam: `SO Monthly September` (123),
   `SO MID SEPTEMBER` (14), `Periode 1 Bulan September` (6), `Konfirmasi` (6),
   `PENYAMAAN STOK DOUGH`, `SO Monthly September Revisi`, `Counter 1 Sep` …
   **Resep filter opname:** `stock_adjustment_type.name == "Stock Opname"`
   **DAN** `reason != "Auto stock balancing"` → **210** dokumen di Sep 2026
   (filter `reason == "SO Monthly September"` saja hanya dapat 123).
5. **eResto mengizinkan qty negatif** (`current_quantity` −60, `real_quantity`
   −0,5) — ERPNext tidak (`allow_negative_stock=0`). Target RECO negatif =
   tidak valid → keluarkan & catat, jangan post.
6. **SKU pada SA bisa berakhiran `-b`** (varian/renaming: `BB0121-b` "Plastik
   Paking Dough", `BB0155-b` "Karet Gelang"); SKU dasar bisa sudah di-rename
   jadi "Deleted 1" (`BB0121`) → map by SKU, dan kalau tak ada di `docs/02`
   keluarkan & catat (jangan tebak).
7. Nomor SA selalu pola `SA<branch alnum>.<DDMMYY>.<seq>` (11.319/11.319 cocok).

Skrip acuan: `experiments/fetch_so_monthly.py` (checksum `meta.total_value`) —
**pagination-nya masih pakai aturan lama** (`len(batch) < PER_PAGE` → hasil
terpotong); lihat `PROJECT_STATE.md` §Known issues.

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

1. Sumber bukti berurutan: `docs/02-erpnext-mapping.md` (tabel utama) →
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
| Stock adjustment eResto (SA + item → RECO/SE) | `docs/01-eresto-api.md` §Stock adjustment |
| Rantai produk dough→matang→bundle + resep yield | `docs/05-alur-dough-ke-bundle.md` |
| Mapping SKU/outlet/payment/void/refund (SINGLE SOURCE) | `docs/02-erpnext-mapping.md` |
| Mapping SKU by `product_sku`, bukan nama; sumber kebenaran = dokumen mapping utama, bukan CSV | `docs/02-erpnext-mapping.md` |
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
