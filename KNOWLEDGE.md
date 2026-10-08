# KNOWLEDGE.md — eResto ↔ ERPNext (basis pengetahuan untuk AI & manusia)

> **English abstract:** This repo migrates Ropi's POS operations from the
> eResto SaaS (ropi.eresto.id) into ERPNext v16 — target site
> `ropierpnext.frappe.cloud` (new/production), source site
> `rotiropi.j.frappe.cloud` (old/historic). This file is the durable system
> map: what each system is, every known URL/endpoint, the business rules,
> and the API traps. `AGENTS.md` holds project rules, `PROJECT_STATE.md`
> holds live status. No credentials are stored here — env vars only.

Dokumen ini menjawab tiga hal: **apa** sistemnya, **di mana** URL/endpoint-nya,
dan **bagaimana** cara kerja yang benar. Urutan baca untuk AI/engineer baru:
`KNOWLEDGE.md` (ini) → `AGENTS.md` (aturan tetap) → `PROJECT_STATE.md`
(status terbaru) → `docs/01..11` sesuai topik.

---

## 1. Gambaran besar

Tiga sistem, tiga peran:

| Sistem | Peran | Status |
|---|---|---|
| **eResto** (`ropi.eresto.id`) | Sumber data operasional: penjualan POS, refund, produksi/sesi masak, stok opname, pembelian legacy | **Stock truth sampai cutover** — tetap jalan, READ-ONLY bagi kita |
| **ERPNext Baru** (`ropierpnext.frappe.cloud`) | Target produksi: POS Invoice, Work Order, PO/PR/SO/DN, aset, print format | Target semua migrasi & sync harian |
| **ERPNext Lama** (`rotiropi.j.frappe.cloud`) | Sumber historis transaksi internal ERPNext (invoice kasir, WO, PO) yang belum pernah masuk eResto | Sumber read-only untuk migrasi |

Alur data: **eResto → script Python (`experiments/`, `pos_sync/`) → ERPNext Baru**.
Migrasi ERPNext Lama → Baru berjalan paralel (WO, PO, PR, SO, DN, aset).
ERPNext Lama tidak memuat stock movement POS per SKU; eResto tetap pemegang
kebenaran stok sampai cutover (docs/03 "Cutover rule").

---

## 2. URL semua sistem

### 2.1 eResto

| Hal | URL |
|---|---|
| Web / login | `https://ropi.eresto.id/` |
| Manager SPA (semua layar) | `https://ropi.eresto.id/manager/v2/index.html#/<route>` |
| API base | `https://ropi.eresto.id` (endpoint di §4) |
| Referer wajib untuk API | `https://ropi.eresto.id/manager/v2/index.html` |

Route Manager **hash-based** (segala layar di bawah `#/`); deep link langsung
bisa dibagikan. Route penting yang sudah dipetakan:

**Laporan penjualan**
| Route | Layar |
|---|---|
| `#/sales_report/orders/orders` | Daftar order POS — dipakai cross-check 3 `order_no` per fetch (docs/01) |

**Purchasing (sisi pusat / PT JURI ke supplier)**
| Route | Layar |
|---|---|
| `#/purchasing/purchases/orders` | Purchase order |
| `#/purchasing/payments/invoices` | Faktur pembelian |
| `#/purchasing/payments/purchase_payments` | Pembayaran ke supplier |
| `#/purchasing/deliveries/deliveries` | Pengiriman / surat jalan |
| `#/purchasing/deliveries/receipts` | Penerimaan barang |

**Inventories — laporan stok**
| Route | Layar |
|---|---|
| `#/inventories/inventory_reports/inventory_movements` | Mutasi stok |
| `#/inventories/inventory_reports/stock_cards` | Kartu stok — dipakai proyek untuk melacak sesi masak & bahan terpakai (docs/05) |

