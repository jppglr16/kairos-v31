import logging,pandas as pd
from datetime import datetime
log=logging.getLogger(__name__)
class CandleBuilder:
    def __init__(self,tf):
        self.tf=tf;self.candles=[];self.current=None
    def add_tick(self,price,volume=0):
        now=datetime.now();mb=(now.minute//self.tf)*self.tf
        ct=now.replace(minute=mb,second=0,microsecond=0)
        if self.current is None or self.current['time']!=ct:
            if self.current:
                self.candles.append(self.current)
                if len(self.candles)>200:self.candles=self.candles[-200:]
            self.current={'time':ct,'open':price,'high':price,'low':price,'close':price,'volume':volume}
        else:
            self.current['high']=max(self.current['high'],price)
            self.current['low']=min(self.current['low'],price)
            self.current['close']=price;self.current['volume']+=volume
    def get_df(self):
        data=self.candles.copy()
        if self.current:data.append(self.current)
        if len(data)<20:return None
        return pd.DataFrame(data,columns=['time','open','high','low','close','volume'])
class MarketDataFeed:
    def __init__(self,client):
        self.client=client
        # All 18 instruments
        ALL_INSTRUMENTS=['NIFTY','BANKNIFTY','SENSEX','FINNIFTY','MIDCPNIFTY',
                         'CRUDEOIL','GOLDM','SILVERM','NATURALGAS',
                         'LT','NTPC','MARUTI','BHARTIARTL','SBIN',
                         'TATAMOTORS','RELIANCE','HINDUNILVR','TCS','TATASTEEL']
        self.builders={inst:{'5':CandleBuilder(5),'15':CandleBuilder(15)}
                       for inst in ALL_INSTRUMENTS}
        self.tokens={
            'NIFTY':{'token':'26000','segment':'nse_cm'},
            'BANKNIFTY':{'token':'26009','segment':'nse_cm'},
            'SENSEX':{'token':'1','segment':'bse_cm'},
            'FINNIFTY':{'token':'26037','segment':'nse_cm'},
            'MIDCPNIFTY':{'token':'26074','segment':'nse_cm'},
            'CRUDEOIL':{'token':'472790','segment':'mcx_fo'},
            'GOLDM':{'token':'477904','segment':'mcx_fo'},
            'SILVERM':{'token':'457533','segment':'mcx_fo'},
            'NATURALGAS':{'token':'475111','segment':'mcx_fo'},
            'LT':{'token':'11483','segment':'nse_cm'},
            'NTPC':{'token':'11630','segment':'nse_cm'},
            'MARUTI':{'token':'10999','segment':'nse_cm'},
            'BHARTIARTL':{'token':'10604','segment':'nse_cm'},
            'SBIN':{'token':'3045','segment':'nse_cm'},
            'TATAMOTORS':{'token':'3456','segment':'nse_cm'},
            'RELIANCE':{'token':'2885','segment':'nse_cm'},
            'HINDUNILVR':{'token':'1394','segment':'nse_cm'},
            'TCS':{'token':'11536','segment':'nse_cm'},
            'TATASTEEL':{'token':'3499','segment':'nse_cm'},
        }
        self.prices={}
    def on_tick(self,data):
        try:
            for item in data:
                token=str(item.get('instrument_token',''));price=float(item.get('last_price',0))
                vol=int(item.get('volume',0));inst=None
                for i,t in self.tokens.items():
                    if t['token']==token:inst=i;break
                if not inst or price<=0:continue
                self.prices[inst]=price
                self.builders[inst]['5'].add_tick(price,vol)
                self.builders[inst]['15'].add_tick(price,vol)
        except Exception as e:log.error(f'Tick:{e}')
    def get_candles(self,inst,tf):return self.builders[inst][tf].get_df()
    def get_price(self,inst):return self.prices.get(inst,0)
    def start(self):
        try:
            tokens=[{'instrument_token':t['token'],'exchange_segment':t['segment']} for t in self.tokens.values()]
            self.client.subscribe(instrument_tokens=tokens,isIndex=True,isDepth=False)
            self.client.on_ticks=self.on_tick
            log.info('[FEED] Live feed started!')
        except Exception as e:log.error(f'Feed error:{e}')
    def load_historical(self,inst,tf):
        try:
            t=self.tokens[inst];interval='5minute' if tf==5 else '15minute'
            now=datetime.now();start=now.replace(hour=9,minute=15,second=0)
            data=self.client.history(instrument_token=t['token'],exchange_segment=t['segment'],to_date=now.strftime('%Y-%m-%d %H:%M'),from_date=start.strftime('%Y-%m-%d %H:%M'),interval=interval)
            if data and 'data' in data:
                for c in data['data']:
                    self.builders[inst][str(tf)].candles.append({'time':c[0],'open':c[1],'high':c[2],'low':c[3],'close':c[4],'volume':c[5]})
                log.info(f'[FEED] {inst} {tf}m: {len(data["data"])} candles loaded')
        except Exception as e:log.error(f'Historical:{e}')

# Patch builders and tokens for new instruments
def patch_feed(feed):
    from v30_feed import CandleBuilder
    for inst in ['FINNIFTY','MIDCPNIFTY','SENSEX','GOLDM','SILVERM']:
        if inst not in feed.builders:
            feed.builders[inst]={'5':CandleBuilder(5),'15':CandleBuilder(15)}
    feed.tokens['FINNIFTY']={'token':'26037','segment':'nse_cm'}
    feed.tokens['MIDCPNIFTY']={'token':'26074','segment':'nse_cm'}
    feed.tokens['SENSEX']={'token':'99919000','segment':'bse_cm'}
    feed.tokens['GOLDM']={'token':'477904','segment':'mcx_fo'}
    feed.tokens['SILVERM']={'token':'457533','segment':'mcx_fo'}
