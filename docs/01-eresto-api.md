# eResto API — pengambilan data

Base URL: `https://ropi.eresto.id`. Tenant `ropi` is a path-level
subdomain; all calls below use it.

## Auth

Two parts, both required on every request:

1. Header: `Authorization: Token token={TOKEN}, email={EMAIL}`.
2. Query params: `token={TOKEN}`, `domain=ropi`,
   `current_user_id={USER_ID}`.

Plus headers: `Accept: application/json, text/plain, */*`,
`Referer: https://ropi.eresto.id/manager/v2/index.html`,
`User-Agent: Mozilla/5.0 ...`, `Cache-Control/Pragma: no-cache`.
Credentials live in env (`ERESTO_TOKEN`, `ERESTO_EMAIL`,
`ERESTO_USER_ID`). The known-good pair is the network-capture pair
(user `8fd6b4ec-...`), proven with HTTP 200 on `/v3/orders`.
The PO-script pair is unproven for orders.

## Endpoints

| Data | Method | URL pattern |
|---|---|---|
| POS order list | GET | `/v3/orders` |
| POS order detail | GET | `/v3/orders/{order_id}` |
| Refund list | GET | `/v2/refunds` |
| Production list | GET | `/v2/productions` |
| PO list (legacy) | GET | `/v2/purchases` |
| PO detail (legacy) | GET | `/v2/purchases/{id}/detail` (fallback `/v2/purchases/{id}`) |
| Purchase invoice list | GET | `/v2/purchase_invoices` (`transaction_date[geq/leq]`, ISO format) |
| Stock adjustment list | GET | `/v2/stock_adjustments` |
| Stock adjustment items | GET | `/v2/stock_adjustment_items?stock_adjustment_id={id}` |
| Inventories (SKU + stok per division) | GET | `/v2/inventories` (`division_inventories[]`) |
| Stock cards (mutasi) | GET | `/v2/stock_cards` |

Do not send `If-None-Match`. The browser capture returned 304
because of it; scripts without it always get 200.

## List query params (orders)

- `date[geq]` / `date[leq]`: `YYYY-MM-DD HH:mm:ss.SSS`
  (`00:00:00.000` to `23:59:59.999`). Production list uses
  `Sun, 4 Oct 2026 00:00:00.000` day-name format instead.
- `outlet_id`: UUID, empty = all outlets. Prefer per-outlet loops;
  one outlet failing must not cancel the rest.
- Refund list uses `created_at[geq]` / `created_at[leq]` (day-name
  format) plus `timezone=+07:00` instead of `date[]`.
- `division_id`: production list equivalent of `outlet_id`.
- `page` (from 1), `per_page` (use 200, not 20).
- `sort[property]=date`, `sort[order]=asc` (use asc for sync).
- Cache buster `_={timestamp_ms}`.

## Pagination

Stop when `meta.next_page` is null. Do **not** stop merely because
`len(batch) < per_page` — that rule truncated the September 2026 stock
adjustment pull (4,645 of 11,319 rows). Trust `meta.total_count` /
`meta.next_page`; `total_count` drifts while data is live.
Dedup by `id`. Retry transient codes
429/500/502/503/504, max 3 with backoff, 90s timeout.
Parallel detail fetch: max 10 workers. 160 details took 5.5s.

## JSON contracts

List item: `data[]` with `type: simple_order`, key fields under
`attributes`: `order_no` (`OR<branch>.<DDMMYY>.<seq>`),
`outlet_id`, `outlet_name`, `outlet_branch_number`, `date`,
`local_time`, `cashier_name`, `category`, `source`, `item_quantity`,
`void_quantity`, plus `payment` (`receipt_number` `PY...`, `total`,
`cash_amount`, `ewallet_amount`, `credit/debit/transfer_amount`).

Detail: `GET /v3/orders/{id}` returns `{"data": {"id", "type": "order",
"attributes": {...}}}` — unwrap `data.attributes` exactly like the list
(older captures showed `attributes` at root; handle both). Inside,
`attributes.order_items[]`: `product_name`, `product_sku`,
`product_id` (UUID), `quantity`, `price`, `discount_item_amount`,
`tax_amount`, `void`, `void_by`, `void_note`, `void_quantity`,
`paid_quantity`. Payment adds `sub_total`, `discount_amount`,
`rounding_amount`, `voucher_amount`, `ewallet_name`, `transfer_name`,
`refunded_at`, `refunded_by_id`, `return_amount`,
`sales_return_amount`. List has no line items; detail is the
only SKU source (N+1 pattern).

