# Cara kerja penjualan di POSNext — opening, invoice, closing

Sumber: kode app `pos_next` di container `frappe-backend-1`
(`/home/frappe/frappe-bench/apps/pos_next`), diverifikasi terhadap
site lokal `erp.localhost` port 8081 pada 2026-10-04.
Fokus: bagaimana satu penjualan berjalan dari buka shift sampai tutup shift.

Dokumen ini memakai satu nama untuk satu hal.
`Shift` = satu sesi kasir (`POS Opening Shift` + `POS Closing Shift`).
`Profil` = `POS Profile` (`SHIFT 1 - <company>` atau `SHIFT 2 - <company>`).
`Invoice` = dokumen penjualan (`POS Invoice` atau `Sales Invoice`,
ditentukan satu setting global, bukan oleh kasir).

## Ringkasan alur

Penjualan POSNext selalu berjalan dalam tiga fase berurutan.

1. **Opening.** Kasir login, pilih profil, catat modal awal, submit shift.
   Shift berstatus `Open`. Tanpa shift terbuka, kasir tidak bisa jualan.
2. **Invoice.** Kasir tambah item, sistem hitung offer dan pajak, kasir
   terima pembayaran, sistem submit invoice. Setiap invoice menempel
   ke shift lewat field `posa_pos_opening_shift`.
3. **Closing.** Kasir tarik rekap dari semua invoice shift, hitung uang
   fisik per metode bayar, submit closing. Status shift menjadi `Closed`.
   Laporan EOD tercetak otomatis.

Closing tidak membuat jurnal akuntansi baru.
Invoice sudah memposting stok dan GL masing-masing saat submit.
Closing hanya merekap, menghitung selisih kas, dan menutup shift.

## Prasyarat master data

Bagian ini menjelaskan data yang harus ada sebelum kasir bisa buka shift.
Setup lokal proyek ini sudah memenuhi semuanya.

- **Company per outlet.** Satu outlet = satu company, anak `OUTLET REGULER`.
  Invoice, warehouse, dan akun selalu di-scope per company.
- **POS Profile per company per shift.** Pola lokal: `SHIFT 1 - <company>`
  (00:00-23:59) dan `SHIFT 2 - <company>` (05:00-14:00, grup `SHIFT 2`).
  Profil membawa warehouse (`Stores - <abbr>`), price list, customer
  (`Walk-in Customer`), akun write-off/income/expense/kembalian,
  tabel `payments` (Cash default + Debit + Credit + QRIS),
  dan tabel `item_groups` (`Products`).
- **Price Group memiliki harga.** Satu Price Group memiliki satu
  Price List (`PG-<nama>`) plus Item Price dan mengklaim semua profil
  company-nya lewat child `outlets`. Jangan buat Price List manual
  untuk tier POSNext. Ownership field menolaknya.
- **Shift Group memiliki jadwal.** `POS Profile Group` (`ALL TIME`,
  `SHIFT 2`) menyimpan jam di tabel Members. Simpan grup = push jam
  ke semua member. Edit link grup langsung di profil ditolak.
  Profil tanpa baris Members yang cocok tidak bisa disimpan.
- **Mode of Payment.** Setiap profil butuh baris akun Mode of Payment
  untuk keempat metode. ERPNext menolak simpan profil tanpa akun.
- **POS Next Global Settings.** Satu dokumen single. Field penting:
  `invoice_type` (`POS Invoice` default), naming series per doctype,
  `allow_negative_stock`, knob diskon (`allow_user_to_edit_rate`,
  `max_discount_allowed`, `price_replay_audit_only`),
  knob kredit (`allow_credit_sale`, `allow_customer_credit_payment`,
  `allow_partial_payment`), knob refund (`allow_return`,
  `require_refund_code`, `return_validity_days`),
  knob antrean (`enable_pos_queue`), knob pajak (`tax_inclusive`),
  dan `hide_expected_amount` (mode blind count).
- **Role.** `POSNext Cashier` (jualan, buka/tutup shift sendiri,
  tanpa cancel/delete) dan `POSNext Manager` (bisa tutup shift orang,
  perpanjang deadline, backdate). Administrator lolos semua gate profil.

Data live lokal saat dokumen ini ditulis: 322 profil
(161 `SHIFT 1` + 161 `SHIFT 2`), semua `pos_schedule_enabled=1`,
jam 00:00-23:59:59, `enforce_closing=0`, grup `ALL TIME`.
Belum ada satu pun baris `POS Opening Shift`.

---

## Bagian 1 — Opening POS (buka shift)

### 1.1 Model data

DocType `POS Opening Shift`:

- `autoname` = `POSA-OS-.YY.-.#######`. Hook `autoname()` memanggil
  `pos_next.naming_series.apply_naming_series_setting`. Jika Global
  Settings mengisi pola, pola itu menang. Pola tanpa `#` ditambah `.#####`.
- `is_submittable = 1`, `track_changes = 1`.
- Field kunci: `period_start_date` (Datetime, wajib, = waktu server
  saat buka), `period_end_date` (Date, read-only, tidak ditulis oleh
  alur closing), `status` (Select `Draft/Open/Closed/Cancelled`,
  default `Draft`, read-only), `posting_date` (Date, default Today),
  `company` (Link, wajib), `pos_profile` (Link, wajib),
  `pos_closing_shift` (Data, terisi saat closing submit),
  `user` (Link User, label Cashier, wajib),
  `balance_details` (Table `POS Opening Shift Detail`, wajib).
- Snapshot jadwal: `pos_schedule_enabled`, `pos_schedule_start`,
  `pos_schedule_end`, `pos_schedule_deadline` (Datetime, read-only),
  `pos_schedule_warning_minutes`, `pos_schedule_enforce_closing`.
  Section berlabel `Shift Schedule (Snapshot)`.
- Child `POS Opening Shift Detail` hanya dua field:
  `mode_of_payment` (Link, wajib) dan `amount` (Currency, wajib,
  label Opening Amount).

Fungsi `set_status` di `pos_opening_shift.py` menentukan status:

- `docstatus 0` = `Draft`.
- `docstatus 1` + `pos_closing_shift` kosong = `Open`.
- `docstatus 1` + `pos_closing_shift` terisi = `Closed`.
- `docstatus 2` = `Cancelled`.

Hook lifecycle di controller:

- `before_insert` = `apply_schedule_snapshot`.
- `validate` = `freeze_schedule_snapshot` + `validate_pos_profile_and_cashier`
  + `set_status`.
- `before_submit` = `apply_schedule_snapshot` ulang.
- `on_submit` = `set_status(update=True)` via `db.set_value`.

Urutan ini penting. Insert mengambil snapshot dari profil.
Submit menghitung ulang snapshot dari profil pada detik submit.
Draft yang disimpan melewati jam wajib tidak bisa disubmit.
Edit klien ke field snapshot selalu ditimpa server.

Validasi `validate_pos_profile_and_cashier`:

- `company` dokumen harus sama dengan company profil.
  Beda company = throw `POS Profile ... does not belongs to company ...`.
- User kasir harus `enabled`. User disabled = throw.

### 1.2 Jadwal shift (schedule snapshot dan gate)

File `pos_next/shift_schedule.py` mengatur semua logika jam.
Konstanta `SCHEDULE_FIELDS` berisi lima field jadwal.
`GATE_TITLE` = `Shift Schedule` (judul semua error jadwal).

`get_effective_schedule(pos_profile)` membaca lima field dari profil.
Link grup yang tidak ada di `POS Profile Group` ditolak.
Nilai jadwal rusak ditolak oleh `validate_schedule_values`
(jam mulai/selesai hilang saat schedule on, warning negatif).

`resolve_window(now, start, end)` mencari jendela yang memuat `now`:

- Jendela overnight (`end <= start`) menyeberang tengah malam.
  Fungsi memeriksa hari ini lalu kemarin.
- `start == end` = jendela 24 jam.
- Batas `start <= now < end`. Tepat di detik end = di luar jendela.

`apply_schedule_snapshot(opening)` berjalan saat insert dan submit:

- Salin lima field dari profil ke dokumen.
- `deadline = None` bila schedule off. Shift bisa buka tanpa deadline.
- Bila schedule on, hitung window berisi `now_datetime()`.
  Ada window = `deadline = window_end`.
- Tidak ada window + `enforce_closing = 1` = throw
  `... is outside the scheduled shift hours ... A shift cannot be opened now`.
- Tidak ada window + `enforce = 0` = shift tetap buka, deadline `None`.

`freeze_schedule_snapshot(opening)` berjalan di setiap validate
setelah dokumen ada di DB. Fungsi baca nilai tersimpan dan timpa
field dokumen. Efek: deadline tidak bisa diubah lewat API atau Desk.
Jalur resmi ubah deadline hanya dua: `frappe.db.set_value` oleh admin,
atau endpoint `extend_deadline` (role System Manager/POSNext Manager,
forward-only, tulis Comment audit).

`get_shift_gate(opening_shift)` kembalikan `None` bila shift tidak ada,
belum submit, schedule off, enforce off, atau deadline kosong.
Selain itu kembalikan `{opening_shift, deadline, expired}`.
`expired = now >= deadline`. Tepat di deadline = expired.

`_gate_shifts(shift, profile)` memilih shift yang harus lolos gate.
Field shift dari klien hanya dipercaya bila menunjuk shift
`docstatus 1` + status `Open` + profil sama. Selain itu fallback
ke semua shift Open milik profil. Desain fail-closed: bisa over-block,
tidak pernah under-block.

`assert_sales_allowed(opening_shift)` menolak pembayaran dan refund baru
setelah deadline dengan pesan `Shift ... ended at ... Closing is required`.
Closing tidak pernah di-gate. Kasir selalu bisa tutup shift.

`validate_invoice(doc)` adalah hook validate untuk invoice.
Aturan admission memakai jam server dan `doc.creation`, bukan timestamp klien:

- Invoice yang `creation`-nya sebelum atau tepat di deadline tetap
  boleh submit (draft tercetak yang disettle saat closing, draft basi).
- Invoice yang `creation`-nya setelah deadline ditolak.
- Pengecualian backdate HO (`_backdate_exempt`): flag request-scoped
  `frappe.flags.pos_next_backdate_entry` + posting date di dalam
  periode shift. Flag ini tidak bisa dipalsukan klien.

### 1.3 Endpoint opening

Tiga endpoint di `pos_next/api/shifts.py`.

`get_opening_dialog_data` kembalikan data dialog:

- `pos_profiles_data`: SQL profil di mana session user terdaftar
  di `POS Profile User`, `disabled = 0`.
- `companies`: company unik dari profil itu.
- `payments_method`: baris `POS Payment Method` milik profil itu,
  kecuali mode bertipe wallet (`is_wallet_payment = 1`).
  Wallet tidak ikut modal awal. Tiap baris ditambah `currency` profil.

`check_opening_shift(user=None)` cek shift terbuka:

- Param `user` milik orang lain butuh permission read Opening Shift.
- Filter: `user = session user`, `pos_closing_shift is not set`,
  `docstatus = 1`, `status = Open`, urut `period_start_date desc`.
- Baris dengan link profil yang sudah dihapus di-skip.
  Tidak ada baris valid = return `None`.
- Return: dokumen opening + profil (cache) + company (cache) +
  `server_now` (string waktu server, jangkar durasi dan jadwal).

`create_opening_shift(pos_profile, company, balance_details)` buat shift:

1. Parse `balance_details` (JSON string atau list).
2. `_check_profile_access`: Administrator lolos. Selain itu wajib ada
   baris `POS Profile User` untuk profil itu. Bukan anggota = 403.
3. Kunci baris profil (`for_update=True`). Kunci ini men-serialize
   create konkuren untuk profil yang sama.
4. Cek duplikat: `check_opening_shift(session user)`. Sudah punya
   shift Open = throw `You already have an open shift: ...`.
   Unik per user, dijaga di level aplikasi, tanpa unique constraint DB.
5. Bangun dokumen: `period_start_date = get_datetime()`,
   `posting_date = nowdate()`, `user = session user`, profil, company,
   `status = Open` (server hitung ulang).