**Inventory & Sales (siklus pembelian sisi outlet/unit — padanan rantai
ERPNext PO → PR → PI → Payment → Return; ini layar asal migrasi "PO Outlet → JURI")**
| Route | Layar |
|---|---|
| `#/inventory_sales/purchase_order/all_purchase_order` | Semua surat pesanan |
| `#/inventory_sales/purchase_order/awaiting_purchase_order` | Menunggu diproses |
| `#/inventory_sales/purchase_order/processing_purchase_order` | Diproses |
| `#/inventory_sales/purchase_order/completed_purchase_order` | Selesai |
| `#/inventory_sales/purchase_order/reject_cancel_purchase_order` | Ditolak / batal |
| `#/inventory_sales/purchase_delivery/my_deliveries` | Pengiriman saya |
| `#/inventory_sales/purchase_delivery/received_deliveries` | Sudah diterima |
| `#/inventory_sales/purchase_invoice/unpaid_invoices` | Tagihan belum bayar |
| `#/inventory_sales/purchase_invoice/partially_paid_invoices` | Dibayar sebagian |
| `#/inventory_sales/purchase_invoice/fully_paid_invoices` | Lunas |
| `#/inventory_sales/purchase_payment/unconfirmed_payments` | Pembayaran belum dikonfirmasi |
| `#/inventory_sales/purchase_payment/confirmed_payments` | Pembayaran terkonfirmasi |
| `#/inventory_sales/purchase_return/return_on_process` | Retur diproses |
| `#/inventory_sales/purchase_return/return_received` | Retur diterima |

> Layar `purchasing/*` dan `inventory_sales/*` di atas sudah dikatalogkan
> sebagai acuan navigasi; API counterpart-nya belum di-probe script di repo ini
> (yang terbukti via API baru `/v2/purchases` legacy, §4). Cara menambah route
> baru: buka layar di browser, lihat hash URL + capture request API-nya
> (metode yang dipakai membangun docs/01).

### 2.2 ERPNext

| Hal | URL |
|---|---|
| **Baru (target produksi)** | `https://ropierpnext.frappe.cloud` (desk: `/desk`) |
| **Lama (sumber historis)** | `https://rotiropi.j.frappe.cloud` (desk: `/desk`) |
| API (kedua site) | `https://<site>/api/resource/<DocType>` + `/api/method/frappe.client.*`, `/api/method/pos_next.api.*` |
| Referensi API | `https://frappeframework.com/docs/user/en/api/rest` |
| Dev lokal baru | `http://erp.localhost:8081` (docker project `frappe-*`, site `erp.localhost`) |
| Dev lokal lama | `http://site-lama.localhost:8082` (docker project `site-lama-*`, frozen data 2 Okt) |

Versi: Frappe/ERPNext **v16**, cloud Baru memakai app **POSNext** +
`production_app` + `warehouse_app` (hook app yang menyinkronkan tahap WO).
Autentikasi API: header `Authorization: token <api_key>:<api_secret>`
(kunci per site — kunci site baru TIDAK berlaku di site lama dan sebaliknya).
Kredensial disimpan user di file env di `/tmp` (nama saja, §9) — jangan
pernah masuk repo.

---

## 3. eResto API — akses

Autentikasi DUA bagian, keduanya wajib di setiap request:

1. Header: `Authorization: Token token={TOKEN}, email={EMAIL}`
2. Query: `token={TOKEN}`, `domain=ropi`, `current_user_id={USER_ID}`

Plus header `Accept: application/json, text/plain, */*` dan
`Referer: https://ropi.eresto.id/manager/v2/index.html`.

Aturan yang terbukti (docs/01):

- **Jangan kirim `If-None-Match`** — server membalas 304; tanpa itu selalu 200.
- **Token mati → HTTP 500** `{"status":500,...}` di semua endpoint (bukan 401).
  Kalau semua call tiba-tiba 500, uji token lain dulu sebelum menyimpulkan outage.
- Pagination: `page` (mulai 1), `per_page=200`; berhenti saat
  `len(batch) < per_page` atau `meta.next_page = null`. Dedup by `id`;
  `meta.total_count` bisa bergerak saat fetch (data live).
- Retry transien 429/500/502/503/504 — maks 3 dengan backoff, timeout 90s.
- Fetch detail paralel maks **10 worker**. Volume: 160 detail ≈ 5.5s.
- Pola sync yang benar: **per outlet per jam/hari secara inkremental**, bukan
  tarikan multi-hari global + N+1 sekaligus.
- `outlet_id`/`division_id` kosong = semua outlet — jangan; loop per outlet
  agar satu outlet gagal tidak membatalkan sisanya.
- Cache buster `_={timestamp_ms}`.

### 3.1 Query params khusus

