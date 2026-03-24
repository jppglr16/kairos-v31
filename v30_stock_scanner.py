import requests,json,os,time,pyotp
import pandas as pd
from datetime import datetime,timedelta
from v30_cache import cache

HEADERS={'User-Agent':'Mozilla/5.0','Accept':'application/json','Referer':'https://www.nseindia.com'}

ANGEL_CONFIG={
    'api_key':os.getenv('ANGEL_API_KEY',''),
    'client_id':os.getenv('ANGEL_CLIENT_ID',''),
    'mpin':'1605',
    'totp_secret':os.getenv('ANGEL_TOTP','')
}

# Priority index instruments
INDEX_PRIORITY=[
    'NIFTY','SENSEX','BANKNIFTY',
    'FINNIFTY','MIDCPNIFTY'
]

# Top F&O stocks to scan
FNO_STOCKS={
    'RELIANCE':   {'token':'2885','exchange':'NSE','lot':250},
    'HDFCBANK':   {'token':'1333','exchange':'NSE','lot':550},
    'ICICIBANK':  {'token':'4963','exchange':'NSE','lot':700},
    'SBIN':       {'token':'3045','exchange':'NSE','lot':1500},
    'TCS':        {'token':'11536','exchange':'NSE','lot':150},
    'INFY':       {'token':'1594','exchange':'NSE','lot':400},
    'LT':         {'token':'11483','exchange':'NSE','lot':450},
    'BAJFINANCE': {'token':'317','exchange':'NSE','lot':125},
    'MARUTI':     {'token':'10999','exchange':'NSE','lot':100},
    'TATAMOTORS': {'token':'3456','exchange':'NSE','lot':1350},
    'WIPRO':      {'token':'3787','exchange':'NSE','lot':1500},
    'AXISBANK':   {'token':'5900','exchange':'NSE','lot':625},
    'KOTAKBANK':  {'token':'1922','exchange':'NSE','lot':400},
    'BHARTIARTL': {'token':'10604','exchange':'NSE','lot':950},
    'SUNPHARMA':  {'token':'3351','exchange':'NSE','lot':350},
    'HINDUNILVR': {'token':'1394','exchange':'NSE','lot':300},
    'NTPC':       {'token':'11630','exchange':'NSE','lot':4500},
    'POWERGRID':  {'token':'14977','exchange':'NSE','lot':3400},
    'ONGC':       {'token':'2475','exchange':'NSE','lot':1925},
    'TATASTEEL':  {'token':'3499','exchange':'NSE','lot':5500},
}

def get_angel_client():
    try:
        from SmartApi import SmartConnect
        obj=SmartConnect(api_key=ANGEL_CONFIG['api_key'])
        totp=pyotp.TOTP(ANGEL_CONFIG['totp_secret']).now()
        obj.generateSession(ANGEL_CONFIG['client_id'],ANGEL_CONFIG['mpin'],totp)
        return obj
    except Exception as e:
        print(f'[SCANNER] Angel login error: {e}')
        return None

def get_stock_candles(client,symbol,tf_minutes=5):
    cached=cache.get(f'stock_candles_{symbol}_{tf_minutes}')
    if cached is not None:return cached
    try:
        info=FNO_STOCKS.get(symbol)
        if not info:return None
        now=datetime.now()
        trade_day=now.strftime('%Y-%m-%d')
        interval='FIVE_MINUTE' if tf_minutes==5 else 'FIFTEEN_MINUTE'
        params={
            'exchange':info['exchange'],
            'symboltoken':info['token'],
            'interval':interval,
            'fromdate':f'{trade_day} 09:15',
            'todate':now.strftime('%Y-%m-%d %H:%M')
        }
        data=client.getCandleData(params)
        if data and data.get('data'):
            candles=[]
            for c in data['data']:
                candles.append({
                    'time':c[0],'open':float(c[1]),
                    'high':float(c[2]),'low':float(c[3]),
                    'close':float(c[4]),'volume':float(c[5])
                })
            df=pd.DataFrame(candles)
            df.columns=['time','open','high','low','close','volume']
            cache.set(f'stock_candles_{symbol}_{tf_minutes}',df,60)
            return df
        return None
    except Exception as e:
        return None

