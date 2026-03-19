import time,logging,threading
log=logging.getLogger(__name__)

MAX_DELAY=60         # Signal valid for 60 seconds
MAX_PRICE_SLIP=0.20  # 20% max price movement
ORDER_TIMEOUT=120    # Cancel after 2 minutes

class SafeOrderEngine:
    """
    Production-safe order execution:
    1. Signal expiry check
    2. Price validation
    3. Order confirmation
    4. Auto-cancel stale orders
    5. Duplicate protection
    """

    def __init__(self,angel_obj):
        self.obj=angel_obj
        self.active_orders={}  # order_id -> details
        self.active_trades={}  # symbol -> trade_info
        self._start_stale_monitor()

    # ============================================================
    # STEP 1: SIGNAL EXPIRY CHECK
    # ============================================================
    def is_signal_fresh(self,signal):
        """Check if signal is still valid"""
        signal_time=signal.get('signal_time',time.time())
        age=time.time()-signal_time
        if age>MAX_DELAY:
            log.warning(f'[SAFE] Signal expired! Age:{age:.0f}s > {MAX_DELAY}s')
            return False
        log.info(f'[SAFE] Signal fresh: {age:.0f}s old ✅')
        return True

    # ============================================================
    # STEP 2: PRICE VALIDATION
    # ============================================================
    def validate_price(self,exchange,symbol,token,signal_price):
        """Check if current price is within acceptable range"""
        try:
            ltp_resp=self.obj.ltpData(exchange,symbol,token)
            if not ltp_resp or not ltp_resp.get('data'):
                log.warning('[SAFE] Cannot get LTP for validation')
                return False,0

            current=float(ltp_resp['data'].get('ltp',0))
            if current<=0:return False,0

            # Check price slippage
            if signal_price>0:
                slip=abs(current-signal_price)/signal_price
                if slip>MAX_PRICE_SLIP:
                    log.warning(f'[SAFE] Price moved too much! signal={signal_price} current={current} slip={slip:.1%}')
                    return False,current

            log.info(f'[SAFE] Price valid: signal={signal_price} current={current} ✅')
            return True,current
        except Exception as e:
            log.error(f'[SAFE] Price validation error: {e}')
            return False,0

    # ============================================================
    # STEP 3: DUPLICATE PROTECTION
    # ============================================================
    def is_duplicate(self,symbol):
        """Check if trade already active for this symbol"""
        if symbol in self.active_trades:
            log.warning(f'[SAFE] Trade already active for {symbol}!')
            return True
        return False

    # ============================================================
    # STEP 4: SAFE ORDER PLACEMENT
    # ============================================================
    def place_safe_order(self,exchange,symbol,token,qty,
                        signal_price,signal,action='BUY'):
        """
        Complete safe order placement:
        1. Check signal freshness
        2. Validate price
        3. Check duplicates
        4. Place order
        5. Confirm execution
        6. Auto-cancel if stale
        """
        from v30_notify import send

        instrument=signal.get('instrument',symbol)

        # Step 1: Signal expiry
        signal['signal_time']=signal.get('signal_time',time.time())
        if not self.is_signal_fresh(signal):
            send(f'⚠️ {instrument} signal expired - skipped!')
            return None

        # Step 2: Duplicate check
        if self.is_duplicate(symbol):
            return None

        # Step 3: Price validation
        price_ok,current_price=self.validate_price(exchange,symbol,token,signal_price)
        if not price_ok:
            send(f'⚠️ {instrument} price moved too much!\nSignal: Rs.{signal_price}\nCurrent: Rs.{current_price:.0f}\nSkipped!')
            return None

        # Step 4: Place MARKET order
        order={
            'variety':'NORMAL',
            'tradingsymbol':symbol,
            'symboltoken':token,
            'transactiontype':action,
            'exchange':exchange,
            'ordertype':'MARKET',
            'producttype':'INTRADAY',
            'duration':'DAY',
            'quantity':str(qty)
        }

        log.info(f'[SAFE] Placing order: {symbol} {action} {qty}')

        try:
            resp=self.obj.placeOrder(order)
            if not resp or not resp.get('status'):
                log.error(f'[SAFE] Order rejected: {resp}')
                send(f'❌ {instrument} order rejected!\n{resp}')
                return None

            order_id=resp.get('data',{}).get('orderid','')
            log.info(f'[SAFE] Order placed: {order_id}')

            # Track order
            self.active_orders[order_id]={
                'symbol':symbol,
                'instrument':instrument,
                'action':action,
                'qty':qty,
                'time':time.time(),
                'signal_price':signal_price
            }
            self.active_trades[symbol]=order_id

        except Exception as e:
            log.error(f'[SAFE] Place error: {e}')
            return None

        # Step 5: Confirm execution (check every 2s for 2 mins)
        confirmed=self._confirm_order(order_id,instrument)

        if confirmed=='COMPLETE':
            send(f'✅ {instrument} order FILLED!\nID: {order_id}')
            return order_id
        elif confirmed in ['CANCELLED','REJECTED']:
            del self.active_trades[symbol]
            send(f'❌ {instrument} order {confirmed}!\nID: {order_id}')
            return None
        else:
            # Timeout - cancel
            self._cancel_order_safe(order_id,symbol,instrument)
            return None

    # ============================================================
    # STEP 5: ORDER CONFIRMATION
    # ============================================================
    def _confirm_order(self,order_id,instrument,max_wait=120):
        """Wait for order confirmation"""
        start=time.time()
        while time.time()-start<max_wait:
            try:
                time.sleep(2)
                orders=self.obj.orderBook()
                if not orders or not orders.get('data'):continue

                for o in orders['data']:
                    if str(o.get('orderid',''))==str(order_id):
                        status=o.get('orderstatus','').upper()
                        log.info(f'[SAFE] Order {order_id} status: {status}')
                        if status=='COMPLETE':return 'COMPLETE'
                        if status in ['CANCELLED','REJECTED']:return status
            except:pass

        log.warning(f'[SAFE] Order {order_id} timeout after {max_wait}s')
        return 'TIMEOUT'

    # ============================================================
    # STEP 6: STALE ORDER MONITOR
    # ============================================================
    def _start_stale_monitor(self):
        """Background thread to cancel stale orders"""
        def monitor():
            while True:
                try:
                    time.sleep(30)
                    self.cancel_stale_orders()
                except:pass
        t=threading.Thread(target=monitor,daemon=True)
        t.start()
        log.info('[SAFE] Stale order monitor started!')

    def cancel_stale_orders(self):
        """Cancel orders pending > 2 minutes"""
        try:
            orders=self.obj.orderBook()
            if not orders or not orders.get('data'):return 0

            now=time.time()
            cancelled=0
            for o in orders['data']:
                status=o.get('orderstatus','').upper()
                if status in ['OPEN','PENDING','TRIGGER PENDING']:
                    try:
                        # Parse order time
                        order_time_str=o.get('updatetime','')
                        if order_time_str:
                            import datetime
                            order_time=datetime.datetime.strptime(
                                order_time_str,'%d-%b-%Y %H:%M:%S').timestamp()
                            age=now-order_time
                            if age>ORDER_TIMEOUT:
                                oid=o.get('orderid','')
                                variety=o.get('variety','NORMAL')
                                self.obj.cancelOrder(oid,variety)
                                cancelled+=1
                                log.warning(f'[SAFE] Stale order cancelled: {oid} age={age:.0f}s')

                                # Notify
                                from v30_notify import send
                                sym=o.get('tradingsymbol','')
                                send(f'⚠️ Stale order cancelled!\n{sym}\nAge: {age:.0f}s')
                    except:pass
            return cancelled
        except Exception as e:
            log.error(f'[SAFE] Stale monitor error: {e}')
            return 0

    def _cancel_order_safe(self,order_id,symbol,instrument):
        """Cancel order and cleanup"""
        try:
            self.obj.cancelOrder(order_id,'NORMAL')
            log.warning(f'[SAFE] Order cancelled: {order_id}')
            if symbol in self.active_trades:
                del self.active_trades[symbol]
            from v30_notify import send
            send(f'⚠️ {instrument} order cancelled (not filled in 2 mins)\nSetup may be invalid!')
        except Exception as e:
            log.error(f'[SAFE] Cancel error: {e}')

    def release_trade(self,symbol):
        """Release trade lock when position closed"""
        if symbol in self.active_trades:
            del self.active_trades[symbol]
            log.info(f'[SAFE] Trade lock released: {symbol}')

# Global instance
safe_engine=None

def get_safe_engine(angel_obj):
    global safe_engine
    if safe_engine is None:
        safe_engine=SafeOrderEngine(angel_obj)
    return safe_engine