6. Mapping balance: tiap baris `{mode_of_payment, amount: opening_amount}`.
7. `insert(ignore_permissions=True)` lalu `submit()`.
   Snapshot jadwal dihitung di sini. Di luar jam + enforce = gagal di sini.
8. Return dokumen + profil + company + `server_now`.

Tidak ada rate limit di ketiga endpoint opening.

### 1.4 Frontend opening

State inti ada di `POS/src/composables/useShift.js`:

- `shiftState` menyimpan opening, profil, company, flag open,
  plus `_initialElapsedMs`, `_receivedAt`, `_serverNowMs`.
- `applyShiftData` tulis state Pinia dan `localStorage[pos_shift_data]`.
- `checkOpeningShift` sukses dengan data = hitung elapsed dari
  `server_now - period_start_date`, lalu apply. Sukses null = reset
  dan hapus cache. Error offline = pakai cache. Error online = buang cache.
- `createOpeningShift` kirim `{pos_profile, company,
  balance_details: JSON.stringify(...)}`. Sukses = apply.
- `submitClosingShift` sukses = reset state dan hapus cache.

Store `POS/src/stores/posShift.js` membungkus `useShift`:

- Timer 1 detik update `currentTime`, `shiftDuration`, `scheduleStatus`.
- Durasi = `_initialElapsedMs + (Date.now() - _receivedAt)`.
  Timer freeze saat `shiftTimerPaused` (dialog closing terbuka).
- `scheduleStatus` hanya di-assign saat transisi nyata
  (`isSameScheduleStatus`), supaya watcher forced-close tidak re-fire.

Util `POS/src/utils/shiftSchedule.js` murni dan ada test vitest:

- `parseServerDatetime` Safari-safe (`" "` jadi `"T"`, buang fraksi detik).
- `computeScheduleStatus(shift, clock)`: null bila schedule off.
  `nowMs = serverNowMs + elapsed lokal`. `expired = nowMs >= deadlineMs`.
  `warning` bila dalam `warningMinutes` sebelum deadline.
  `minutesLeft = ceil((deadline - now) / 60000)`.
- `isScheduleBlocking(status) = enforce && expired`.

Dialog `ShiftOpeningDialog.vue` adalah wizard tiga langkah:

1. Step 1 Select POS Profile. Grid kartu (nama, company, currency).
   Data dari `pos_next.api.pos_profile.get_pos_profiles`.
   Tombol Next mati tanpa pilihan.
2. Step 2 Enter Opening Balances. Label tegas: Opening Balance (Optional).
   Satu input per mode pembayaran non-wallet milik profil terpilih.
   Format ribuan Indonesia (titik ribuan, koma desimal).
   Default 0. Tombol Back ganti profil, tombol Open Shift submit.
3. Step 3 Existing Shift Found. Muncul bila user sudah punya shift Open.
   Tombol Resume Shift (masuk dengan shift lama) atau Close and Open New
   (buka dialog closing, lalu buka shift baru setelah closing).

Dialog reset state saat dibuka, bukan saat ditutup.
Reset saat close pernah membuat transisi reka-ui macet (ada regression test).

Rangkaian halaman:

- `router.js`: history `/pos`. Route `/` = POSSale, `/account/login` = Login,
  `/direct-print` = DirectPrint. Belum login = redirect Login.
- `Login.vue`: submit `login` (`usr`/`pwd`). Sukses = refresh CSRF,
  cache hash password untuk unlock offline, lalu tampilkan dialog opening.
- `POSSale.vue onMounted initPOS`: `checkShift()`. Tidak ada shift =
  tampilkan empty state `Please open a shift to start making sales`
  + tombol Open Shift, lalu stop. Ada shift = set profil dan shift ke cart,
  set warehouse ke stock store, load settings, preload offline, hitung draft,
  paket, kunci sesi, aturan pajak.
- `handleShiftOpened`: tutup dialog. Bila profil berganti, cart lama
  dibuang (`clearCart`). Toast `You can now start making sales`.
- Watcher jadwal: warning = toast sekali `Shift schedule ends in ...`.
  Blocking = `forceScheduleClose`. Online = tutup dialog opening,
  buka dialog closing. Offline = toast minta reconnect.
  Submit cart yang sedang jalan tidak dipotong di tengah
  (`pendingForceClose` menunggu `isSubmitting` selesai).

### 1.5 Alur langkah-demi-langkah opening

1. Kasir buka `/pos`. Belum login = redirect ke halaman Login.
2. Kasir login. Dialog opening terbuka otomatis.
3. Dialog fetch profil milik user, lalu cek shift terbuka.
4. Bila shift terbuka sudah ada, dialog tampilkan step 3.
   Kasir pilih Resume (lanjut jualan) atau Close and Open New (tutup dulu).
5. Bila tidak ada shift, kasir pilih satu profil di step 1, klik Next.
6. Dialog fetch payment method non-wallet profil itu.
7. Kasir isi modal awal per metode bayar di step 2 (boleh 0),
   klik Open Shift.
8. Frontend POST `create_opening_shift`.
9. Server cek akses profil, kunci baris profil, cek duplikat per user,
   insert dokumen, snapshot jadwal, submit dokumen.
   Di luar jam + enforce = request gagal di sini.
10. Server kembalikan dokumen + profil + company + `server_now`.
11. Frontend simpan ke Pinia dan localStorage, tutup dialog,
    siapkan cart/warehouse/settings, mulai timer durasi dan jadwal.
12. Kasir masuk layar jualan. Timer tampilkan durasi shift.
    Warning muncul `warningMinutes` sebelum deadline (bila di-set).

---

## Bagian 2 — POS Invoice (penjualan)

### 2.1 Dua jenis invoice, satu mesin

File `pos_next/invoice_type.py` menentukan doctype aktif:

- `get_pos_invoice_doctype()` baca single `POS Next Global Settings.invoice_type`.
  Nilai valid hanya `Sales Invoice` atau `POS Invoice`.
  Default = `POS Invoice`. Hasil di-cache per request.
- `is_pos_next_owned(doc) = bool(doc.posa_pos_opening_shift)`.
  Ini gerbang ownership. Hanya invoice ber-shift POSNext yang
  menjalankan efek khusus POSNext.
- Laporan membaca union kedua doctype. Mode POS Invoice mengecualikan
  baris Sales Invoice ber-`is_consolidated = 1` (anti double count).
- Ganti setting ditolak bila ada shift terbuka, ada `Offline Invoice Sync`
  Pending, atau ada POS Invoice lama belum posting GL/SLE.

Fungsi `_resolve_target_doctype` di `pos_next/api/invoices.py`:

- Payload `Sales Order` = Sales Order (draft saja, fitur terima order).
- Payload `Sales Invoice` diabaikan. Server tetap pakai setting global.
- Artinya frontend tidak menentukan doctype invoice.
  Field `doctype` dari klien selalu dibuang.

Override akuntansi di `pos_next/overrides/sales_invoice.py`:

- `CustomSalesInvoice(SalesInvoice)`: GL POS untuk wallet
  (`party_type`/`party`), GL kembalian (`post_change_gl_entries`,
  v16 `get_gle_for_change_amount`), submit tanpa baris payment bila
  flag server `pos_next_redeemed_customer_credit` atau
  `pos_next_credit_sale`, merge packed item bundle gratis, paksa jalur
  legacy serial-batch untuk item bundle.
- `CustomPOSInvoice(CustomSalesInvoice, POSInvoice)`:
  `_post_parity_accounting` = `update_stock_ledger` + `make_gl_entries`
  + `repost_future_sle_and_gle`. `on_submit` milik POSNext posting stok
  dan GL sendiri. POS Invoice POSNext tidak menunggu konsolidasi.
- `validate_pos_opening_entry` untuk invoice owned: shift wajib `Open`
  dan profil invoice sama dengan profil shift.
- Hook `POS Invoice Merge Log.before_validate` menolak konsolidasi
  invoice owned (`guard_against_retroactive_consolidation`).
  Sudah posting sendiri, konsolidasi = double posting.
- `hooks.py`: `Sales Invoice` = `CustomSalesInvoice`,
  `POS Invoice` = `CustomPOSInvoice`.

Naming series di `pos_next/naming_series.py`:

- Pola per doctype dari Global Settings
  (`pos_invoice_naming_series`, `pos_opening_shift_naming_series`,
  `pos_closing_shift_naming_series`). Global-only.
- `apply_naming_series_setting` dipanggil dari `autoname()`,
  sehingga mencakup checkout, offline sync, return, dan Desk.

### 2.2 Endpoint invoice

File `pos_next/api/invoices.py` adalah API utama.
Dua endpoint inti adalah `update_invoice` (buat/update draft)
dan `submit_invoice` (submit). Pola selalu dua langkah.

Endpoint baca dan util:

- `get_invoice(invoice_name)`: detail satu invoice (coba kedua doctype)
  + `cashier_name`.
- `get_invoices(pos_profile, ...)`: riwayat union dua doctype
  + payments + items.
- `delete_invoice(invoice)`: hapus draft (gate owner + profil).
- `cleanup_old_drafts(pos_profile, max_age_hours)`: hapus draft sendiri
  lebih tua dari `max(24 jam, param)`.
- `validate_cart_items(items, pos_profile)`: pre-check stok.
- `search_invoice_by_number`, `get_returnable_invoices`,
  `search_invoices_for_return`, `check_invoice_return_validity`,
  `get_invoice_for_return`, `prepare_return_invoice`,
  `validate_return_items`, `apply_offers`.

Endpoint terkait di modul lain:

- `pos_next.api.queue.get_next_queue_number(pos_profile)`: nomor antrean harian.
- `pos_next.api.items.search_by_barcode`, `get_item_details`,
  `get_stock_quantities`.
- `pos_next.api.pos_profile.get_taxes`, `get_default_customer`.
- `pos_next.api.offers.get_offers`, `validate_coupon`,
  `get_active_coupons`, `get_customer_one_time_redemptions`.
- `pos_next.api.packages.get_packages`, `quote_package`.
- `pos_next.api.discount_code.get_status`,
  `validate_confirmation_code`, `check_code` (POST only).
- `pos_next.api.partial_payments.*` (khusus Sales Invoice).
- `pos_next.api.credit_sales.get_customer_balance`,
  `get_available_credit`, `redeem_customer_credit` (khusus Sales Invoice).
- `pos_next.api.wallet.*`.

### 2.3 Hook dokumen

`hooks.py` memasang rangkaian hook ini.

Sales Invoice `validate` (urut): `sales_invoice_hooks.validate`
(pajak inclusive + loyalty) = `wallet.validate_wallet_payment` =
`packages.validate_invoice_packages` =
`pricing_rule.apply_min_max_price_discounts` =
`discount_code.validate_invoice_discounts` =
`pos_offer_usage.validate_invoice_offers` =
`shift_schedule.validate_invoice`.

Sales Invoice `on_submit`: emit event stok realtime =
proses loyalty ke wallet = catat one-time offer usage =
catat pemakaian kode diskon = catat offer usage =
naikkan queue counter.

Sales Invoice `on_cancel`: emit stok + lepas one-time usage +
lepas kupon + lepas offer usage. `after_insert`: emit invoice created.
`before_cancel`: `sales_invoice_hooks.before_cancel`.

POS Invoice (`pos_invoice_events.py`) menjalankan rangkaian yang sama,
tapi semua efek POSNext di-gate `is_pos_next_owned(doc)`.
Event stok tidak di-gate supaya terminal melihat penjualan POS bawaan juga.

POS Profile `validate` = `shift_schedule.validate_profile_schedule`.
POS Profile `on_update` = emit event profil.
Promotional Scheme dan Pricing Rule `validate` = jaga konfigurasi Min/Max
dan jaga sync offer. Scheduler harian = bersihkan promosi kedaluwarsa.

### 2.4 Tambah item ke cart

Frontend di `POS/src`.