def calc_momentum_score(df):
    try:
        if df is None or len(df)<20:return 0
        c=df['close']
        v=df['volume']
        # RSI
        delta=c.diff()
        gain=delta.clip(lower=0).rolling(14).mean()
        loss=-delta.clip(upper=0).rolling(14).mean()
        rsi=100-(100/(1+gain/loss))
        rsi_val=rsi.iloc[-1]
        # MACD
        ema12=c.ewm(span=12).mean()
        ema26=c.ewm(span=26).mean()
        macd=ema12-ema26
        signal=macd.ewm(span=9).mean()
        macd_hist=(macd-signal).iloc[-1]
        # Volume surge
        vol_surge=v.iloc[-1]>v.rolling(20).mean().iloc[-1]*1.5
        # Price momentum
        ret5=(c.iloc[-1]-c.iloc[-6])/c.iloc[-6] if len(c)>6 else 0
        # Trend
        sma20=c.rolling(20).mean().iloc[-1]
        above_sma=c.iloc[-1]>sma20
        # Score
        score=0
        if 40<rsi_val<60:score+=1
        if rsi_val<35:score+=3  # Oversold bounce
        if rsi_val>65:score+=3  # Strong momentum
        if macd_hist>0:score+=2
        if vol_surge:score+=3
        if abs(ret5)>0.005:score+=2
        if above_sma:score+=1
        # Direction
        direction='BUY' if rsi_val<50 and macd_hist>0 else \
                  'SELL' if rsi_val>50 and macd_hist<0 else None
        return score,direction,rsi_val
    except:
        return 0,None,50

def scan_momentum_stocks(client,top_n=3):
    cached=cache.get('momentum_scan')
    if cached:return cached
    results=[]
    print(f'[SCANNER] Scanning {len(FNO_STOCKS)} stocks...')
    for symbol,info in FNO_STOCKS.items():
        try:
            time.sleep(0.5)
            df=get_stock_candles(client,symbol,5)
            if df is None or len(df)<20:continue
            score_result=calc_momentum_score(df)
            if isinstance(score_result,tuple):
                score,direction,rsi=score_result
            else:
                continue
            if score>=5 and direction:
                results.append({
                    'symbol':symbol,
                    'score':score,
                    'direction':direction,
                    'rsi':rsi,
                    'lot':info['lot'],
                    'price':df['close'].iloc[-1]
                })
        except:continue
    results.sort(key=lambda x:-x['score'])
    top=results[:top_n]
    cache.set('momentum_scan',top,300)
    if top:
        print(f'[SCANNER] Top stocks:')
        for r in top:
            print(f'  {r["symbol"]}: score={r["score"]} dir={r["direction"]} RSI={r["rsi"]:.1f}')
    else:
        print('[SCANNER] No momentum stocks found')
    return top

def get_stock_option_symbol(symbol,action,current_price):
    try:
        # Round to nearest strike
        if current_price>10000:step=500
        elif current_price>5000:step=200
        elif current_price>2000:step=100
        elif current_price>1000:step=50
        else:step=20
        atm=round(current_price/step)*step
        now=datetime.now()
        # Monthly expiry last Thursday
        year=now.year;month=now.month
        # Find last Thursday of month
        import calendar
        last_day=calendar.monthrange(year,month)[1]
        last_thu=max(d for d in range(1,last_day+1)
                    if datetime(year,month,d).weekday()==3)
        expiry=datetime(year,month,last_thu)
        if now.date()>expiry.date():
            # Move to next month
            if month==12:month=1;year+=1
            else:month+=1
            last_day=calendar.monthrange(year,month)[1]
            last_thu=max(d for d in range(1,last_day+1)
                        if datetime(year,month,d).weekday()==3)
            expiry=datetime(year,month,last_thu)
        expiry_str=expiry.strftime('%d%b%y').upper()
        option_type='CE' if action=='BUY' else 'PE'
        symbol_str=f'{symbol}{expiry_str}{atm}{option_type}'
        return symbol_str,atm,option_type
    except Exception as e:
        print(f'[SCANNER] Symbol error: {e}')
        return None,0,None

def should_scan_stocks(active_trades,instruments):
    # Scan stocks if less than 2 index trades active
    index_trades=sum(1 for k in active_trades if k in instruments)
    return index_trades<2

def get_best_opportunity(feed,active_trades,index_instruments,capital):
    try:
        # First check indices by priority
        for inst in INDEX_PRIORITY:
            if inst in active_trades:continue
            df5=feed.get_candles(inst,'5')
            df15=feed.get_candles(inst,'15')
            if df5 is None or df15 is None:continue
            if len(df5)>=20:
                return inst,None  # Signal generation in main loop
        # If no index opportunity, scan stocks
        if should_scan_stocks(active_trades,index_instruments):
            client=get_angel_client()
            if not client:return None,None
            stocks=scan_momentum_stocks(client,top_n=3)
            if stocks:
                best=stocks[0]
                return None,best
        return None,None
    except Exception as e:
        print(f'[SCANNER] Error: {e}')
        return None,None