A dead/invalid token answers HTTP 500 `{"status":500,"error":
"Internal Server Error"}` on every endpoint (not 401). If all calls
suddenly 500, test another known token pair before assuming an outage.

Production list: root `{"productions": [...], "meta": {...}}`.
Row keys: `production_number` (`120.041026.000004`),
`division_id`, `date`, `note` ("Masak shift 3"),
`quantity`/`result_quantity`/`broken_quantity` (null at header
level), `transaction_group.transactions[]` (auto journal:
debit Finished Good `1 1 03 03`, credit Semi Finished Good
`1 1 03 02`). `division` embeds outlet (`branch_number`,
`category: outlet`, `parent_division: REGULER`,
`division_price_groups` with GrabFood/ShopeeFood/GoFood couriers).
Item-level BOM (inputs vs outputs) is not yet mapped; probe one
production detail before designing Stock Entry posts.

## Stock adjustment (SA) — opname & auto balancing

Two READ-ONLY endpoints:

| Data | Method | URL pattern |
|---|---|---|
| Stock adjustment list | GET | `/v2/stock_adjustments` |
| Stock adjustment items | GET | `/v2/stock_adjustment_items?stock_adjustment_id={id}` |

List params: `date[geq]`/`date[leq]` in **day-name** format (like refunds,
`Wed, 21 Oct 2026 00:00:00.000`), `division_id=` (empty = all divisions),
`page`, `per_page` (use 200), `sort[property]=updated_at` +
`sort[order]=desc` for incremental catch-up. Do not send `If-None-Match`
(browser capture answered 304 because of it). Root:
`{"stock_adjustments": [...], "meta": {current_page, next_page, prev_page,
total_pages, total_count}}`.

### Row contract (verified live 2026-10-21)

| Field | Content |
|---|---|
| `id` | UUID |
| `number` | `SA<branch>.<DDMMYY>.<seq>` — branch is **alphanumeric** (`SA220.211026.005`, `SAO77.211026.004`), do not parse it as digits |
| `reason` | document note — **free text, not standardised**: `Auto stock balancing` (10,840 of 11,319 in Sep), `SO Monthly September` (123), `SO MID SEPTEMBER` (14), `Periode 1 Bulan September` (6), `PENGAMBILAN HARIAN GUDANG BARANG JADI` (15), `From RSIA Nganjuk`, `BAJB-213 …`, `Reject expired close`, `Revisi`, `Konfirmasi` … |
| `date` | ISO with `+07:00` offset; `created_at` / `updated_at` likewise |
| `division` | embedded outlet: `name`, `branch_number` (e.g. `"220"`), `category: outlet`, `parent_division.name` (`REGULER`), `company`, price groups + couriers |
| `stock_adjustment_type` | embedded: `name` (9 types, see catalogue below), **`adjustment_type`** (`adjustment` \| `loss` \| `add` \| `new`), `account_id` (counterpart account of the auto journal), `default`, `company_id` |
| `transaction_group` | auto journal: `number` (`R211026143317795`), `automatic: true`, `note` ("auto journal posting for inventory stock adjustment SA…"), `transactions[]` = legs (`account_number`, `account_name`, `debit_amount`, `credit_amount` — **strings**, may be `"0.0"`), `cashflow_activity` |
| `deleted_at` / `synced_at` | both `null` on live rows — filter `deleted_at` anyway |
| root `adjustment_type` | **always `null`** — the real discriminator is `stock_adjustment_type.adjustment_type` |

Observed journal legs (21 Okt 2026, 107 SA): `1 1 03 03` Pesediaan Finished
Good ↔ `5 2 00 01` HPP Produksi (auto-balancing, 2 legs), and for warehouse
issue `6 1 01 25` Beban Operasional / `1 1 03 01` Persediaan Raw Matterial /
`2 1 01 07` Hutang Lain-lain (3 legs). Debit/credit order is not stable
(101 vs 5 flipped) — read per leg, never by position. Accounts seen across
Sep 2026: `1 1 03 01` Persediaan Raw Matterial, `1 1 03 02` Persediaan Semi
Finished Good, `1 1 03 03` Pesediaan Finished Good, `2 1 01 07` Hutang
Lain-lain, `5 2 00 01` HPP Produksi, `6 1 01 25` Beban Operasional, Piutang
Outlet, Opening Balance, Beban Perlengkapan Kantor, Cadangan Research and
Development, Aset Tetap - Peralatan Kantor, Peralatan dan Perlengkapan
Kemitraan.

