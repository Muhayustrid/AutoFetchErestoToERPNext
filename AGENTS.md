# AGENTS.md — eResto → ERPNext Migration

Parallel POS migration for 160+ outlets. eResto stays live until cutover.
ERPNext records sales, production, and purchase data from the eResto API.

## Project state (mandatory)

- **New here / non-human reader: read `KNOWLEDGE.md` (repo root) first** —
  system map: what eResto, ERPNext baru and lama are, every URL/endpoint,
  business rules, and the proven Frappe API traps. Skill mirror:
  `.agents/skills/eresto-erpnext/SKILL.md`.
- **Before starting work: read `PROJECT_STATE.md`** — current phase,
  active tasks, blockers, design decisions, and known issues live there.
- **After finishing work: update `PROJECT_STATE.md`** — refresh Status,
  Active tasks, Next steps, Known issues, and add a dated Changelog entry
  (end of each work session, not each commit).
- Keep `PROJECT_STATE.md` short. Durable rules (style, constraints, flow)
  belong in this file; only what changes often goes in PROJECT_STATE.md.
  Never put tokens, API keys, or passwords in it.

## Commands

- Activate env: `source .venv/bin/activate` (repo root).
- Install deps: `.venv/bin/pip install requests pandas openpyxl`.
- Fetch POS list: `test_fetch_orders.py --date YYYY-MM-DD --outlet-id UUID`
  (needs `ERESTO_TOKEN`, `ERESTO_EMAIL`, `ERESTO_USER_ID` in env).
- Fetch POS details: `test_fetch_order_details.py --src <v1 xlsx>`.
- Sales recap: `test_sales_recap.py` (dates are constants at file top).
- No build step. No test suite. Verification is Excel output + checks
  printed to stdout (all must read OK/LOLOS).

## Project Structure

- `experiments/pos-fetch/` — throwaway spike scripts and Excel output.
  `test_*` files are probes, not production code. Never import from them.
- `experiments/Item.xlsx` — ERPNext Item master, new site (308 rows).
- `experiments/Template_Mapping_SKU.xlsx` — mapping workbench (human edits
  column E). `sku_to_item_code.csv` is the generated final mapping.
- `dokumen/` — import templates for the new ERPNext site
  (`Mode of Payment.xlsx`, `Fiscal Year.xlsx`). Root `Item (1).xlsx`
  is the fuller Item import template (309 rows with accounts).
- `Backup SIte Production/` — production DB backup 2026-10-04. Read-only.
- Production code goes in `pos_sync/` (planned, not yet created).
  See `docs/03-production-sync-design.md` before writing it.
- `/Users/rotiropi/Downloads/EResto_ERPNext_PO_Improved.py` — legacy PO
  CLI (purchase flow). Reuse its retry, ThreadPool, and normalize helpers.
  Do not port its hardcoded maps; codes changed on the new site.

## Coding Style

- Python scripts, stdlib first. Deps allowed: requests, pandas, openpyxl.
- Credentials only from env (`ERESTO_TOKEN`, `ERESTO_EMAIL`,
  `ERESTO_USER_ID`). Never hardcode tokens. Never print tokens.
- Match POS SKU by `product_sku`, never by name. One SKU = one name
  (verified). Same product can have different SKUs per outlet type
  (`PR001` owned vs `P0004` franchise); both map to one Item Code.
- Use `paid_quantity`, not `quantity`. Skip rows with `void=True`,
  `paid_quantity=0`, or header `total=0`. Keep `void_note` for audit.
- Idempotency key for ERPNext posts: `outlet_id + date` (aggregate) or
  `order_no` (per-transaction). Reruns must not duplicate.
- Sheet names in Excel output: `Raw_*`, `Rekap_*`, `Validation`,
  `Failed`. Freeze panes on A2, header fill `#D9EAF7`, bold, centered.

## Git Workflow

- No git repo yet. When created: branch per task
  (`spike/*`, `feat/*`, `docs/*`), one concern per commit.
- Commit message: short imperative subject, max 72 chars.
- Commit Excel and CSV outputs only when they are agreed artefacts.
  Never commit tokens, `.venv/`, or `~$*.xlsx` lock files.

## Constraints

- Do not touch `Backup SIte Production/`.
- Do not add npm/JS deps or frameworks (no Celery, no RQ, no dashboards)
  until the daily aggregate is proven short. See design doc for limits.
