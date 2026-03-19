import requests,json,logging
import numpy as np
from v30_cache import cache
log=logging.getLogger(__name__)

HEADERS={
    "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept-Language":"en-US,en;q=0.9",
    "Accept-Encoding":"gzip, deflate, br",
    "Accept":"application/json",
    "Referer":"https://www.nseindia.com/option-chain"
}

def get_nse_session():
    """Create NSE session with proper cookie setup"""
    try:
        import time
        s=requests.Session()
        s.headers.update(HEADERS)
        # Step 1: visit main site
        s.get("https://www.nseindia.com",timeout=10)
        time.sleep(2)
        # Step 2: visit option chain page
        s.get("https://www.nseindia.com/option-chain",timeout=10)
        time.sleep(2)
        return s
    except:return None

def get_option_chain(symbol):
    """Fetch live option chain from NSE"""
    try:
        cached=cache.get(f'oc_{symbol}')
        if cached:return cached
        sym=symbol.replace('NIFTY','NIFTY').replace('BANKNIFTY','BANKNIFTY')
        url=f'https://www.nseindia.com/api/option-chain-indices?symbol={sym}'
        s=get_nse_session()
        if not s:return None
        r=s.get(url,timeout=10)
        if r.status_code==200:
            data=r.json()
            cache.set(f'oc_{symbol}',data,300)
            return data
    except Exception as e:
        log.error(f'[GAMMA] OC fetch error {symbol}: {e}')
    return None

def get_gamma_walls(symbol,current_price):
    """
    Find Gamma Walls:
    Call Wall = Strike with max Call OI
    Put Wall = Strike with max Put OI
    """
    try:
        data=get_option_chain(symbol)
        if not data:
            # Fallback: estimate from price
            step=100 if 'BANK' in symbol else 50
            call_wall=round((current_price+step*3)/step)*step
            put_wall=round((current_price-step*3)/step)*step
            return {
                'call_wall':call_wall,
                'put_wall':put_wall,
                'max_call_oi':0,
                'max_put_oi':0,
                'source':'estimate'
            }

        records=data.get('records',{}).get('data',[])
        call_oi={}
        put_oi={}

        for rec in records:
            strike=rec.get('strikePrice',0)
            if rec.get('CE'):
                call_oi[strike]=rec['CE'].get('openInterest',0)
            if rec.get('PE'):
                put_oi[strike]=rec['PE'].get('openInterest',0)

        if not call_oi or not put_oi:return None

        call_wall=max(call_oi,key=call_oi.get)
        put_wall=max(put_oi,key=put_oi.get)

        result={
            'call_wall':call_wall,
            'put_wall':put_wall,
            'max_call_oi':call_oi[call_wall],
            'max_put_oi':put_oi[put_wall],
            'call_oi':call_oi,
            'put_oi':put_oi,
            'source':'live'
        }
        log.info(f'[GAMMA] {symbol}: Call Wall={call_wall} Put Wall={put_wall}')
        return result

    except Exception as e:
        log.error(f'[GAMMA] Error {symbol}: {e}')
        return None

