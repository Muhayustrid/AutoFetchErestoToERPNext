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
> sebagai acuan navigasi; API counterpart-nya sebagian sudah di-probe
> (`/v2/purchases`, `/v2/purchase_invoices` — §4). Cara menambah route
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
- Pagination: `page` (mulai 1), `per_page=200`; andalkan `meta.next_page` /
  `meta.total_count` — **jangan berhenti hanya karena `len(batch) < per_page`**
  (terbukti memotong: 1–30 Sep 2026 terukur 4.645 SA di 4 Okt, sebenarnya
  **11.319 SA / 57 halaman** — `meta.total_count` 11.319, terukur ulang 21 Okt).
  Dedup by `id`; `meta.total_count` bisa bergerak saat fetch (data live).
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
| `/v2/stock_adjustments` | `date[geq/leq]` day-name (seperti refunds), `sort[property]=updated_at` + `sort[order]=desc`, `division_id=` kosong = semua divisi | item ada di endpoint terpisah; `per_page=200` |

---

## 4. eResto API — endpoint

| Data | Method | Endpoint | Kontrak singkat |
|---|---|---|---|
| POS order list | GET | `/v3/orders` | `data[]` type `simple_order`, field di `attributes`: `order_no` (`OR<branch>.<DDMMYY>.<seq>`), `outlet_id/name/branch_number`, `date`, `cashier_name`, `item_quantity`, `void_quantity`, `payment` (`receipt_number PY...`, `total`, `cash_amount`, `ewallet_amount`, `credit/debit/transfer_amount`). **Tanpa line item.** |
| POS order detail | GET | `/v3/orders/{order_id}` | `{"data":{"type":"order","attributes":{...}}}` — **unwrap `data.attributes`** (capture lama: `attributes` di root — handle keduanya). `order_items[]`: `product_sku`, `product_name`, `quantity`, `price`, `discount_item_amount`, `tax_amount`, `void`, `void_note`, `void_quantity`, **`paid_quantity`**. Payment + `sub_total`, `rounding_amount`, `voucher_amount`, `refunded_at`, `return_amount`. **Satu-satunya sumber SKU (pola N+1).** |
| Refund list | GET | `/v2/refunds` | root `{"refunds":[...], "meta":{"total","total_count"}}`. Row: `note`, `created_at`, `outlet.name`, `payment`, `order{order_no, order_status: void}`. 2/308 baris `order: null` (refund pembayaran standalone). |
| Production list | GET | `/v2/productions` | `production_number` (`045.DDMMYY.NNNNNN`), `division_id`, `date`, `note` ("Masak shift 3"), `transaction_group.transactions[]` (jurnal otomatis: Dr Finished Good `1 1 03 03` / Cr Semi Finished `1 1 03 02`). Detail BOM per produk belum dipetakan. |
| PO list (legacy) | GET | `/v2/purchases` | dipakai CLI PO legacy |
| Purchase Request list | GET | `/v2/purchase_requests` | User browser capture HTTP 200 (2026-10-30): root `purchase_requests[]` + `meta`; headers `id`, `request_no`. `created_at[geq/leq]` day-name, `division_id`, `po_status=uncreated`, updated_at descending, page/per_page (20 captured). Follow `meta.next_page`; uncreated-PO subset, not all PRs. Item fields/detail endpoint remain unverified; see `docs/01-eresto-api.md` §Purchase Requests. Not ERPNext Purchase Receipt. |
| PO detail (legacy) | GET | `/v2/purchases/{id}/detail` | fallback `/v2/purchases/{id}` |
| **Faktur pembelian (list)** | GET | `/v2/purchase_invoices` | root `{"purchase_invoices":[...],"meta":{...}}`. Filter `transaction_date[geq/leq]` format **ISO** (`YYYY-MM-DD HH:mm:ss.SSS`, day-name juga jalan) + `division_id`, `sort[property]=transaction_date`. Row: `transaction_number` (`INV<branch>.<DDMMYY>.<seq>`), `transaction_date`, `status` (`paid`/`unpaid`), `total_amount`, `balance_due`, **`purchase_id`** + `purchase.purchase_number` (link ke PO), `purchase_invoice_items[]` (embed `inventory_id` + item), `vendor_ref_no`. Tanpa filter: 13.203 faktur / 2.641 halaman. **Jebakan: `purchase` embedded TIDAK memuat tanggal PO** → tanggal PO harus diambil dari `/v2/purchases/{purchase_id}/detail`. |
| Stock adjustment list | GET | `/v2/stock_adjustments` | root `{"stock_adjustments":[...],"meta":{...}}`. `number` = `SA<branch>.<DDMMYY>.<seq>` (branch **alnum**: `SA220.`, `SAO77.`), `reason` = catatan dokumen (`SO Monthly September`, `Auto stock balancing`, `PENGAMBILAN HARIAN ...` — **teks bebas**). Embed `division` (outlet: `name`, `branch_number`), `stock_adjustment_type` (`name` "Stock Opname"/"Opening Stock"/"Adjusmen Beli Inventory outlet"/"Adjusment Jual Inventory Outlet"/"Adjustment Stock Out"/"Reject Outlet"/"Keperluan Produksi"/"Cangkang Telur"/"Keperluan RnD", **`adjustment_type`** `adjustment`\|`loss`\|`add`\|`new`, `account_id` akun lawan), `transaction_group` (jurnal otomatis `automatic: true`, `transactions[]` kaki jurnal `account_number`/`account_name`/`debit_amount`/`credit_amount`). **Jebakan: field root `adjustment_type` selalu null** — penentunya `stock_adjustment_type.adjustment_type`. Detail `/v2/stock_adjustments/{id}` tidak menambah apa pun. |
| Stock adjustment items | GET | `/v2/stock_adjustment_items?stock_adjustment_id={id}` | `current_quantity` (sistem), `real_quantity` (fisik), `adjustment_quantity` = real−current, `adjustment_value` (Rp), `reason` **per item** (hanya auto-balancing: "…- inbound"/"…- outbound"; dokumen lain null), `unit.name`, embed `inventory` (sku/nama) + `division` + `stock_card` (`initial_stock`/`stock_in`/`stock_out`/`stock_balance`). `meta.total_value` = checksum **hanya sah untuk tipe `adjustment`/`add`/`new`**; tipe `loss` → meta 0 walau Σ item ≠ 0. Item selisih 0 tetap termuat → `real_quantity` = stok fisik utuh. Qty bisa **negatif** (eResto boleh). |
| Inventories (live) | GET | `/v2/inventories` | tiap inventory punya `division_inventories[]` (`division_id`, `quantity`). Stok berjalan, bukan snapshot opname. |
| Stock cards (mutasi) | GET | `/v2/stock_cards?division_id=...` | `reference_type = Production` = hasil masak masuk; `ProductionResultItem` = bahan terpakai keluar (docs/05). |