`GET /v2/stock_adjustments/{id}` adds **nothing** over the list row — only the
aggregate journal. Line items live in `/v2/stock_adjustment_items`.
There is **no master endpoint** for the types: `/v2/stock_adjustment_types`
and `/v2/stock_adjustment_type` both answer 404 — the type object only comes
embedded in each row.

### Item contract

`current_quantity` (system before count), `real_quantity` (physical count),
`adjustment_quantity` = real − current, `adjustment_value` (IDR),
`current_cost` / `real_cost`, `reason` per item — **only** populated for
auto-balancing ("Auto stock balancing - inbound" / "- outbound"); for all
other document types the item `reason` is `null` and the note lives in the
header `reason`. `unit` embedded (`name`, `alias`), `inventory` embedded
(`sku`, `name`, `account_id`, `cost`, `conversion`), `division` embedded
(outlet), `stock_card` embedded (`initial_stock`, `stock_in`, `stock_out`,
`stock_balance` = mutation trail), `stock_adjustment` back-reference,
`synced_at` / `deleted_at`.

Zero-difference items are still returned, so `real_quantity` carries the
**full physical count**, not only the corrected rows.

**eResto allows negative quantities** — observed `current_quantity` = −60,
`real_quantity` = −0.5 / −4. ERPNext does not (`allow_negative_stock = 0`),
so a negative target count is not a valid RECO row.

Checksum: `meta.total_value` (string) vs `Σ adjustment_value` of the items —
**valid only for `adjustment` / `add` / `new` types**:

| SA | type | Σ items | `meta.total_value` | verdict |
|---|---|---|---|---|
| `SA116.300926.006` | Stock Opname (`SO Monthly September`) | −1,325,788 | −1,325,788 | match |
| `SA227.300926.002` | Adjusmen Beli Inventory outlet (`add`) | 694,148 | 694,148 | match |
| `SA186.010926.001` | Opening Stock (`new`) | 23,598,000 | 23,598,000 | match |
| `SA208.300926.006` | Reject Outlet (`loss`) | −58,900 | 0 | meta 0 — expected for `loss` |
| `SA133.300926.001` | Adjusment Jual Inventory Outlet (`loss`) | −694,148 | 0 | meta 0 — expected for `loss` |
| `SA171.300926.006` | Auto stock balancing | 0 | 0 | match (in/out cancel) |

So a validator that requires `Σ items == meta.total_value` **false-alarms on
every `loss` document**. For `Auto stock balancing` 0 means OK, not "empty".

Historical volume: 1–30 Sep 2026 = **11,319 SA / 57 pages** at
`per_page=200` (`meta.total_count` 11,319, re-measured 2026-10-21). The
earlier figure in this file (4,645 rows / 24 pages, measured 2026-10-04) was
**truncated** by the "stop when a page is shorter than `per_page`" rule — trust
`meta.total_count` / `meta.next_page` instead. Of the Sep set: 10,840
`Auto stock balancing` (system) and **210 physical-count documents** — every
row with `stock_adjustment_type.name = "Stock Opname"` and
`reason != "Auto stock balancing"`. Their `reason` values are free text
(`SO Monthly September` 123, `SO MID SEPTEMBER` 14, `Konfirmasi` 6,
`Periode 1 Bulan September` 6, `Revisi` 3, `rev` 2, `Counter 1 Sep` 2,
`PENYAMAAN STOK DOUGH` 2, `SO Monthly September Revisi` 1, `SO G.Produksi
30.09.26` 1, …) — **filter by type + "not auto balancing", not by reason
string**: `reason == "SO Monthly September"` alone returns only 123 of 210.
No row in the window has an empty `reason`.

### Type catalogue (1–30 Sep 2026) and ERPNext mapping

`stock_adjustment_type.name` / `adjustment_type` → what the document is →
the ERPNext document it becomes (new site):