def check_gamma_signal(symbol,current_price,df5,atr):
    """
    Gamma Wall Signal Detection:
    
    Setup 1 - REJECTION:
    Price near Call Wall + Liq Sweep + FVG → BUY PUT
    
    Setup 2 - BREAKOUT:
    Price breaks Call Wall + Volume spike → BUY CE
    """
    try:
        walls=get_gamma_walls(symbol,current_price)
        if not walls:return None

        call_wall=walls['call_wall']
        put_wall=walls['put_wall']

        # Distance threshold = 0.5% of price
        threshold=current_price*0.005
        dist_call=abs(current_price-call_wall)
        dist_put=abs(current_price-put_wall)

        h=df5['high'];l=df5['low'];v=df5['volume']
        vol_avg=float(v.rolling(20).mean().iloc[-1])
        vol_spike=float(v.iloc[-1])>vol_avg*1.5

        signal=None

        # Setup 1: REJECTION at Call Wall
        if dist_call<threshold:
            # Near call wall = strong resistance
            signal={
                'type':'GAMMA_REJECTION',
                'action':'SELL',
                'option':'PE',
                'wall':'CALL_WALL',
                'wall_level':call_wall,
                'distance':dist_call,
                'reason':f'Price near Call Wall {call_wall}',
                'strength':5
            }
            log.info(f'[GAMMA] {symbol} REJECTION at Call Wall {call_wall}')

        # Setup 1: REJECTION at Put Wall
        elif dist_put<threshold:
            signal={
                'type':'GAMMA_REJECTION',
                'action':'BUY',
                'option':'CE',
                'wall':'PUT_WALL',
                'wall_level':put_wall,
                'distance':dist_put,
                'reason':f'Price near Put Wall {put_wall}',
                'strength':5
            }
            log.info(f'[GAMMA] {symbol} SUPPORT at Put Wall {put_wall}')

        # Setup 2: BREAKOUT above Call Wall
        elif current_price>call_wall and vol_spike:
            signal={
                'type':'GAMMA_BREAKOUT',
                'action':'BUY',
                'option':'CE',
                'wall':'CALL_WALL_BREAK',
                'wall_level':call_wall,
                'distance':current_price-call_wall,
                'reason':f'Broke Call Wall {call_wall} with volume',
                'strength':7
            }
            log.info(f'[GAMMA] {symbol} BREAKOUT above Call Wall {call_wall}')

        # Setup 2: BREAKDOWN below Put Wall
        elif current_price<put_wall and vol_spike:
            signal={
                'type':'GAMMA_BREAKOUT',
                'action':'SELL',
                'option':'PE',
                'wall':'PUT_WALL_BREAK',
                'wall_level':put_wall,
                'distance':put_wall-current_price,
                'reason':f'Broke Put Wall {put_wall} with volume',
                'strength':7
            }

        if signal:
            signal['call_wall']=call_wall
            signal['put_wall']=put_wall
            signal['current_price']=current_price

        return signal

    except Exception as e:
        log.error(f'[GAMMA] Signal error: {e}')
        return None

def check_oi_trap(symbol,current_price,df5):
    """
    OI Trap Model:
    Price falling + Put OI increasing rapidly
    = Market bearish BUT institutions push UP
    = SHORT COVERING RALLY!
    
    Price rising + Call OI increasing rapidly
    = Market bullish BUT institutions push DOWN
    = LONG UNWINDING!
    """
    try:
        walls=get_gamma_walls(symbol,current_price)
        if not walls:return None

        call_oi=walls.get('call_oi',{})
        put_oi=walls.get('put_oi',{})
        if not call_oi or not put_oi:return None

        # Get ATM strikes
        step=100 if 'BANK' in symbol else 50
        atm=round(current_price/step)*step

        # OI near ATM
        atm_call_oi=sum(call_oi.get(atm+s,0) for s in [0,step,step*2])
        atm_put_oi=sum(put_oi.get(atm-s,0) for s in [0,step,step*2])

        # Price direction
        c=df5['close']
        price_falling=float(c.iloc[-1])<float(c.iloc[-5]) if len(c)>=5 else False
        price_rising=float(c.iloc[-1])>float(c.iloc[-5]) if len(c)>=5 else False

        pcr=atm_put_oi/atm_call_oi if atm_call_oi>0 else 1

        trap=None

        # BEAR TRAP: Price falling + High Put OI
        if price_falling and pcr>1.5:
            trap={
                'type':'BEAR_TRAP',
                'action':'BUY',
                'reason':'Price falling but institutions building Put OI = SHORT COVER rally incoming!',
                'pcr':pcr,
                'strength':8,
                'confidence':70
            }
            log.info(f'[GAMMA] {symbol} BEAR TRAP detected! PCR={pcr:.2f}')

        # BULL TRAP: Price rising + High Call OI
        elif price_rising and pcr<0.7:
            trap={
                'type':'BULL_TRAP',
                'action':'SELL',
                'reason':'Price rising but institutions building Call OI = LONG UNWIND incoming!',
                'pcr':pcr,
                'strength':8,
                'confidence':70
            }
            log.info(f'[GAMMA] {symbol} BULL TRAP detected! PCR={pcr:.2f}')

        return trap

    except Exception as e:
        log.error(f'[GAMMA] OI trap error: {e}')
        return None