Volume acuan (terukur 1–4 Okt 2026): 27.053 order / 137 outlet / Rp709 jt;
±9.4k order/hari; refund ≈1.1%/hari.

---

## 5. Aturan bisnis yang tidak boleh dilanggar

**Mapping SKU & item** (sumber kebenaran TUNGGAL sejak 2026-10-13:
`docs/02-erpnext-mapping.md` — tabel SKU terurut; 172 SKU per 14 Okt + 3
tambahan `BB0039`/`BB0152`/`BB0162`; semua kode diverifikasi ada di BARU;
CSV `experiments/*.csv` hanya arsip/turunan — jangan menebak):

- Kunci mapping = **`product_sku`**, tidak pernah nama. Satu SKU = satu nama.
  Produk sama bisa beda SKU per tipe outlet: `PR001/PR002/PR003` (owned) vs
  `P0004/P0001/P0002` (franchise) → semuanya ke `RP001/002/003`.
- Kode eResto ≠ kode ERPNext (jebakan nyata: eResto `PG001` = Roti Gempi,
  ERPNext dulu `PG001` = "Goodie Bag 6 Roti" — **item legacy ini sudah
  di-merge ke `PEL260072` "Goodie Bag" & dihapus 2026-10-09**).
- Goodie Bag kanonik = **`PEL260072`** (keputusan user 2026-10-09):
  eResto `BB0066`/`PKG01` → `PEL260072`; jangan pakai `PG001` lagi
  (sudah tidak ada; `POS Package` "Paket Goodiebag 6 ROPI" memakai
  `PEL260072`).
- Item POS = **Product Bundle non-stok**; stok ada di komponen.
- Rantai barang tetap (docs/05): **dough (Pabrik `PJ*`) → matang (Outlet `PJO*`)
  → bundle jual (`RP00x`/`CR001`/`GM00x`)**. Yield terukur: 1 pack Ropi → 12 pcs,
  Gempi → 3, Croissant → 6. Pengecualian: `PJ260015` Dubai Dough dijual sebagai
  dough (tanpa matang/bundle) — jangan dibuatkan PJO.
