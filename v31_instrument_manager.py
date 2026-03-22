"""
Auto-Instrument Manager
Add any script name → auto downloads data, adds to all layers!
"""
import json,os,logging,time
log=logging.getLogger(__name__)

# ============================================================
# MASTER INSTRUMENT CONFIG
# Add new instrument here ONLY - everything else auto!
# ============================================================
INSTRUMENTS={
    # NSE INDICES
    'NIFTY':     {'exchange':'NSE','token':'99926000','lot':65, 'step':50, 'exch_seg':'NFO','type':'INDEX'},
    'BANKNIFTY': {'exchange':'NSE','token':'99926009','lot':30, 'step':100,'exch_seg':'NFO','type':'INDEX'},
    'FINNIFTY':  {'exchange':'NSE','token':'99926037','lot':60, 'step':50, 'exch_seg':'NFO','type':'INDEX'},
    'MIDCPNIFTY':{'exchange':'NSE','token':'99926074','lot':120,'step':25, 'exch_seg':'NFO','type':'INDEX'},
    'SENSEX':    {'exchange':'BSE','token':'99919000','lot':20, 'step':100,'exch_seg':'BFO','type':'INDEX'},

    # MCX COMMODITIES
    'CRUDEOIL':  {'exchange':'MCX','token':'234825', 'lot':100,  'step':100,'exch_seg':'MCX','type':'COMMODITY'},
    'GOLDM':     {'exchange':'MCX','token':'477904', 'lot':10,   'step':100,'exch_seg':'MCX','type':'COMMODITY'},
    'SILVERM':   {'exchange':'MCX','token':'479510', 'lot':30,   'step':500,'exch_seg':'MCX','type':'COMMODITY'},
    'NATURALGAS':{'exchange':'MCX','token':'475111', 'lot':1250, 'step':10, 'exch_seg':'MCX','type':'COMMODITY'},

    # NSE STOCKS
    'LT':        {'exchange':'NSE','token':'11483', 'lot':450,  'step':50, 'exch_seg':'NFO','type':'STOCK'},
    'NTPC':      {'exchange':'NSE','token':'11630', 'lot':900, 'step':5,  'exch_seg':'NFO','type':'STOCK'},
    'MARUTI':    {'exchange':'NSE','token':'10999', 'lot':100,  'step':100,'exch_seg':'NFO','type':'STOCK'},
    'BHARTIARTL':{'exchange':'NSE','token':'10604', 'lot':950,  'step':20, 'exch_seg':'NFO','type':'STOCK'},
    'SBIN':      {'exchange':'NSE','token':'3045',  'lot':1500, 'step':5,  'exch_seg':'NFO','type':'STOCK'},
    'TATAMOTORS':{'exchange':'NSE','token':'3456',  'lot':1350, 'step':5,  'exch_seg':'NFO','type':'STOCK'},
    'RELIANCE':  {'exchange':'NSE','token':'2885',  'lot':250,  'step':20, 'exch_seg':'NFO','type':'STOCK'},
    'HINDUNILVR':{'exchange':'NSE','token':'1394',  'lot':300,  'step':20, 'exch_seg':'NFO','type':'STOCK'},
    'TCS':       {'exchange':'NSE','token':'11536', 'lot':150,  'step':20, 'exch_seg':'NFO','type':'STOCK'},
    'TATASTEEL': {'exchange':'NSE','token':'3499',  'lot':5500, 'step':2,  'exch_seg':'NFO','type':'STOCK'},

    # New F&O stocks added 22-Mar-2026
    'EICHERMOT': {'exchange':'NSE','token':'910',  'lot':50,  'step':50, 'exch_seg':'NFO','type':'STOCK'},
    'SHREECEM':  {'exchange':'NSE','token':'3103', 'lot':10,  'step':100,'exch_seg':'NFO','type':'STOCK'},
    'CUMMINSIND':{'exchange':'NSE','token':'1901', 'lot':75,  'step':20, 'exch_seg':'NFO','type':'STOCK'},
    'ABB':       {'exchange':'NSE','token':'13',   'lot':50,  'step':50, 'exch_seg':'NFO','type':'STOCK'},
    'DIVISLAB':  {'exchange':'NSE','token':'10940','lot':50,  'step':50, 'exch_seg':'NFO','type':'STOCK'},
    'HEROMOTOCO':{'exchange':'NSE','token':'1348', 'lot':50,  'step':50, 'exch_seg':'NFO','type':'STOCK'},
    'INDIGO':    {'exchange':'NSE','token':'11195','lot':75,  'step':100,'exch_seg':'NFO','type':'STOCK'},
    'TATAELXSI': {'exchange':'NSE','token':'3411', 'lot':75,  'step':50, 'exch_seg':'NFO','type':'STOCK'},
    'AMBER':     {'exchange':'NSE','token':'1185', 'lot':50,  'step':100,'exch_seg':'NFO','type':'STOCK'},
    'ALKEM':     {'exchange':'NSE','token':'11703','lot':75,  'step':50, 'exch_seg':'NFO','type':'STOCK'},
    'TORNTPHARM':{'exchange':'NSE','token':'3518', 'lot':50,  'step':50, 'exch_seg':'NFO','type':'STOCK'},
    'KEI':       {'exchange':'NSE','token':'13310','lot':200, 'step':10, 'exch_seg':'NFO','type':'STOCK'},
    # BANKEX removed - BSE token not available in Angel One
    # === ADD NEW INSTRUMENTS HERE ===
    # 'HDFCBANK': {'exchange':'NSE','token':'1333','lot':550,'step':20,'exch_seg':'NFO','type':'STOCK'},
    # 'ICICIBANK': {'exchange':'NSE','token':'4963','lot':700,'step':20,'exch_seg':'NFO','type':'STOCK'},
    # 'BAJFINANCE': {'exchange':'NSE','token':'317','lot':125,'step':100,'exch_seg':'NFO','type':'STOCK'},
}

