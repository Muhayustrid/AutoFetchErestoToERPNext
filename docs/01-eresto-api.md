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

Stop when `len(batch) < per_page` or `meta.next_page` is null.
Dedup by `id`. Watch `meta.total_count` drift mid-fetch (live data:
27,049 at probe, 27,053 collected). Retry transient codes
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

## Stock opname (diukur 2026-10-04)

`GET /v2/stock_adjustments` (list, `date[geq/leq]` format day-name
seperti refunds). Periode 1-30 Sep 2026: 4.645 baris, 24 page
(`per_page=200`). `reason` = catatan dokumen; mayoritas
`"Auto stock balancing"` (sistem) dan `"SO Monthly September"`
(93 dokumen, 91 outlet). Detail dokumen
(`/v2/stock_adjustments/{id}`) HANYA memuat jurnal agregat; baris
item ada di `/v2/stock_adjustment_items?stock_adjustment_id={id}`
(embed `inventory` sku/nama dan `division` outlet/branch).

Field baris item: `current_quantity` (sistem sebelum opname),
`real_quantity` (hasil hitung fisik = stok opname),
`adjustment_quantity` = real - current, `adjustment_value`
(rupiah), `current_cost`/`real_cost`. `meta.total_value` =
checksum; jumlah `adjustment_value` harus sama (terbukti 93/93 di
`fetch_so_monthly.py`). Item ber-selisih 0 tetap termuat, jadi
`real_quantity` = stok fisik lengkap hasil hitung, bukan hanya
yang dikoreksi.

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