- `PJO2601–2605` tidak punya SKU POS; jangan dipetakan sebagai item jual.
- **Alur repack bahan baku (Gula Cair & Olesan Pastry):**
  - **Gula Cair:** dibeli purchasing dalam kg, gudang receipt dalam ctn (25 kg/ctn) dan disimpan dalam ctn. Gudang merepack ke botol 250 g untuk kiriman PO outlet. Master bulk = `BB26008` (kg); master hasil repack = `BB26009` (Gula Cair 250 g, Botol).
  - **Olesan Pastry (aturan tanggal — keputusan user 2026-10-12):** untuk PO ke
    supplier **PT. JUARA ROTI INDONESIA**, item "Olesan Pastry" pada PO
    **BER-TANGGAL SETELAH 8 OKTOBER 2026** wajib memakai **`BB26012`
    ("Olesan Pastry (250 g)", stock_uom `g`, UOM Botol = 250 g)** — BUKAN
    `BB260046` ("Olesan Pastry", bulk). PO ber-tanggal **≤ 8 Okt 2026** tetap
    `BB260046` (data historis, jangan diubah). Pemetaan SKU eResto:
    `BB0174` ("TIDAK AKTIF Olesan Pastry") & `BB0352` ("Olesan Pastry 250g") →
    `BB26012` bila tanggal PO > 2026-10-08, selain itu → `BB260046`.
    Gudang merepack bulk `BB260046` (kg/ctn) ke botol 250 g `BB26012` untuk
    kiriman ke outlet. Ambang batas: `PO_DATE > 2026-10-08`.

**Work Order & Production Plan (pabrik, `production_app`):**

