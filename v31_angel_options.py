import logging,time
from SmartApi import SmartConnect
import pyotp
from datetime import datetime,timedelta
import json,os

log=logging.getLogger(__name__)

# Exchange mapping
EXCHANGE_MAP={
    'NIFTY':'NFO','BANKNIFTY':'NFO','SENSEX':'BFO','SENSEX50':'BFO',
    'FINNIFTY':'NFO','MIDCPNIFTY':'NFO',
    'CRUDEOIL':'MCX','GOLDM':'MCX','SILVERM':'MCX','NATURALGAS':'MCX',
    'LT':'NFO','NTPC':'NFO','MARUTI':'NFO','BHARTIARTL':'NFO',
    'SBIN':'NFO','TATAMOTORS':'NFO','RELIANCE':'NFO',
    'HINDUNILVR':'NFO','TCS':'NFO','TATASTEEL':'NFO'
}

# Strike step
STEP_MAP={
    'NIFTY':50,'BANKNIFTY':100,'SENSEX':100,'SENSEX50':100,
    'FINNIFTY':50,'MIDCPNIFTY':25,
    'CRUDEOIL':100,'GOLDM':100,'SILVERM':500,'NATURALGAS':10,
    # Stocks - 10 point strikes
    'HINDUNILVR':10,'HDFCBANK':10,'ICICIBANK':10,'SBIN':10,
    'TATAMOTORS':5,'TMPV':5,'TATASTEEL':5,'BHARTIARTL':10,'NTPC':5,
    'LT':50,'RELIANCE':50,'TCS':50,'INFOSYS':50,
    'MARUTI':100,'BAJFINANCE':50,'BAJAJ-AUTO':50,
    'EICHERMOT':50,'SIEMENS':50,'POLYCAB':50,
    'DIVISLAB':50,'APOLLOHOSP':50,'BRITANNIA':50,
    'BOSCHLTD':100,'PAGEIND':100,'SOLARINDS':50,
    'TVSMOTOR':10,'HEROMOTOCO':50,'INDIGO':100,
    'TATAELXSI':50,'AMBER':50,'ALKEM':50,
    'TORNTPHARM':50,'KEI':50,'ABB':50,
    'CUMMINSIND':50,'SHREECEM':100,'OFSS':50,
}

def get_expiry_str(inst):
    """Get nearest expiry in DDMMMYY format"""
    from datetime import timedelta
    today=datetime.now()
    if inst in ['NIFTY','BANKNIFTY','FINNIFTY','MIDCPNIFTY','SENSEX']:
        # Use master file for nearest expiry
        try:
            import json,os,re
            master='angel_options_lookup.json'
            prefix={'NIFTY':'NIFTY','BANKNIFTY':'BANKNIFTY','FINNIFTY':'FINNIFTY','MIDCPNIFTY':'MIDCPNIFTY','SENSEX':'SENSEX50'}.get(inst,inst)
            if os.path.exists(master):
                lookup=json.load(open(master))
                expiries=set()
                for k in lookup:
                    if k.startswith(prefix) and k[len(prefix):len(prefix)+2].isdigit() and 'CE' in k:
                        m2=re.search(prefix+r'(\d{2}[A-Z]{3}\d{2})',k)
                        if m2:expiries.add(m2.group(1))
                future=[]
                for e in expiries:
                    try:
                        dt=datetime.strptime(e,'%d%b%y')
                        if dt.date()>=today.date():future.append((dt,e))
                    except:pass
                if future:
                    return min(future,key=lambda x:x[0])[1]
        except:pass
        days=(3-today.weekday())%7
        if days==0:days=7
        from datetime import timedelta
        expiry=today+timedelta(days=days)
    elif inst in ['CRUDEOIL','GOLDM','SILVERM','NATURALGAS']:
        # MCX options expire on 3rd Wednesday of month
        import calendar
        def mcx_option_expiry(y,m):
            # Find 3rd Wednesday
            count=0
            for d in range(1,calendar.monthrange(y,m)[1]+1):
                if datetime(y,m,d).weekday()==2:  # Wednesday
                    count+=1
                    if count==3:
                        return datetime(y,m,d)
            return datetime(y,m,15)

        exp=mcx_option_expiry(today.year,today.month)
        # Switch to next month if < 2 days to expiry or passed
        if (exp.date()-today.date()).days<2:
            m=today.month+1 if today.month<12 else 1
            y=today.year+1 if today.month==12 else today.year
            exp=mcx_option_expiry(y,m)
        expiry=exp
    else:
        # Stocks - last Thursday of month
        import calendar
        y,m=today.year,today.month
        def last_thursday(y,m):
            last=calendar.monthrange(y,m)[1]
            for d in range(last,0,-1):
                if datetime(y,m,d).weekday()==3:
                    return datetime(y,m,d)
            return datetime(y,m,1)
        exp=last_thursday(y,m)
        # If expiry passed or today, use next month
        if exp.date()<=today.date():
            m=m+1 if m<12 else 1
            y=y+1 if today.month==12 else y
            exp=last_thursday(y,m)
        # Angel One uses settlement date (T+2) for stocks
        from datetime import timedelta
        settlement=exp+timedelta(days=2)
        # Skip weekend
        if settlement.weekday()==5:settlement+=timedelta(days=2)
        elif settlement.weekday()==6:settlement+=timedelta(days=1)
        expiry=settlement
    return expiry.strftime('%d%b%y').upper()