1. `stores/itemSearch.js searchByBarcode` panggil
   `pos_next.api.items.search_by_barcode`. Barcode timbang atau harga
   di-resolve oleh `pos_next/services/barcode.py` (`resolve_barcode`,
   `compute_resolved_item_data`). Barcode timbang = qty dari barcode.
   Barcode harga = qty 1 dengan rate dari barcode. Konversi UOM bila perlu.
2. `POSSale.vue handleItemSelected`: item parent paket = buka PackageDialog.
   Paket parent tanpa paket tersedia = error. Barcode autoAdd = tambah
   dengan resolved qty. Item bervarian = dialog varian. Item multi-UOM =
   dialog UOM. Item batch/serial = dialog batch/serial.
   Selain itu tambah 1 pcs.
3. `stores/posCart.js addItem` cek stok dulu, lalu `useInvoice.addItem`
   (`composables/useInvoice.js`): merge baris dengan `item_code` + `uom`
   sama (kecuali item paket), update `price_list_rate`, quantity,
   conversion factor, gabung serial unik, hitung ulang diskon dan pajak
   per baris, update jumlah.
4. Stok tampilan di `stores/stock.js`: `display = server - reserved`.
   Reserved = qty cart semua till yang diketahui client.
   Refresh stok dari `pos_next.api.items.get_stock_quantities`.
   Event realtime `pos_stock_update` per room profil
   (`realtime_events.emit_stock_update_event`, termasuk saat cancel).

Pajak per baris dihitung di frontend dan dihitung ulang di server:

- Exclusive: net = subtotal - diskon, tax = net x rate.
- Inclusive: gross = subtotal - diskon, net = gross / (1 + rate),
  tax = gross - net.
- `computeBackendRate`: inclusive kirim gross rate, exclusive kirim amount/qty.

### 2.5 Offer otomatis

`posCart.js` watch item/qty/uom/diskon/subtotal/customer, lalu
`debouncedProcessOffers` (100/200/300 ms) dengan generation counter
anti-stale. `processOffersInternal`:

- Pastikan offer ter-fetch (`pos_next.api.offers.get_offers`,
  di-cache ke IndexedDB untuk offline).
- Offline = mesin offer klien (`applyOfflinePriceDiscount`,
  `applyOfflineFreeItem`, gate one-time dari cache).
- Online = POST `apply_offers` dengan `selected_offers`,
  lalu `parseOfferResponse`: set `discount_percentage`/`amount`/
  `pricing_rules` per baris, tambah baris free item (`is_free_item = 1`,
  rate 0), terapkan diskon header transaction-level, dan hanya
  tampilkan offer yang dikonfirmasi server.

Server `apply_offers` memakai ulang mesin ERPNext `apply_pricing_rule`:

- Aturan coupon-based dilewati (jalur kupon terpisah).
- Aturan one-time dilewati untuk walk-in atau sudah redeem
  (`One Time Customer Offer Usage`).
- Aturan transaction-scope dievaluasi lewat dokumen Sales Invoice
  sementara (`_evaluate_transaction_offers`).
- Aturan Min/Max lewat `apply_min_max_price_discounts`: ranking lintas
  cart, hanya satu baris target, batas qty `min_or_max_discount_qty_limit`.
- Response: `items[]`, `free_items[]`, `applied_pricing_rules[]`,
  `additional_discount_percentage`, `discount_amount`, `apply_discount_on`.
- Cap persen diskon per unit `pos_offer_max_discount` (`_cap_percentage_discount`).

### 2.6 Checkout dan pembayaran

`POSSale.vue handleProceedToPayment`: cart tidak kosong + customer
(fallback customer default profil) = buka `PaymentDialog.vue`.

PaymentDialog menghitung `remainingAmount = max(0, grandTotal - totalPaid)`
dan `changeAmount = max(0, totalPaid - grandTotal)`.
Aturan pembayaran:

- Multi-mode: tiap baris `payments[]` berisi mode dan amount.
- Non-cash harus tepat sasaran. Overpay hanya untuk cash.
  Overpay besar minta konfirmasi eksplisit.
- Write-off dibatasi `write_off_limit` profil.
- Customer Credit (`is_customer_credit`, khusus Sales Invoice).
- Wallet payment (`is_wallet_payment`, lock saldo wallet di server).
- Pay on Receivable Account (`receivable_account`).
- Pay on Account / credit sale (nol baris payment, `is_credit_sale`,
  khusus Sales Invoice dan setting `allow_credit_sale`).
- `completePayment` emit `payment-completed` dengan payments, change,
  paid, outstanding, write-off, sales team, delivery date,
  receivable account, flag credit sale.
- Bila diskon manual butuh kode HQ, dialog minta `confirmationCode`
  dan validasi lewat restriction store sebelum lanjut.

`POSSale.vue handlePaymentCompleted(paymentData)`:

- Kunci anti dobel `submitInFlight` (double-tap tombol bayar).
- Blokir bila `scheduleBlockingNow()` (deadline wajib lewat).
  Blokir checkout offline bila `scheduleEnforcedNow()`
  (invoice offline bisa basi dan ditolak permanen saat sync).
- Isi payments, sales team, delivery date, write-off ke cart store.
- Online = `cartStore.submitInvoice`.
- Offline = bangun `invoiceData` (offline_id, items, payments, totals,
  write-off, change, relay offer, queue stamp, `edited_from` bila edit
  antrean lama) = `offlineStore.saveInvoiceOffline` (worker IndexedDB) =
  cetak struk lokal = dialog sukses + auto-print bila `print_mode = Auto`.

### 2.7 Submit dua langkah

`composables/useInvoice.js submitInvoice` dibungkus `CoalescingMutex`
dan flag `isSubmitting`. Langkahnya:

1. Nomor antrean (hanya mode Sales Invoice, `queueEnabled`, ada company):
   `utils/queue/queueNumber.acquireQueueNumber` = server
   `pos_next.api.queue.get_next_queue_number`. Offline atau gagal =
   lanjut nomor lokal `pos_queue_last::<company>`.
2. Bangun `invoiceData`: doctype, profil, `posa_pos_opening_shift`,
   customer, buyer, items (`formatItemsForSubmission`), payments
   (split customer credit), `discount_amount`, coupon, `apply_discount_on`
   (default `Grand Total`), `discount_confirmation_code`, `is_pos = 1`,
   `update_stock = 1`, relay offer, receivable account, sales team,
   queue stamp.
3. Step 1 POST `update_invoice` (draft, docstatus 0) = dapat `name`.
4. Step 2 POST `submit_invoice` dengan `{invoice, data: {change_amount,
   write_off_amount, redeemed_customer_credit?, customer_credit_dict?,
   is_credit_sale?}}`.
5. Server kembalikan `{name, status, grand_total, total, net_total,
   outstanding_amount, paid_amount, change_amount, offline_id?,
   pos_queue_number?}`.
6. Frontend `resetInvoice` (cart kosong), tutup dialog, refresh stok
   item terjual, refresh status kode diskon, refresh cache riwayat,
   tampilkan dialog sukses dengan nomor antrean 3 digit,
   auto-print bila profil mengaktifkan.

Detail `update_invoice` (`pos_next/api/invoices.py`):

1. Parse JSON. Simpan pra-strip: relay offer, doctype payload, kupon.
2. `_strip_server_managed_fields`: buang `doctype`, `packed_items`,
   `pos_applied_offer_rules`, `pos_applied_one_time_rules`,
   `pos_relayed_offer_rules`, `pos_offer_item_rules`,
   `coupon_code`, `pos_coupon_code`, `is_pos`, `is_consolidated`,
   `is_cash_or_non_trade_discount`. Klien tidak boleh set field ini.
3. Pop field identitas (`owner`, `docstatus`, `amended_from`, `modified_by`).
4. Normalisasi `pricing_rules` item (list/JSON jadi string koma).
5. Ada `name` = update draft milik sendiri atau berhak tulis.
   Cek konflik `modified` (beda = HTTP 409, kecuali `force_update`).
   Tidak ada `name` = insert draft baru milik sendiri.
6. `_require_return_against` untuk invoice non-SO.
7. Flag permission: `ignore_permissions` untuk draft sendiri,
   `ignore_account_permission = True`.
8. `_enforce_posting_date_policy`: geser posting date hanya lewat lane
   backdate HO (marker `pos_next_backdate_entry`, role + setting
   `allow_change_posting_date`). Selain itu PermissionError.
9. `_check_profile_access`: anggota `POS Profile User` atau punya write
   doctype. Administrator lolos.
10. Set profil, company, currency, branch ke header dan tiap baris.
11. `_set_payment_accounts`: isi `account` tiap baris payment lewat
    `get_payment_account` (rantai: Mode of Payment Account = Payment Method
    profil = default cash company = default bank = Cash/Bank apa pun =
    throw `Missing Account`).
12. Return = `validate_return_items`.
13. Auto-create Customer bila belum ada, set `customer_name`.
14. `ignore_pricing_rule = 1`. Diskon dihitung POSNext sendiri.
15. Ambil setting efektif profil (`allow_user_to_edit_rate`,
    `max_discount_allowed`, `price_replay_audit_only`,
    `disable_rounded_total`).
16. `_validate_item_rates` (SEC-04): server fetch `price_list_rate` sendiri,
    deteksi edit rate manual server-side (rate di bawah list price),
    validasi `validate_manual_rate_edit` (rate positif, editing diizinkan,
    cap `max_discount_allowed`). Baris diskon eksplisit, offer, free,
    paket, dan return dikecualikan dari lane ini.
17. `_verify_offer_rate_magnitudes` (SEC-23): replay pipeline harga yang sama
    dengan `apply_offers` di atas harga server. Mismatch dan setting
    `price_replay_audit_only` = hanya `log_error`. Selain itu throw.
18. Stash offer: query rule one-time, bootstrap total qty/total,
    verifikasi nama rule relay (`verify_transaction_rule_names`),
    tulis `pos_applied_offer_rules` dan `pos_applied_one_time_rules`.
19. Set `is_pos = 1`, `update_stock = 1`, `set_warehouse` = warehouse profil.
20. `set_missing_values(for_validate=True)`. Wajib True.
    False akan memanggil `update_multi_mode_option` yang mengosongkan
    payments dan membuat invoice tampak unpaid.
21. `_ensure_apply_discount_on`: bila ada `discount_amount` tapi basis kosong,
    ambil basis dari kupon else `Grand Total`. Nilai asing ditolak.
22. `calculate_taxes_and_totals`. Null-kan grand total bila None.
23. Return = negasikan semua amount payment.
24. Kupon (key-presence): ada key = validasi `check_coupon_code`
    (customer/company) = stamp `pos_coupon_code` kanonik.
    Return dengan kupon ditolak. Key ada tapi kosong = stamp dibuang.
25. Ada stamp = `_apply_stamped_coupon_discount` dua pass:
    pass satu hitung basis pra-diskon, hitung `expected_coupon_discount`,
    set `discount_amount`, pass dua hitung ulang.
26. Cek stok draft (`_collect_stock_errors`). Langgar = throw JSON `{errors}`.
27. `_enforce_profile_warehouse`: warehouse profil menang di header
    dan semua baris (isolasi outlet).
28. `docstatus = 0`, save, return dict.

Detail `submit_invoice`:

1. Parsing fleksibel (`invoice`/`data`, JSON string, nested).
   Capture pra-strip sama seperti draft.
2. Dedupe offline: `offline_id` = `_ensure_offline_uniqueness`
   (baca `Offline Invoice Sync` `for_update`). Pending di bawah 5 menit =
   throw `SYNC_IN_PROGRESS`. Pending kedaluwarsa/Failed/Synced tanpa
   invoice valid = reuse record. Synced + invoice masih submitted =
   kembalikan invoice lama (`duplicate_prevented: true`).
   Belum ada = insert reservasi Pending. Race unique = rekursi.
3. Mode POS Invoice menolak credit sale, redeem credit, dan partial payment.
   Pesan: switch ke Sales Invoice.
4. Tidak ada `invoice_name` = re-inject relay + kupon = panggil
   `update_invoice` penuh = ambil dokumen. Ada draft = cek owner,
   snapshot attribution item, update dokumen, restore attribution server
   (`_reapply_item_offer_attribution`), verifikasi harga ulang
   (jalur submit tidak boleh lewati verifikasi, COR-BE-02).