- **1 baris Production Plan = 1 WO.** Menghapus WO lalu membuat ulang dari UI
  bisa salah nempel ke baris plan lain (kasus nyata 2026-10-09: WO-061 Krim Kopi
  rebind ke baris 60 milik WO-060 → submit WO-060 ditolak *"... exceeds the
  remaining allowed quantity 12.5"*).
- **Ganti WO = jangan cancel-hapus-recreate dari UI.** Rebind eksplisit
  `production_plan_item` WO yang ada, lalu luruskan `ordered_qty` baris plan
  (Σ qty WO submitted per baris). Pola script + verifikasi:
  `pos_sync/fix_wo_061_rebind_9okt.py`.
- **Gate qty native v16** (`ProductionPlanWorkOrderQuantities`, jalan saat
  `before_submit`): `max = planned_qty × (1 + overproduction%/100) − Σ WO
  submitted lain di baris itu`. Overproduction JURI = 50. Pesan error di app
  produksi tampil sebagai **"Persiapan Gagal"**.

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

**Sumber input pembelian (keputusan user 2026-10-08):**

- **PI site LAMA = test/trial saja; site BARU = data sebenarnya.** Jangan
  pakai PI lama sebagai acuan pembayaran; yang mengikat = dokumen BARU.
  **Jangan migrasi PI dari site lama ke site baru** (audit 2026-10-09:
  5 PI lama — `PI-011026-001/002`, `PI-270826-001`, 2 downstream
  `PI-250926-*` — 0 ada di BARU; sudah dicek nama/total/supplier/item).
- Sebelum input PO/pembelian dari eResto: **cek dua site dulu** (lama + baru,
  cocokkan supplier + tanggal + item/qty sadar-UOM). Dokumen yang sudah ada
  menang; eResto hanya acuan silang (nomor faktur, tanggal, harga).
- eResto = transaksi nyata (PO, penerimaan, faktur supplier, penjualan) tapi
  TANPA jurnal/PPN/hutang/valuasi — akuntansinya hanya ada di ERPNext.
- Dua pintu input tanpa cek silang = akar duplikat (kasus nyata: 26 draft PO
  eResto duplikat PO native + 3 pasangan stok dobel, dibersihkan 2026-10-08
  via `pos_sync/bersih_po_juri.py`).
- Antrean `Repost Item Valuation` bisa tertunda — poll sampai `Completed`
  sebelum menyimpulkan angka stok/valuasi dari Bin. Bila worker tidak jalan:
  `POST /api/method/erpnext.stock.doctype.repost_item_valuation.repost_item_valuation.execute_repost_item_valuation`
  (whitelisted, memaksa enqueue job).

**Lane "PO outlet → supplier gudang internal JURI" (eResto `internal_supplier`):**

- Sumber = eResto `/v2/purchases` (`internal_supplier = true`). "Supplier" di sini
  adalah **gudang internal JURI**, bukan vendor luar. Nama gudang eResto → gudang
  asal JURI (peta `WAREHOUSE_MAP` di `migrate_po_juri_9_12_okt.py`):
  `Gudang Barang Jadi - PH Klaten` → `Gudang Barang Jadi - JURI`;
  `Gudang Jakarta` → `Gudang Jakarta - JURI`; `Gudang Outlet - PH Klaten` →
  `Gudang Outlet - JURI`; `Gudang Bahan Baku - PH Klaten` → `Gudang Bahan Baku - JURI`;
  `Gudang Peralatan Klaten` → `Gudang Peralatan - JURI`;
  `Gudang Produksi Klaten` → `Gudang Produksi - JURI`; dll.
- **Jangan tertukar arah:** "PO Gudang Jakarta" di proyek ini = PO dgn
  **`supplier.name = 'Gudang Jakarta'`** (Gudang Jakarta **menjual/mengirim** ke
  outlet; Company = divisi outlet pemesan, mis. `RSUD SEKAYU BANYUASIN`).
  **BUKAN** PO dgn **divisi pemesan** `Gudang Jakarta` (yang terakhir ini =
  Gudang Jakarta **membeli** dari vendor luar — `POCK2.*`, supplier
  Tokopedia/Arta Boga/Ayla Java; itu lane eksternal, bukan lane ini). Dua hal
  ini mudah tertukar saat audit; cek field mana yang bernilai `Gudang Jakarta`.
- Bentuk dokumen per PO (ID identik eResto via `rename_doc`):
  - **Outlet biasa → Purchase Order**: `company` = divisi outlet pemesan;
    `supplier` = `PT. JUARA ROTI INDONESIA`; `set_warehouse` = `Stores - <ABBR>`
    (gudang penerimaan outlet); `set_from_warehouse` = gudang JURI asal (peta di
    atas); `buying_price_list` = `Harga Outlet`; baris `expense_account` =
    `4210.000 - HPP Pembelian - <ABBR>`, `cost_center` = `Main - <ABBR>`.
  - **Outlet FRC (divisi `... (FRC)`) → Sales Order** (keputusan user: franchise
    langsung jadi customer): `company` = `PT. JUARA ROTI INDONESIA`,
    `customer` = internal FRC (`Customer` group `Outlet Franchise`, cocokkan by
    `customer_name`), `set_warehouse` = `Gudang Barang Jadi - JURI`,
    **tanpa** `inter_company_order_reference`.
- **ANTI-DUPLIKAT 3 LAPIS — jangan pernah andalkan ID saja** (permintaan user
  2026-10-14): sebuah PO dianggap sudah ada bila cocok **salah satu**:
  (a) nama dokumen == nomor PO eResto; (b) `title == 'ERESTO <nomor-PO>'`
  (menangkap dokumen dgn nama series fallback); (c) **signature isi** =
  `company + supplier + transaction_date + grand_total + multiset (item_code, qty)`.
  Untuk SO FRC: title ATAU signature `(item_code, qty)`. Lapis (c) menangkap
  duplikat yang dibuat manual / ID beda tapi isi kembar.
- **Urutan cek penting**: cek duplikat (name/title) **sebelum** validasi item;
  kalau tidak, PO yang sudah ada tapi memakai SKU tak-termap / item Olesan
  Pastry akan salah masuk `Skipped` alih-alih `SKIP_EXISTS`.
- Status eResto `rejected`/`canceled` **tidak** dimigrasi. Status default draft
  bisa dipaksa (`FORCE_DRAFT`) atau mengikuti eResto — ikuti instruksi user.
- SKU tanpa padanan Item **tidak ditebak** — baris/PO di-skip & dicatat.
  (mis. `BB0043` "Daun Teh Enak Kata Orang" belum ada padanan di BARU →
  dipakai di 10 PO (1 Sep–15 Okt), 6 di antaranya supplier Gudang Jakarta/GBJ;
  baris dikeluarkan & dicatat, bukan ditebak.)
- **Rename PO/SO butuh `allow_rename` sementara** (Purchase Order & Sales Order
  `allow_rename = 0`): lihat jebakan §6.8a. Bila rename gagal, dokumen tertinggal
  dgn nama series (`PO-.ABBR.-.YY..MM..DD.###`); self-heal lewat cek `title`.
  **Jebakan #8b: kegagalan rename itu SILENT** — POST bisa `200` tapi rename
  `417`; wajib cek status rename & panggil `ensure_allow_rename` SEBELUM create.
- **Jendela yang belum digarap = sumber gap besar.** Jangan asumsikan
  "PO lama sudah dimigrasi": 2026-10-14 ditemukan **seluruh September 2026
  (1–24 Sep) belum pernah digarap** untuk supplier `Gudang Jakarta` (67 PO
  regular hilang; Sekayu 4 PO). Cara audit cepat: tarik `/v2/purchases` jendela
  lebar, filter supplier-gudang, banding dgn index dokumen BARU (name+title).
  Skrip rentang: `migrate_po_gudang_jakarta_window.py --from --to`.
- Skrip per jendela mengikuti pola sama, jangan saling menimpa cache/laporan:
  `migrate_po_juri_9_12_okt.py`, `migrate_po_juri_13_14_okt.py`,
  `migrate_po_gudang_jakarta_9okt.py` (satu tanggal),
  **`migrate_po_gudang_jakarta_window.py`** (rentang tanggal, `FORCE_DRAFT`,
  `EXTRA_ITEM_MAP`), dan **`migrate_po_gbj_klaten.py`**
  (supplier `Gudang Barang Jadi - PH Klaten`, CLI
  `--dump/--refresh/--dry-run/--verify/--date-from/--date-to`, laporan
  auto-nama per jendela).


**Stock & item kanonik (keputusan user 2026-10-09):**

- **Stock minus DILARANG** — `Stock Settings.allow_negative_stock = 0`
  permanen di cloud baru (dikunci setelah 0 Bin negatif; submit yang membuat
  minus ditolak `NegativeStockError` — terverifikasi smoke test). Jangan
  menyalakannya tanpa izin user; kalau terpaksa (backfill), sementara +
  restore di `finally`. Kekurangan stok = catat pergerakan riil
  (repack/receipt/transfer), bukan buka izin minus.
- **Goodie Bag kanonik = `PEL260072`.** Item legacy `PG001` "Goodie Bag 6
  Roti" sudah **di-merge** ke `PEL260072` (rename_doc merge=1: SLE, POS
  Invoice, SE, RECO, POS Package ikut pindah) lalu dihapus 2026-10-09 —
  jangan pakai `PG001`. POS Package "Paket Goodiebag 6 ROPI" memakai
  komponen `PEL260072`; `PKG01` (eResto) -> `PEL260072`.
