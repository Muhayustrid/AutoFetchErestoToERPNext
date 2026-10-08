# AutoFetchErestoToERPNext — eResto ⇄ ERPNext (Ropi)

Tooling + knowledge base for migrating **Ropi's** POS operations from the
eResto SaaS into **ERPNext v16**, and for the parallel migration between two
ERPNext sites (old → new cloud).

- **eResto** (`ropi.eresto.id`) — source of truth for sales, refunds,
  production and stock until cutover. Treated as READ-ONLY.
- **ERPNext Baru** (`ropierpnext.frappe.cloud`) — production target: POS
  Invoice, Work Order, PO/PR/SO/DN, assets, print formats.
- **ERPNext Lama** (`rotiropi.j.frappe.cloud`) — historic source of internal
  transactions that never lived in eResto.

## Start here

| For | Read |
|---|---|
| What the systems are, all URLs & endpoints, business rules, API traps | [`KNOWLEDGE.md`](KNOWLEDGE.md) |
| Project rules for AI agents & humans (style, constraints, flow) | [`AGENTS.md`](AGENTS.md) |
| Current status: what's done, active tasks, known issues, how to run | [`PROJECT_STATE.md`](PROJECT_STATE.md) |
| Deep dives per topic (eResto API, mappings, POSNext, WO replay, print formats) | [`docs/`](docs/) |

AI agents: if your tool doesn't auto-read the files above, paste
`KNOWLEDGE.md` into context first — it is written to be self-contained.

## The two product chains to keep in mind

1. **Sales chain** — eResto order (`OR<branch>.<DDMMYY>.<seq>`) → ERPNext
   `POS Invoice` (+ opening/closing shift per outlet per day).
2. **Stock chain** — dough (factory, `PJ*`) → matang (outlet, `PJO*`) →
   sell bundle (`RP00x`/`CR001`/`GM00x`). One Ropi pack of dough yields
   12 pieces, Gempi 3, Croissant 6. See `docs/05`.

## Layout

```text
KNOWLEDGE.md      system map for AI/humans (read first)
AGENTS.md         project rules
PROJECT_STATE.md  live status + changelog + how to run
docs/             topic docs 01..11
experiments/      ERPNext setup scripts + fetch probes (test_* are probes)
pos_sync/         migration & injection tooling (idempotent CLI scripts)
dokumen/          import templates (Mode of Payment, Fiscal Year)
```

## Running it

Credentials come from environment variables only — never committed:

```bash
source .venv/bin/activate
pip install requests pandas openpyxl
export ERESTO_TOKEN=... ERESTO_EMAIL=... ERESTO_USER_ID=...   # eResto API
export ERPNEXT_URL=... ERPNEXT_API_KEY=...                    # Frappe site
```

Frappe auth header is `Authorization: token <api_key>:<api_secret>`; eResto
uses `Authorization: Token token=<t>, email=<e>` plus query params — full
detail in `KNOWLEDGE.md` §3. Every script is idempotent (check-then-skip by
order number, `ERESTO` marker, or document name) so reruns never duplicate.

Verification pattern: every run writes an Excel report
(`Raw_*`, `Rekap_*`, `Validation`, `Failed` sheets) and prints checks that
must read **OK / LOLOS**.

## Notes

- Raw dumps & detail caches (regenerable via each script's `--dump`) and the
  private production DB backup are **not** in this repo — see `.gitignore`.
- No test suite; verification is the Excel report + cross-checking both
  sites' APIs.
