"""
V31 Candle Cache - Production Grade v2
Event-driven architecture: WebSocket → Cache → Signal Engine

Critical fixes:
1. Delta volume (not cumulative sum)
2. New candle creation if missing
3. Race condition fix (lock on tick cache)
4. Tick deduplication
5. Latency tracking
6. Candle completeness check
"""
import pandas as pd
import json, os, logging, threading, time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict

log = logging.getLogger(__name__)

MAX_CANDLES = 5000
CANDLE_INTERVAL = 300  # 5 mins

TOKENS = {
    'NIFTY':'99926000','BANKNIFTY':'99926009',
    'SENSEX':'99919000','FINNIFTY':'99926037',
    'MIDCPNIFTY':'99926074',
    'CRUDEOIL':'486503','GOLDM':'477904',
    'SILVERM':'466029','NATURALGAS':'487465',
    'LT':'11483','NTPC':'11630','MARUTI':'10999',
    'BHARTIARTL':'10604','SBIN':'3045',
    'TATAMOTORS':'3456','RELIANCE':'2885',
    'HINDUNILVR':'1394','TCS':'11536',
    'TATASTEEL':'3505','HDFCBANK':'1333',
    'ICICIBANK':'4963','BAJFINANCE':'317',
    'SIEMENS':'3150','POLYCAB':'14418',
    'SOLARINDS':'22592','TVSMOTOR':'3775',
    'BOSCHLTD':'2181','PAGEIND':'14413',
    'BRITANNIA':'547','APOLLOHOSP':'157',
    'OFSS':'10738','BAJAJ-AUTO':'16669',
    'EICHERMOT':'910','SHREECEM':'3103',
    'CUMMINSIND':'1901','ABB':'13',
    'DIVISLAB':'10940','HEROMOTOCO':'1348',
    'INDIGO':'11195','TATAELXSI':'3411',
    'AMBER':'19234','ALKEM':'11703',
    'TORNTPHARM':'3518','KEI':'13310',
}

MCX_INST = ['CRUDEOIL','GOLDM','SILVERM','NATURALGAS']

