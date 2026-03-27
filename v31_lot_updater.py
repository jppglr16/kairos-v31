"""
V31 Auto Lot Size Updater
Fetches correct lot sizes from Angel master
Runs at startup and weekly
"""
import requests, json, os, logging
from datetime import datetime

log = logging.getLogger(__name__)
LOT_FILE = 'lot_sizes.json'

# V31 instruments to track
INSTRUMENTS = [
    'NIFTY','BANKNIFTY','FINNIFTY','MIDCPNIFTY','SENSEX',
    'LT','NTPC','MARUTI','BHARTIARTL','SBIN',
    'TATAMOTORS','TMPV','RELIANCE','HINDUNILVR',
    'TCS','TATASTEEL','CRUDEOIL','GOLDM','SILVERM','NATURALGAS'
]

# Default fallback lot sizes
DEFAULTS = {
    'NIFTY':75,'BANKNIFTY':30,'FINNIFTY':65,
    'MIDCPNIFTY':120,'SENSEX':20,
    'LT':450,'NTPC':4500,'MARUTI':100,
    'BHARTIARTL':475,'SBIN':1500,
    'TATAMOTORS':675,'TMPV':800,
    'RELIANCE':250,'HINDUNILVR':300,
    'TCS':150,'TATASTEEL':5500,
    'CRUDEOIL':100,'GOLDM':10,
    'SILVERM':30,'NATURALGAS':1250,
}

def fetch_lot_sizes():
    """Fetch latest lot sizes from Angel master"""
    try:
        url = 'https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json'
        log.info('[LOT] Downloading master file...')
        data = requests.get(url, timeout=30).json()
        log.info(f'[LOT] Downloaded {len(data)} instruments')

        lot_sizes = {}
        for inst in INSTRUMENTS:
            # Find options for this instrument
            opts = [d for d in data
                   if d.get('symbol','').startswith(inst)
                   and d.get('exch_seg') in ['NFO','BFO','MCX']
                   and d.get('instrumenttype') in ['OPTSTK','OPTIDX','OPTFUT']]

            if opts:
                lot = int(opts[0].get('lotsize', DEFAULTS.get(inst,75)))
                lot_sizes[inst] = lot
                log.info(f'[LOT] {inst}: {lot}')
            else:
                lot_sizes[inst] = DEFAULTS.get(inst, 75)
                log.warning(f'[LOT] {inst}: using default {lot_sizes[inst]}')

        # Save to file
        json.dump({
            'updated': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'lot_sizes': lot_sizes
        }, open(LOT_FILE,'w'), indent=2)

        log.info(f'[LOT] ✅ Updated {len(lot_sizes)} lot sizes!')
        return lot_sizes

    except Exception as e:
        log.error(f'[LOT] Fetch error: {e}')
        return load_lot_sizes()

def load_lot_sizes():
    """Load from file or use defaults"""
    try:
        if os.path.exists(LOT_FILE):
            d = json.load(open(LOT_FILE))
            # Check if less than 7 days old
            updated = datetime.strptime(
                d['updated'], '%Y-%m-%d %H:%M')
            age = (datetime.now() - updated).days
            if age < 7:
                return d['lot_sizes']
            log.info('[LOT] Lot sizes stale, refreshing...')
    except: pass
    return DEFAULTS.copy()

def get_lot(instrument):
    """Get lot size for instrument"""
    sizes = load_lot_sizes()
    # Handle TATAMOTORS → TMPV rename
    if instrument == 'TATAMOTORS':
        return sizes.get('TMPV', sizes.get('TATAMOTORS', 675))
    return sizes.get(instrument, 75)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    sizes = fetch_lot_sizes()
    print('\n=== Current Lot Sizes ===')
    for inst, lot in sorted(sizes.items()):
        default = DEFAULTS.get(inst, 75)
        changed = '⚠️ CHANGED!' if lot != default else ''
        print(f'{inst}: {lot} {changed}')