5. `_require_return_against`, flag permission, policy posting date,
   cek akses profil. `update_stock = 1`. Return =
   `update_outstanding_for_self = 0` (GL against voucher ke invoice asal).
6. Isi branch dari profil. Isi akun payment. Ganti sales team dari payload.
7. Kupon: bandingkan stamp dokumen vs payload (divergen = `Invalid coupon
   code`), lalu `increment_coupon_usage` dalam transaksi submit
   (lock baris, tolak max-use dan one-use per customer).
8. `_auto_set_return_batches`: return tanpa batch = isi FIFO batch tersedia.
9. Write-off: ambil dari data/invoice, validasi `write_off_limit` profil,
   set akun dan cost center write-off.
10. Paksa warehouse profil. Validasi stok invoice (`_validate_stock_on_invoice`).
11. Kredit: redeem tanpa payment = flag server
    `pos_next_redeemed_customer_credit`. Credit sale tanpa payment =
    cek `allow_credit_sale` = flag `pos_next_credit_sale`.
12. `_ensure_apply_discount_on` + `_apply_stamped_coupon_discount`
    (jalur draft eksis juga), save, submit.
13. Pasca-submit berurutan, semua fail-closed (throw = rollback total):
    return = `reverse_wallet_transactions_for_return` (semua baris wajib sukses),
    `add_to_customer_balance` = `credit_return_to_wallet`,
    offline = `_complete_offline_sync` (tulis pointer invoice, status Synced),
    `redeem_customer_credit` (JE/PE alokasi dengan lock baris),
    audit rate manual = `log_manual_rate_edit` (Comment per item).
14. Return ringkasan totals + change + offline_id.
15. `finally`: belum submit + ada sync record = `_cleanup_failed_sync`
    (status Failed, audit retry).

### 2.8 Pembayaran, kembalian, kredit, partial

- Baris payment = child `Sales Invoice Payment` untuk kedua doctype.
  `_set_payment_accounts` mengisi akun tiap baris.
- Kembalian hanya untuk cash. Non-cash exact amount.
  GL kembalian memakai akun `account_for_change_amount` profil
  (`make_pos_gl_entries`, v16 `get_gle_for_change_amount`).
- Cash mode efektif (`services/cash_mode.py get_cash_mode_of_payment`):
  field `posa_cash_mode_of_payment` profil = baris bertipe Cash
  (default dulu) = literal `Cash`. Ini mencegah baris kas phantom saat closing.
- Wallet (`api/wallet.py`): `validate_wallet_payment` (lock Wallet,
  cek saldo), `process_loyalty_to_wallet` (loyalty jadi saldo pasca-submit),
  cancel wallet di `before_cancel` (hard gate, gagal = cancel batal).
- Customer credit (khusus Sales Invoice): frontend pisah baris
  `is_customer_credit`, server `redeem_customer_credit` buat Journal Entry
  (sumber Invoice) atau Payment Entry alokasi (sumber Advance) dengan lock.
  `get_available_credit` hitung kredit hanya dari return ber-outstanding
  negatif + advance tak teralokasi. Refund tunai outstanding 0 tidak dihitung.
- Partial payment (`api/partial_payments.py`, khusus Sales Invoice):
  daftar unpaid/partial, summary, riwayat dari Payment Ledger Entry,
  `create_payment_entry` (satu-satunya cara tambah bayar setelah submit;
  amount di atas 0 dan di bawah outstanding, tanggal di atas tanggal invoice,
  akun Bank/Cash milik company), `add_payment_to_partial_invoice`
  (batch satu savepoint, semua gagal = rollback),
  gate jadwal `assert_invoice_sales_allowed`.
- Mode POS Invoice mematikan UI credit sale dan customer credit
  (`isPosInvoiceMode` di settings store). Server menolak tiga fitur itu.

### 2.9 Stok

- `_get_available_stock(item)`: batch = `get_batch_qty(batch, warehouse)`.
  Selain itu `Bin.actual_qty`. Bin live karena POS Invoice parity
  posting SLE sendiri (tidak perlu adjustment konsolidasi).
- `_collect_stock_errors(items)`: hitung `stock_qty = qty x conversion`.
  Item `allow_negative_stock = 1` dilewati.
- `_should_block(pos_profile)`: prioritas Stock Settings
  `allow_negative_stock` (linked ke Global Settings) =
  toggle profil `posa_block_sale_beyond_available_qty`
  (0 eksplisit dihormati, kosong = block) = default block bila ada profil.
- `_validate_stock_on_invoice`: saat submit. SKIP untuk Sales Invoice
  tanpa `update_stock`. Cek item stok + packed item. Langgar = throw JSON.
- Draft save di `update_invoice` juga cek stok
  (lookup `is_stock_item` dari master karena baris baru belum punya flag).
- `_enforce_profile_warehouse`: isolasi outlet. Warehouse profil menang.
- Return batch: `_auto_set_return_batches` FIFO. Tanpa batch tersedia = throw.
- Frontend: cart cek stok saat tambah dan naik qty
  (`stockValidator.js`, basis server agar cart tidak dihitung dua kali).
- Offline: worker `SAVE_INVOICE` tidak mengurangi stok lokal
  (komentar eksplisit: hindari NegativeStockError saat sync).
  Setelah sync sukses, stok server di-refresh.

### 2.10 Nomor antrean dan idempotency

- `pos_next/api/queue.py get_next_queue_number(pos_profile)`:
  butuh `enable_pos_queue`. Baris `POS Queue Counter` per `(company, date)`.
  Baca `for_update` = `next = current + 1`. Insert bila belum ada
  (3x coba untuk race unique). `frappe.db.commit()` disengaja agar nomor
  bertahan dan lock lepas.
- `overrides/queue_counter.py bump_queue_counter` (on_submit):
  skip `is_consolidated`. Clamp 1 sampai 10000 (anti-poison payload).
  `UPDATE ... SET current_number = GREATEST(current_number, n)`.
  Tidak pernah menurunkan counter. Insert bila belum ada.
  Nomor offline yang sudah tercetak tidak didaur ulang.
- Frontend `utils/queue/queueNumber.js`: online = server.
  Offline/gagal = lanjut lokal `pos_queue_last::<company>`
  (restart 1 di hari baru, tabrakan antar till offline diterima,
  nomor hanya alat panggil). Format 3 digit. Dialokasikan sebelum draft
  save dan di jalur offline, ikut field invoice, dicetak, tampil di dialog sukses.
- Idempotency kunci: dobel-klik online = `CoalescingMutex` + `isSubmitting`
  (useInvoice) + `submitInFlight` (POSSale) + guard PaymentDialog.
  Offline replay = `offline_id` unik + reservasi `Offline Invoice Sync`
  (Pending/Synced/Failed, stale 5 menit, lock baris) + pre-check
  `check_offline_invoice_synced` + pointer fill-only + pola error
  `DUPLICATE_OFFLINE_INVOICE`. Diskon/offer = ledger `POS Offer Usage`
  nama komposit dan `One Time Customer Offer Usage` nama komposit.
  Kupon = increment/decrement `POS Coupon.used`. Draft conflict = 409.

### 2.11 Diskon: manual, kode HQ, offer, kupon, paket

- Rate manual: `validate_manual_rate_edit` (rate positif, editing diizinkan,
  cap `max_discount_allowed`), audit `log_manual_rate_edit`
  (Comment per item), flag `is_rate_manually_edited` + `original_rate`.
  Deteksi server-side (SEC-04), flag klien hanya hint.
- Discount code gate (`overrides/discount_code.py`): setiap diskon manual
  (item atau header) dan setiap refund butuh `POS Discount Confirmation Code`
  dari HO. `validate_invoice_discounts` saat validate:
  return = wajib kode bila `require_refund_code` (default fail-closed),
  sales = wajib kode bila `invoice_has_manual_discount`.
  Header discount dianggap manual kecuali ada rule transaction terverifikasi
  atau stamp kupon yang menjelaskan header. Item dianggap manual kecuali
  claim rule terverifikasi, applicable, dan rekonsiliasi
  (`_item_offer_matches`, toleransi persen 0.5).
  `validate_code` cek status Active, window, scope outlet.
  `record_code_usage_on_submit` cek ulang di bawah lock dan stamp
  `used_count`, `last_used_by`, `last_used_in_invoice`, `last_used_on`.
- Kupon (`POS Coupon`): `check_coupon_code` (disabled, max use, tanggal,
  restriksi customer), `coupon_base_amount` (basis pra-diskon),
  `expected_coupon_discount` (pct/amount, cap max, di bawah basis),
  `increment_coupon_usage` (lock, tolak max-use dan one-use per customer),
  `decrement_coupon_usage` saat cancel. Alur: validate + stamp di
  `update_invoice`, own dua pass di `_apply_stamped_coupon_discount`,
  increment di `submit_invoice`, release saat cancel.
  Kupon tidak boleh dipakai di return.
- Kuota offer (`overrides/pos_offer_usage.py`): `get_quota_info`
  (scope Global/Per Company, periode Campaign Total/Daily,
  limit global atau baris company), `check_quota`,
  `validate_invoice_offers` (hard gate saat validate),
  `record_offer_usage_on_submit` (lock offer, cek ulang,
  insert idempoten), `release_offer_usage_on_cancel`.
  Mapping rule ke offer via `Pricing Rule.promotional_scheme`
  ke `Promotional Scheme.pos_offer`.
- Paket (`api/packages.py`): satu baris parent role `Package`
  (harga penuh, item non-stok) + komponen role `Package Item` rate 0
  (stok bergerak di komponen, revenue di parent).
  `quote` server-side: `total = base + sum(option.price_adjustment x qty)`.
  Validasi grup (min/max), option max qty, `qty_per_unit`.
  Snapshot disimpan. `validate_invoice_packages` re-quote dari snapshot
  server (harga klien tidak dipercaya), samakan baris, hitung ulang totals.
  Return paket: proporsi komponen wajib. Frontend `packageQuote.js`
  mirror rumus untuk offline. `posPackages.js` cache definisi.

### 2.12 Pajak

- Template pajak profil: `pos_next.api.pos_profile.get_taxes`
  (account, charge type, rate, description, included in print rate).
- Hook `apply_tax_inclusive`: setting efektif `tax_inclusive` per profil.
  Tandai `included_in_print_rate` untuk semua baris kecuali
  `charge_type = Actual`. Recalc bila berubah. Return dengan
  `return_against` salin flag dari invoice asal (koreksi konsisten).
- Diskon header: basis `apply_discount_on` (`Grand Total`/`Net Total`)
  dipaksa valid. Kupon menguasai basis.
- Return: `_build_item_tax_map` (v16 child `item_wise_tax_details`,
  v15 JSON `item_wise_tax_detail`) = `tax_per_unit`, `rate_with_tax`,
  `tax_included_in_rate` untuk dialog return.

### 2.13 Return (retur/refund)

- Cari invoice: `get_returnable_invoices`, `search_invoice_by_number`,
  `search_invoices_for_return`. Scope `_return_scope_for`
  (hanya profil milik user, Administrator di-scope ke profil diminta).
  Filter invoice yang sudah full-return.
- Validitas: `check_invoice_return_validity` = `not_found`/`wrong_outlet`/
  `return_period_expired` (`return_validity_days`, backdate exempt).
- Persiapan: `prepare_return_invoice(invoice_name, pos_opening_shift)`
  memakai `make_sales_return` sesuai doctype asal. Drop `pos_coupon_code`.
  Hitung sisa qty per baris via link `sales_invoice_item` (SI) atau
  `pos_invoice_item` (POS Invoice). `_remap_foreign_payment_modes`
  untuk cross-outlet (Cash ke Cash, Bank ke Bank, fallback cash profil)
  agar refund masuk akun outlet yang benar.
- Submit: `ReturnInvoiceDialog.vue` buat payload `is_return = 1`,
  `return_against`, `update_outstanding_for_self = 0`, qty negatif per baris
  + link baris asal, payments negatif (atau kosong bila add-to-credit),
  `discount_confirmation_code` (gate refund), remarks. Kirim via `submit_invoice`.
