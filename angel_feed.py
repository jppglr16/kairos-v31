import pyotp
from SmartApi import SmartConnect
from datetime import datetime,timedelta

ANGEL_CONFIG={
    'api_key':'pEOas0vU',
    'client_id':'J234619',
    'mpin':'1605',
    'totp_secret':'R2T2F2BMP56U44O4OMOYJZTFJI'
}

SYMBOLS={
    'NIFTY':     {'token':'99926000','exchange':'NSE'},
    'BANKNIFTY': {'token':'99926009','exchange':'NSE'},
    'FINNIFTY':  {'token':'99926037','exchange':'NSE'},
    'MIDCPNIFTY':{'token':'99926074','exchange':'NSE'},
    'SENSEX':    {'token':'99919000','exchange':'BSE'},
    'CRUDEOIL':  {'token':'472790','exchange':'MCX'},
    'GOLDM':     {'token':'477904','exchange':'MCX'},
    'SILVERM':   {'token':'457533','exchange':'MCX'},
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
        time.sleep(0.5)  # Rate limit: 0.5s between calls!
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