- **Barang in-transit (`Goods In Transit - JURI`) — jangan dibalikin lewat
  transit lagi.** Dua SE migrasi 8 Okt (`SE-MTF-261009020/021`) berisi 12 item
  kiriman ke Gudang Jakarta; kalau barang **sudah ada di GIT**, perbaikan =
  **end-transit `GIT → Gudang Jakarta`** (satu Stock Entry), GBJ **tidak
  disentuh**. Jalur `GBJ → GIT → Jakarta` membuat GBJ keluar **2× qty** →
  minus (terukur `PJ260013` −17.832, `PJ260012` −13.716, `PJ260014` −20.856,
  `PJ260010` −2.958 Pcs). Kalau GIT **kosong**, baru kompensasi RECO
  penyesuaian (`5110.020`) ke GBJ lalu transfer. Skrip:
  `pos_sync/endtransit_cloud_jakarta.py` (cloud),
  `pos_sync/fix_git_jakarta_ke_gbj_transfer.py` (lokal),
  audit: `pos_sync/audit_cloud_jakarta_git.py`.
- **Stock adjustment eResto (SA) → dokumen stok ERPNext** (kontrak lengkap di
  `docs/01-eresto-api.md` §Stock adjustment; skill
  `.agents/skills/eresto-erpnext/SKILL.md` §Stock adjustment eResto):
  - 9 tipe `stock_adjustment_type` (terukur 1–30 Sep 2026, **11.319 SA** —
    angka lama 4.645 terpotong aturan stop pagination, andalkan
    `meta.total_count`/`meta.next_page`): `Stock Opname` (`adjustment`),
    `Opening Stock` (`new`), `Adjusmen Beli Inventory outlet` (`add`),
    `Adjusment Jual Inventory Outlet`/`Reject Outlet`/`Adjustment Stock Out`/
    `Keperluan Produksi`/`Cangkang Telur`/`Keperluan RnD` (`loss`).
  - **Peta tipe → dokumen ERPNext:** opname (`reason` `SO Monthly …` /
    `SO MID …` / `Periode …`) → `Stock Reconciliation` (qty absolut) akun
    `5110.020 - Penyesuaian Stock`; `Opening Stock` → RECO opening
    `1171.000 - Pembukaan sementara`; `Adjusmen Beli` + `Adjusment Jual` =
    **satu** transfer antar outlet (nilainya berlawanan & sama → Stock Entry
    transfer, jangan dua RECO); `Adjustment Stock Out` = pengambilan gudang →
    Stock Entry (Material Transfer/Repack); `Reject Outlet`/`Cangkang Telur`/
    `Keperluan RnD` → RECO penyesuaian; `Keperluan Produksi` → Stock Entry
    Manufacture. `Stock Opname` ber-reason **`Auto stock balancing`** =
    koreksi delta sistem (~10,8k/bulan) → **jangan post**, jejak audit saja.
  - Idempotensi marker: `remarks = "ERESTO SA<number>"` (dokumen tanpa
    `remarks` → `title`), cek-dulu-skip. Nomor SA = `SA<branch alnum>.<DDMMYY>.<seq>`.
  - Klasifikasi jangan pakai field root `adjustment_type` (selalu `null`);
    penentunya `stock_adjustment_type.adjustment_type`
    (`adjustment` | `loss` | `add` | `new`).
  - Checksum `meta.total_value` **hanya sah untuk tipe `adjustment`/`add`/`new`**;
    tipe `loss` meta = 0 walau Σ item ≠ 0 → jangan gagalkan batch karena itu.
  - `reason` = teks bebas (opname: `SO Monthly September` 123, `SO MID
    SEPTEMBER` 14, `Konfirmasi` 6, `Periode 1 Bulan September` 6, `Revisi`,
    `PENYAMAAN STOK DOUGH`, …) → **filter opname = tipe `Stock Opname` AND
    `reason != "Auto stock balancing"`** (210 dokumen di Sep 2026; filter
    `reason == "SO Monthly September"` saja cuma dapat 123).
  - **eResto mengizinkan qty negatif** (`current_quantity` −60, `real_quantity`
    −0,5) → target RECO negatif tidak valid, keluarkan & catat.
  - SKU SA bisa berakhiran `-b` (varian: `BB0121-b` "Plastik Paking Dough",
    `BB0155-b` "Karet Gelang"); SKU dasar bisa sudah di-rename jadi "Deleted 1"
    → map by SKU, tak ada di `docs/02` → keluarkan & catat (jangan tebak).
  - RECO backdated di atas saldo minus ditolak `NegativeStockError`
    (`allow_negative_stock=0`) → catat pergerakan riil, jangan buka flag.