- Server: `_require_return_against` wajib, `validate_return_items`
  (cap qty kumulatif), `_validate_return_packages`, batch FIFO,
  wallet reversal wajib sukses, `credit_return_to_wallet` bila add-to-credit,
  `update_outstanding_for_self = 0` sehingga GL against voucher ke invoice
  asal (status Credit Note Issued). Outstanding negatif return = saldo
  credit customer.
- Cancel: `before_cancel` cancel wallet (hard) + credit JE (soft warning).
  `on_cancel` lepas one-time/kupon/offer usage dan decrement kupon.

### 2.14 Offline

- DB Dexie `pos_next_offline`: `settings`, `invoice_queue`
  (`++id, &offline_id, timestamp, synced`), `items`, `customers`,
  `item_prices`, `stock`, `payment_methods`, `sales_persons`, `drafts`,
  `translations`, `offers`, `packages`, `invoice_history`,
  `unpaid_invoices`, `one_time_redemptions`.
- Cache (`cache.js`), status (`offlineState.js`, manual offline),
  worker (`workerClient.js` ke `workers/offline.worker.js`).
  Semua operasi antrean lewat worker pesan.
- Simpan: `worker.saveOfflineInvoice` (`SAVE_INVOICE`) tulis baris antrean
  `{offline_id, data, timestamp, synced: false, retry_count: 0}`.
  Tidak menyentuh stok lokal.
- Sync (`utils/offline/sync.js`): `syncMutex` 60 detik, max 3 retry,
  cleanup 7 hari, ping 3 detik, backoff `5000 x 2^retry`,
  batch max 50 per cycle. Per invoice: pre-check `checkOfflineIdSynced`,
  POST `submit_invoice` dengan `offline_id`, sukses = `markInvoiceSynced`
  (+ hapus receipt cache), `SYNC_IN_PROGRESS` = tunggu 2 detik retry max 3,
  duplikat = tandai synced dengan nama invoice, error permanen
  (ValidationError, non-5xx) = `sync_failed` + pesan server tanpa auto-retry,
  error transient = retry dengan backoff, lewat 3 = `sync_failed`.
- `normalizeInvoiceForSync` (qty wajib di atas 0, stringify pricing rules).
  Edit invoice queued: `supersedeOfflineInvoice` (baris lama `superseded`,
  tidak ikut sync). Checkout baru simpan `edited_from`.
- Replay server melewati `submit_invoice` normal. Semua gerbang harga,
  offer, diskon, stok, shift, dan posting date berlaku.
  Relay offer offline ikut diverifikasi ulang.

### 2.15 Cetak struk

`utils/printInvoice.js printWithSilentFallback`:

- Invoice lokal/offline: hydrate dari `offlineReceiptCache` + antrean DB.
- Invoice server: ambil HTML via `frappe.www.printview.get_html_and_style`
  + `get_invoice` paralel. Kirim ke transport `imin = qz = browser`,
  plus slip kru copy-2 bila profil cetak di atas 1 copy.
- Gagal = fallback `printInvoiceByName` (browser
  `/printview?trigger_print=1`) = fallback template struk hardcoded.
- Offline: `silentPrintInvoiceFromDoc` (template lokal),
  `flagOfflineInvoicePrinted` untuk tanda tercetak.
- Guard dobel cetak: map `printJobsInFlight`.
  Guard `PostPrintError`: bila kertas sudah keluar, jangan fallback browser
  yang mencetak copy kedua.
- Config driver dari POS Settings (`browser|imin|qz`).
  `DirectPrint.vue` + `api/printing.py` untuk uji cetak langsung.

### 2.16 Perbedaan mode Sales Invoice vs POS Invoice

| Aspek | Sales Invoice | POS Invoice (default) |
|---|---|---|
| Posting GL/SLE | Standar SalesInvoice | Parity oleh `CustomPOSInvoice._post_parity_accounting` |
| Konsolidasi (POS Closing Entry) | n/a | Dilarang untuk owned (`guard_against_retroactive_consolidation`) |
| Credit sale, redeem credit, partial payment | Didukung | Ditolak di `submit_invoice` |
| UI credit dan customer-credit | Tampil | Dimatikan via `isPosInvoiceMode` |
| Validasi shift | Standar `validate_pos_opening_entry` | Override owned: shift wajib Open + profil cocok |
| Laporan | Satu doctype | Union + anti double-count SI consolidated |
| `pos_applied_one_time_rules` | Kolom tersimpan | Hanya in-memory |

### 2.17 Alur langkah-demi-langkah satu penjualan normal

1. Kasir sudah login dan shift Open. Layar POSSale tampil.
2. Kasir scan barcode atau pilih item. Dialog varian/UOM/batch muncul bila perlu.
3. Cart merge baris sama, hitung diskon dan pajak per baris,
   kurangi stok tampilan (`server - reserved`).
4. Offer engine jalan debounce: online tanya server `apply_offers`,
   offline pakai mesin lokal. Baris free item rate 0 masuk cart.
   Diskon header transaction-level masuk `additionalDiscount`.
5. Kasir klik Proceed to Payment. Dialog payment tampil dengan
   remaining dan change live.
6. Kasir input satu atau banyak metode bayar. Non-cash wajib pas.
   Overpay cash besar minta konfirmasi. Write-off dibatasi limit.
   Kode HQ diminta bila ada diskon manual.
7. Kasir klik Complete Payment. Frontend kunci `submitInFlight`,
   cek gate jadwal shift, isi payments ke cart.
8. Online: frontend alokasikan queue number, bangun `invoiceData`,
   POST `update_invoice` (draft), POST `submit_invoice` (submit).
   Offline: frontend simpan ke IndexedDB worker, cetak struk lokal,
   tampilkan sukses, antre sync.
9. Server validasi profil, warehouse, akun payment, harga server-side,
   replay offer, stamp kupon, cek stok, tulis attribution offer,
   increment kupon, redeem credit, audit rate manual, submit dokumen,
   posting stok dan GL (mode POS Invoice), naikkan queue counter.
10. Server kembalikan nama invoice, totals, paid, outstanding, change,
    queue number. Frontend reset cart, refresh stok, tampilkan dialog
    sukses dengan nomor antrean, auto-print bila diaktifkan.
11. Struk tercetak via silent transport (imin/qz/browser) atau fallback
    printview. Invoice tercatat di riwayat dan masuk dataset closing shift.

---

## Bagian 3 — POS Closing (tutup shift)

### 3.1 Model data

DocType `POS Closing Shift`:

- `autoname` = `POSA-CS-.YY.-.#######` (naming series setting bila diisi).
- `is_submittable = 1`, `track_changes = 1`.
- Header: `period_start_date` (fetch dari opening),
  `period_end_date` (Datetime, default Today, diisi `get_datetime()`
  saat build), `posting_date`, `pos_opening_shift` (Link, wajib),
  `company`, `pos_profile`, `user` (Cashier, fetch dari opening).
- `pos_transactions` (Table `Sales Invoice Reference`):
  `sales_invoice` atau `pos_invoice` (sesuai doctype asal),
  `posting_date`, `customer`, `grand_total` (base), `transaction_currency`,
  `transaction_amount` (mata uang invoice).
- `payment_reconciliation` (Table `POS Closing Shift Detail`):
  `mode_of_payment` (wajib), `opening_amount` (read-only),
  `closing_amount` (input kasir, wajib), `expected_amount` (read-only),
  `difference` (read-only). Semua Currency company.
- `pos_payments` (Table `POS Payment Entry Reference`):
  `payment_entry`, `posting_date`, `customer`, `paid_amount`,
  `mode_of_payment` (Data).
- `grand_total`, `net_total` (Currency, read-only),
  `total_quantity` (Float, read-only).
- `taxes` (Table `POS Closing Shift Taxes`, read-only):
  `account_head`, `rate`, `amount`.
- `payment_reconciliation_details` (HTML, hanya docstatus 1).
- Permission: System Manager, Sales Manager, POSNext Manager
  (tanpa delete), Administrator (full),
  POSNext Cashier (create/read/write/submit/print/report,
  tanpa cancel/delete).

Efek ke opening:

- `POSClosingShift.on_submit`: `opening.pos_closing_shift = self.name`,
  `set_status()`, save. Status opening menjadi `Closed`.
- `POSClosingShift.on_cancel`: bila link masih menunjuk dokumen ini,
  kosongkan link, `set_status()`, save. Opening kembali `Open`.
- Opening tidak menerima `period_end_date` dari alur ini.
  Waktu tutup aktual dibaca dari `POS Closing Shift.period_end_date`.

### 3.2 Pengumpulan data dari invoice

`get_pos_invoices(pos_opening_shift, doctype=None)`
di `pos_closing_shift.py`:

- Gate baca (SEC-NEW-01): bukan owner dan tanpa permission read
  Closing Shift = `PermissionError(You can only view your own closing shift)`.
- Query per doctype POS Invoice/Sales Invoice (default keduanya):
  `docstatus = 1 AND posa_pos_opening_shift = %s`.
  POS Invoice tambah `consolidated_invoice is null/empty`
  (invoice terkonsolidasi dikecualikan).
- Bulk fetch header (`name, customer, posting_date, posting_time, currency,
  conversion_rate, grand_total, base_grand_total, net_total, base_net_total,
  total_qty, is_return, return_against, change_amount, base_change_amount`)
  + child payments (`mode_of_payment, amount, base_amount`)
  + child taxes (`account_head, rate, tax_amount, base_tax_amount`).
- Murni read. Draft tercetak tidak di-submit di sini (COR-BE-15).
  Hanya dihitung (`_count_pending_printed_drafts`) sebagai peringatan.

`get_payments_entries(pos_opening_shift)` ambil Payment Entry partial:

- `Payment Entry` `docstatus = 1`, `payment_type = Receive`,
  yang reference row-nya menunjuk invoice shift
  (POS Invoice atau Sales Invoice). Match lewat reference rows,
  bukan `reference_no`. Produksi menulis `POS-<invoice>`,
  bukan nama shift.
- Field: `name, mode_of_payment, paid_amount, base_paid_amount`,
  rate, `reference_no`, `posting_date`, `party`.

`_process_invoice` adalah inti perhitungan per invoice:

- `get_base_value`: pakai `base_<field>` bila ada,
  else `value x conversion_rate` (fallback rate berantai, default 1).
- `base_grand_total`, `base_net_total` dihitung sama.
- Credit return tanpa baris payment hanya hasilkan row transaksi
  `grand_total = 0` (audit). Tidak tambah totals, pajak, payment, kas.
  Konsisten dengan `_NO_DRAWER_RETURN` di recap service.
- Row `pos_transactions`: link sesuai doctype asal, posting date/time,
  `grand_total` base, `transaction_currency` + `transaction_amount` asli,
  customer, `is_return`, `return_against` (hanya return).
- Summary: `grand_total += base_grand_total`,
  `net_total += base_net_total`, `total_quantity += total_qty`.
  Return tambah `returns_total += abs(base)`, `returns_count += 1`.
  Sale tambah `sales_total += base`, `sales_count += 1`.
- Pajak: tiap baris taxes agregat kunci `(account_head, rate)`.
  Ketemu tambah amount, tidak ketemu append row baru.
- Payment: tiap baris payments agregat kunci `mode_of_payment`.
  Ketemu tambah `expected_amount`, tidak ketemu append
  `{mode, opening 0, expected amount}`. Return bermode asing
  di-remap ke cash mode (safety net cross-branch).
- Kembalian: `base_change` dikurangi sekali dari cash mode
  (`_aggregate_payment(payments, cash_mode, -base_change)`),
  di luar loop payment agar tidak dobel.

`make_closing_shift_from_opening(opening_shift)` orkestrator dan preview:

- Terima JSON string opening shift. Gate ownership sama.
- Bangun dokumen baru: link opening, period start/end (`end = now`),
  profil, user, company.
- Opening balances: tiap `balance_details` jadi payment row
  `{mode, opening_amount: amount, expected_amount: amount}`.
