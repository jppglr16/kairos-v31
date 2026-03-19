import logging,json,os,pandas as pd
from datetime import datetime
log=logging.getLogger(__name__)

class AngelMCXFeed:
    def __init__(self):
        self.prices={}

    def connect(self):
        try:
            import time
            time.sleep(2)  # Rate limit delay
            from SmartApi import SmartConnect
            import pyotp
            self.obj=SmartConnect(api_key='pEOas0vU')
            totp=pyotp.TOTP('R2T2F2BMP56U44O4OMOYJZTFJI').now()
            self.obj.generateSession('J234619','1605',totp)
            log.info('[ANGEL] MCX connected!')
            return True
        except Exception as e:
            log.error(f'[ANGEL] Error: {e}')
            return False

    def download_history(self,inst,token,exchange='NSE'):
        """Auto download 3 years if not exists"""
        import time
        year=datetime.now().strftime('%Y')
        fname=f'historical_data/{inst}_{year}_5min.json'
        if os.path.exists(fname):
            return  # Already have data!
        log.info(f'[ANGEL] Downloading history for {inst}...')
        quarters=[
            ('2023-01-01','2023-06-30'),
            ('2023-07-01','2023-12-31'),
            ('2024-01-01','2024-06-30'),
            ('2024-07-01','2024-12-31'),
            ('2025-01-01','2025-12-31'),
            ('2026-01-01',datetime.now().strftime('%Y-%m-%d')),
        ]
        all_candles=[]
        for start,end in quarters:
            try:
                time.sleep(0.5)
                resp=self.obj.getCandleData({
                    'exchange':exchange,
                    'symboltoken':token,
                    'interval':'FIVE_MINUTE',
                    'fromdate':f'{start} 09:00',
                    'todate':f'{end} 23:30'
                })
                if resp and resp.get('data'):
                    all_candles.extend(resp['data'])
                    log.info(f'[ANGEL] {inst} {start}: {len(resp["data"])} candles')
            except:pass
        if all_candles:
            json.dump(all_candles,open(fname,'w'))
            log.info(f'[ANGEL] {inst}: {len(all_candles)} candles saved!')

    _last_fetch={}

    def get_candles(self,inst,tf=5):
        import time
        # Rate limit: 1 second between same instrument fetches
        now=time.time()
        last=self._last_fetch.get(inst,0)
        if now-last<1.0:
            time.sleep(1.0-(now-last))
        self._last_fetch[inst]=time.time()

        try:
            candles=[]
            for year in [2022,2023,2024,2025,2026]:
                for fname in [
                    f'historical_data/{inst}_{year}_5min.json',
                ]:
                    if os.path.exists(fname):
                        candles.extend(json.load(open(fname)))
            if not candles:return None
            df=pd.DataFrame(candles,columns=['time','open','high','low','close','volume'])
            for c in ['open','high','low','close','volume']:
                df[c]=pd.to_numeric(df[c],errors='coerce')
            df=df.dropna().sort_values('time').reset_index(drop=True)
            # Get latest candle from Angel API
            try:
                now=datetime.now()
                resp=self.obj.getCandleData({
                    'exchange':'MCX',
                    'symboltoken':{'CRUDEOIL':'472790','GOLDM':'477904','SILVERM':'457533','NATURALGAS':'475111','NIFTY':'99926000','BANKNIFTY':'99926009','SENSEX':'99919000','FINNIFTY':'99926037','MIDCPNIFTY':'99926074','LT':'11483','NTPC':'11630','MARUTI':'10999','BHARTIARTL':'10604','SBIN':'3045','TATAMOTORS':'3456','RELIANCE':'2885','HINDUNILVR':'1394','TCS':'11536','TATASTEEL':'3499'}.get(inst,''),
                    'interval':'FIVE_MINUTE',
                    'fromdate':now.strftime('%Y-%m-%d 09:00'),
                    'todate':now.strftime('%Y-%m-%d %H:%M')
                })
                if resp and resp.get('data'):
                    new_df=pd.DataFrame(resp['data'],columns=['time','open','high','low','close','volume'])
                    for c in ['open','high','low','close','volume']:
                        new_df[c]=pd.to_numeric(new_df[c],errors='coerce')
                    df=pd.concat([df,new_df]).drop_duplicates('time').sort_values('time').reset_index(drop=True)
                    log.debug(f'[ANGEL] {inst} updated with {len(resp["data"])} today candles')
            except:pass
            if tf==5:return df.tail(100)
            return df.tail(300).iloc[::3]
        except Exception as e:
            log.error(f'[ANGEL] Candles {inst}: {e}')
            return None

    def get_price(self,inst):
        return self.prices.get(inst,0)

angel_mcx_feed=AngelMCXFeed()
