import requests,json,os,logging
from datetime import datetime
log=logging.getLogger(__name__)

DEFAULT_LOTS={
    'NIFTY':65,'BANKNIFTY':30,'SENSEX':20,'FINNIFTY':60,
    'MIDCPNIFTY':120,'CRUDEOIL':100,'GOLDM':10,'SILVERM':30,
    'NATURALGAS':1250,'LT':450,'NTPC':4500,'MARUTI':100,
    'BHARTIARTL':950,'SBIN':1500,'TATAMOTORS':1350,
    'RELIANCE':250,'HINDUNILVR':300,'TCS':150,'TATASTEEL':5500
}

def fetch_lot_sizes():
    try:
        log.info('[LOTS] Fetching latest lot sizes...')
        url='https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json'
        r=requests.get(url,timeout=60)
        data=r.json()
        lots=DEFAULT_LOTS.copy()
        targets=list(DEFAULT_LOTS.keys())
        year=str(datetime.now().year)
        for item in data:
            sym=item.get('symbol','')
            name=item.get('name','')
            lotsize=item.get('lotsize',0)
            exch=item.get('exch_seg','')
            if name in targets and exch in ['NFO','BFO','MCX'] and 'FUT' in sym and year in sym:
                if int(lotsize)>0:
                    lots[name]=int(lotsize)
        json.dump(lots,open('ml_models/lot_sizes.json','w'))
        print(f'Updated {len(lots)} lot sizes!')
        return lots
    except Exception as e:
        print(f'Fetch error: {e}')
        return DEFAULT_LOTS

def get_lot_sizes():
    fname='ml_models/lot_sizes.json'
    if os.path.exists(fname):
        import time
        age=(time.time()-os.path.getmtime(fname))/86400
        if age<7:return json.load(open(fname))
    return fetch_lot_sizes()

if __name__=='__main__':
    lots=fetch_lot_sizes()
    print('Latest lot sizes:')
    for inst,lot in lots.items():
        print(f'  {inst:<15}: {lot}')