| Endpoint group | Filter tanggal | Catatan |
|---|---|---|
| `/v3/orders` | `date[geq]` / `date[leq]` format `YYYY-MM-DD HH:mm:ss.SSS` (`00:00:00.000`…`23:59:59.999`) | plus `outlet_id`, `sort[property]=date`, `sort[order]=asc` |
| `/v2/refunds` | `created_at[geq]` / `created_at[leq]` format day-name (`Sun, 4 Oct 2026 00:00:00.000`) + `timezone=+07:00` | join ke order via `order_no` |
| `/v2/productions` | format day-name, `division_id` sebagai ganti `outlet_id` | root `{"productions":[...],"meta":{}}` |
| `/v2/stock_adjustments` | `date[geq/leq]` day-name (seperti refunds) | item ada di endpoint terpisah |

---

## 4. eResto API — endpoint

| Data | Method | Endpoint | Kontrak singkat |
|---|---|---|---|
| POS order list | GET | `/v3/orders` | `data[]` type `simple_order`, field di `attributes`: `order_no` (`OR<branch>.<DDMMYY>.<seq>`), `outlet_id/name/branch_number`, `date`, `cashier_name`, `item_quantity`, `void_quantity`, `payment` (`receipt_number PY...`, `total`, `cash_amount`, `ewallet_amount`, `credit/debit/transfer_amount`). **Tanpa line item.** |
| POS order detail | GET | `/v3/orders/{order_id}` | `{"data":{"type":"order","attributes":{...}}}` — **unwrap `data.attributes`** (capture lama: `attributes` di root — handle keduanya). `order_items[]`: `product_sku`, `product_name`, `quantity`, `price`, `discount_item_amount`, `tax_amount`, `void`, `void_note`, `void_quantity`, **`paid_quantity`**. Payment + `sub_total`, `rounding_amount`, `voucher_amount`, `refunded_at`, `return_amount`. **Satu-satunya sumber SKU (pola N+1).** |
| Refund list | GET | `/v2/refunds` | root `{"refunds":[...], "meta":{"total","total_count"}}`. Row: `note`, `created_at`, `outlet.name`, `payment`, `order{order_no, order_status: void}`. 2/308 baris `order: null` (refund pembayaran standalone). |
| Production list | GET | `/v2/productions` | `production_number` (`045.DDMMYY.NNNNNN`), `division_id`, `date`, `note` ("Masak shift 3"), `transaction_group.transactions[]` (jurnal otomatis: Dr Finished Good `1 1 03 03` / Cr Semi Finished `1 1 03 02`). Detail BOM per produk belum dipetakan. |
| PO list (legacy) | GET | `/v2/purchases` | dipakai CLI PO legacy |
| PO detail (legacy) | GET | `/v2/purchases/{id}/detail` | fallback `/v2/purchases/{id}` |
| Stock adjustment list | GET | `/v2/stock_adjustments` | `reason` = catatan dokumen (`SO Monthly September`, `Auto stock balancing`). Detail dokumen hanya jurnal agregat. |
| Stock adjustment items | GET | `/v2/stock_adjustment_items?stock_adjustment_id={id}` | `current_quantity` (sistem), `real_quantity` (fisik), `adjustment_quantity` = real−current, `adjustment_value` (Rp), embed `inventory` + `division`. `meta.total_value` = checksum. Item selisih 0 tetap termuat → `real_quantity` = stok fisik utuh. |
| Inventories (live) | GET | `/v2/inventories` | tiap inventory punya `division_inventories[]` (`division_id`, `quantity`). Stok berjalan, bukan snapshot opname. |
| Stock cards (mutasi) | GET | `/v2/stock_cards?division_id=...` | `reference_type = Production` = hasil masak masuk; `ProductionResultItem` = bahan terpakai keluar (docs/05). |

Volume acuan (terukur 1–4 Okt 2026): 27.053 order / 137 outlet / Rp709 jt;
±9.4k order/hari; refund ≈1.1%/hari.

---

## 5. Aturan bisnis yang tidak boleh dilanggar

**Mapping SKU & item** (sumber kebenaran: `experiments/sku_to_item_code.csv`
untuk POS, `stok_sku_to_item.csv` untuk inventory — jangan menebak):

- Kunci mapping = **`product_sku`**, tidak pernah nama. Satu SKU = satu nama.
  Produk sama bisa beda SKU per tipe outlet: `PR001/PR002/PR003` (owned) vs
  `P0004/P0001/P0002` (franchise) → semuanya ke `RP001/002/003`.
- Kode eResto ≠ kode ERPNext (jebakan nyata: eResto `PG001` = Roti Gempi,
  ERPNext `PG001` = Goodie Bag).
