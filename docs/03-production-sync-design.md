# Production sync design — POS, production, purchase

Status: spike phase. Excel verification only. No ERPNext POST yet.

## Proven (measured)

- POS list + detail + recap scripts in `experiments/pos-fetch/`.
- Detail endpoint `GET /v3/orders/{id}` returns line items.
- 27,053 orders / 137 outlets / Rp709M fetched in ~6 min, no 429.
- SKU key is stable; void pattern is full-order only.
- Mapping CSV covers 100% of SKUs in 3 outlet-days.

## Phase 1 — aggregate sales (first ERPNext write)

One Sales Invoice or Journal per outlet per day: debit outlet cash
register (cash total) + debit e-wallet clearing (ewallet total),
credit POS revenue. Idempotency: `outlet_id + date`.
157–160 docs/day. No stock movement; eResto keeps stock truth
until cutover. Requires: site URL + API key, per-outlet
Customer/Warehouse/CostCenter/POS Profile, revenue/cash/clearing
accounts, FRC treatment decision. **Keputusan 2026-10-05: FRC
dikecualikan** (bukan pendapatan grup; lihat docs/02 "Outlet FRC
dikecualikan"). Skrip injeksi wajib skip outlet `(FRC)`.

## Phase 2 — per-transaction POS Invoice (optional)

One POS Invoice per `order_no` with mapped Item Codes, then daily
`POS Closing Entry` per outlet. ~9k docs/day. Requires approved
mapping CSV and full master data. Fallback is the Data Import Tool
with the PO script's parent/child row pattern.

## Phase 3 — production to Stock Entry

eResto `/v2/productions` → ERPNext Stock Entry (manufacture or
material transfer). **Rantai barang + resep yield sudah terverifikasi
(2026-10-04) — lihat `docs/05-alur-dough-ke-bundle.md`:** dough
(PJ*) → matang (PJO*), yield terukur Ropi 1 pack→12 pcs, Gempi 1→3,
Croissant 1→6. Pengecualian: `PJ260015` Dubai Dough Salt Butter
dijual sebagai dough (tanpa matang/bundle) — jangan tunggu output
matang untuknya. Sesi "Masak" terbaca di `/v2/stock_cards`
(`reference_type = Production` = hasil, `ProductionResultItem` =
bahan terpakai). Pilot outlet: Majenang branch 120 atau Kebumen
branch 045. eResto auto-journal (debit `1 1 03 03` Finished Good,
credit `1 1 03 02` Semi Finished) adalah reconciliation reference.
Bahan pendamping (Krim Kopi BB0085, Gula Cair BB0305) belum
teratribusi per produk di stock card — probe resep resmi dulu
sebelum jadi BOM.

## Phase 4 — purchase flow (legacy, reuse)

PO CLI at `/Users/rotiropi/Downloads/EResto_ERPNext_PO_Improved.py`
already handles fetch→Excel→manual import. Reuse its transport
and audit sheet pattern. Its hardcoded maps are stale (old-site
codes); rebuild supplier/item/warehouse maps against the new
site before reuse. Still manual import; API posting comes after
POS phases prove out.

## Stok outlet — SO Monthly September (sumber terukur 2026-09)

Snapshot stok fisik outlet yang lengkap dan paling baru: 93 dokumen
`SO Monthly September` (91 outlet), 2.782 baris item, checksum
93/93 cocok. Skrip `experiments/fetch_so_monthly.py`; output
`experiments/Stock_SO_Monthly_September.xlsx` (sheet `SO_Items`,
`Rekap_Outlet`, `Meta`) + `stock_so_monthly.json`.
`Auto stock balancing` **diskip total** (menurut user); item
ber-selisih 0 tetap termuat sehingga `real_qty` = hasil hitung
fisik utuh, bukan hanya koreksi.

- Kandidat seed stok outlet per SKU saat cutover/fase stok.
  Sekarang **belum dipakai** — eResto tetap stock truth.
- Butuh mapping baru: SKU inventory eResto (mis. `RR0001` Ropi
  Butter, `BB0046` Dough Butter, `BB0085` Krim Kopi) -> Item Code
  ERPNext. `sku_to_item_code.csv` (POS) tidak memuat SKU ini.
- Stok live (bukan snapshot) tersedia via `/v2/inventories`
  `division_inventories[]` bila nanti butuh angka berjalan.

## Cutover rule

eResto is stock truth during parallel run. ERPNext posts must
not move stock per SKU until cutover day. Aggregate sales
(Phase 1) complies by design.