- Proses semua invoice lewat `_process_invoice`.
- Proses Payment Entry jadi tabel `pos_payments` + tambah expected.
- Set header totals dan child tables.
- Response = dict closing + field display `returns_total/count`,
  `sales_total/count`, `pos_transactions` penuh
  (dengan `is_return` dan posting time), `pending_printed_drafts`.

Cash mode resolver (`services/cash_mode.py get_cash_mode_of_payment`):

- Field `posa_cash_mode_of_payment` profil, bila kolom ada.
- Baris `POS Payment Method` bertipe Cash (default dulu, lalu idx).
- Fallback literal `Cash`.
- Dipakai closing, session summary, dan endpoint
  `get_effective_cash_mode_of_payment`.

Hasil agregat:

- `payment_reconciliation[i].expected_amount` = opening float mode itu
  + semua payment invoice (base) + Payment Entry (base)
  - change (semua change dibebankan ke cash mode).
- `closing_amount` = angka hitung fisik kasir.
  Satu-satunya kontribusi klien di jalur API.
- `difference = closing_amount - expected_amount`
  (presisi `System Settings.currency_precision` atau 3).
- `grand_total` = jumlah base grand total (return ikut negatif,
  credit return tanpa payment wajib 0).
- `net_total` = jumlah base net total.
- `total_quantity` = jumlah total_qty.
- `taxes[i].amount` = jumlah base tax per `(account, rate)`.

### 3.3 Validasi dan siklus dokumen

`POSClosingShift.validate`:

1. Duplicate check dengan locking read: cari Closing Shift submitted
   lain untuk user + opening yang sama (`for_update=True`).
   Ada = throw `Duplicate Closing Entry`.
   Locking perlu karena submit memegang lock row opening.
2. Opening harus `status = Open`.
   Selain itu throw `Selected POS Opening Shift should be open`.
3. `update_payment_reconciliation`: hitung ulang difference per baris.

`before_submit`:

- `submit_printed_invoices(shift, doctype)` untuk POS Invoice dan
  Sales Invoice. Draft Sales Invoice ber-`posa_is_printed = 1`,
  `docstatus = 0`, milik shift ini di-submit. POS Invoice early-return
  (tanpa state printed).
- `_merge_late_submitted_invoices`: invoice shift yang baru submitted
  tapi belum ada di `pos_transactions` di-append (additive, baris manual
  Desk tetap). Totals, pajak, payment, expected di-fold ke nilai dokumen.
- Hitung ulang difference.

`on_submit`:

- `opening.pos_closing_shift = self.name`, `set_status()`,
  `delete_draft_invoices()`, `opening.save()`.
- `_set_closing_entry_invoices`: stamp `pos_closing_entry = self.name`
  ke setiap invoice di `pos_transactions` (bila kolom ada).

`delete_draft_invoices`: syarat kolom `POS Profile.posa_allow_delete`
ada dan true + kolom `posa_pos_opening_shift` ada. Hapus draft milik shift.
Sales Invoice hanya yang `posa_is_printed = 0`. `delete_doc(force=1)`.

`on_cancel`: kosongkan link opening bila masih menunjuk dokumen ini,
`set_status()`, save. Hapus stamp `pos_closing_entry` dari semua invoice
(`_clear_closing_entry_invoices`) agar bisa diproses ulang.

Fungsi inti `submit_closing_shift(closing_shift)`:

1. Parse JSON. `pos_opening_shift` wajib (`MandatoryError`).
2. Lock pertama: `get_value(Opening Shift, name, for_update=True)`.
   Tidak ada = `DoesNotExistError`. Lock ini men-serialize close bersamaan.
3. Load opening. Gate kepemilikan: bukan owner dan tanpa permission
   submit Closing Shift = `PermissionError(You can only close your own shift)`.
4. Auto-submit printed drafts untuk kedua doctype.
5. Server recompute penuh via `make_closing_shift_from_opening`.
   Semua `grand_total`/`net_total`/`expected`/`taxes` dari payload klien
   diabaikan. Angka forged tidak bisa masuk.
6. Klien hanya menyumbang `closing_amount`: dict
   `{mode_of_payment: closing_amount}` dari payload disalin ke row server.
   Row bermode tak dikenal di-drop. Row tanpa hitung dibiarkan.
7. `get_doc(server_data)`, `ignore_permissions = True`, save, submit.
   Return `doc.name`.

Wrapper API di `pos_next/api/shifts.py`:

- `get_closing_shift_data(opening_shift)`: gate di luar try
  (bukan owner dan tanpa read Opening Shift doc itu = 403).
  Ambil opening doc = JSON `default=str` =
  `make_closing_shift_from_opening` = JSON serializable.
  PermissionError di-re-raise (403). Error lain = log + throw generik.
- `submit_closing_shift(closing_shift)`: dict jadi JSON string,
  panggil fungsi doctype, sukses = `{name, status: success}`.
  PermissionError di-re-raise. Error lain = log + throw generik.

Helper print di file doctype:

- `get_cashiers`: hanya filter key `parent` yang diterima.
  Gate member profil atau read Closing Shift.
- `get_payment_reconciliation_details`: render
  `closing_shift_details.html`. Hitung `mode_summaries`
  (base = expected - opening, breakdown per currency),
  `sales_currency_breakdown`, `net_currency_breakdown`.

### 3.4 Endpoint rekap dan riwayat

| Endpoint | Isi | Gate |
|---|---|---|
| `get_session_summary(opening_shift)` | Preview pra-closing = `build_recap(shift_scope(...))` + info shift, kasir, cash mode, `closing_time`/`closing_source` (`actual` dari closing submitted, `estimate` dari deadline, else None) | Owner atau read Opening Shift doc |
| `get_shift_dashboard` | Summary + `hourly` (`shift_hourly`) + `recent` (`shift_recent`) | Sama |
| `get_period_summary` | `build_recap(period_scope(profil, from, to))`, semua kasir, `shift_count`, rate limit 30/60 detik, max 366 hari | `_check_profile_access` |
| `get_period_dashboard` | Summary + hourly + recent periode | Sama |
| `get_shift_history(filters, limit, offset, pos_profile)` | Riwayat shift user: opening/closing name, date, profil, kasir, open/close time, opening amount (sum Opening Detail), closing amount (sum Closing Detail), sales total (closing grand_total), difference (sum). Totals lintas filter tanpa page cap. Limit clamp 1-100, default 25 | Read Opening Shift, user dipaksa server-side |

Atribusi outlet di `period_scope` lewat link shift, bukan field profil invoice.
Invoice backdate masuk shift yang benar walau posting date beda.

### 3.5 Recap service

File `pos_next/services/sales_recap.py`.

Scope:

- `shift_scope(opening_shift)`: `docstatus = 1 AND posa_pos_opening_shift = shift`.
- `period_scope(profil, from, to)`: semua shift submitted profil sebagai
  daftar shift. `shifts` yang posting date di window (drawer).
  `invoice_shifts` semua shift profil (atribusi invoice, termasuk backdate).
  Tanpa shift = `1 = 0` (hasil kosong).
- Sumber invoice: `sales_invoice_union` (POS Invoice + Sales Invoice legacy,
  kecuali SI `is_consolidated = 1` saat mode POS Invoice).
- `_NO_DRAWER_RETURN`: `NOT (is_return = 1 AND tanpa baris payment)`.
  Return kredit tanpa payment keluar dari semua agregat uang dan count.

`build_recap(scope, cash_mode, pos_profile)` hasilkan:

- `_aggregate_totals`: counted invoices, `gross_sales` (non-return),
  `returns_total` (abs), `sales_count`, `returns_count`,
  `net_sales` (jumlah base grand, termasuk return),
  `net_total` (jumlah base net), `total_taxes_and_charges`,
  `invoice_discount` (base discount), `total_qty`,
  `credit_outstanding` (outstanding di atas 0 x rate),
  `average_sale` (gross/count), `currency_breakdown`, `invoice_count`.
- `_aggregate_payments`: payments per mode (payment invoice base +
  Payment Entry Receive base yang refer ke invoice scope),
  `change` (jumlah base change) dikurangi dari cash mode,
  semua mode terkonfigurasi profil tampil walau 0,
  mode terpakai tapi tak terkonfigurasi menyusul (`configured: False`),
  `is_cash` dari tipe Mode of Payment, `total_cash`, `total_non_cash`,
  `methods_grand_total`, `opening_cash` (sum Opening Detail mode Cash
  milik shift scope), `cash_collected = total_cash`,
  `cash_expected = cash_in_hand = opening + collected`,
  `expense: None`, `expense_supported: False`
  (tidak ada ledger expense, sengaja bukan nol palsu).
- `_aggregate_items(limit 100)`: per item + role paket, exclude `Package Item`.
- `_aggregate_charges`: join Account. `account_type = Tax` masuk `tax_total`.
  Selain itu masuk `other_charges` + `other_charges_total`.
- `_aggregate_categories(limit 20)`: per `item_group`
  (fallback Item), item per kategori max 50 + flag truncated.
- `_aggregate_discounts`: `item_discount` = jumlah
  `(price_list_rate - rate) x qty`. `total_discount` = item + invoice.
- Dashboard: `shift_hourly`/`period_hourly` (bucket jam/hari/bulan,
  `is_current`, nol tetap ada), `shift_recent` (invoice terbaru +
  payment mode baris pertama, tanpa drawer filter).

### 3.6 Cetak EOD

Helper Jinja `pos_next/pos_next/utils/pos_closing_print.py`:

- `format_rupiah(value)`: quantize 1 desimal HALF_UP, format `Rp1.234`,
  minus prefix `-`.
- `_as_closing_doc(doc)`: string = get_doc. Tanpa akses baca
  (bukan owner dan tanpa read doc) = kembalikan doc kosong, tidak throw,
  agar print tidak batal.
- `get_items_sold(doc)`: parent target dari `pos_transactions`
  (`sales_invoice` langsung, `pos_invoice` resolve via
  `consolidated_invoice` bila ada). Query child per doctype,
  merge kunci `(item_code, item_name)`, urut amount desc.
  Terdaftar sebagai Jinja method dan dipakai test.
  Format EOD saat ini memakai `get_sales_recap`, bukan fungsi ini.
- `get_sales_recap(doc)`: `total_sales` = grand_total closing,
  `total_order` = jumlah baris transaksi,
  `average_per_order` = total/order. Cash: `opening_balance` (sum opening
  mode Cash), `cash_payment` (sum expected - opening mode Cash),
  `total_expense` hardcoded 0.0, `cash_in_hand` (sum closing mode Cash).
  `payment_methods`: `{mode, amount: expected - opening, is_cash}`.
  `total_cash`, `total_non_cash`, `methods_grand_total`.
  Service vs tax via `_classify_charge` keyword nama
  (PPN/TAX/VAT/PAJAK = tax, SERVICE/JASA/CHARGE = service, default tax).
  Heuristik nama, bukan `Account.account_type` seperti recap service.
  `product_discount` = item-level `(list - rate) x qty` dua doctype
  + invoice-level `discount_amount`. `payment_discount` 0.0.
  `refund_total` = jumlah abs baris transaksi grand negatif.
  `categories` = item grup `item_group`, urut amount desc.

Print format `POS Next EOD Report` (Jinja, doc POS Closing Shift):

- `{% set r = get_sales_recap(doc) %}`.
- CSS sama dengan struk (DejaVu Sans 11px, divider dashed).
- Urutan: header (Cashier, Shift, Start, Closing, Print Date
  `%d/%m/%Y %H:%M`), SALES SUMMARY (Total Sales/Total Order/Average),
  CASH SUMMARY (Opening/Cash Payment/Total Expense/Cash in Hand),
  PAYMENT METHOD (per mode + Total Cash/Total Non Cash/GRAND TOTAL),
  CHARGE (Service, Tax/PPN), DISCOUNT (Product, Payment),
  REFUND (Total Refund), SALES PER CATEGORY
  (kategori + item `qty x item_name`), footer `-- Akhir Laporan --`.
- Registrasi `hooks.py jinja.methods`:
  `get_items_sold`, `get_sales_recap`, `format_rupiah`.