- Item POS = **Product Bundle non-stok**; stok ada di komponen.
- Rantai barang tetap (docs/05): **dough (Pabrik `PJ*`) → matang (Outlet `PJO*`)
  → bundle jual (`RP00x`/`CR001`/`GM00x`)**. Yield terukur: 1 pack Ropi → 12 pcs,
  Gempi → 3, Croissant → 6. Pengecualian: `PJ260015` Dubai Dough dijual sebagai
  dough (tanpa matang/bundle) — jangan dibuatkan PJO.
- `PJO2601–2605` tidak punya SKU POS; jangan dipetakan sebagai item jual.

**Order & uang:**

- Pakai **`paid_quantity`**, bukan `quantity`. Skip baris `void=True`,
  `paid_quantity=0`, atau header `total=0`; simpan `void_note` untuk audit.
- Refund eResto = auto-void order (bukan Sales Return negatif). Void selalu
  full-order, ±1.1%/hari; total order void sudah 0 sehingga skip tidak
  mengubah omzet.
- Order total nol tanpa flag void (RSUD Blora) = complimentary/OC — dikeluarkan
  dari revenue, bukan refund (tidak ada di `/v2/refunds`).
- Mix bayar terukur: cash 70.7%, ewallet/QRIS 29.1%, debit 0.2%, kredit ~0.

**Master data & struktur:**

- **Outlet = Company** anak `OUTLET REGULER` (CoA seragam). Nama FRC persis
  eResto termasuk `(FRC)`. Outlet FRC **dikecualikan** dari injeksi pendapatan
  grup (keputusan 2026-10-05; skema franchise belum final).
- **POSNext:** Price Group memiliki satu Price List `PG-<nama>` + Item Price,
  dan mengklaim semua POS Profile company-nya. Jangan buat Price List/Item
  Price manual — ownership field menolak. Urutan: `prep → pg → prof → claim → group`.
- **Shift Group:** membership hanya lewat tabel Members milik grup; menyimpan
  grup = sync jadwal + unlink profil yang tidak terdaftar.
- Setiap POS Profile: Cash (default, allow returns) + Debit Card + Credit Card
  + QRIS; tiap company butuh baris Mode of Payment Account ke-4 metode itu.

**Idempotensi (wajib — rerun tidak boleh menduplikasi):**

| Lane | Kunci |
|---|---|
| POS Invoice per order | marker `remarks = "ERESTO <order_no>"` (cek-dulu-skip) |
| Agregat outlet-hari | `cheque_no = "ERESTO-<branch>-<date>"` |
| PO/SO/DN (tak punya field `remarks`) | taruh di **`title`** + check-then-skip by name |
| Semua migrasi `pos_sync/` | `rename_doc` ke ID lama + `SKIP_EXISTS` bila sudah ada |

---

## 6. Jebakan API Frappe/ERPNext (terbukti, sering kena)

1. **`frappe.client.rename_doc`** harus dikirim **form-encoded**, bukan JSON.
2. **`posting_date` di-reset** ke tanggal submit saat submit — kirim
   `set_posting_time=1` untuk mempertahankan tanggal.
3. **`fetch_meta` tidak memuat Custom Fields** — payload "pick" terhadap meta
   membuang semua `custom_*` diam-diam. Merge dulu dari
   `/api/resource/Custom Field?filters=[["dt","=",DocType]]`.
4. **Stock Entry: `qty` dalam UOM baris**, API `stock_qty` null — kalikan
   `conversion_factor` ke stock UOM saat replay. UOM site baru huruf kecil
   (`kg`, bukan `Kg`).
5. **Valuation rate wajib** saat gudang sumber kosong di target → salin
   `basic_rate` dari dokumen lama + `allow_zero_valuation_rate=1`.
6. **`allow_negative_stock=1` global di cloud** selama fase migrasi — itu yang
   meloloskan submit Stock Entry backdated yang saldo point-in-time-nya minus.
7. **Stock Reconciliation = qty ABSOLUT** pada timestamp posting-nya. RECO
   backdated lalu di-cancel merusak Bin vs ledger; perbaikan = RECO baru yang
   sesuai ledger, bukan koreksi lama.
8. **Update setelah submit:** `before_save` tidak jalan → pakai Property Setter
   `allow_on_submit=1` sementara + `frappe.client.set_value`, lalu pulihkan ke 0.
9. **Payment Ledger Entry read-only via API** (403). Hapus dokumen ber-ledger:
   cancel → purge Print Log → set `delete_linked_ledger_entries=1` sementara di
   Accounts Settings → delete → pulihkan 0.