- Do not POST to ERPNext before the mapping CSV is approved and the
  target site URL plus API key exist.
- Do not guess Item Codes. Source of truth is
  `experiments/sku_to_item_code.csv`; conflicts stay flagged, not guessed.
- Rate limit: max 10 parallel workers, 3 retries with backoff on
  429/5xx, 90s timeout. Never hammer the eResto API.
- Token in shell history is exposed. Ask the user to rotate it if a
  command line contained the raw token.

## Docs

- `KNOWLEDGE.md` — system map for AI/humans: three systems, all URLs,
  eResto Manager routes, rules, gotchas. Keep it current when systems change.
- `docs/01-eresto-api.md` — auth, endpoints, params, JSON contracts.
- `docs/02-erpnext-mapping.md` — SKU map, outlet/payment mapping, void rules,
  pilot invoice, mapping stok SO.
- `docs/03-production-sync-design.md` — sync architecture and phases.
- `docs/04-posnext-cara-kerja-penjualan.md` — POSNext opening/invoice/closing.
- `docs/05-alur-dough-ke-bundle.md` — **rantai barang tetap**: dough
  (Pabrik/PJ*) → matang (Outlet/PJO*) → bundle jual (RP00x/CR001/GM00x).
  Semua keluarga dough mengikuti pola ini; jangan jual/seed di luar pola.
- ERPNext REST API: `https://frappeframework.com/docs/user/en/api/rest`.
  POS Invoice flow: `POS Invoice` per order plus `POS Closing Entry`
  per outlet per day. Bulk alternative: Data Import Tool with parent/child
  rows (header on first row only).

## POS setup (ERPNext lokal, 2026-10-04)

State: 322 POS Profile (161 `SHIFT 1` + 161 `SHIFT 2`), 16 Price
Group, 19 Price List, 2 Shift Groups (`ALL TIME` 161 members,
`SHIFT 2` 161 members). Summary: `experiments/POS_Setup_Report.xlsx`.

- POSNext flow: a Price Group owns one Price List (`PG-<name>`),
  its Item Prices, and claims every POS Profile of its outlet
  companies. Never hand-create the Price List/Item Price of a tier:
  the ownership field rejects it. Order: prep -> pg -> prof ->
  claim -> group.
- Shift Group membership is edited on the group (Members table);
  saving the group syncs hours and unlinks profiles not listed.
- Every POS Profile carries Cash (default, allow returns) +
  Debit Card + Credit Card + QRIS (`update_pos_payments.py`).
- Duplicate profiles (misspelled vs eResto) are removed with
  `delete_duplicate_profiles.py`: it pre-checks links/transactions,
  unlinks from the Shift Group, then deletes. Companies stay.
- `SHIFT 2 - <company>` exists for every company, cloned from its
  SHIFT 1 (`create_shift2.py`); it joins Shift Group `SHIFT 2`
  (05:00-14:00). Re-running refreshes PG outlet rows to list both.
- Scripts: `build_pos_matrix.py`, `fetch_tier_prices.py`,
  `apply_pos_bulk.py` (stages + `--only`/`--tier`),
  `create_shift2.py`, `build_pos_report.py`. All idempotent,
  API key from env.
- New companies: child of `OUTLET REGULER`, FRC names keep `(FRC)`.

## Stock mapping (eResto inventory -> ERPNext Item)

- Source: SO Monthly September fetch (`fetch_so_monthly.py`).
  Decisions live in `build_stok_mapping.py` (review date 2026-10-04);
  outputs `stok_sku_to_item.csv` + `Template_Mapping_Stok.xlsx`.
- RR* finished goods -> PJO* (matang) items; the RP00x/CR001/GM001
  sales items are non-stock bundles, never receive stock balances.
  The full dough → matang → bundle chain is `docs/05-alur-dough-ke-bundle.md`.
- Powder items without a match were created as `BB260057-62`.
- The Item doctype here auto-names `BB26-.###`, overriding the
  requested `item_code`; always rename after create
  (`frappe.client.rename_doc`, see `create_stok_items.py`).
- Pack/kg conversions: stock goes into ERPNext `stock_uom`
  (g for powders, Pack dough -> Pcs assumed 1:1 pending confirm).
