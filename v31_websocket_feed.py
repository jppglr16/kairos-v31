"""
V31 WebSocket Feed - Angel One - Production Grade
All 4 critical fixes:
1. Heartbeat monitor
2. Delta volume (not cumulative)
3. Backpressure queue
4. Exchange timestamp
"""
import logging, json, threading, time
from datetime import datetime
from queue import Queue, Full

log = logging.getLogger(__name__)

WS_TOKENS = {
    'NIFTY':     {'token':'99926000', 'exchange':'NSE'},
    'BANKNIFTY': {'token':'99926009', 'exchange':'NSE'},
    'FINNIFTY':  {'token':'99926037', 'exchange':'NSE'},
    'MIDCPNIFTY':{'token':'99926074', 'exchange':'NSE'},
    'SENSEX':    {'token':'99919000', 'exchange':'BSE'},
    'CRUDEOIL':  {'token':'486503',   'exchange':'MCX'},
    'GOLDM':     {'token':'477904',   'exchange':'MCX'},
    'SILVERM':   {'token':'466029',   'exchange':'MCX'},
    'NATURALGAS':{'token':'487465',   'exchange':'MCX'},
    'LT':        {'token':'11483',    'exchange':'NSE'},
    'NTPC':      {'token':'11630',    'exchange':'NSE'},
    'MARUTI':    {'token':'10999',    'exchange':'NSE'},
    'BHARTIARTL':{'token':'10604',    'exchange':'NSE'},
    'SBIN':      {'token':'3045',     'exchange':'NSE'},
    'TATAMOTORS':{'token':'3456',     'exchange':'NSE'},
    'RELIANCE':  {'token':'2885',     'exchange':'NSE'},
    'HINDUNILVR':{'token':'1394',     'exchange':'NSE'},
    'TCS':       {'token':'11536',    'exchange':'NSE'},
    'TATASTEEL': {'token':'3505',     'exchange':'NSE'},
    'HDFCBANK':  {'token':'1333',     'exchange':'NSE'},
    'ICICIBANK': {'token':'4963',     'exchange':'NSE'},
    'BAJFINANCE':{'token':'317',      'exchange':'NSE'},
    'SIEMENS':   {'token':'3150',     'exchange':'NSE'},
    'POLYCAB':   {'token':'14418',    'exchange':'NSE'},
    'SOLARINDS': {'token':'22592',    'exchange':'NSE'},
    'TVSMOTOR':  {'token':'3775',     'exchange':'NSE'},
    'BOSCHLTD':  {'token':'2181',     'exchange':'NSE'},
    'PAGEIND':   {'token':'14413',    'exchange':'NSE'},
    'BRITANNIA': {'token':'547',      'exchange':'NSE'},
    'APOLLOHOSP':{'token':'157',      'exchange':'NSE'},
    'OFSS':      {'token':'10738',    'exchange':'NSE'},
    'BAJAJ-AUTO':{'token':'16669',    'exchange':'NSE'},
    'EICHERMOT': {'token':'910',      'exchange':'NSE'},
    'SHREECEM':  {'token':'3103',     'exchange':'NSE'},
    'CUMMINSIND':{'token':'1901',     'exchange':'NSE'},
    'ABB':       {'token':'13',       'exchange':'NSE'},
    'DIVISLAB':  {'token':'10940',    'exchange':'NSE'},
    'HEROMOTOCO':{'token':'1348',     'exchange':'NSE'},
    'INDIGO':    {'token':'11195',    'exchange':'NSE'},
    'TATAELXSI': {'token':'3411',     'exchange':'NSE'},
    'AMBER':     {'token':'19234',    'exchange':'NSE'},
    'ALKEM':     {'token':'11703',    'exchange':'NSE'},
    'TORNTPHARM':{'token':'3518',     'exchange':'NSE'},
    'KEI':       {'token':'13310',    'exchange':'NSE'},
}

TOKEN_TO_INST = {v['token']: k for k, v in WS_TOKENS.items()}