10. **Validasi intercompany:** customer internal untuk SO butuh
    `represents_company` = **company outlet (sisi pembeli)**, bukan JURI; salah
    arah → `Invalid Customer for Inter Company Transaction`. Supplier JURI juga
    butuh outlet terdaftar di `Allowed To Transact With`.
11. **WO outlet wajib `use_multi_level_bom = 0`** (permintaan SPA kasir tidak
    menyetelnya; app `production_app` sudah dipasangi guard `before_validate`).
    Tanpa itu, SE Manufacture meledakkan resep dough dan bisa gagal
    "Valuation Rate for Item X is required".
12. **Item doctype auto-naming `BB26-.###`** menimpa `item_code` saat create →
    selalu `rename_doc` setelah create.
13. **Filter `name in [...]`** kena limit request-line → potong query per ±40.
14. **Fiscal Year** harus mencakup tanggal posting; company baru wajib
    didaftarkan ke FY (Frappe menolak company di FY yang rentangnya tumpang
    tindih — pilih FY yang memuat tanggal transaksi).
15. **Customer matching by `customer_name`**, bukan kode `CUST-*` (kode sama
    bisa beda RS antar site). Supplier: fallback case-insensitive
    (`SUP260008` = PT. JUARA vs "PT. JUARA ROTI INDONESIA").
16. **Python 3.14 `urllib` di Mac user gagal verifikasi SSL** ke
    `*.frappe.cloud` — pakai `curl` untuk call API dari shell.
17. **Queue Repost Item Valuation macet** → jalankan `repost_entries()` manual
    via `bench execute`.

---

## 7. Lingkungan & cara menjalankan

Env (nama saja — nilai ada di file `/tmp` yang **tidak** di-commit):
`ERESTO_TOKEN`, `ERESTO_EMAIL`, `ERESTO_USER_ID` (eResto);
`ERPNEXT_URL` + `ERPNEXT_API_KEY` (site sesuai pass); di `/tmp/eresto_mig.env`
& `/tmp/eresto_prod.env`. File `/tmp` volatile — hilang saat reboot, minta
ulang ke user. Muat dengan: `set -a && . /tmp/eresto_mig.env && set +a`.

Struktur kode:

| Lokasi | Isi |
|---|---|
| `experiments/pos-fetch/` | probe fetch (`test_*`, **bukan** produksi — jangan di-import) + output Excel/JSON |
| `experiments/*.py` | setup ERPNext (company, POS matrix, tier harga, stok opname, mapping, injeksi agregat, pilot) |
| `pos_sync/` | kode migrasi & injeksi produksi (site lama→baru, WO, PO/PR, SO/DN, POS Invoice, print format, aset) — semua idempoten, CLI terpisah |
| `docs/` | dokumentasi per topik (§8) |
| `Backup SIte Production/` | backup DB produksi — **read-only, jangan disentuh** |
| `KNOWLEDGE.md` | dokumen ini |

Pola verifikasi proyek (tanpa test suite): tiap script menghasilkan
**laporan Excel** (sheet `Raw_*`, `Rekap_*`, `Validation`, `Failed`;
header `#D9EAF7`, freeze `A2`) + cek stdout yang harus terbaca OK/LOLOS.
Migrasi besar diverifikasi dua sisi (tarik ulang sumber & target, bandingkan
jumlah/nilai/docstatus/baris) — contoh: `pos_sync/migrate_outlet_po_to_juri.py --verify`.

Perintah utama (detail flag & urutan di `PROJECT_STATE.md` §Cara jalanin):

| Lane | Script |
|---|---|
| Fetch POS list/detail/recap | `experiments/pos-fetch/test_fetch_orders.py`, `test_fetch_order_details.py`, `test_sales_recap.py` |
| Setup POS (company, price group, profil, shift) | `experiments/apply_pos_bulk.py`, `update_pos_payments.py`, `create_shift2.py` |
| Injeksi POS Invoice (per order, backfill) | `pos_sync/inject_pos_invoice.py` (+ `set_item_valuation.py` sekali di awal) |
| Migrasi WO pabrik | `pos_sync/migrate_wo_full_okt.py` (`--dump/--plans/--wos/--mrs/--ses/--verify`) |
| Migrasi PO Outlet → JURI | `pos_sync/migrate_outlet_po_to_juri.py` (`--dump/--prep/--migrate/--verify/--rewarehouse`) |
| Migrasi SO + DN Outlet → JURI | `pos_sync/migrate_outlet_so_dn_to_juri.py` (`--dump/--prep/--so/--dn/--verify`) |
| Print format (header global) | `pos_sync/migrate_print_formats.py` (`--build/--push/--verify/--revert --stage local\|cloud`) |
| Catch-up delta harian | `pos_sync/catchup_oct7.py` (pola mengikuti) |