# ============================================================
# AUTO FUNCTIONS
# ============================================================
class InstrumentManager:

    def __init__(self):
        self.config_file='instrument_config.json'
        self._load_config()

    def _load_config(self):
        if os.path.exists(self.config_file):
            self.config=json.load(open(self.config_file))
            # Load saved instruments into INSTRUMENTS dict
            for name,data in self.config.items():
                if name not in INSTRUMENTS:
                    INSTRUMENTS[name]=data
                    log.info(f'[IM] Loaded saved instrument: {name}')
        else:
            self.config={}

    def get_all_instruments(self):
        return list(INSTRUMENTS.keys())

    def get_lot(self,instrument):
        return INSTRUMENTS.get(instrument,{}).get('lot',75)

    def get_token(self,instrument):
        return INSTRUMENTS.get(instrument,{}).get('token','')

    def get_exchange(self,instrument):
        return INSTRUMENTS.get(instrument,{}).get('exchange','NSE')

    def get_step(self,instrument):
        return INSTRUMENTS.get(instrument,{}).get('step',50)

    def get_type(self,instrument):
        return INSTRUMENTS.get(instrument,{}).get('type','STOCK')

    def is_mcx(self,instrument):
        return INSTRUMENTS.get(instrument,{}).get('type')=='COMMODITY'

    def is_index(self,instrument):
        return INSTRUMENTS.get(instrument,{}).get('type')=='INDEX'

    # ============================================================
    # AUTO DATA DOWNLOAD
    # ============================================================
    def download_data(self,instrument,angel_obj,years=5):
        """Download historical data for any instrument"""
        from datetime import datetime,timedelta
        import pandas as pd

        token=self.get_token(instrument)
        exchange=self.get_exchange(instrument)
        if not token:
            log.error(f'[IM] No token for {instrument}!')
            return False

        data_file=f'historical_data/{instrument}_5min.csv'
        os.makedirs('historical_data',exist_ok=True)

        # Check existing data
        if os.path.exists(data_file):
            existing=pd.read_csv(data_file,index_col=0,parse_dates=True)
            last_date=existing.index[-1]
            # Only download missing data
            start_date=last_date+timedelta(days=1)
            log.info(f'[IM] {instrument}: updating from {start_date.date()}')
        else:
            start_date=datetime.now()-timedelta(days=365*years)
            existing=None
            log.info(f'[IM] {instrument}: downloading {years}Y data')

        all_chunks=[]
        end=datetime.now()
        chunk_start=start_date

        while chunk_start<end:
            chunk_end=min(chunk_start+timedelta(days=90),end)
            try:
                time.sleep(0.5)
                params={
                    'exchange':exchange,
                    'symboltoken':token,
                    'interval':'FIVE_MINUTE',
                    'fromdate':chunk_start.strftime('%Y-%m-%d %H:%M'),
                    'todate':chunk_end.strftime('%Y-%m-%d %H:%M')
                }
                resp=angel_obj.getCandleData(params)
                if resp and resp.get('data'):
                    df=pd.DataFrame(resp['data'],
                        columns=['timestamp','open','high','low','close','volume'])
                    df['timestamp']=pd.to_datetime(df['timestamp'])
                    df.set_index('timestamp',inplace=True)
                    all_chunks.append(df)
                    log.info(f'[IM] {instrument}: {len(df)} candles from {chunk_start.date()}')
            except Exception as e:
                log.error(f'[IM] {instrument} download error: {e}')

            chunk_start=chunk_end+timedelta(days=1)

        if all_chunks:
            new_data=pd.concat(all_chunks)
            if existing is not None:
                combined=pd.concat([existing,new_data])
                final=combined[~combined.index.duplicated(keep='last')]
            else:
                final=new_data
            final.sort_index(inplace=True)
            final.to_csv(data_file)
            log.info(f'[IM] {instrument}: {len(final)} total candles saved!')
            return True

        return False

    # ============================================================
    # ADD INSTRUMENT TO ALL LAYERS
    # ============================================================
    def register_instrument(self,name,exchange,token,lot,step,exch_seg,inst_type,angel_obj=None):
        """
        Add new instrument to ALL V31 layers automatically!
        """
        from v30_notify import send

        log.info(f'[IM] Registering {name}...')

        # Step 1: Add to INSTRUMENTS dict (runtime)
        INSTRUMENTS[name]={
            'exchange':exchange,
            'token':token,
            'lot':lot,
            'step':step,
            'exch_seg':exch_seg,
            'type':inst_type
        }

        # Step 2: Save config
        self.config[name]=INSTRUMENTS[name]
        json.dump(self.config,open(self.config_file,'w'))

        # Step 3: Download data
        if angel_obj:
            log.info(f'[IM] Downloading data for {name}...')
            success=self.download_data(name,angel_obj)
            if success:
                log.info(f'[IM] {name} data downloaded!')
            else:
                log.warning(f'[IM] {name} data download failed!')

        # Step 4: Update options master
        self._update_options_master(name)

        # Step 5: Notify
        send(f'🆕 New instrument registered: {name}\n'
             f'Exchange: {exchange}\n'
             f'Lot: {lot}\n'
             f'Type: {inst_type}\n'
             f'Data: {"✅" if angel_obj else "⏳"}')

        log.info(f'[IM] {name} registered successfully!')
        return True

    def _update_options_master(self,instrument):
        """Update options lookup for new instrument"""
        try:
            import requests
            data=json.load(open('angel_options_lookup.json'))
            # Check if instrument already in lookup
            existing=[k for k in data if k.startswith(instrument)]
            log.info(f'[IM] {instrument}: {len(existing)} options in master')
        except:pass

    def auto_add_instrument(self,name,angel_obj):
        """
        Fully automatic - just provide name!
        Fetches token, lot, everything from Angel One
        """
        from v30_notify import send
        try:
            # Search Angel One for instrument
            resp=angel_obj.searchScrip(exchange='NSE',searchscrip=name)
            if not resp or not resp.get('data'):
                resp=angel_obj.searchScrip(exchange='MCX',searchscrip=name)

            if resp and resp.get('data'):
                results=resp['data']
                exact=[x for x in results if x.get('tradingsymbol','').upper().startswith(name.upper())]
                s=exact[0] if exact else results[0]
                token=s.get('symboltoken','')
                exchange='MCX' if s.get('exchange')=='MCX' else 'NSE'
                exch_seg='MCX' if exchange=='MCX' else 'NFO'

                # Get lot from master
                import json
                master=json.load(open('angel_options_lookup.json'))
                lots=[int(v.get('lotsize',0)) for k,v in master.items() if k.startswith(name) and int(v.get('lotsize',0))>0]
                lot=max(lots) if lots else 75

                self.register_instrument(
                    name,exchange,token,lot,50,exch_seg,
                    'COMMODITY' if exchange=='MCX' else 'STOCK',
                    angel_obj
                )
                return True
        except Exception as e:
            log.error(f'[IM] Auto-add error: {e}')
        return False


# Global instance
instrument_manager=InstrumentManager()
