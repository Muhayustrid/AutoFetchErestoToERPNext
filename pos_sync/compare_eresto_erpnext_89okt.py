"""Bandingkan pergerakan 8-9 Okt: eResto stock_cards vs ERPNext Stock Ledger.
Div pusat: Gudang Barang Jadi / Produksi / Bahan Baku - PH Klaten, Gudang Jakarta.
Output: Excel + print selisih. READ-ONLY eResto.
"""
import json, ssl, urllib.request, urllib.parse, os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
env = {}
for line in open('/tmp/eresto_prod.env'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1); env[k] = v
base = env['ERPNEXT_URL']; tok = env['ERPNEXT_API_KEY']
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE

def erp(path_params, doctype):
    r = urllib.request.Request(base + '/api/resource/' + urllib.parse.quote(doctype) + '?' +
        urllib.parse.urlencode(path_params), headers={'Authorization': 'token ' + tok})
    return json.load(urllib.request.urlopen(r, timeout=90, context=ctx))['data']

# 1) eResto agregat per (div, sku)
d = json.load(open(os.path.join(HERE, 'eresto_stockcard_89okt.json')))
er = defaultdict(lambda: [0.0, 0.0])
for x in d:
    div = (x.get('division') or {}).get('name')
    sku = (x.get('inventory') or {}).get('sku')
    if div in ('Gudang Barang Jadi - PH Klaten', 'Gudang Produksi Klaten',
               'Gudang Bahan Baku - PH Klaten', 'Gudang Jakarta'):
        er[(div, sku)][0] += x['stock_in']
        er[(div, sku)][1] += x['stock_out']

# 2) ERPNext agregat per (wh, item)
WAREHOUSES = ['Gudang Barang Jadi - JURI', 'Gudang Produksi - JURI',
              'Gudang Bahan Baku - JURI', 'Gudang Jakarta - JURI']
ep = defaultdict(lambda: [0.0, 0.0])
for wh in WAREHOUSES:
    for pdt in ('2026-10-08', '2026-10-09'):
        page = 1
        while True:
            rows = erp({'filters': json.dumps([['item_code', '!=', ''],
                        ['warehouse', '=', wh], ['posting_date', '=', pdt]]),
                'fields': json.dumps(['item_code', 'actual_qty', 'voucher_type']),
                'limit_page_length': 200, 'limit_start': (page-1)*200}, 'Stock Ledger Entry')
            for e in rows:
                ep[(wh, e['item_code'])][0 if e['actual_qty'] > 0 else 1] += abs(e['actual_qty'])
            if len(rows) < 200:
                break
            page += 1
json.dump({f'{k[0]}|{k[1]}': v for k, v in ep.items()},
          open(os.path.join(HERE, 'erpnext_move_89okt.json'), 'w'))

# 3) mapping div eResto -> wh ERPNext & sku eResto -> item ERPNext
DIV2WH = {'Gudang Barang Jadi - PH Klaten': 'Gudang Barang Jadi - JURI',
          'Gudang Produksi Klaten': 'Gudang Produksi - JURI',
          'Gudang Bahan Baku - PH Klaten': 'Gudang Bahan Baku - JURI',
          'Gudang Jakarta': 'Gudang Jakarta - JURI'}
# sku->item dari migrasi PO JURI 9-12 Okt (sumber kebenaran mapping bahan pusat)
SKU2ITEM = {}
import re
_map_src = open(os.path.join(HERE, 'migrate_po_juri_9_12_okt.py')).read()
m = re.search(r'ITEM_MAP\s*=\s*\{(.*?)\n\}', _map_src, re.S)
if m:
    for sku, item in re.findall(r'"(BB\d+[^"]*)"\s*:\s*"([^"]+)"', m.group(1)):
        SKU2ITEM[sku] = item
# item->sku reverse utk perbandingan dua arah
ITEM2SKU = {v: k for k, v in SKU2ITEM.items()}

# 4) bandingkan per warehouse
report = {}
for wh in WAREHOUSES:
    div = [k for k, v in DIV2WH.items() if v == wh][0]
    pairs = set(k for k in er if k[0] == div) | set(k for k in ep if k[0] == wh)
    out_rows = []
    for divsku in sorted(k for k in pairs if k[0] == div):
        sku = divsku[1]
        ein, eout = er.get(divsku, [0.0, 0.0])
        # cari item di ERPNext: lewat mapping sku->item; kalau tidak ada, coba sku langsung
        item = SKU2ITEM.get(sku, sku)
        pin, pout = ep.get((wh, item), [0.0, 0.0])
        if abs(ein-pin) < 0.01 and abs(eout-pout) < 0.01:
            continue  # cocok
        out_rows.append((sku, item, ein, eout, pin, pout))
    report[wh] = out_rows

n = 0
for wh, rows in report.items():
    print('=' * 10, wh, f'({len(rows)} selisih)')
    for sku, item, ein, eout, pin, pout in rows[:80]:
        print(f'  {sku:<9} {item:<10} eResto in={ein:>10.2f} out={eout:>10.2f} | ERP in={pin:>10.2f} out={pout:>10.2f}')
        n += 1
print('TOTAL selisih:', n)
