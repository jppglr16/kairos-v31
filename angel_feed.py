import pyotp
from SmartApi import SmartConnect
from datetime import datetime,timedelta

import os
ANGEL_CONFIG={
    'api_key':os.getenv('ANGEL_API_KEY',''),
    'client_id':os.getenv('ANGEL_CLIENT_ID',''),
    'mpin':os.getenv('ANGEL_MPIN','1605'),
    'totp_secret':os.getenv('ANGEL_TOTP','')
}

SYMBOLS={
    # Indices
    'NIFTY':     {'token':'99926000','exchange':'NSE'},
    'BANKNIFTY': {'token':'99926009','exchange':'NSE'},
    'FINNIFTY':  {'token':'99926037','exchange':'NSE'},
    'MIDCPNIFTY':{'token':'99926074','exchange':'NSE'},
    'SENSEX':    {'token':'99919000','exchange':'BSE'},
    # MCX
        'CRUDEOIL': {'token':'486502','exchange':'MCX'}  # CRUDEOIL20APR26FUT,  # CRUDEOIL20APR26FUT
        'GOLDM': {'token':'477904','exchange':'MCX'}  # GOLDM03APR26FUT,  # GOLDM03APR26FUT
        'SILVERM': {'token':'457533','exchange':'MCX'}  # SILVERM30APR26FUT,  # SILVERMIC30APR26FUT
        'NATURALGAS': {'token':'487465','exchange':'MCX'}  # NATURALGAS27APR26FUT,  # NATURALGAS27APR26FUT
    # NSE Stocks
    'LT':        {'token':'11483','exchange':'NSE'},
    'NTPC':      {'token':'11630','exchange':'NSE'},
    'MARUTI':    {'token':'10999','exchange':'NSE'},
    'BHARTIARTL':{'token':'10604','exchange':'NSE'},
    'SBIN':      {'token':'3045','exchange':'NSE'},
    'TATAMOTORS':{'token':'3456','exchange':'NSE'},
    'RELIANCE':  {'token':'2885','exchange':'NSE'},
    'HINDUNILVR':{'token':'1394','exchange':'NSE'},
    'TCS':       {'token':'11536','exchange':'NSE'},
    'TATASTEEL': {'token':'3505','exchange':'NSE'},
    'HDFCBANK':  {'token':'1333','exchange':'NSE'},
    'ICICIBANK': {'token':'4963','exchange':'NSE'},
    'BAJFINANCE':{'token':'317','exchange':'NSE'},
    'SIEMENS':   {'token':'3150','exchange':'NSE'},
    'POLYCAB':   {'token':'14418','exchange':'NSE'},
    'SOLARINDS': {'token':'22592','exchange':'NSE'},
    'TVSMOTOR':  {'token':'3775','exchange':'NSE'},
    'BOSCHLTD':  {'token':'2181','exchange':'NSE'},
    'PAGEIND':   {'token':'14413','exchange':'NSE'},
    'BRITANNIA': {'token':'547','exchange':'NSE'},
    'APOLLOHOSP':{'token':'157','exchange':'NSE'},
    'OFSS':      {'token':'10738','exchange':'NSE'},
    'BAJAJ-AUTO':{'token':'16669','exchange':'NSE'},
    'EICHERMOT': {'token':'910','exchange':'NSE'},
    'SHREECEM':  {'token':'3103','exchange':'NSE'},
    'CUMMINSIND':{'token':'1901','exchange':'NSE'},
    'ABB':       {'token':'13','exchange':'NSE'},
    'DIVISLAB':  {'token':'10940','exchange':'NSE'},
    'HEROMOTOCO':{'token':'1348','exchange':'NSE'},
    'INDIGO':    {'token':'11195','exchange':'NSE'},
    'TATAELXSI': {'token':'3411','exchange':'NSE'},
    'AMBER':     {'token':'19234','exchange':'NSE'},
    'ALKEM':     {'token':'11703','exchange':'NSE'},
    'TORNTPHARM':{'token':'3518','exchange':'NSE'},
    'KEI':       {'token':'13310','exchange':'NSE'},
}

def get_angel_client():
    try:
        obj=SmartConnect(api_key=ANGEL_CONFIG['api_key'])
        totp=pyotp.TOTP(ANGEL_CONFIG['totp_secret']).now()
        data=obj.generateSession(ANGEL_CONFIG['client_id'],ANGEL_CONFIG['mpin'],totp)
        print(f'[ANGEL] Login: {data["status"]}')
        return obj
    except Exception as e:
        print(f'[ANGEL] Login error: {e}')
        return None

def get_trading_day():
    now=datetime.now()
    if now.hour<9 or (now.hour==9 and now.minute<15):
        now=now-timedelta(days=1)
    while now.weekday()>=5:
        now=now-timedelta(days=1)
    return now.strftime('%Y-%m-%d')

def get_historical(client,instrument,tf_minutes):
    try:
        sym=SYMBOLS[instrument]
        interval='FIVE_MINUTE' if tf_minutes==5 else 'FIFTEEN_MINUTE'
        trade_day=get_trading_day()
        now=datetime.now()
        if now.hour<9:
            to_time=f'{trade_day} 23:30'
        else:
            to_time=now.strftime('%Y-%m-%d %H:%M')
        from_time=f'{trade_day} 09:00'
        params={
            'exchange':sym['exchange'],
            'symboltoken':sym['token'],
            'interval':interval,
            'fromdate':from_time,
            'todate':to_time
        }
        import time
        global _last_call,_MIN_GAP,_last_adjust,_throttle_lock
        with _throttle_lock:
            _now=time.time()
            _gap=_now-_last_call
            if _gap<_MIN_GAP:
                time.sleep(_MIN_GAP-_gap)
            _last_call=time.time()
            # Soft reset: recover every 60s
            if _now-_last_adjust>60:
                _MIN_GAP=max(_MIN_GAP-0.1,0.7)
                _last_adjust=_now
                log.debug(f'[FEED] throttle gap={_MIN_GAP:.2f}s')
        data=client.getCandleData(params)
        if data and data.get('status') and data.get('data'):
            candles=[]
            for c in data['data']:
                candles.append({'time':c[0],'open':float(c[1]),'high':float(c[2]),'low':float(c[3]),'close':float(c[4]),'volume':float(c[5])})
            print(f'[ANGEL] {instrument} {tf_minutes}m: {len(candles)} candles!')
            return candles
        return []
    except Exception as e:
        print(f'[ANGEL] Error {instrument}: {e}')
        return []