Transport print (`pos_next/api/printing.py`):

- Config per profil (fallback baris POS Settings enabled pertama,
  lalu default): `get_print_config`/`update_print_config`.
- Knob EOD: `imin_eod_print_copies`, `imin_eod_copy_delay_ms`,
  `imin_eod_feed_dots`, `imin_eod_tail_dots`, `imin_eod_font_scale`,
  `imin_eod_line_spacing`, `imin_eod_side_margin`, `imin_eod_top_margin`,
  plus `print_driver` (`browser|qz|imin`) dan `print_fallback_enabled`.
- `get_latest_closing_shift` = closing submitted terbaru (sample EOD).
- `log_print_attempt` tulis `POS Print Log`. `MAX_COPIES = 5`.

Frontend `POS/src/utils/printEod.js printEODReport(name, profil)`:

1. `silentPrintDoc(POS Closing Shift, name, POS Next EOD Report,
   profil, eod)` = `fetchServerPrintHTML`
   (`frappe.www.printview.get_html_and_style`, `no_letterhead: 1`) =
   `transportPrint` (chain imin = qz = browser, knob EOD).
2. Gagal dan fallback on = buka
   `/printview?doctype=POS Closing Shift&name=...&format=...
   &no_letterhead=1&trigger_print=1`. Return `{method: printview}`.
   Popup diblokir = throw.
3. Fallback off (strict driver) = error asli di-rethrow.

Desk: tombol Print EOD Report pada closing submitted buka
`/pos/direct-print?eod=<name>&profile=<profil>`.
`DirectPrint.vue autoprintEod` memakai jalur `silentPrintDoc` yang sama,
banner status + retry, log via fetchLogs.

Backdate entry (`api/backdate_invoices.py`, HO):

- `reopen_shift(pos_opening_shift)`: cek shift submitted + Closed +
  punya closing. Gate role (System Manager/POSNext Manager/Sales Manager/
  Accounts Manager atau Administrator) dan `allow_change_posting_date`
  profil. `POS Closing Shift.cancel()` (on_cancel buka link opening).
  Insert Comment info. Return status.
- `submit_backdate_invoice(invoice)`: shift harus Open hasil reopen.
  Posting date wajib dalam `[period_start_date, today]`.
  Server paksa profil, posting date, `set_posting_time = 1`.
  Set flag `pos_next_backdate_entry = True` (dihormati policy posting date,
  gate jadwal, validasi return), panggil `submit_invoice`, reset flag.
- Setelah backdate, re-close lewat alur closing normal (recompute total).

### 3.7 Frontend closing

Resource di `useShift.js`: `getClosingShiftData` (`{opening_shift}`,
auto false), `submitClosingShift` (`{closing_shift: JSON.stringify(...)}`,
sukses reset state + localStorage), plus check/open yang sama dengan opening.

`ShiftClosingDialog.vue` props `{modelValue, openingShift}`,
emit `update:modelValue`, `shift-closed`:

- Saat dibuka: pause timer durasi, reload POS settings
  (untuk `hide_expected_amount`), hitung invoice offline pending,
  lalu GET `get_closing_shift_data`.
- `loadClosingData`: map `payment_reconciliation` ke row reactive.
  Mode normal: `closing_amount = expected` + text terformat.
  Mode blind (`hideExpectedAmount`): text kosong, amount 0,
  expected tidak ditampilkan. Lalu `calculateDifference` per row.
- Input aktual: `onClosingInput` format ribuan = parse =
  `calculateDifference` (`closing - expected`).
- `canSubmit`: semua row sudah disentuh dan amount terisi.
  False bila `hasPendingInvoices` (pesan `... invoice(s) are still
  pending sync ... sync them before closing ...`) atau cart submitting.
- UI: metric Gross Sales/Returns/Net Sales/Tax Collected,
  list invoice (Invoice, Type Sale/Return, Customer, Time, Amount, net total),
  kartu per mode (Opening/Expected + sales/Actual input,
  badge Balanced/Over +x/Short -x, alert Cash Over/Short),
  Total Expected/Total Actual/Net Variance, Tax Summary.
- `submitClosing`: recalc difference = POST `submit_closing_shift`
  (seluruh objek, server tetap recompute). Sukses = ambil `result.name` =
  panggil `printEODReport(name, pos_profile)`.
  Print gagal = warning `EOD report did not print. Use the Reprint button
  to retry`, tampilkan success report + tombol Print EOD Report
  (`retryEodPrint`). Print sukses + mode blind = success report
  (review angka final) + tombol Close. Print sukses + mode normal =
  emit `shift-closed` + tutup dialog.
  Fallback printview sukses = info `Direct print was not detected.
  The EOD report was opened in a print preview window instead`.
  Submit gagal = `Failed to close shift. Please verify all amounts
  and try again`.
- Mode blind entry: input ringkas per mode
  (`Enter the actual counted amounts for each payment method`).
- `closeDialog`: emit `shift-closed` bila success report tampil,
  reset semua state.

`POSSale.vue` bagian closing:

- Tombol Close Shift = `handleCloseShift` = guard `hasOpenShift` =
  `showCloseShiftDialog = true`.
- Komponen `<ShiftClosingDialog v-model ... :opening-shift ...
  @shift-closed="handleShiftClosed" />`.
- `handleShiftClosed`: tutup dialog, toast `Shift closed successfully`,
  `clearCart` (boundary shift akhiri cart aktif),
  `logoutAfterClose` = cleanup + logout,
  else 500 ms = buka dialog opening shift baru.
- `logoutWithCloseShift`: konfirmasi logout = `logoutAfterClose = true`,
  buka dialog closing.
- `handleCloseExistingShift` (Step 3 Close and Open New dialog opening)
  langsung buka dialog closing.
- Watcher jadwal: warning = toast sekali. Blocking = `forceScheduleClose`.
  Offline = warning reconnect. Online = tutup dialog opening,
  buka dialog closing. Tunggu submit cart in-flight selesai dulu.

### 3.8 Alur langkah-demi-langkah closing

1. Kasir klik Close Shift di POSSale. Guard shift terbuka lolos.
   `showCloseShiftDialog = true`. Dialog ter-mount dengan nama opening shift.
2. Dialog pause timer durasi, reload settings, hitung invoice offline pending,
   lalu GET `get_closing_shift_data {opening_shift}`.
3. Server bangun preview: gate kepemilikan, opening balances dari
   `balance_details`, `get_pos_invoices` (POS Invoice + Sales Invoice
   submitted milik shift), `_process_invoice` per invoice
   (grand/net/qty, payment base, change ke cash mode, pajak,
   skip credit return tanpa payment), `get_payments_entries`
   (Receive PE partial), set child tables + header totals +
   `pending_printed_drafts`.
4. Dialog tampilkan rekap: Gross Sales, Returns, Net Sales, Tax,
   kartu per mode (Opening, Expected, Actual input auto = Expected
   bila bukan blind), invoice detail collapsible, tax summary.
   Peringatan bila ada printed draft pending auto-submit.
5. Kasir hitung uang fisik dan isi Actual Amount tiap mode.
   Live difference = closing - expected, badge Balanced/Over/Short,
   alert Cash Over/Short, Total Expected/Actual/Net Variance update.
   Submit diblokir bila ada invoice offline pending atau cart submitting.
6. Kasir klik Close Shift. POST `submit_closing_shift {closing_shift}`.
7. Server: lock row opening FOR UPDATE, gate owner/submit permission,
   auto-submit printed drafts, recompute penuh dari sumber
   (angka klien diabaikan), salin hanya `closing_amount` per mode,
   save + submit. Validasi duplikat dan opening Open.
   Difference dihitung ulang. `on_submit` set link opening,
   status opening Closed, hapus draft (bila `posa_allow_delete`),
   stamp `pos_closing_entry` ke invoice. Return `{name, success}`.
8. Klien cetak EOD otomatis: `printEODReport(name, profil)` =
   render Jinja server (`get_sales_recap` + `format_rupiah`) =
   transport (iMin = QZ = browser, knob `imin_eod_*`).
   Gagal = fallback printview. Masih gagal = warning + tombol retry.
9. Selesai. Mode normal = tutup dialog + emit `shift-closed`.
   Mode blind = tampilkan success report + tombol Close.
   State shift reset + localStorage dihapus.
   `handleShiftClosed` kosongkan cart lalu buka dialog opening baru
   (atau logout bila logout-with-close).
10. Jalur Desk alternatif: buat POS Closing Shift, pilih opening
    (`status Open, docstatus 1`), JS tarik balance + invoice + PE,
    isi aktual, Save/Submit (jalur `before_submit` merge),
    tombol Print EOD Report = `/pos/direct-print?eod=...`.
11. Backdate/reopen (HO): `reopen_shift` = cancel closing = opening Open,
    `submit_backdate_invoice` (posting date dalam rentang shift),
    re-close normal (recompute).

### 3.9 Selisih kas, pajak, total (presisi)

- Selisih per mode: `difference = closing - expected`,
  presisi `System Settings.currency_precision` atau 3.
  Dihitung di `validate` dan `before_submit`.
  Quirk: handler Desk `pos_closing_shift.js` menghitung
  `expected - closing` (tanda terbalik) saat input.
  Nilai itu dikoreksi saat save karena server hitung ulang.
- Expected = opening float mode itu + jumlah base payment invoice
  + jumlah base Payment Entry (partial) - total change
  (semua change dibebankan ke cash mode).
- Grand total = jumlah base grand total invoice
  (return ikut negatif, credit return tanpa payment wajib 0).
  Net total = jumlah base net total.
  Total quantity = jumlah total_qty.
- Pajak closing: rows `taxes` dari `Sales Taxes and Charges` per invoice,
  agregat `(account_head, rate)`, nilai `base_tax_amount`.
  Tidak diklasifikasi. Klasifikasi baru muncul di print
  (`_classify_charge` keyword) dan recap service
  (`Account.account_type = Tax`).
- Refund print: baris transaksi grand negatif, jumlah abs.
  Returns preview: `returns_total/count` dari `_process_invoice`.
- Saldo kas print helper: `cash_in_hand` = jumlah `closing_amount`
  mode Cash (uang fisik). `cash_payment` = jumlah expected - opening
  mode Cash. `opening_balance` = jumlah opening mode Cash.
  `total_expense` hardcode 0.
- Recap service `cash_in_hand` = opening + total cash
  (expected, bukan fisik). `expense: None` (bukan 0).

---

## Lintas isu (berlaku untuk semua fase)

### Keamanan dan permission

- Create opening: anggota `POS Profile User`, kecuali Administrator.
  Lock baris profil + cek duplikat per user.
- Check opening orang lain: butuh read Opening Shift.
- Closing dan summary orang lain: owner atau permission read/submit
  dokumen yang tepat (`POS Opening Shift` read dengan doc,
  `POS Closing Shift` read/submit). Beda endpoint beda gate, disengaja.
- Non-owner dengan permission submit Closing Shift boleh tutup shift
  (diuji di `test_closing_shift_security.py`).
- Draft invoice: owner atau write doc-level. Konflik `modified` = 409.
- Posting date: hanya lane backdate HO (role + setting
  `allow_change_posting_date` + marker request-scoped).
- Deadline schedule: klien tidak bisa ubah setelah shift ada.
  Hanya `extend_deadline` (audit Comment) atau `db.set_value` admin.
- Kupon dan kode diskon: cek ulang di bawah lock saat submit.
  Stamp server menang atas klaim klien.
- Harga: server fetch list price sendiri dan replay offer.
  Payload klien yang relevan di-strip sebelum save.

### Concurrency dan idempotency

- Buka shift ganda profil sama: lock baris profil men-serialize.
  Sisa race kecil: satu user buka dua profil beda paralel
  (komentar `ponytail` di kode menandai upgrade path lock row User).
- Tutup shift ganda: lock row opening + duplicate check locking read.
- Nomor antrean: lock counter + commit disengaja + `GREATEST` anti-mundur
  + clamp 10000 + retry insert 3x.
- Offline replay: reservasi `Offline Invoice Sync` + stale 5 menit +
  lock baris + pointer fill-only + pre-check + pola error duplikat.
