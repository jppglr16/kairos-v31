import time,logging
from datetime import datetime
log=logging.getLogger(__name__)

class Cache:
    def __init__(self):
        self.store={}

    def get(self,key):
        if key not in self.store:return None
        val,expiry=self.store[key]
        if time.time()>expiry:
            del self.store[key]
            return None
        return val

    def set(self,key,val,ttl_seconds):
        self.store[key]=(val,time.time()+ttl_seconds)

cache=Cache()

def cached_vix():
    v=cache.get('vix')
    if v is not None:return v
    try:
        from v30_filters import get_india_vix
        v=get_india_vix()
        cache.set('vix',v,300)
        return v
    except:return 15.0

def cached_fii():
    v=cache.get('fii')
    if v is not None:return v
    try:
        from v30_filters import get_fii_dii_bias
        v=get_fii_dii_bias()
        cache.set('fii',v,1800)
        return v
    except:return {'fii_net':0,'dii_net':0,'bias':'NEUTRAL'}

def cached_pcr(instrument):
    key=f'pcr_{instrument}'
    v=cache.get(key)
    if v is not None:return v
    try:
        from v30_oi import get_pcr_and_bias
        v=get_pcr_and_bias(instrument)
        if v:cache.set(key,v,300)
        return v
    except:return None

def cached_greeks(instrument,option_type):
    key=f'greeks_{instrument}_{option_type}'
    v=cache.get(key)
    if v is not None:return v
    try:
        from v30_greeks import get_best_strike_by_delta
        strike,premium=get_best_strike_by_delta(instrument,option_type,0.4)
        v={'strike':strike,'premium':premium}
        if strike:cache.set(key,v,300)
        return v
    except:return {'strike':None,'premium':0}

def cached_sentiment():
    v=cache.get('sentiment')
    if v is not None:return v
    try:
        from v30_sentiment import get_sentiment_score
        v=get_sentiment_score()
        cache.set('sentiment',v,1800)
        return v
    except:return 0

def cached_prev_levels():
    v=cache.get('prev_levels')
    if v is not None:return v
    try:
        from v30_filters import get_prev_day_levels
        v=get_prev_day_levels()
        cache.set('prev_levels',v,3600)
        return v
    except:return {}

def cached_sgx():
    v=cache.get('sgx')
    if v is not None:return v
    try:
        from v30_filters import get_sgx_nifty
        v=get_sgx_nifty()
        cache.set('sgx',v,300)
        return v
    except:return {'price':0,'change':0,'bias':'NEUTRAL'}

def preload_cache():
    log.info('[CACHE] Preloading all market data...')
    cached_vix()
    cached_fii()
    cached_sentiment()
    cached_prev_levels()
    cached_sgx()
    for inst in ['NIFTY','BANKNIFTY']:
        cached_pcr(inst)
        cached_greeks(inst,'CE')
        cached_greeks(inst,'PE')
    log.info('[CACHE] Preload complete!')
