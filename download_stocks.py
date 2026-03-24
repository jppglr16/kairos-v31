import pyotp,time,json,os
from SmartApi import SmartConnect

STOCKS={
    'RELIANCE':  {'token':'2885','lot':250},
    'HDFCBANK':  {'token':'1333','lot':550},
    'ICICIBANK': {'token':'4963','lot':700},
    'SBIN':      {'token':'3045','lot':1500},
    'TCS':       {'token':'11536','lot':150},
    'INFY':      {'token':'1594','lot':400},
    'LT':        {'token':'11483','lot':450},
    'BAJFINANCE':{'token':'317','lot':125},
    'MARUTI':    {'token':'10999','lot':100},
    'TATAMOTORS':{'token':'3456','lot':1350},
    'WIPRO':     {'token':'3787','lot':1500},
    'AXISBANK':  {'token':'5900','lot':625},
    'KOTAKBANK': {'token':'1922','lot':400},
    'BHARTIARTL':{'token':'10604','lot':950},
    'SUNPHARMA': {'token':'3351','lot':350},
    'HINDUNILVR':{'token':'1394','lot':300},
    'NTPC':      {'token':'11630','lot':4500},
    'POWERGRID': {'token':'14977','lot':3400},
    'ONGC':      {'token':'2475','lot':1925},
    'TATASTEEL': {'token':'3499','lot':5500},
}

def get_client():
    obj=SmartConnect(api_key=os.getenv('ANGEL_API_KEY',''))
    totp=pyotp.TOTP(os.getenv('ANGEL_TOTP','')).now()
    obj.generateSession(os.getenv('ANGEL_CLIENT_ID',''),'1605',totp)
    return obj

def download_stock_history(client,symbol,token,year):
    os.makedirs('historical_data',exist_ok=True)
    fname=f'historical_data/{symbol}_{year}_5min.json'
    if os.path.exists(fname):
        data=json.load(open(fname))
        if len(data)>1000:
            print(f'[DL] {symbol} {year} exists ({len(data)} candles)')
            return data
    quarters=[
        (f'{year}-01-01',f'{year}-03-31'),
        (f'{year}-04-01',f'{year}-06-30'),
        (f'{year}-07-01',f'{year}-09-30'),
        (f'{year}-10-01',f'{year}-12-31'),
    ]
    all_candles=[]
    for start,end in quarters:
        try:
            time.sleep(2)
            params={
                'exchange':'NSE',
                'symboltoken':token,
                'interval':'FIVE_MINUTE',
                'fromdate':f'{start} 09:15',
                'todate':f'{end} 15:30'
            }
            data=client.getCandleData(params)
            if data and data.get('data'):
                all_candles.extend(data['data'])
                print(f'[DL] {symbol} {year} {start}: {len(data["data"])} candles')
        except Exception as e:
            print(f'[DL] Error {symbol} {year} {start}: {e}')
            time.sleep(5)
    if all_candles:
        json.dump(all_candles,open(fname,'w'))
        print(f'[DL] Saved {symbol} {year}: {len(all_candles)} candles')
    return all_candles

if __name__=='__main__':
    print('Downloading 3 years stock history...')
    client=get_client()
    time.sleep(2)
    for symbol,info in STOCKS.items():
        for year in [2022,2023,2024]:
            download_stock_history(client,info['token'] if 'token' in info else '0',info['token'],year)
            time.sleep(3)
    print('All downloads complete!')
