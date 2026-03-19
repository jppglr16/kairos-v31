"""
BFO Options Handler - SENSEX/BSE Options
Fetches real strikes from Angel One master file
"""
import requests,re,json,os,logging
from datetime import datetime
log=logging.getLogger(__name__)

URL="https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
BFO_CACHE=None
CACHE_TIME=None
CACHE_TTL=3600  # Refresh every hour

def load_bfo_options(force=False):
    """Load BFO options with caching"""
    global BFO_CACHE,CACHE_TIME
    import time
    now=time.time()

    # Return cache if valid
    if BFO_CACHE and CACHE_TIME and not force:
        if now-CACHE_TIME<CACHE_TTL:
            return BFO_CACHE

    # Try local file first
    cache_file='bfo_options_cache.json'
    if os.path.exists(cache_file) and not force:
        try:
            age=now-os.path.getmtime(cache_file)
            if age<CACHE_TTL:
                BFO_CACHE=json.load(open(cache_file))
                CACHE_TIME=now
                log.info(f'[BFO] Loaded {len(BFO_CACHE)} options from cache')
                return BFO_CACHE
        except:pass

    # Download fresh
    log.info('[BFO] Downloading fresh BFO options...')
    try:
        data=requests.get(URL,timeout=60).json()
        bfo=[]
        for d in data:
            sym=d.get('symbol','')
            if d.get('exch_seg')!='BFO':continue
            if not sym.endswith(('CE','PE')):continue

            # Extract 5-digit strike
            m=re.search(r'(\d{5,6})',sym)
            if not m:continue

            strike=int(m.group(1))
            if strike<50000 or strike>100000:continue  # Valid SENSEX range

            expiry_str=d.get('expiry','')
            if not expiry_str:continue

            bfo.append({
                'symbol':sym,
                'token':d.get('token',''),
                'strike':strike,
                'expiry':expiry_str,
                'lotsize':int(d.get('lotsize',20)),
                'type':'CE' if sym.endswith('CE') else 'PE'
            })

        BFO_CACHE=bfo
        CACHE_TIME=now
        json.dump(bfo,open(cache_file,'w'))
        log.info(f'[BFO] Downloaded {len(bfo)} BFO options')
        return bfo
    except Exception as e:
        log.error(f'[BFO] Download error: {e}')
        return BFO_CACHE or []


def is_valid_expiry(exp_str):
    """Check if expiry is in the future"""
    try:
        # Handle different formats
        for fmt in ['%d%b%Y','%d%b%y','%Y-%m-%d']:
            try:
                dt=datetime.strptime(exp_str,fmt)
                return dt.date()>=datetime.now().date()
            except:pass
        return False
    except:
        return False


def get_nearest_expiry(options,opt_type):
    """Get nearest valid expiry date"""
    expiries=set()
    for o in options:
        if o['type']==opt_type and is_valid_expiry(o['expiry']):
            expiries.add(o['expiry'])
    if not expiries:return None

    # Parse and sort
    valid=[]
    for e in expiries:
        for fmt in ['%d%b%Y','%d%b%y']:
            try:
                dt=datetime.strptime(e,fmt)
                valid.append((dt,e))
                break
            except:pass

    return min(valid,key=lambda x:x[0])[1] if valid else None


def get_bfo_option(instrument,price,opt_type,shift=0):
    """
    Get BFO option symbol with token
    instrument: 'SENSEX'
    price: current spot price
    opt_type: 'CE' or 'PE'
    shift: 0=ATM, 1=1OTM, 2=2OTM, -1=1ITM
    """
    try:
        options=load_bfo_options()
        if not options:
            log.warning('[BFO] No options data!')
            return None,None,None,None

        # Round to nearest 100 for SENSEX
        step=100
        base_strike=round(price/step)*step
        strike=base_strike+(shift*step)

        # Get nearest expiry
        nearest_exp=get_nearest_expiry(options,opt_type)
        if not nearest_exp:
            log.warning('[BFO] No valid expiry found!')
            return None,None,None,None

        # Filter candidates
        candidates=[o for o in options
                   if o['strike']==strike
                   and o['type']==opt_type
                   and is_valid_expiry(o['expiry'])]

        if not candidates:
            # Try nearest available strike
            all_strikes=sorted(set(o['strike'] for o in options
                                  if o['type']==opt_type
                                  and is_valid_expiry(o['expiry'])))
            if not all_strikes:
                log.warning(f'[BFO] No strikes found for {opt_type}')
                return None,None,None,None

            nearest=min(all_strikes,key=lambda x:abs(x-strike))
            candidates=[o for o in options
                       if o['strike']==nearest
                       and o['type']==opt_type
                       and is_valid_expiry(o['expiry'])]
            if candidates:
                strike=nearest
                log.info(f'[BFO] Using nearest strike {nearest} instead of {base_strike+(shift*step)}')

        if not candidates:
            return None,None,None,None

        # Pick nearest expiry
        def parse_exp(e):
            for fmt in ['%d%b%Y','%d%b%y']:
                try:return datetime.strptime(e,fmt)
                except:pass
            return datetime.max

        best=min(candidates,key=lambda x:parse_exp(x['expiry']))
        log.info(f'[BFO] Found: {best["symbol"]} token={best["token"]}')
        return best['symbol'],best['token'],best['strike'],best['expiry']

    except Exception as e:
        log.error(f'[BFO] Error: {e}')
        return None,None,None,None


def get_bfo_ltp(angel_obj,instrument,price,opt_type,shift=0):
    """Get real LTP for BFO option"""
    try:
        sym,token,strike,expiry=get_bfo_option(instrument,price,opt_type,shift)
        if not token:return 0,None

        ltp_resp=angel_obj.ltpData('BFO',sym,token)
        if ltp_resp and ltp_resp.get('data'):
            price_val=float(ltp_resp['data'].get('ltp',0))
            log.info(f'[BFO] {sym}: Rs.{price_val}')
            return price_val,sym
        return 0,sym
    except Exception as e:
        log.error(f'[BFO] LTP error: {e}')
        return 0,None


# Test function
if __name__=='__main__':
    print('Loading BFO options...')
    opts=load_bfo_options(force=True)
    print(f'Total: {len(opts)}')

    # Test SENSEX
    sym,token,strike,exp=get_bfo_option('SENSEX',76700,'CE',shift=0)
    print(f'SENSEX ATM CE: {sym} strike={strike} exp={exp} token={token}')

    sym,token,strike,exp=get_bfo_option('SENSEX',76700,'PE',shift=0)
    print(f'SENSEX ATM PE: {sym} strike={strike} exp={exp} token={token}')

    sym,token,strike,exp=get_bfo_option('SENSEX',76700,'CE',shift=1)
    print(f'SENSEX OTM CE: {sym} strike={strike} exp={exp} token={token}')