- **Konversi UOM dokumen LAMA → stok BARU**: dokumen LAMA memakai UOM baris
  (`Pack`, `Kg`) dan site BARU `stock_uom` bisa beda (`Pcs`, `g`) dengan
  `conversion_factor` **berbeda per item** (`PJ260010` cf=6, `PJ260011` cf=3,
  `PJ26001x` lain cf=12; `BB260043` kg=1000). Ambil CF dari **master Item
  site BARU** — jangan asumsikan 1:1, dan `Kg` (K besar) ≠ `kg` (lowercase).

- **Dokumen cancelled tidak dibiarkan menumpuk**: `pos_sync/bersih_dokumen_cancelled.py`
  menghapus permanen dokumen docstatus=2 (scope company, dry-run default).

- **Urutan hapus dokumen cancelled**: backup JSON per dokumen -> purge
  POS Print Log -> `Accounts Settings.delete_linked_ledger_entries=1`
  (sementara) -> hapus berurutan dependency-safe (SE amended dulu, PR
  sebelum PO) -> restore setting -> verifikasi `docstatus=2` sisa 0,
  Bin net-zero, GL/SLE/PLE per nama 0.

- **Akun RECO (kanonik, 2026-10-09):** dokumen `Stock Reconciliation`
  ber-`purpose = "Opening Stock"` (pembukaan 30 Sep 2026 23:00) memakai
  `1171.000 - Pembukaan sementara` — **satu dokumen per gudang**, posting
  `2026-09-30 23:00:00`. Dokumen penyesuaian/operasional (purpose
  `"Stock Reconciliation"`) memakai `5110.020 - Penyesuaian Stock`.
  Jangan campur; konsolidasi awal 2026-10-09 memakai
  `pos_sync/konsolidasi_opening_reco.py` (plan/execute/cleanup/report).