- Offer/kupon/one-time: nama komposit idempoten + lock + cek ulang.
- Submit online dobel-klik: mutex + flag submitting di tiga lapis
  (useInvoice, POSSale, PaymentDialog) + draft lalu submit dua langkah.

### Akuntansi dan stok (kapan GL/SLE ditulis)

- Mode POS Invoice (default lokal): invoice posting stok (SLE) dan GL
  sendiri saat submit (`_post_parity_accounting`). Tidak ada dokumen
  konsolidasi. Merge log retroaktif ditolak.
- Mode Sales Invoice: posting standar SalesInvoice.
  Partial payment menambah Payment Entry setelah submit.
  Credit sale dan redeem credit hanya ada di mode ini.
- Closing tidak menulis GL/SLE. Cancel closing hanya lepas link.
- Return menulis pembalik stok/GL + reversal wallet wajib sukses +
  credit JE (soft warning saat cancel) + lepas usage offer/kupon/one-time.
- Selama paralel eResto (aturan proyek): aggregate Phase 1 tidak gerakkan
  stok per SKU. eResto tetap stock truth sampai cutover.

### Audit trail

- Comment: perpanjangan deadline, edit rate manual per item,
  info reopen shift.
- Ledger usage: `POS Offer Usage` (komposit offer-invoice),
  `One Time Customer Offer Usage` (komposit customer-rule),
  `POS Coupon.used` + `last_used_*`, `POS Queue Counter`,
  `Offline Invoice Sync` (Pending/Synced/Failed + pointer invoice),
  stamp `pos_closing_entry` di invoice, `pos_queue_number/date`,
  `pos_applied_offer_rules`, `pos_coupon_code`,
  `discount_confirmation_code`, `void_note` eResto di sisi fetch
  (bukan field POSNext).
- Print log: `POS Print Log` via `log_print_attempt`.
- Track changes: Opening dan Closing Shift `track_changes = 1`.

### Laporan bawaan

- `cashier_performance_report`, `inventory_impact_and_fast_movers_report`,
  `offline_sync_and_system_health_report`, `sales_vs_shifts_report`,
  `payments_and_cash_control_report` di `pos_next/pos_next/report/`.
- HQ monitoring (`hq_sales_monitoring` page, `hq_monitoring.py`,
  `hq_scope.py`), outlet targets (`outlet_targets`, `target_basis.py`,
  `pos_monthly_target`), backdate entry page, shift history API,
  session/period dashboard (hourly + recent).

---

## Implikasi untuk migrasi eResto (proyek ini)

- Kunci mapping tetap `product_sku` ke Item Code via
  `experiments/sku_to_item_code.csv`. Jangan tebak Item Code.
  Konflik tetap flagged. Aturan ini selaras dengan verifikasi harga
  server-side POSNext (rate di bawah list price = edit manual yang diaudit).
- Idempotency `pos_sync` mengikuti dua pola POSNext:
  agregat `outlet_id + date`, per-transaksi `order_no`
  (sejajar `offline_id` dan nama komposit usage di POSNext).
- Phase 1 (agregat per outlet per hari) sejajar closing shift:
  satu dokumen rekap per outlet per hari, tanpa gerakan stok per SKU.
- Phase 2 (satu POS Invoice per `order_no` + `POS Closing Entry` harian
  per outlet) wajib isi `posa_pos_opening_shift` agar invoice owned,
  patuhi gate jadwal shift, dan tolak jalur kredit/partial
  (tidak ada di mode POS Invoice).
- Aturan void/refund eResto (skip void, `paid_quantity` bukan `quantity`,
  refund = auto-void tanpa Sales Return negatif) tetap berlaku di sisi fetch.
  Di sisi POSNext, refund butuh `return_against` + kode HQ
  (kecuali `require_refund_code` dimatikan) dan Jalur `prepare_return_invoice`.
  Jangan campur dua konsep refund ini.
- Jangan POST sebelum mapping CSV disetujui dan site URL + API key ada.
  Rate limit 10 worker, 3 retry backoff untuk 429/5xx, timeout 90 detik.
- Shift lokal sudah siap (322 profil, 2 grup, 4 metode bayar).
  Belum ada shift dibuka (0 Opening Shift). POST pilot pertama
  (1 order Kebumen) harus buka shift dulu lewat `create_opening_shift`,
  submit invoice dengan `posa_pos_opening_shift` terisi,
  lalu tutup lewat `submit_closing_shift` untuk verifikasi jurnal + stok.

---

## Lampiran A — endpoint yang dipakai alur jualan

| Endpoint | Dipakai untuk |
|---|---|
| `pos_next.api.bootstrap.get_initial_data` | Bootstrap app (shift, profil, settings, payment, precision, locale) |
| `pos_next.api.pos_profile.get_pos_profiles` | Daftar profil step 1 dialog opening |
| `pos_next.api.shifts.get_opening_dialog_data` | Payment method step 2 dialog opening |
| `pos_next.api.shifts.check_opening_shift` | Cek shift terbuka milik user |
| `pos_next.api.shifts.create_opening_shift` | Buat dan submit shift |
| `pos_next.api.invoices.update_invoice` | Step 1 submit (draft) |
| `pos_next.api.invoices.submit_invoice` | Step 2 submit (submit + semua efek) |
| `pos_next.api.invoices.check_offline_invoice_synced` | Pre-check dedupe offline |
| `pos_next.api.invoices.apply_offers` | Mesin offer server-side |
| `pos_next.api.queue.get_next_queue_number` | Nomor antrean harian |
| `pos_next.api.items.search_by_barcode` | Scan barcode |
| `pos_next.api.items.get_item_details` | Detail item dan UOM/batch |
| `pos_next.api.items.get_stock_quantities` | Refresh stok tampilan |
| `pos_next.api.pos_profile.get_taxes` | Template pajak profil |
| `pos_next.api.pos_profile.get_default_customer` | Fallback customer |
| `pos_next.api.offers.get_offers` | Daftar offer profil |
| `pos_next.api.packages.get_packages`, `quote_package` | Daftar dan quote paket |
| `pos_next.api.discount_code.*` | Status dan validasi kode HQ |
| `pos_next.api.partial_payments.*` | Partial payment (khusus Sales Invoice) |
| `pos_next.api.credit_sales.*` | Customer credit (khusus Sales Invoice) |
| `pos_next.api.wallet.*` | Wallet dan loyalty |
| `pos_next.api.shifts.get_closing_shift_data` | Preview closing (rekap server) |
| `pos_next.api.shifts.submit_closing_shift` | Submit closing |
| `pos_next.api.shifts.get_session_summary` | Preview pra-closing shift berjalan |
| `pos_next.api.shifts.get_shift_dashboard` | Summary + hourly + recent |
| `pos_next.api.shifts.get_period_summary` | Rekap periode (rate limited) |
| `pos_next.api.shifts.get_shift_history` | Riwayat shift user (paginated) |
| `pos_next.api.printing.*` | Config print, closing terbaru, print log |
| `pos_next.api.backdate_invoices.*` | Reopen shift dan backdate HO |
| `pos_next.shift_schedule.extend_deadline` | Perpanjang deadline (HQ recovery) |

## Lampiran B — doctype kunci

| DocType | Peran |
|---|---|
| `POS Opening Shift` | Sesi shift (Draft/Open/Closed/Cancelled) + snapshot jadwal |
| `POS Opening Shift Detail` | Modal awal per metode bayar |
| `POS Closing Shift` | Rekap shift + selisih kas + pajak + link invoice |
| `POS Closing Shift Detail` | Rekonsiliasi per mode (opening/expected/closing/difference) |
| `POS Closing Shift Taxes` | Pajak agregat per (akun, rate) |
| `Sales Invoice Reference` | Baris transaksi closing (link invoice + base + mata uang) |
| `POS Payment Entry Reference` | Baris Payment Entry partial di closing |
| `POS Profile Group` | Shift Group (jadwal + Members, push ke profil) |
| `POS Profile Group Member` | Baris member grup |
| `POS Queue Counter` | Counter antrean per (company, date) |
| `Offline Invoice Sync` | Reservasi replay offline (Pending/Synced/Failed) |
| `POS Offer Usage` | Ledger pemakaian offer (komposit offer-invoice) |
| `One Time Customer Offer Usage` | Ledger one-time per customer (komposit customer-rule) |
| `POS Coupon` | Kupon (stamp, usage, max-use, one-use per customer) |
| `POS Discount Confirmation Code` | Kode HQ untuk diskon manual dan refund |
| `POS Offer` + `POS Offer Company` | Definisi offer dan kuota per company |
| `POS Package` + grup/option/outlet | Definisi paket jual |
| `POS Production Recipe` | Resep produksi (sync BOM per company) |
| `POS Next Global Settings` | Setting global (tipe invoice, naming, diskon, kredit, pajak, antrean) |
| `POS Settings` | Setting per profil (efektif via resolver) |
| `POS Print Log` | Log_attempt cetak |
| `POS Closing Shift` print format `POS Next EOD Report` | Struk EOD (Jinja `get_sales_recap`) |

## Lampiran C — peta file kode

| Area | File |
|---|---|
| Opening API | `pos_next/api/shifts.py` (`get_opening_dialog_data`, `check_opening_shift`, `create_opening_shift`) |
| Closing API | `pos_next/api/shifts.py` (`get_closing_shift_data`, `submit_closing_shift`, `get_session_summary`, `get_shift_history`, dashboard, period) |
| Controller opening | `pos_next/pos_next/doctype/pos_opening_shift/pos_opening_shift.py` |
| Controller closing | `pos_next/pos_next/doctype/pos_closing_shift/pos_closing_shift.py` |
| Jadwal shift | `pos_next/shift_schedule.py` |
| Grup shift | `pos_next/pos_next/doctype/pos_profile_group/pos_profile_group.py` |
| Tipe invoice | `pos_next/invoice_type.py` |
| Invoice API | `pos_next/api/invoices.py` (`update_invoice`, `submit_invoice`, return, kupon, offer relay) |
| Event POS Invoice | `pos_next/pos_invoice_events.py` |
| Override akuntansi | `pos_next/overrides/sales_invoice.py` |
| Hook Sales Invoice | `pos_next/api/sales_invoice_hooks.py` |
| Cash mode | `pos_next/services/cash_mode.py` |
| Rekap | `pos_next/services/sales_recap.py` |
| Barcode | `pos_next/services/barcode.py` |
| Naming | `pos_next/naming_series.py` |
| Ownership Price Group | `pos_next/price_group_ownership.py` |
| Print API | `pos_next/api/printing.py` |
| Backdate | `pos_next/api/backdate_invoices.py` |
| Print helper closing | `pos_next/pos_next/utils/pos_closing_print.py` |
| Format EOD | `pos_next/pos_next/print_format/pos_next_eod_report/pos_next_eod_report.json` |
| Frontend shift | `POS/src/composables/useShift.js`, `POS/src/stores/posShift.js`, `POS/src/utils/shiftSchedule.js`, `shiftDuration.js`, `POS/src/components/ShiftOpeningDialog.vue`, `ShiftClosingDialog.vue` |
| Frontend jualan | `POS/src/pages/POSSale.vue`, `POS/src/stores/posCart.js`, `POS/src/composables/useInvoice.js`, `POS/src/stores/posDrafts.js`, `posSync.js`, `posOffers.js`, `posPackages.js`, `itemSearch.js`, `stock.js`, `customerSearch.js`, `POS/src/components/sale/PaymentDialog.vue`, `ReturnInvoiceDialog.vue` |
| Frontend print | `POS/src/utils/printInvoice.js`, `POS/src/utils/printEod.js`, `POS/src/utils/print/*`, `POS/src/pages/DirectPrint.vue` |
| Frontend offline | `POS/src/utils/offline/db.js`, `cache.js`, `sync.js`, `offlineState.js`, `workerClient.js` |
| Route dan bootstrap | `POS/src/router.js`, `POS/src/main.js`, `pos_next/api/bootstrap.py`, `pos_next/www/pos.html`, `hooks.py website_route_rules` |