---

## 8. Indeks dokumen

| Doc | Isi |
|---|---|
| `docs/01-eresto-api.md` | Auth, endpoint, params, kontrak JSON eResto (dasar §3–4 di atas) |
| `docs/02-erpnext-mapping.md` | Mapping SKU→Item, outlet, payment, aturan void/refund, pilot 1 order, mapping stok SO |
| `docs/03-production-sync-design.md` | Desain sync POS→produksi→purchase, fase 1–4, aturan cutover |
| `docs/04-posnext-cara-kerja-penjualan.md` | Cara kerja POSNext: opening shift, invoice, closing |
| `docs/05-alur-dough-ke-bundle.md` | Rantai tetap dough→matang→bundle + resep yield terukur |
| `docs/06-migrasi-site-lama-ke-baru.md` | Migrasi ERPNext lama→baru (Okt 2026) + jebakan Frappe |
| `docs/07-injeksi-production.md` | Injeksi master+transaksi ke PRODUCTION |
| `docs/08-injeksi-pos-invoice-lokal.md` | Injeksi POS Invoice lokal 1–5 Okt (backdate + shift) |
| `docs/09-migrasi-wo-juri-replay.md` | Replay 244 WO JURI 1–6 Okt via alur production_app |
| `docs/10-migrasi-wo-lanjutan.md` | Audit & catch-up WO/MR/SE/PO↔MR + WIP |
| `docs/11-migrasi-print-format.md` | Header global + 10 print format default |

---

## 9. Aturan aman untuk AI (ringkas — detail di `AGENTS.md`)

- **eResto READ-ONLY**: hanya GET. Jangan pernah POST/PUT/DELETE ke eResto.
- **Rahasia hanya dari env**; jangan hardcode, jangan print token, jangan commit
  file env. Kalau token tercecer di shell history → minta user rotasi.
- **Jangan POST ke ERPNext** sebelum mapping disetujui & URL+API key tersedia.
- **Jangan menebak Item Code** — konflik tetap di-flag, bukan ditebak.
- **Rerun harus idempoten**; semua script cek-dulu-skip.
- **Rate limit**: maks 10 worker paralel, 3 retry backoff pada 429/5xx, timeout 90s.
- **Destruktif (cancel/delete dokumen ber-ledger, rewarehouse massal)**: ikuti
  prosedur yang terdokumentasi (§6) dan catat di `PROJECT_STATE.md`.
- **Update `PROJECT_STATE.md`** tiap akhir sesi kerja (status, changelog) —
  file itu yang dibaca AI berikutnya untuk tahu kondisi terkini.

## 10. Glosarium

| Istilah | Arti |
|---|---|
| Outlet / division | Unit penjualan eResto; di ERPNext menjadi **Company** |
| FRC | Franchise (nama company mengandung `(FRC)`) — dikecualikan dari pendapatan grup |
| Tier / Price Group | Tingkat harga per tipe outlet; pemilik Price List POSNext |
| Shift | Sesi kasir (`SHIFT 1` 0:00–23:59, `SHIFT 2` 05:00–14:00) |
| Dough / matang / bundle | 3 tingkat barang: PJ* (pabrik) → PJO* (outlet) → RP*/CR*/GM* (jual) |
| WO | Work Order; tahap app: Persiapan → Material → Pre-Packing → Post-Packing → Finish |
| MR / serah terima | Material Request — serah terima bahan gudang→produksi (form order) |
| SE / TFM / MFG / MT / Repack | Stock Entry; tipe: Transfer for Manufacture, Manufacture, Material Transfer, Repack |
| RECO | Stock Reconciliation (opening/penyesuaian stok, qty absolut) |
| PINV / POPEN / POCLO | POS Invoice / POS Opening Shift / POS Closing Entry |
| MR Purchase | Material Request tipe Purchase — penghubung PO ↔ kebutuhan bahan |
| OC / complimentary | Order total 0 tanpa refund (dikeluarkan dari revenue) |