- **Warehouse testing DIHAPUS (keputusan user 2026-10-09):** "Gudang
  Finished Goods Testing / Gudang Testing Manufacture / WIP Testing — stock
  di web lama cuma testing aja, hapus ajaa." Ketiganya dihapus di **LAMA**
  (`- ROPI`) dan 2 padanannya di **BARU** (`Gudang Testing Manufacture -
  JURI`, `WIP Testing - JURI`) via `pos_sync/hapus_warehouse_testing.py`;
  4 SE + 2 draft testing LAMA & 2 RECO opening testing BARU ikut dihapus.
  Jangan buat ulang ketiga gudang ini di script migrasi/opening.

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
7a. **Cancel RECO di ERPNext v16 menggeser seluruh trail setelahnya**
    (`update_qty_in_future_sle`: shift `-qty`, dipotong di "RECO berikutnya"
    yang masih visible). Konsekuensi: (a) membatalkan RECO lama bisa
    memunculkan kembali saldo minus yang dulu ditutupnya dan **submit ulang
    RECO di timestamp lama bisa DITOLAK `NegativeStockError`** bila anchor
    (saldo sebelum timestamp itu) negatif — bahkan dengan baris zero-out;
    (b) urutan cancel harus **ascending creation** agar batas "RECO berikutnya"
    tetap terjaga. Kalau recreate ditolak karena anchor negatif: jangan paksa
    flag — pulihkan efeknya via **SE Material Receipt** (qty = |saldo minus|,
    rate sama, expense 5110) supaya Bin → 0; jalur ini setara dan tidak butuh
    `allow_negative_stock`.
7b. **RECO zero-out (`qty=0`) tak bisa di-recreate tanpa flag** bila saldo
    saat itu negatif (validasi anchor v16). Untuk dokumen semacam ini:
    biarkan cancelled (dihapus), ganti efeknya dengan Material Receipt
    (lihat `pos_sync/restore_sr7_zeroouts.py` sebagai contoh).
8. **Update setelah submit:** `before_save` tidak jalan → pakai Property Setter
   `allow_on_submit=1` sementara + `frappe.client.set_value`, lalu pulihkan ke 0.
8a. **Rename dokumen dengan `allow_rename=0`** (mis. Purchase Order, Sales Order):
   `frappe.client.rename_doc` menolak `HTTP 417 ValidationError: ... not allowed
   to be renamed` (validate_rename cek `meta.allow_rename`). Bikin **Property
   Setter** `{doc_type, property=allow_rename, property_type=Check, value=1}`
   sementara → rename → **hapus** setter (bila dibuat barusan) atau kembalikan
   ke 0. Pola ini wajib agar ID dokumen bisa disamakan dgn nomor PO eResto;
   kalau lupa, POST tetap berhasil tapi dokumen tertinggal dgn nama series
   (`PO-.ABBR.-.YY..MM..DD.###`) → self-heal lewat cek `title = 'ERESTO <PO>'`.
8b. **Jebakan #8a SILENT kecuali status HTTP rename dicek.** Kasus nyata
   2026-10-14: lane PO Gudang Jakarta rentang-September membuat 60 PO sukses
   (`HTTP 200`) tetapi **seluruh 60 `rename_doc` gagal `417`** — script hanya
   mencetak status, tidak raise, jadi dokumen jatuh ke nama auto `PO-<ABBR>-...`
   dan user melihat "ID eResto tidak dipakai". **Aturan: di lane tulis mana pun,
   `ensure_allow_rename(dt)` dipanggil SEBELUM create bila akan rename; dan
   periksa status rename (`st == 200`), jangan hanya andalkan "POST sukses".**
   Perbaikan massal: `pos_sync/fix_rename_po_jakarta_window.py` (nyalakan setter →
   rename per `title` marker → hapus setter → verifikasi 0 sisa). Helper rujukan:
   `migrate_mr_po_25sep_7okt.ensure_allow_rename`, `migrate_pi_central_okt.ensure_allow_rename`.
8c. **"Buat semua DRAFT" ≠ ikut status eResto.** Beberapa lane punya flag
   `FORCE_DRAFT` (mis. lane PO Gudang Jakarta rentang) — docstatus 0 apa pun
   status eResto. Jangan campur dengan default lane lain
   (`processing/completed`→submit). Tentukan per instruksi user, catat di laporan.
9. **Payment Ledger Entry read-only via API** (403). Hapus dokumen ber-ledger:
   cancel → purge Print Log → set `delete_linked_ledger_entries=1` sementara di
   Accounts Settings → delete → pulihkan 0.
