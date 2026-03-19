"""
V31 Universal Option Engine - Clean Production Version
Uses Angel One strike field directly (no regex!)
"""
import requests,json,os,logging,time
from datetime import datetime
log=logging.getLogger(__name__)

URL="https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
CACHE=None
CACHE_FILE='option_engine_cache.json'
CACHE_TTL=3600

# ============================================================
# CONFIG
# ============================================================
CONFIG={
    'NIFTY':     {'seg':'NFO','step':50},
    'BANKNIFTY': {'seg':'NFO','step':100},
    'FINNIFTY':  {'seg':'NFO','step':50},
    'MIDCPNIFTY':{'seg':'NFO','step':25},
    'SENSEX':    {'seg':'BFO','step':100},
    'LT':        {'seg':'NFO','step':50},
    'RELIANCE':  {'seg':'NFO','step':20},
    'TCS':       {'seg':'NFO','step':20},
    'HDFCBANK':  {'seg':'NFO','step':10},
    'ICICIBANK': {'seg':'NFO','step':20},
    'BHARTIARTL':{'seg':'NFO','step':20},
    'SBIN':      {'seg':'NFO','step':5},
    'TATAMOTORS':{'seg':'NFO','step':5},
    'HINDUNILVR':{'seg':'NFO','step':20},
    'MARUTI':    {'seg':'NFO','step':100},
    'NTPC':      {'seg':'NFO','step':5},
    'TATASTEEL': {'seg':'NFO','step':2},
    'BAJFINANCE':{'seg':'NFO','step':50},
    'SIEMENS':   {'seg':'NFO','step':50},
    'POLYCAB':   {'seg':'NFO','step':50},
    'BAYERCROP': {'seg':'NFO','step':50},
    'SOLARINDS': {'seg':'NFO','step':100},
    'TVSMOTOR':  {'seg':'NFO','step':50},
    'APARINDS':  {'seg':'NFO','step':100},
    'MRF':       {'seg':'NFO','step':500},
    'BOSCHLTD':  {'seg':'NFO','step':100},
    'ABBOTINDIA':{'seg':'NFO','step':100},
    'PAGEIND':   {'seg':'NFO','step':100},
    'BAJAJAUTO': {'seg':'NFO','step':100},
    'BRITANNIA': {'seg':'NFO','step':50},
    'APOLLOHOSP':{'seg':'NFO','step':50},
    'OFSS':      {'seg':'NFO','step':100},
    'NATURALGAS':{'seg':'MCX','step':10},
    'CRUDEOIL':  {'seg':'MCX','step':100},
    'GOLDM':     {'seg':'MCX','step':100},
    'SILVERM':   {'seg':'MCX','step':500},
}

# ============================================================
# STRIKE EXTRACTOR (No Regex!)
# ============================================================
def get_strike(d):
    """Extract real strike from Angel One data"""
    try:
        # Angel provides strike scaled by 100
        raw=float(d.get('strike',0) or 0)
        if raw>0:
            return int(raw)//100
        return None
    except:
        return None

# ============================================================
# INSTRUMENT MATCHER
# ============================================================
def match_instrument(d,instrument):
    """Match instrument using name OR symbol"""
    name=d.get('name','').upper().strip()
    sym=d.get('symbol','').upper().strip()
    inst=instrument.upper()
    return inst in name or sym.startswith(inst)

# ============================================================
# EXPIRY PARSER
# ============================================================
def parse_expiry(exp_str):
    """Parse Angel One expiry format"""
    for fmt in ['%d%b%Y','%d%b%y','%Y-%m-%d']:
        try:
            return datetime.strptime(exp_str,fmt)
        except:pass
    return None

def is_valid_expiry(exp_str):
    dt=parse_expiry(exp_str)
    return dt and dt.date()>=datetime.now().date()

# ============================================================
# LOADER WITH CACHE
# ============================================================
def load_all_options(force=False):
    global CACHE
    now=time.time()

    if CACHE and not force:
        return CACHE

    # Check file cache
    if os.path.exists(CACHE_FILE) and not force:
        try:
            age=now-os.path.getmtime(CACHE_FILE)
            if age<CACHE_TTL:
                CACHE=json.load(open(CACHE_FILE))
                log.info(f'[OE] Loaded {len(CACHE)} from cache')
                return CACHE
        except:pass

    log.info('[OE] Downloading options master...')
    try:
        data=requests.get(URL,timeout=60).json()
        options=[]
        for d in data:
            sym=d.get('symbol','')
            seg=d.get('exch_seg','')

            if seg not in ('NFO','BFO','MCX'):continue
            if not sym.endswith(('CE','PE')):continue

            strike=get_strike(d)
            if not strike or strike<=0:continue

            expiry=d.get('expiry','')
            if not expiry:continue

            options.append({
                'name':d.get('name','').strip(),
                'symbol':sym,
                'token':d.get('token',''),
                'strike':strike,
                'expiry':expiry,
                'lotsize':int(float(d.get('lotsize',0) or 0)),
                'type':'CE' if sym.endswith('CE') else 'PE',
                'seg':seg
            })

        CACHE=options
        json.dump(options,open(CACHE_FILE,'w'))
        log.info(f'[OE] Cached {len(options)} options')
        return options
    except Exception as e:
        log.error(f'[OE] Error: {e}')
        return CACHE or []

# ============================================================
# NEAREST EXPIRY
# ============================================================
def get_nearest_expiry_options(options):
    today=datetime.now().replace(hour=0,minute=0,second=0)
    valid=[]
    for o in options:
        dt=parse_expiry(o['expiry'])
        if dt and dt>=today:
            valid.append((dt,o))
    if not valid:return []
    valid.sort(key=lambda x:x[0])
    nearest=valid[0][0]
    return [o for dt,o in valid if dt==nearest]