class AngelWebSocketFeed:
    def __init__(self):
        self._ws = None
        self._connected = False
        self._reconnect = True
        self._lock = threading.Lock()
        self._tick_count = 0
        self._dropped_ticks = 0
        self._last_tick = {}
        self._last_cum_volume = {}  # Fix 2: track cumulative vol
        self._feed_token = None
        self._client_code = None

        # Fix 1: Heartbeat tracking
        self._last_tick_time = time.time()

        # Fix 3: Backpressure queue
        self._tick_queue = Queue(maxsize=10000)

    def connect(self, feed_token, client_code):
        self._feed_token = feed_token
        self._client_code = client_code
        self._start_ws()

    def _start_ws(self):
        """Start WS + worker + heartbeat threads"""
        # WebSocket thread
        t = threading.Thread(target=self._ws_loop, daemon=True)
        t.name = 'AngelWS'
        t.start()

        # Fix 3: Tick processor thread
        w = threading.Thread(target=self._tick_worker, daemon=True)
        w.name = 'TickWorker'
        w.start()

        # Fix 1: Heartbeat monitor thread
        h = threading.Thread(target=self._heartbeat_monitor, daemon=True)
        h.name = 'WSHeartbeat'
        h.start()

        log.info('[WS] Angel WebSocket threads started!')

    def _heartbeat_monitor(self):
        """Fix 1: Detect stale connection!"""
        while self._reconnect:
            try:
                if (self._connected and
                    time.time() - self._last_tick_time > 30):
                    log.warning('[WS] Stale connection! '
                               f'No ticks for 30s! Reconnecting...')
                    try:
                        self._ws.close_connection()
                    except: pass
                    self._connected = False
            except Exception as e:
                log.debug(f'[WS] Heartbeat error: {e}')
            time.sleep(5)

    def _ws_loop(self):
        """WebSocket loop with auto-reconnect"""
        while self._reconnect:
            try:
                from SmartApi import SmartWebSocket
                self._ws = SmartWebSocket(
                    self._feed_token,
                    self._client_code
                )
                self._ws.ON_OPEN = self._on_open
                self._ws.ON_DATA = self._on_tick
                self._ws.ON_ERROR = self._on_error
                self._ws.ON_CLOSE = self._on_close

                log.info('[WS] Connecting...')
                self._ws.connect()

            except Exception as e:
                log.error(f'[WS] Error: {e}')
                self._connected = False

            if self._reconnect:
                log.info('[WS] Reconnecting in 5s...')
                time.sleep(5)

    def _on_open(self):
        """Subscribe all on connect"""
        try:
            self._connected = True
            self._last_tick_time = time.time()
            log.info('[WS] ✅ Connected! Subscribing...')

            tokens = list(WS_TOKENS.items())
            for i in range(0, len(tokens), 20):
                batch = tokens[i:i+20]
                for inst, info in batch:
                    try:
                        self._ws.subscribe(
                            inst,
                            info['exchange'],
                            info['token']
                        )
                    except Exception as e:
                        log.debug(f'[WS] Sub {inst}: {e}')
                time.sleep(0.5)

            log.info(f'[WS] ✅ Subscribed {len(WS_TOKENS)} instruments!')

        except Exception as e:
            log.error(f'[WS] Subscribe error: {e}')

    def _on_tick(self, ws, data):
        """
        Receive tick → push to queue (non-blocking!)
        Fix 3: Backpressure protection!
        """
        try:
            # Fix 1: Update heartbeat!
            self._last_tick_time = time.time()

            try:
                self._tick_queue.put_nowait(data)
            except Full:
                # Queue full = drop oldest tick
                try:
                    self._tick_queue.get_nowait()
                    self._tick_queue.put_nowait(data)
                    self._dropped_ticks += 1
                except: pass

        except Exception as e:
            log.debug(f'[WS] Tick receive error: {e}')

    def _tick_worker(self):
        """
        Process ticks from queue in separate thread!
        Fix 3: Decouples WS receive from processing!
        """
        while True:
            try:
                data = self._tick_queue.get(timeout=1.0)
                self._process_tick(data)
                self._tick_queue.task_done()
            except Exception:
                continue

    def _process_tick(self, data):
        """
        Process single tick with all fixes!
        """
        try:
            self._tick_count += 1

            token = str(data.get('token', ''))
            inst = TOKEN_TO_INST.get(token, '')
            if not inst:
                return

            ltp = float(
                data.get('last_traded_price', 0) or
                data.get('ltp', 0))
            cum_vol = int(
                data.get('volume_trade_for_the_day', 0) or
                data.get('volume', 0))

            if ltp <= 0:
                return

            # Fix 2: Delta volume!
            with self._lock:
                prev_vol = self._last_cum_volume.get(inst, 0)

                # Handle volume reset
                if cum_vol < prev_vol:
                    tick_vol = cum_vol  # Reset
                else:
                    tick_vol = max(0, cum_vol - prev_vol)

                self._last_cum_volume[inst] = cum_vol

                # Fix 4: Exchange timestamp
                ex_time = (
                    data.get('exchange_timestamp') or
                    data.get('exchange_time') or
                    time.time()
                )

                self._last_tick[inst] = {
                    'ltp': ltp,
                    'volume': tick_vol,
                    'cum_volume': cum_vol,
                    'local_time': time.time(),
                    'exchange_time': ex_time,
                }

            # Route to candle cache!
            try:
                from v31_candle_cache import candle_cache
                candle_cache.process_tick(inst, {
                    'ltp': ltp,
                    'volume': cum_vol,      # Cache handles delta
                    'exchange_time': ex_time,
                })
            except Exception as ce:
                log.debug(f'[WS] Cache error: {ce}')

            # Log every 1000 ticks
            if self._tick_count % 1000 == 0:
                log.info(
                    f'[WS] Ticks:{self._tick_count} '
                    f'Dropped:{self._dropped_ticks} '
                    f'Queue:{self._tick_queue.qsize()} '
                    f'Instruments:{len(self._last_tick)}')

        except Exception as e:
            log.debug(f'[WS] Process error: {e}')

    def _on_error(self, ws, error):
        log.error(f'[WS] Error: {error}')
        self._connected = False

    def _on_close(self):
        log.warning('[WS] Closed!')
        self._connected = False

    def get_ltp(self, inst):
        """Get latest price"""
        with self._lock:
            tick = self._last_tick.get(inst)
            return tick['ltp'] if tick else None

    def is_connected(self):
        return self._connected

    def get_stats(self):
        with self._lock:
            avg_latency = 0
            if self._last_tick:
                latencies = [
                    t['local_time'] - float(t.get('exchange_time',
                                                   t['local_time']))
                    for t in self._last_tick.values()
                    if 'local_time' in t
                ]
                if latencies:
                    avg_latency = sum(latencies)/len(latencies)*1000

            return {
                'connected': self._connected,
                'instruments': len(self._last_tick),
                'tick_count': self._tick_count,
                'dropped': self._dropped_ticks,
                'queue_size': self._tick_queue.qsize(),
                'avg_latency_ms': round(avg_latency, 1),
                'last_tick_age': round(
                    time.time()-self._last_tick_time, 1),
            }

    def stop(self):
        self._reconnect = False
        if self._ws:
            try: self._ws.close_connection()
            except: pass

# Global instance
angel_ws = AngelWebSocketFeed()