9a. **Hapus Warehouse:** (i) `on_trash` menolak bila masih ada SLE (walau
    cancelled), Bin ber-qty, atau child warehouse; Bin kosong & Item Default
    di-unlink otomatis. (ii) Link-check Frappe menolak delete bila ada dok
    lain docstatus≠2 yang merefer: termasuk **Repost Item Valuation** (jejak
    repost) — RIV `Queued` tak bisa di-cancel (before_cancel menolak), jadi
    set status→`Skipped` via **Property Setter `allow_on_submit` sementara**
    (pola #8) → cancel → delete → buang setter. (iii) Di site LAMA
    `Accounts Settings.delete_linked_ledger_entries` **tak bisa disetel**
    (doc settings rusak: "Row #6 Doctype: Expense Claim"); jalur gantinya:
    **hapus langsung baris GL Entry & SLE yang `is_cancelled=1`** via REST
    (mereka tak lagi berdampak saldo tapi tetap dianggap link) → baru
    dokumennya bisa dihapus. Skrip: `pos_sync/hapus_warehouse_testing.py`.
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
18. **Ganti WO: jangan cancel-hapus-recreate dari UI** — pengganti bisa rebind
    ke baris plan lain → baris asal kehilangan WO, baris tetangga dobel →
    submit ditolak "*... exceeds the remaining allowed quantity ...*" (tampil
    di app sebagai "Persiapan Gagal"). Rebind `production_plan_item` + luruskan
    `ordered_qty` (lihat §5 "Work Order & Production Plan").
19. **Field yang tidak ada di DocType membuat SELURUH query gagal, bukan
    diabaikan.** Contoh nyata: `Material Request` menolak `custom_department`
    di `fields` → HTTP 417 `Field not permitted in query` — helper yang
    menelan error lalu mengembalikan `[]` membuat dokumen "hilang" tanpa
    jejak. **Selalu cek status HTTP di list helper**, jangan asumsikan list
    kosong = data kosong.
20. **Normalisasi akun, bukan hanya gudang.** Baris dokumen pembelian
    (`Material Request`, `Purchase Order`, `Purchase Receipt`) menyimpan
    `expense_account` (`4210.000 - HPP Pembelian - ROPI`) dan `cost_center`
    (`Main - ROPI`) — keduanya ikut `- ROPI` → `- JURI`, kalau tidak:
    `LinkValidationError: Could not find Row #1: Expense Account`.
21. **Template pajak beda NAMA antar site** (jangan andalkan suffix):
    LAMA `Purchase Tax - ROPI` (= PPN 11% **di atas** net) → BARU
    `Purchase Tax - JURI`; LAMA `Purchase Tax 11% (Include) - ROPI` →
    BARU `Purchase Tax (Termasuk Pajak) - JURI`. Template "Include" **tidak
    butuh baris pajak** (grand = net sudah benar); template "di atas net"
    butuh baris `taxes` eksplisit.
22. **Mengubah total dokumen ber-docstatus=1 butuh Property Setter untuk
    SEMUA field turunannya sekaligus** — bukan hanya `taxes`. Untuk PO:
    `taxes`, `total_taxes_and_charges`, `grand_total`, `rounded_total`,
    `base_grand_total`, `base_rounded_total`, `in_words`, `taxes_and_charges`.
    Lewat satu saja → `UpdateAfterSubmitError`. Dan `PUT` **tidak memicu
    recalc pajak** di v16: hitung `tax_amount`/`total`/`base_*` manual, kalau
    tidak barisnya masuk tapi bernilai 0.
23. **Idempotensi `title` menyeberangi penamaan berbeda.** Dokumen yang dulu
    dimigrasi dengan pola nama `PO-JURI-261004*` tetap dikenali lewat
    `title = "ERESTO <id-lama>"` — cari by name **dan** title sebelum
    menyimpulkan "belum ada".

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
| Migrasi PO eResto supplier Gudang Barang Jadi Klaten (13–14 Okt) | `pos_sync/migrate_po_gbj_klaten.py` (`--dump/--refresh/--dry-run/--verify/--date-from/--date-to`; outlet→PO draft, FRC→SO draft, anti-duplikat 3 lapis) |
| Migrasi SO + DN Outlet → JURI | `pos_sync/migrate_outlet_so_dn_to_juri.py` (`--dump/--prep/--so/--dn/--verify`) |
| Print format (header global) | `pos_sync/migrate_print_formats.py` (`--build/--push/--verify/--revert --stage local\|cloud`) |
| Catch-up delta harian | `pos_sync/catchup_oct7.py` (pola mengikuti) |

---

## 8. Indeks dokumen

| Doc | Isi |
|---|---|
| `docs/01-eresto-api.md` | Auth, endpoint, params, kontrak JSON eResto (dasar §3–4 di atas) |
| `docs/02-erpnext-mapping.md` | **Sumber tunggal mapping SKU→Item** (tabel SKU terurut; 172 +3 SKU 14 Okt) + outlet, payment, aturan void/refund, pilot 1 order, mapping stok SO |
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
