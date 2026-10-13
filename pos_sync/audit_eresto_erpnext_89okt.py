"""Audit penuh pergerakan 8-9 Okt: eResto stock_cards vs ERPNext Stock Ledger,
NORMALISASI UOM via master Item ERPNext (uoms[] conversion), per warehouse.
Output: Excel 4 sheet gudang + ringkasan status. READ-ONLY.
Status: COCOK / SELISIH RIIL / UOM BEDA (tak normalisasi) / TANPA PADANAN ERP /
        TIDAK ADA DI ERESTO (item ERP ada gerakan, eResto tidak).
"""
import json, ssl, csv, re, os, time
import urllib.request, urllib.parse
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
env = {}
for line in open('/tmp/eresto_prod.env'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1); env[k] = v
base = env['ERPNEXT_URL']; tok = env['ERPNEXT_API_KEY']
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE

def erp(params, doctype):
    r = urllib.request.Request(base + '/api/resource/' + urllib.parse.quote(doctype) + '?' +
        urllib.parse.urlencode(params), headers={'Authorization': 'token ' + tok})
    for i in range(3):
        try:
            return json.load(urllib.request.urlopen(r, timeout=90, context=ctx))['data']
        except Exception:
            time.sleep(2 * (i + 1))
    return []

DIV2WH = {'Gudang Barang Jadi - PH Klaten': 'Gudang Barang Jadi - JURI',
          'Gudang Produksi Klaten': 'Gudang Produksi - JURI',
          'Gudang Bahan Baku - PH Klaten': 'Gudang Bahan Baku - JURI',
          'Gudang Jakarta': 'Gudang Jakarta - JURI'}
WAREHOUSES = list(DIV2WH.values())

# sku->item dari migrasi PO JURI 9-12 Okt (sumber kebenaran mapping bahan pusat)
SKU2ITEM = {}
import re
_map_src = open(os.path.join(HERE, 'migrate_po_juri_9_12_okt.py')).read()
m = re.search(r'ITEM_MAP\s*=\s*\{(.*?)\n\}', _map_src, re.S)
if m:
    for sku, item in re.findall(r'"(BB\d+[^"]*)"\s*:\s*"([^"]+)"', m.group(1)):
        SKU2ITEM[sku] = item
d = json.load(open(os.path.join(HERE, 'eresto_stockcard_89okt.json')))
er = defaultdict(lambda: [0.0, 0.0, ''])  # (div,sku) -> [in,out,nama]
for x in d:
    div = (x.get('division') or {}).get('name')
    if div in DIV2WH:
        inv = x.get('inventory') or {}
        r = er[(div, inv.get('sku'))]
        r[0] += x['stock_in']; r[1] += x['stock_out']; r[2] = inv.get('name') or ''

# ---------- 2) ERP agregat ----------
ep = defaultdict(lambda: [0.0, 0.0, ''])  # (wh,item) -> [in,out,nama]
uom_fact = {}  # item -> {uom_lower: factor}, stock_uom
all_items = set()
for wh in WAREHOUSES:
    for pdt in ('2026-10-08', '2026-10-09'):
        page = 1
        while True:
            rows = erp({'filters': json.dumps([['warehouse', '=', wh], ['posting_date', '=', pdt]]),
                        'fields': json.dumps(['item_code', 'actual_qty']),
                        'limit_page_length': 200, 'limit_start': (page-1)*200}, 'Stock Ledger Entry')
            for e in rows:
                all_items.add(e['item_code'])
                r = ep[(wh, e['item_code'])]
                if e['actual_qty'] > 0: r[0] += e['actual_qty']
                else: r[1] += -e['actual_qty']
            if len(rows) < 200: break
            page += 1
print('item unik di ERP ledger 8-9 Okt (4 gudang):', len(all_items), flush=True)

# ---------- 3) master UOM per item (uoms[] + stock_uom) ----------
for it in sorted(all_items):
    rows = erp({'filters': json.dumps([['name', '=', it]]),
                'fields': json.dumps(['name', 'stock_uom', 'uoms'])}, 'Item')
    if rows:
        x = rows[0]
        uom_fact[it] = {'stock_uom': x['stock_uom'],
                        'uoms': {u['uom'].lower(): u['conversion_factor'] for u in (x.get('uoms') or [])}}
print('master uom terambil:', len(uom_fact), flush=True)

# konversi eResto UOM (Pcs/Pack/kg/g/ctn) -> stock_uom ERP per item:
# kita tidak tahu unit eResto dari stock_card simple, tapi tahu unit_id.
# Pendekatan pragmatis: bandingkan dengan faktor yang membuat selisih minimal
# dari kandidat konversi ERP (1 dan faktor-faktor uoms[]).
def best_match(ein, eout, pin, pout, uoms):
    best = None
    cands = [1.0] + [f for f in uoms.values() if f]
    for f in sorted(set(cands)):
        err = abs(ein*f-pin) + abs(eout*f-pout)
        rel = err / max(1.0, max(pin, pout, ein*f, eout*f))
        if best is None or rel < best[1]:
            best = (f, rel)
    return best  # (faktor, err_relatif)

# ---------- 4) audit dua arah ----------
rows_out = []
for wh in WAREHOUSES:
    div = [k for k, v in DIV2WH.items() if v == wh][0]
    er_keys = {k[1]: v for k, v in er.items() if k[0] == div}
    ep_keys = {k[1]: v for k, v in ep.items() if k[0] == wh}
    # mapping sku->item
    for sku, (ein, eout, nama) in sorted(er_keys.items()):
        item = SKU2ITEM.get(sku, sku)
        p = ep_keys.get(item)
        if p is None:
            rows_out.append([wh, div, sku, nama, '', ein, eout, '', '', '', '', 'TANPA PADANAN ERP'])
            continue
        pin, pout, _ = p
        if abs(ein-pin) < 0.01 and abs(eout-pout) < 0.01:
            rows_out.append([wh, div, sku, nama, item, ein, eout, pin, pout, 1.0, '', 'COCOK'])
            continue
        uoms = uom_fact.get(item, {}).get('uoms', {})
        bm = best_match(ein, eout, pin, pout, uoms)
        if bm and bm[1] < 0.005:
            rows_out.append([wh, div, sku, nama, item, ein, eout, pin, pout, bm[0], '',
                             'COCOK SETELAH KONVERSI (x%s)' % bm[0]])
        elif bm and bm[0] != 1.0 and bm[1] < 0.05:
            rows_out.append([wh, div, sku, nama, item, ein, eout, pin, pout, bm[0],
                             round(ein*bm[0]-pin, 2), 'SELISIH KECIL (x%s)' % bm[0]])
        else:
            rows_out.append([wh, div, sku, nama, item, ein, eout, pin, pout, 1.0,
                             round(ein-pin, 2), 'SELISIH RIIL'])
    # arah sebaliknya: item ERP bergerak tapi tidak ada di eResto
    mapped_items = {SKU2ITEM.get(s, s) for s in er_keys}
    for item, (pin, pout, _) in sorted(ep_keys.items()):
        if item not in mapped_items:
            rows_out.append([wh, div, '', '', item, '', '', pin, pout, '', '', 'TIDAK ADA DI ERESTO'])

json.dump(rows_out, open(os.path.join(HERE, 'audit_89okt_rows.json'), 'w'))
from collections import Counter
c = Counter(r[-1] for r in rows_out)
print('--- RINGKASAN STATUS ---')
for k, v in c.most_common():
    print(f'{v:>5} {k}')