class CandleCache:
    def __init__(self):
        self._cache5 = {}
        self._cache15 = {}
        self._lock = threading.RLock()
        self._tick_lock = threading.RLock()  # Separate tick lock!
        self._last_update = {}
        self._initialized = set()
        self._dirty = set()
        self._tick_cache = defaultdict(list)
        self._latency = {}         # Latency tracking
        self._last_tick_price = {}  # Deduplication
        self._last_tick_volume = {} # Volume dedup

    # ============================================
    # HISTORICAL LOAD
    # ============================================
    def load_historical(self, inst):
        try:
            candles = []
            for year in [2023, 2024, 2025, 2026]:
                fname = f'historical_data/{inst}_{year}_5min.json'
                if os.path.exists(fname):
                    candles.extend(json.load(open(fname)))

            if not candles:
                return False

            df = pd.DataFrame(candles,
                columns=['time','open','high','low','close','volume'])
            for c in ['open','high','low','close','volume']:
                df[c] = pd.to_numeric(df[c], errors='coerce')

            df['time'] = pd.to_datetime(df['time'])
            df = df.dropna().sort_values('time')
            if len(df) > MAX_CANDLES:
                df = df.tail(MAX_CANDLES)
            df = df.reset_index(drop=True)

            with self._lock:
                self._cache5[inst] = df
                self._cache15[inst] = self._resample_15(df)
                self._initialized.add(inst)

            log.info(f'[CACHE] {inst}: {len(df)} candles loaded')
            return True

        except Exception as e:
            log.error(f'[CACHE] Load error {inst}: {e}')
            return False

    def load_all_historical(self, instruments):
        log.info(f'[CACHE] Loading {len(instruments)} instruments...')
        start = time.time()
        with ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(self.load_historical, instruments))
        loaded = sum(results)
        log.info(f'[CACHE] Loaded {loaded}/{len(instruments)} '
                f'in {time.time()-start:.1f}s')
        return loaded

    # ============================================
    # LIVE UPDATE
    # ============================================
    def _needs_update(self, inst):
        last = self._last_update.get(inst, 0)
        if last == 0:
            return True
        now_dt = datetime.now()
        boundary = now_dt.replace(
            minute=(now_dt.minute//5)*5,
            second=0, microsecond=0
        ).timestamp()
        return last < boundary

    def update_live(self, inst, angel_obj):
        try:
            if not self._needs_update(inst):
                return True
            if not self._is_market_open(inst):
                return False

            token = TOKENS.get(inst, '')
            if not token:
                return False

            now = datetime.now()
            resp = angel_obj.getCandleData({
                'exchange': self._get_exchange(inst),
                'symboltoken': token,
                'interval': 'FIVE_MINUTE',
                'fromdate': now.strftime('%Y-%m-%d 09:00'),
                'todate': now.strftime('%Y-%m-%d %H:%M'),
            })

            if resp and resp.get('data'):
                new_df = pd.DataFrame(resp['data'],
                    columns=['time','open','high','low','close','volume'])
                for c in ['open','high','low','close','volume']:
                    new_df[c] = pd.to_numeric(new_df[c], errors='coerce')
                new_df['time'] = pd.to_datetime(new_df['time'])
                new_df = new_df.dropna()

                with self._lock:
                    if inst in self._cache5:
                        df = pd.concat([self._cache5[inst], new_df])
                        df = df.drop_duplicates('time').sort_values('time')
                        if len(df) > MAX_CANDLES:
                            df = df.tail(MAX_CANDLES)
                        self._cache5[inst] = df.reset_index(drop=True)
                        self._cache15[inst] = self._resample_15(df)

                self._last_update[inst] = time.time()
                self._dirty.add(inst)
                return True

        except Exception as e:
            log.debug(f'[CACHE] Update {inst}: {e}')
            return False

    def update_all_live(self, instruments, angel_obj):
        stale = [i for i in instruments
                if i in self._initialized and self._needs_update(i)]

        if not stale:
            return 0

        log.info(f'[CACHE] Updating {len(stale)} instruments...')
        updated = 0

        # Batches of 5 with 1s pause
        batch_size = 5
        for i in range(0, len(stale), batch_size):
            batch = stale[i:i+batch_size]
            with ThreadPoolExecutor(max_workers=batch_size) as ex:
                results = list(ex.map(
                    lambda inst: self.update_live(inst, angel_obj), batch))
            updated += sum(1 for r in results if r)
            if i + batch_size < len(stale):
                time.sleep(1.0)

        log.info(f'[CACHE] Updated:{updated}/{len(stale)}')
        return updated

    # ============================================
    # WEBSOCKET TICK PROCESSING
    # ============================================
    def process_tick(self, inst, tick_data):
        """
        Event-driven tick processing!
        WebSocket → Cache → Dirty Flag → Signal Engine
        """
        try:
            price = float(tick_data.get('ltp', 0))
            cum_vol = int(tick_data.get('volume', 0))
            if price <= 0:
                return

            # Fix 4: Smart dedup (price + volume!)
            if (self._last_tick_price.get(inst) == price and
                self._last_tick_volume.get(inst) == cum_vol):
                return
            self._last_tick_price[inst] = price
            self._last_tick_volume[inst] = cum_vol

            # Fix 5: Latency tracking!
            if 'exchange_time' in tick_data:
                try:
                    self._latency[inst] = (
                        time.time() - float(tick_data['exchange_time']))
                except: pass

            ts = datetime.now()
            boundary = ts.replace(
                minute=(ts.minute//5)*5,
                second=0, microsecond=0
            )

            # Fix 3: Lock on tick cache access!
            with self._tick_lock:
                ticks = list(self._tick_cache.get(inst, []))

                # New candle boundary?
                if ticks and ticks[-1]['boundary'] != boundary:
                    self._finalize_tick_candle(inst, ticks)
                    self._tick_cache[inst] = []
                    ticks = []

                self._tick_cache[inst].append({
                    'boundary': boundary,
                    'price': price,
                    'cum_vol': cum_vol,
                    'time': ts
                })

            self._update_current_candle(inst, boundary, price, cum_vol)

        except Exception as e:
            log.debug(f'[CACHE] Tick error {inst}: {e}')

    def _finalize_tick_candle(self, inst, ticks):
        """Build OHLCV candle from ticks with delta volume!"""
        try:
            if not ticks:
                return

            prices = [t['price'] for t in ticks]
            cum_vols = [t['cum_vol'] for t in ticks]

            # Fix 1: Delta volume with reset handling!
            real_volume = 0
            for i in range(1, len(cum_vols)):
                if cum_vols[i] < cum_vols[i-1]:
                    # Exchange reset cumulative volume!
                    delta = cum_vols[i]
                else:
                    delta = cum_vols[i] - cum_vols[i-1]
                real_volume += max(0, delta)

            new_row = pd.DataFrame([{
                'time': ticks[0]['boundary'],
                'open': prices[0],
                'high': max(prices),
                'low': min(prices),
                'close': prices[-1],
                'volume': real_volume,
            }])

            with self._lock:
                if inst in self._cache5:
                    df = pd.concat([self._cache5[inst], new_row])
                    df = df.drop_duplicates('time').sort_values('time')
                    if len(df) > MAX_CANDLES:
                        df = df.tail(MAX_CANDLES)
                    self._cache5[inst] = df.reset_index(drop=True)
                    self._cache15[inst] = self._resample_15(
                        self._cache5[inst])
                    self._dirty.add(inst)

        except Exception as e:
            log.debug(f'[CACHE] Finalize error: {e}')

    def _update_current_candle(self, inst, boundary, price, cum_vol):
        """Update or CREATE current candle!"""
        try:
            with self._lock:
                if inst not in self._cache5:
                    return
                df = self._cache5[inst]
                if len(df) == 0:
                    return

                last_time = df['time'].iloc[-1]

                if last_time == boundary:
                    # Update existing candle
                    idx = df.index[-1]
                    df.at[idx, 'high'] = max(
                        float(df['high'].iloc[-1]), price)
                    df.at[idx, 'low'] = min(
                        float(df['low'].iloc[-1]), price)
                    df.at[idx, 'close'] = price
                else:
                    # Fix 2: CREATE new candle if missing!
                    new_row = pd.DataFrame([{
                        'time': boundary,
                        'open': price,
                        'high': price,
                        'low': price,
                        'close': price,
                        'volume': 0
                    }])
                    df = pd.concat([df, new_row])
                    if len(df) > MAX_CANDLES:
                        df = df.tail(MAX_CANDLES)
                    self._cache5[inst] = df.reset_index(drop=True)

        except Exception as e:
            log.debug(f'[CACHE] Update candle error: {e}')

    # ============================================
    # READ: Zero API!
    # ============================================
    def get_candles(self, inst, tf=5):
        """Get candles from cache - ZERO API calls!"""
        with self._lock:
            if str(tf) == '5' or tf == 5:
                df = self._cache5.get(inst)
                n = 100
            else:
                df = self._cache15.get(inst)
                n = 50

            if df is not None and len(df) > 0:
                # Fix 6: Candle completeness check!
                result = df.tail(n).copy()
                last_time = pd.to_datetime(result['time'].iloc[-1])
                now = datetime.now()
                candle_age = (now - last_time).seconds

                # Flag if current candle incomplete (<60s old)
                result.attrs['candle_complete'] = candle_age > 60
                result.attrs['candle_age_secs'] = candle_age
                return result

        return None

    def is_candle_complete(self, inst):
        """
        Check if latest candle is complete!
        Avoid trading on incomplete candles!
        """
        df = self.get_candles(inst, 5)
        if df is None:
            return False
        return df.attrs.get('candle_complete', True)

    # ============================================
    # DIRTY FLAG
    # ============================================
    def is_dirty(self, inst):
        return inst in self._dirty

    def clear_dirty(self, inst):
        self._dirty.discard(inst)

    def get_dirty_instruments(self):
        with self._lock:
            return list(self._dirty)

    # ============================================
    # UTILITIES
    # ============================================
    def _resample_15(self, df5):
        try:
            df = df5.copy()
            if not pd.api.types.is_datetime64_any_dtype(df['time']):
                df['time'] = pd.to_datetime(df['time'])
            df = df.set_index('time')
            df15 = df.resample('15min').agg({
                'open': 'first', 'high': 'max',
                'low': 'min', 'close': 'last',
                'volume': 'sum'
            }).dropna().reset_index()
            return df15
        except:
            return df5

    def _get_exchange(self, inst):
        if inst in MCX_INST: return 'MCX'
        if inst == 'SENSEX': return 'BSE'
        return 'NSE'

    def _is_market_open(self, inst):
        from datetime import time as dtime
        t = datetime.now().time()
        if inst in MCX_INST:
            return dtime(9,0) <= t <= dtime(23,30)
        return dtime(9,15) <= t <= dtime(15,30)

    # ============================================
    # STATE PERSISTENCE (survive restarts!)
    # ============================================
    CACHE_STATE_FILE = 'cache_state.json'

    def save_state(self):
        """Save dedup state for restart recovery"""
        try:
            import json
            state = {
                'last_price': self._last_tick_price,
                'last_volume': self._last_tick_volume,
                'last_update': self._last_update,
                'saved_at': time.time()
            }
            tmp = self.CACHE_STATE_FILE + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(state, f)
            os.replace(tmp, self.CACHE_STATE_FILE)
            log.debug('[CACHE] State saved!')
        except Exception as e:
            log.debug(f'[CACHE] State save error: {e}')

    def load_state(self):
        """Load dedup state after restart"""
        try:
            import json
            if not os.path.exists(self.CACHE_STATE_FILE):
                return False
            state = json.load(open(self.CACHE_STATE_FILE))

            # Only restore if less than 10 mins old!
            age = time.time() - state.get('saved_at', 0)
            if age > 600:
                log.info('[CACHE] State too old, ignoring!')
                return False

            self._last_tick_price = state.get('last_price', {})
            self._last_tick_volume = state.get('last_volume', {})
            self._last_update = state.get('last_update', {})
            log.info(f'[CACHE] State restored! Age:{age:.0f}s')
            return True
        except Exception as e:
            log.debug(f'[CACHE] State load error: {e}')
            return False

    def get_stats(self):
        with self._lock:
            avg_latency = (
                sum(self._latency.values()) / len(self._latency)
                if self._latency else 0)
            return {
                'initialized': len(self._initialized),
                'dirty': len(self._dirty),
                'total_candles': sum(
                    len(df) for df in self._cache5.values()),
                'memory_mb': round(sum(
                    df.memory_usage(deep=True).sum()
                    for df in self._cache5.values()
                ) / 1024 / 1024, 2),
                'avg_latency_ms': round(avg_latency*1000, 1),
                'stale': [
                    i for i,ts in self._last_update.items()
                    if time.time()-ts > 600
                ][:5],
            }

# Global singleton!
candle_cache = CandleCache()
