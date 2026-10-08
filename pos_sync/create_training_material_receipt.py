"""Script pembuat Material Receipt untuk Company TRAINING di ERPNext Baru
berdasarkan data Stock Reconciliation RS PKU MUHAMMADIYAH DELANGGU.
"""

import os
import json
import requests

def load_env(path):
    env = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip().strip('\"\'')
    return env

def main():
    prod_env = load_env('/tmp/eresto_prod.env')
    new_url = prod_env.get('ERPNEXT_URL', 'https://ropierpnext.frappe.cloud')
    new_key = prod_env.get('ERPNEXT_API_KEY')
    headers = {'Authorization': f'token {new_key}', 'Content-Type': 'application/json'}

    reco_names = [
        'RECO-RPMD-261006001',
        'RECO-RPMD-261006002',
        'RECO-RPMD-261006003',
        'RECO-RPMD-261008001'
    ]

    rows = []
    for r_name in reco_names:
        res = requests.get(f'{new_url}/api/resource/Stock Reconciliation/{r_name}', headers=headers).json()['data']
        for row in res['items']:
            r_item = requests.get(f'{new_url}/api/resource/Item/{row["item_code"]}', headers=headers).json().get('data', {})
            stock_uom = r_item.get('stock_uom')
            rows.append({
                'item_code': row['item_code'],
                'qty': row['qty'],
                'uom': stock_uom,
                'stock_uom': stock_uom,
                'conversion_factor': 1.0,
                'transfer_qty': row['qty'],
                'basic_rate': row['valuation_rate'],
                't_warehouse': 'Stores - TRNG',
                'expense_account': '5110.020 - Penyesuaian Stock - TRNG',
                'cost_center': 'Main - TRNG'
            })

    payload = {
        'doctype': 'Stock Entry',
        'stock_entry_type': 'Material Receipt',
        'purpose': 'Material Receipt',
        'company': 'TRAINING',
        'to_warehouse': 'Stores - TRNG',
        'posting_date': '2026-10-08',
        'remarks': 'Material Receipt pembukaan stok training dari Stock Reconciliation RS PKU MUHAMMADIYAH DELANGGU',
        'items': rows
    }

    print(f'Creating Material Receipt for TRAINING with {len(rows)} items...')
    res = requests.post(f'{new_url}/api/resource/Stock Entry', headers=headers, json=payload)
    if res.status_code != 200:
        print('Error:', res.text)
        return
    doc = res.json()['data']
    doc_name = doc['name']
    print(f'Created Draft: {doc_name}, incoming value: {doc.get("total_incoming_value")}')

    # Submit
    res_sub = requests.put(f'{new_url}/api/resource/Stock Entry/{doc_name}', headers=headers, json={'docstatus': 1})
    if res_sub.status_code == 200:
        print(f'Successfully Submitted {doc_name}!')
    else:
        print('Submit error:', res_sub.text)

if __name__ == '__main__':
    main()