| Type | `adjustment_type` | Meaning | ERPNext document |
|---|---|---|---|
| `Stock Opname` | `adjustment` | physical count (reason `SO Monthly …`, `SO MID …`, `Periode …`) | `Stock Reconciliation`, absolute qty, `5110.020 - Penyesuaian Stock` |
| `Stock Opname` | `adjustment` | system delta (reason `Auto stock balancing`, ~10.8k/month) | **do not post** — audit trail only (project already skips it) |
| `Opening Stock` | `new` | opening stock | `Stock Reconciliation` opening, `1171.000 - Pembukaan sementara` |
| `Adjusmen Beli Inventory outlet` | `add` | receiving side of an outlet-to-outlet transfer ("From RSIA Nganjuk") | `Stock Entry` transfer into the receiving outlet |
| `Adjusment Jual Inventory Outlet` | `loss` | giving side of the same transfer ("To RSUP Surakarta") | `Stock Entry` transfer out of the giving outlet |
| `Adjustment Stock Out` | `loss` | daily warehouse issue to outlets | `Stock Entry` (Material Transfer / Repack) warehouse → outlet |
| `Reject Outlet` | `loss` | rejected / expired goods at an outlet | `Stock Reconciliation` (`5110.020`) or Waste |
| `Keperluan Produksi` | `loss` | material for production | `Stock Entry` Manufacture / Material Transfer |
| `Cangkang Telur` | `loss` | eggshell waste | `Stock Reconciliation` / Waste |
| `Keperluan RnD` | `loss` | R&D trial | `Stock Reconciliation` (R&D expense) |

The "Beli"/"Jual" pair is one business movement with **equal and opposite
values** (e.g. ±694,148 on 30 Sep) → post **one** Stock Entry transfer, not
two RECO documents. Note the type names contain typos ("Adjusmen Beli",
"Adjusment Jual") — match on `stock_adjustment_type_id` / `name` exactly as
returned, do not hand-type spellings.

Account mapping to ERPNext follows the existing item/company master
(`docs/02-erpnext-mapping.md` + `lengkapi_item_defaults_semua.py`) — do not
guess account numbers from the eResto COA.

Idempotency marker for the RECO lane: `remarks = "ERESTO SA<number>"` (docs
without `remarks` → `title`), check-then-skip. `allow_negative_stock = 0` is
locked, so a backdated RECO above a negative anchor is rejected
(`NegativeStockError`).

SKU caveat: SA items can carry a `-b` variant SKU (`BB0121-b` "Plastik Paking
Dough", `BB0155-b` "Karet Gelang"), and the base SKU may already be renamed to
"Deleted 1" (`BB0121`). Map by `inventory.sku`; SKUs absent from
`docs/02-erpnext-mapping.md` are skipped and reported, never guessed.

Stok live (bukan snapshot opname): `GET /v2/inventories` ->
tiap inventory punya `division_inventories[]`
(`division_id`, `quantity`). 352 inventory; halaman 176
(`per_page=200`).

## Refunds (measured 2026-10-01..04)

`GET /v2/refunds` returns root `{"refunds": [...], "meta": {...}}`
with `meta.total` (sum) and `meta.total_count`. 308 refunds,
Rp11.58M over 4 days. Row keys: `note` ("salah input" 53%),
`refund_by_name`, `created_at`, `transaction_group_id`,
`outlet.name`, `payment` (original amounts, `status: refund`,
`receipt_number`, `pay_amount`, `cash_amount`), `order`
(`order_no`, `order_status: void`, `total: null`, `payment: null`).
2 of 308 rows have `order: null` (standalone payment refunds).

Refund voids the order: 301 of 304 void/zero orders in the sales
recap match a refund record. The 5 unmatched refunds belong to
orders outside the sales date window (29 Sep orders refunded
1 Oct; 4 Oct order created after the recap fetch). The 3 void
orders without refunds (all RSUD DR. R. SOETIJONO BLORA, zero
total, no void flag) are complimentary/OC, not refunds.
Sync rule: pull refunds by `created_at` window and join on
`order_no`; skip void orders from sales posts, keep refund rows
as the audit trail. Refund rate ≈ 1.1%/day, top outlets RSI
Muhammadiyah Kendal (33) and RSUD M. Yunus Bengkulu (25).

## Volume (measured 2026-10-01..04)

27,053 orders, 137 outlets, Rp709M over 4 days (~9.4k/day).
Per-outlet day: 19 (franchise) to 160 orders. Detail cost ≈
1 req/order; hourly incremental sync per outlet is the pattern,
never multi-day global pulls plus full N+1 in one run.

## POS UI source

`https://ropi.eresto.id/manager/v2/index.html#/sales_report/orders/orders`.
Cross-check 3 `order_no` values per fetch against this screen.
