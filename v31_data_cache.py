"""
V31 Production Data Cache
Prevents API rate limiting with smart caching
"""
import time,logging
log=logging.getLogger(__name__)

# Global cache store
cache={}

# Global API throttle
import threading
_cache_last_call=0
_cache_min_gap=2.0  # Increased!
_cache_lock=threading.Lock()

# TTL per timeframe
TTL_MAP={
    'FIVE_MINUTE':   60,   # 1 min
    'FIFTEEN_MINUTE':180,  # 3 mins
    '5':             60,
    '15':            180,
    'D':             600,
}

def get_candle_cached(instrument,tf,fetch_func):
    """
    Get candles with smart caching + retry
    instrument: NIFTY, BANKNIFTY etc
    tf: FIVE_MINUTE or FIFTEEN_MINUTE
    fetch_func: lambda to fetch from API
    """
    now=time.time()
    key=f'{instrument}_{tf}'
    ttl=TTL_MAP.get(str(tf),60)

    # Cache hit
    if key in cache:
        data,ts=cache[key]
        age=now-ts
        if age<ttl:
            log.debug(f'[CACHE] Hit: {key} age={age:.0f}s')
            return data

    # Global throttle before API call
    global _cache_last_call,_cache_min_gap
    with _cache_lock:
        _now=time.time()
        _gap=_now-_cache_last_call
        if _gap<_cache_min_gap:
            time.sleep(_cache_min_gap-_gap)
        _cache_last_call=time.time()

    # Fetch with retry + backoff
    for attempt in range(3):
        try:
            data=fetch_func()
            if data is not None:
                cache[key]=(data,now)
                log.debug(f'[CACHE] Stored: {key}')
            return data
        except Exception as e:
            err=str(e)
            if 'Too many requests' in err or 'AB1019' in err:
                wait=(attempt+1)*3  # 3s, 6s, 9s
                log.warning(f'[CACHE] Rate limited! {instrument} retry {attempt+1}/3 in {wait}s')
                time.sleep(wait)
            elif 'timeout' in err.lower():
                wait=(attempt+1)*2
                log.warning(f'[CACHE] Timeout {instrument} retry in {wait}s')
                time.sleep(wait)
            else:
                # Return stale cache on other errors
                if key in cache:
                    log.warning(f'[CACHE] Error, using stale: {key}')
                    return cache[key][0]
                raise

    # All retries failed - return stale if available
    if key in cache:
        log.warning(f'[CACHE] All retries failed, using stale: {key}')
        return cache[key][0]
    return None

def cache_stats():
    now=time.time()
    return {
        'total':len(cache),
        'fresh':sum(1 for _,(d,t) in cache.items() if now-t<60),
        'stale':sum(1 for _,(d,t) in cache.items() if now-t>=60),
    }

def clear_all():
    cache.clear()
    log.info('[CACHE] Cleared!')

# Legacy support
_cache=cache
def get_cached(key,fetch_func,ttl=60):
    return get_candle_cached(key,'5',fetch_func)