# ============================================================
# UNIVERSAL OPTION SELECTOR
# ============================================================
def get_option(instrument,price,opt_type,shift=0):
    """
    Universal option lookup - works for all instruments!
    Returns dict with symbol/token/strike/expiry/segment
    or None if not found
    """
    cfg=CONFIG.get(instrument)
    if not cfg:
        log.warning(f'[OE] Unknown: {instrument}')
        return None

    options=load_all_options()
    seg=cfg['seg']
    step=cfg['step']

    # Filter by instrument + segment + type
    opts=[o for o in options
          if match_instrument(o,instrument)
          and o.get('seg')==seg
          and o.get('type')==opt_type]

    if not opts:
        log.warning(f'[OE] No options: {instrument}')
        return None

    # Nearest expiry
    nearest=get_nearest_expiry_options(opts)
    if not nearest:
        log.warning(f'[OE] No valid expiry: {instrument}')
        return None

    # Target strike
    base=round(price/step)*step
    target=base+(shift*step)

    # Exact match
    exact=[o for o in nearest if o['strike']==target]

    if not exact:
        # Nearest available
        strikes=sorted(set(o['strike'] for o in nearest))
        if not strikes:return None
        nearest_s=min(strikes,key=lambda x:abs(x-target))
        exact=[o for o in nearest if o['strike']==nearest_s]
        if exact:
            log.info(f'[OE] {instrument}: nearest={nearest_s} target={target}')

    if not exact:return None

    o=exact[0]
    return {
        'symbol':o['symbol'],
        'token':o['token'],
        'strike':o['strike'],
        'expiry':o['expiry'],
        'segment':seg,
        'lotsize':o.get('lotsize',0)
    }

# ============================================================
# REAL LTP
# ============================================================
def is_liquid(angel_obj,segment,symbol,token,ltp):
    """Check if option is liquid - uses Volume + OI + Spread"""
    try:
        # Get full market depth
        resp=angel_obj.getMarketData('FULL',{segment:[token]})
        if not resp or not resp.get('data'):return True

        fetched=resp['data'].get('fetched',[])
        if not fetched:return True

        d=fetched[0]
        volume=int(d.get('tradeVolume',0) or 0)
        oi=int(d.get('opnInterest',0) or 0)

        # Get bid/ask from depth
        buy_book=d.get('depth',{}).get('buy',[])
        sell_book=d.get('depth',{}).get('sell',[])
        bid=float(buy_book[0].get('price',0)) if buy_book else 0
        ask=float(sell_book[0].get('price',0)) if sell_book else 0

        # Check 1: Volume
        if volume>0 and volume<1000:
            log.info(f'[OE] {symbol} LOW VOLUME: {volume}')
            return False

        # Check 2: OI
        if oi>0 and oi<500:
            log.info(f'[OE] {symbol} LOW OI: {oi}')
            return False

        # Check 3: Spread
        if ltp>0 and bid>0 and ask>0:
            spread_pct=(ask-bid)/ltp*100
            if spread_pct>3.0:
                log.info(f'[OE] {symbol} WIDE SPREAD: {spread_pct:.1f}%')
                return False

        log.info(f'[OE] {symbol} LIQUID vol={volume:,} oi={oi:,}')
        return True
    except Exception as e:
        log.debug(f'[OE] Liquidity check error: {e}')
        return True  # Default allow


def get_option_ltp(angel_obj,instrument,price,opt_type,shift=0):
    """Get real LTP for any option"""
    result=get_option(instrument,price,opt_type,shift)
    if not result:return 0,None
    try:
        resp=angel_obj.ltpData(result['segment'],result['symbol'],result['token'])
        if resp and resp.get('data'):
            ltp=float(resp['data'].get('ltp',0))
            if ltp<=0:return 0,result

            # Liquidity check
            if not is_liquid(angel_obj,result['segment'],
                            result['symbol'],result['token'],ltp):
                log.info(f'[OE] {result["symbol"]} ILLIQUID - skipping!')
                # Try next strike
                return get_option_ltp(angel_obj,instrument,price,opt_type,shift+1)

            log.info(f'[OE] {result["symbol"]}: Rs.{ltp}')
            return ltp,result
    except Exception as e:
        log.error(f'[OE] LTP error: {e}')
    return 0,result

def refresh_cache():
    """Force refresh options cache"""
    global CACHE
    CACHE=None
    if os.path.exists(CACHE_FILE):
        os.remove(CACHE_FILE)
    return load_all_options(force=True)

# ============================================================
# TEST
# ============================================================
if __name__=='__main__':
    print('Universal Option Engine Test')
    opts=load_all_options(force=True)
    print(f'Total: {len(opts)}')

    # Debug sample
    print('\nSample data:')
    for o in opts[:5]:
        print(f'  name={o["name"]} sym={o["symbol"]} strike={o["strike"]} seg={o["seg"]}')

    print()
    tests=[
        ('NIFTY',23750,'CE'),
        ('BANKNIFTY',54000,'CE'),
        ('FINNIFTY',24000,'CE'),
        ('SENSEX',76700,'CE'),
        ('LT',3600,'CE'),
        ('NATURALGAS',284,'CE'),
        ('CRUDEOIL',8800,'CE'),
    ]
    for inst,price,opt in tests:
        r=get_option(inst,price,opt)
        if r:
            print(f'{inst}: {r["symbol"]} strike={r["strike"]} exp={r["expiry"]}')
        else:
            print(f'{inst}: NOT FOUND')