def get_atm_strike(inst,price):
    """Get ATM strike"""
    step=STEP_MAP.get(inst,50)
    if inst not in STEP_MAP:
        if price<=500:step=5
        elif price<=1000:step=10
        elif price<=2000:step=20
        elif price<=5000:step=50
        elif price<=10000:step=100
        else:step=200
    return round(price/step)*step

def get_option_symbol(inst,price,opt_type,lookup=None,today=None):
    """Get option symbol using master lookup"""
    import re
    from datetime import datetime as _dt
    if today is None:today=_dt.now()

    # Prefix mapping
    prefix_map={
        'NIFTY':'NIFTY','BANKNIFTY':'BANKNIFTY',
        'FINNIFTY':'FINNIFTY','MIDCPNIFTY':'MIDCPNIFTY',
        'SENSEX':'SENSEX50','CRUDEOIL':'CRUDEOIL',
        'GOLDM':'GOLDM','SILVERM':'SILVERM','NATURALGAS':'NATURALGAS',
        'TATAMOTORS':'TMPV',  # TATAMOTORS renamed to TMPV on exchanges!
    }
    prefix=prefix_map.get(inst,inst)

    # Strike step
    step=STEP_MAP.get(inst,50)

    strike=round(price/step)*step

    # Load lookup if not provided
    if lookup is None:
        import json,os
        master='angel_options_lookup.json'
        if os.path.exists(master):
            lookup=json.load(open(master))
        else:
            lookup={}

    # Extract expiries
    pattern=prefix+r'([0-9]{2}[A-Z]{3}[0-9]{2})'
    expiries=set()
    for k in lookup:
        if k.startswith(prefix):
            m=re.search(pattern,k)
            if m:expiries.add(m.group(1))

    if not expiries:
        # Fallback
        expiry=get_expiry_str(inst)
        return f'{prefix}{expiry}{int(strike)}{opt_type}',strike,expiry

    # Filter future expiries
    future=[]
    for e in expiries:
        try:
            dt=_dt.strptime(e,'%d%b%y')
            if dt.date()>=today.date():future.append((dt,e))
        except:pass

    if not future:
        expiry=get_expiry_str(inst)
        return f'{prefix}{expiry}{int(strike)}{opt_type}',strike,expiry

    expiry=min(future,key=lambda x:x[0])[1]
    # Try full format first (DDMMMYY+strike)
    symbol=f'{prefix}{expiry}{int(strike)}{opt_type}'

    # If not in lookup, try short format (DDMMM without year)
    if lookup and symbol not in lookup:
        short_exp=expiry[:5]  # e.g. '26MAR' from '26MAR26'
        symbol_short=f'{prefix}{short_exp}{int(strike)}{opt_type}'
        if symbol_short in lookup:
            symbol=symbol_short
        else:
            # Try finding nearest available strike
            import re as _re
            matches=[k for k in lookup
                    if k.startswith(f'{prefix}{short_exp}') and opt_type in k]
            if matches:
                best=min(matches,key=lambda x:abs(
                    int(_re.search(r'(\d+)'+opt_type,x).group(1))-int(strike))
                    if _re.search(r'(\d+)'+opt_type,x) else 99999)
                symbol=best

    return symbol,strike,expiry


def search_option_token(obj,inst,price,opt_type):
    """Search Angel One for option token using master file"""
    symbol,strike,expiry=get_option_symbol(inst,price,opt_type)
    # SENSEX uses BFO exchange
    exchange=EXCHANGE_MAP.get(inst,'NFO')
    if inst=='SENSEX':exchange='BFO' 
    try:
        import json,os
        # Use master file for instant lookup
        master_file='angel_options_lookup.json'
        if os.path.exists(master_file):
            lookup=json.load(open(master_file))
            if symbol in lookup:
                token=lookup[symbol]['token']
                log.info(f'[ANGEL OPT] Token found: {symbol} = {token}')
                return token,symbol,exchange
            # Try finding nearest available strike
            import re
            inst_exp=f'{inst}{expiry}'
            matches=[k for k in lookup if k.startswith(inst_exp) and opt_type in k]
            if matches:
                # Find nearest strike
                target_strike=strike
                best=min(matches,key=lambda x:abs(int(re.search(r'(\d+)'+opt_type,x).group(1))-target_strike))
                token=lookup[best]['token']
                log.info(f'[ANGEL OPT] Nearest token: {best} = {token}')
                return token,best,exchange
        log.warning(f'[ANGEL OPT] Token not found for {symbol}')
        return None,symbol,exchange
    except Exception as e:
        log.error(f'[ANGEL OPT] Search error: {e}')
        return None,symbol,exchange

def place_option_order(obj,inst,price,opt_type,qty,action='BUY'):
    """Place option order on Angel One"""
    try:
        token,symbol,exchange=search_option_token(obj,inst,price,opt_type)
        if not token:
            log.error(f'[ANGEL OPT] No token for {inst} {opt_type}')
            return None

        order={
            'variety':'NORMAL',
            'tradingsymbol':symbol,
            'symboltoken':token,
            'transactiontype':action,
            'exchange':exchange,
            'ordertype':'MARKET',
            'producttype':'INTRADAY',
            'duration':'DAY',
            'quantity':str(qty)
        }

        log.info(f'[ANGEL OPT] Placing: {symbol} {action} {qty}')
        resp=obj.placeOrder(order)
        if resp and resp.get('status'):
            order_id=resp.get('data',{}).get('orderid','')
            log.info(f'[ANGEL OPT] Order placed! ID:{order_id}')
            return order_id
        else:
            log.error(f'[ANGEL OPT] Order failed: {resp}')
            return None
    except Exception as e:
        log.error(f'[ANGEL OPT] Error: {e}')
        return None
