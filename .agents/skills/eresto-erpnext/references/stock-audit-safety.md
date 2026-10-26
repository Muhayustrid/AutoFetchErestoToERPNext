# Stock audit safety

Use with the parent skill before auditing or replacing stock documents. These
are reusable verification rules; current document IDs and decisions stay in
PROJECT_STATE.md, docs/13 and operation evidence.

## Complete, stable reads

- Paginated ERPNext lists must specify `order_by: "name asc"`; do not assume
  a shared helper supplies it. Check unique document/SLE/Bin names and reject
  duplicate or incomplete coverage. Deduplicating a truncated result cannot
  recover missing rows. Preserve the original snapshot when repairing coverage.
- Validate baseline quantity replay against every active SLE and Bin, then
  compare name/modified signatures before destructive actions. If live activity
  changes the snapshot, refresh or reconcile the evidenced concurrent movement;
  do not overwrite legitimate sales to make a frozen comparison pass.
- eResto pagination uses `meta.next_page`/`total_count` and unique IDs. Verify
  returned inventory/division/date filters, not merely the requested parameters.

## Source coverage and the no-op option

- Distinguish source rows, unique SKUs, excluded rows, counted targets and native
  stored rows. Repeated SKUs in different SO snapshots are absolute counts,
  never quantities to sum. Exclude zero counts only with explicit scope approval.
- Native submit may remove a positive or zero row with no quantity/value change.
  Accept an omitted target only when the effective ledger quantity **and valuation
  rate** at that source timestamp independently equal the intended count/rate.
  Otherwise stop. Never force an extra movement to keep a cosmetic row count.
- If all effective counts already match, do not import them again. For a small
  timestamp offset, first prove there was no intervening relevant movement.
  Recommend leaving valid documents alone when no correction is needed, and
  respect an explicit user decision to keep them. There is no blanket time
  tolerance: new or explicitly requested corrected postings use the source time.
- Rows absent from an SO are not zero counts. Preserve or remove inherited
  non-source balances only under an explicit decision; keep them separate from
  source SOs and later operational adjustments. A legacy document alone is not
  proof of a physical movement. Do not invent prices for source zero-cost rows.

## Repost invariants and historical negatives

- Protected RECO counted rows, qty, approved rates, UOM/factor, warehouse, account,
  cost center and posting time stay fixed. Native repost can change row
  `current_qty`, `current_amount`, `current_valuation_rate`, `quantity_difference`,
  `amount_difference` and header `difference_amount`. Compare all other fields
  strictly and export derived-field differences rather than demanding byte-equality.
- Downstream issue rates/amounts and stock values may legitimately change after
  an earlier correction. Verify quantities/accounts separately, balanced journals
  and approved value projections; report actual value deltas. Balanced GL alone
  does not establish full historical stock-value-versus-GL reconciliation.
- Separate current negative Bins, historical negative episodes and temporary
  cancellation gaps. Inventory history is not a standalone record to erase:
  never delete SLE/GL directly or a valid mixed delivery merely to hide a minus.
- Audit all warehouses touched by both sides of a transfer. Require the approved
  corrected projection and current balances to pass; an unrelated pre-existing
  historical negative is not permission to erase it or invent stock. Compare its
  baseline minimum/episode unchanged and report it separately; stop for new or
  worsened deficits. Verify the full surviving SLE quantity trail, not just Bins.
- Correct timing only with traceable receipt/movement evidence and native links.
  If eResto itself shows dispatch before receipt, that does not justify moving
  receipt earlier. Keep every row of mixed vouchers. Replace an existing late
  receipt/transfer rather than adding another one. Temporary-minus permission
  expires with its named operation; obtain a new exception for another correction.

## Native API and recovery guards

- Inspect doctype metadata before using `remarks` or `title`. If both are absent,
  record source/replacement markers as native Comments using reference doctype
  and name. Combine marker lookup with timestamp/item signatures for idempotency.
- Read back draft and submitted qty/UOM/rates/amounts. Native valuation-rate
  rounding can change intended values. Stop before submit on a mismatch; use
  the site's supported precision configuration only within the approved scope,
  restore temporary metadata changes in `finally`, and verify their removal.
- HTTP202 `data: ok` on DELETE means pending, not confirmed deletion. Wait for
  native404 and check old SLE/GL residue0 before retrying or declaring success.
- Persist backup/payload/progress before writes. On timeout or assertion failure,
  inspect actual docstatus and resume from the recorded checkpoint; a successful
  submit can precede a failed read-back guard. Never blindly rerun the batch.
  Wait for repost queued/in-progress/failed0, restore flags and verify live target
  before completion. Older snapshot verifiers become stale after later approved
  corrections; keep their evidence and use the new approved projection.
