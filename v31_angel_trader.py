import logging,time
from SmartApi import SmartConnect
import pyotp
from datetime import datetime

log=logging.getLogger(__name__)

def retry_api(func,attempts=3,delay=2):
    """Retry API call with backoff"""
    for i in range(attempts):
        try:
            result=func()
            if result:return result
        except Exception as e:
            log.warning(f'[RETRY] Attempt {i+1}/{attempts} failed: {e}')
            if i<attempts-1:
                time.sleep(delay*(i+1))
    return None

def verify_order(obj,order_id,max_wait=60):
    """Verify order status after placement"""
    import time as _t
    log.info(f'[VERIFY] Checking order {order_id}...')
    for attempt in range(6):  # Check every 10 secs for 60 secs
        try:
            _t.sleep(10)
            book=obj.orderBook()
            if book and book.get('data'):
                for order in book['data']:
                    if str(order.get('orderid'))==str(order_id):
                        status=order.get('status','').upper()
                        log.info(f'[VERIFY] Order {order_id}: {status}')
                        if status=='COMPLETE':
                            return True,'COMPLETE'
                        elif status in ('REJECTED','CANCELLED'):
                            return False,status
                        # Still pending - continue waiting
        except Exception as e:
            log.warning(f'[VERIFY] Check error: {e}')
    return False,'TIMEOUT'

class AngelOneTrader:
    def __init__(self):
        self.obj=None
        self.connected=False

    def connect(self,retries=3):
        """Connect with retry logic"""
        for attempt in range(retries):
            try:
                import time
                time.sleep(3)
                self.obj=SmartConnect(api_key='pEOas0vU')
                totp=pyotp.TOTP('R2T2F2BMP56U44O4OMOYJZTFJI').now()
                data=self.obj.generateSession('J234619','1605',totp)
                if data and data.get('status'):
                    self.connected=True
                    self._connect_time=datetime.now()
                    self._refresh_token=data.get('data',{}).get('refreshToken','')
                    # Store for WebSocket!
                    self.client_id = 'J234619'
                    self.feed_token = data.get('data',{}).get('feedToken','')
                    log.info(f'[ANGEL] Connected! (attempt {attempt+1})')
                    return True
                log.warning(f'[ANGEL] Connect failed attempt {attempt+1}')
            except Exception as e:
                log.error(f'[ANGEL] Connect error attempt {attempt+1}: {e}')
            time.sleep(5*(attempt+1))  # 5s, 10s, 15s backoff
        log.error('[ANGEL] All connect attempts failed!')
        return False

    def is_connected(self):
        """Heartbeat check"""
        try:
            if not self.connected or not self.obj:
                return False
            profile=self.obj.getProfile()
            if profile and profile.get('status'):
                return True
            self.connected=False
            return False
        except:
            self.connected=False
            return False

    def refresh_session(self):
        """Refresh token before expiry"""
        try:
            if hasattr(self,'_refresh_token') and self._refresh_token:
                data=self.obj.generateToken(self._refresh_token)
                if data and data.get('status'):
                    log.info('[ANGEL] Token refreshed!')
                    self._connect_time=datetime.now()
                    return True
            # Fall back to full reconnect
            return self.reconnect()
        except Exception as e:
            log.error(f'[ANGEL] Token refresh failed: {e}')
            return self.reconnect()

    def reconnect(self):
        """Reconnect on failure"""
        log.warning('[ANGEL] Reconnecting...')
        self.connected=False
        self.obj=None
        time.sleep(5)
        result=self.connect()
        if result:
            log.info('[ANGEL] Reconnected successfully!')
        else:
            log.error('[ANGEL] Reconnect failed!')
        return result

    def check_and_refresh(self):
        """Auto-refresh every 6 hours"""
        try:
            if not hasattr(self,'_connect_time'):
                return
            hours=(datetime.now()-self._connect_time).seconds/3600
            if hours>=6:
                log.info(f'[ANGEL] Token age={hours:.1f}h, refreshing...')
                self.refresh_session()
        except:pass

    def get_capital(self):
        try:
            funds=self.obj.rmsLimit()
            if funds and funds.get('data'):
                cash=float(funds['data'].get('net',0) or
                           funds['data'].get('availablecash',0) or 0)
                if cash>0:
                    log.info(f'[ANGEL] Capital: Rs.{cash:,.0f}')
                    return round(cash)
            return 50000
        except Exception as e:
            log.error(f'[ANGEL] Capital error: {e}')
            return 50000

    def get_available_margin(self):
        """Fetch real available margin from Angel One"""
        try:
            funds=self.obj.rmsLimit()
            if funds and funds.get('data'):
                net=float(funds['data'].get('net',0) or 0)
                cash=float(funds['data'].get('availablecash',0) or 0)
                margin=float(funds['data'].get('availablelimitmargin',0) or 0)
                available=max(net,cash,margin)
                log.info(f'[ANGEL] Available margin: Rs.{available:,.0f}')
                return round(available)
            return 0
        except Exception as e:
            log.error(f'[ANGEL] Margin fetch error: {e}')
            return 0

    def check_margin_sufficient(self,instrument,qty,premium):
        """Check if margin is sufficient before placing order"""
        try:
            available=self.get_available_margin()
            required=premium*qty*1.2  # 20% buffer
            if available<required:
                from v30_notify import send
                send(f"""⚠️ <b>Insufficient Margin!</b>
━━━━━━━━━━━━━━━
📊 {instrument}
💰 Available: Rs.{available:,.0f}
💸 Required: Rs.{required:,.0f}
📉 Shortfall: Rs.{required-available:,.0f}
⚠️ Add funds to Angel One!
🔗 angelone.in""")
                log.warning(f'[ANGEL] Insufficient margin: have Rs.{available:,} need Rs.{required:,}')
                return False,available,required
            log.info(f'[ANGEL] Margin OK: Rs.{available:,} >= Rs.{required:,}')
            return True,available,required
        except Exception as e:
            log.error(f'[ANGEL] Margin check error: {e}')
            return False,0,0

    def refresh_capital(self):
        """Refresh capital from Angel One"""
        try:
            available=self.get_available_margin()
            if available>0:
                log.info(f'[ANGEL] Capital refreshed: Rs.{available:,}')
                return available
            return 0
        except:return 0

    def place_option_trade(self,signal,capital):
        """Place option trade for any instrument"""
        try:
            from v31_angel_options import search_option_token,place_option_order
            instrument=signal['instrument']
            action=signal['action']
            price=float(signal.get('price',0))
            opt_type='CE' if action=='BUY' else 'PE'
            atr=signal.get('atr',50)

            # Get lot size
            LOT={'NIFTY':65,'BANKNIFTY':30,'SENSEX':20,'FINNIFTY':60,
                 'MIDCPNIFTY':120,'CRUDEOIL':100,'GOLDM':10,'SILVERM':30,
                 'NATURALGAS':1250,'LT':450,'NTPC':4500,'MARUTI':100,
                 'BHARTIARTL':950,'SBIN':1500,'TATAMOTORS':1350,
                 'RELIANCE':250,'HINDUNILVR':300,'TCS':150,'TATASTEEL':5500}
            lot=LOT.get(instrument,75)

            # Calculate premium
            # Get real premium from Angel One
            try:
                from v31_angel_options import search_option_token
                _tok,_sym,_exch=search_option_token(self.obj,instrument,float(signal.get('price',0)),opt_type)
                if _tok:
                    _ltp=self.obj.ltpData(_exch,_sym,_tok)
                    prem=float(_ltp['data'].get('ltp',0)) if _ltp and _ltp.get('data') else 0
                else:prem=0
            except:prem=0
            if not prem:prem=signal.get('real_prem',max(50,round(atr*0.9)))

            # Real margin check from Angel One
            margin_ok,available,required=self.check_margin_sufficient(instrument,lot,prem)
            if not margin_ok:
                log.warning(f'[ANGEL] Margin insufficient for {instrument}')
                return None

            # Also check passed capital
            if capital<est_cost*1.2:
                log.warning(f'[ANGEL] Low capital: Rs.{capital:,} need Rs.{est_cost*1.2:,.0f}')
                return None

            order_id=place_option_order(
                self.obj,instrument,price,opt_type,lot,action
            )
            if order_id:
                log.info(f'[ANGEL] Option trade placed: {instrument} {opt_type} ID:{order_id}')

                # Verify order
                import threading
                threading.Thread(
                    target=self.verify_order,
                    args=(order_id,instrument),
                    daemon=True
                ).start()

                # Place SL and Target orders
                import time
                time.sleep(2)

                atr=signal.get('atr',50)
                # Calculate SL and target in premium terms
                if instrument in ['NIFTY','BANKNIFTY','SENSEX','FINNIFTY','MIDCPNIFTY']:
                    opt_prem=max(50,min(500,round(atr*0.9)))
                elif instrument in ['CRUDEOIL','GOLDM','SILVERM','NATURALGAS']:
                    opt_prem=max(30,min(300,round(atr*0.8)))
                else:
                    opt_prem=max(10,min(200,round(float(signal.get('price',100))*0.015)))

                sl_prem=round(opt_prem*0.40)
                t2_prem=round(opt_prem*2.5) if signal.get('score',0)>=22 else round(opt_prem*2.0)

                from v31_angel_options import search_option_token
                token,sym,exch=search_option_token(self.obj,instrument,float(signal.get('price',0)),opt_type)
                if token:
                    threading.Thread(
                        target=self.place_sl_target_orders,
                        args=(order_id,sym,token,exch,lot,opt_prem,sl_prem,t2_prem,opt_type),
                        daemon=True
                    ).start()

            return order_id
        except Exception as e:
            log.error(f'[ANGEL] Option trade error: {e}')
            return None

    def place_order(self,symbol,token,exchange,qty,order_type='BUY'):
        try:
            if not self.connected:
                self.connect()

            # Map exchange
            exch_map={
                'NSE':'NSE','BSE':'BSE','MCX':'MCX'
            }

            order={
                'variety':'NORMAL',
                'tradingsymbol':symbol,
                'symboltoken':token,
                'transactiontype':order_type,
                'exchange':exch_map.get(exchange,'NSE'),
                'ordertype':'MARKET',
                'producttype':'INTRADAY',
                'duration':'DAY',
                'quantity':str(qty)
            }

            resp=self.obj.placeOrder(order)
            if resp and resp.get('status'):
                order_id=resp.get('data',{}).get('orderid','')
                log.info(f'[ANGEL] Order placed! ID:{order_id} {symbol} {order_type} {qty}')
                return order_id
            else:
                log.error(f'[ANGEL] Order failed: {resp}')
                return None
        except Exception as e:
            log.error(f'[ANGEL] Order error: {e}')
            return None

    def verify_order(self,order_id,instrument):
        """Check order status after placement"""
        try:
            import time
            time.sleep(2)  # Wait for order to process
            
            # Get order book
            resp=self.obj.orderBook()
            if not resp or not resp.get('data'):
                return 'UNKNOWN'
            
            for order in resp['data']:
                if str(order.get('orderid',''))==str(order_id):
                    status=order.get('orderstatus','').upper()
                    qty=order.get('quantity',0)
                    price=order.get('averageprice',0)
                    symbol=order.get('tradingsymbol','')
                    
                    from v30_notify import send
                    if status=='COMPLETE':
                        send(f"""✅ <b>Order FILLED!</b>
━━━━━━━━━━━━━━━
📊 {symbol}
💰 Price: Rs.{price}
📦 Qty: {qty}
🆔 ID: {order_id}
🕐 {datetime.now().strftime("%H:%M:%S")}""")
                        log.info(f'[ANGEL] Order filled: {order_id} at Rs.{price}')
                        return 'FILLED'
                    elif status in ['REJECTED','CANCELLED']:
                        send(f"""❌ <b>Order {status}!</b>
━━━━━━━━━━━━━━━
📊 {symbol}
❗ Reason: {order.get("text","")}
🆔 ID: {order_id}
🕐 {datetime.now().strftime("%H:%M:%S")}""")
                        log.warning(f'[ANGEL] Order {status}: {order_id}')
                        return status
                    else:
                        log.info(f'[ANGEL] Order status: {status}')
                        return status
            return 'NOT_FOUND'
        except Exception as e:
            log.error(f'[ANGEL] Verify error: {e}')
            return 'ERROR'

    def place_order_with_retry(self,order,max_attempts=3):
        """Place order with retry logic"""
        from v30_notify import send
        for attempt in range(1,max_attempts+1):
            try:
                import time
                resp=self.obj.placeOrder(order)
                if resp and resp.get('status'):
                    order_id=resp.get('data',{}).get('orderid','')
                    log.info(f'[ANGEL] Order placed attempt {attempt}: {order_id}')
                    return order_id
                else:
                    log.warning(f'[ANGEL] Attempt {attempt} failed: {resp}')
                    time.sleep(2)
            except Exception as e:
                log.error(f'[ANGEL] Attempt {attempt} error: {e}')
                time.sleep(2)

        # All attempts failed
        send(f"""❌ Order Failed!
━━━━━━━━━━━━━━━
📊 {order.get('tradingsymbol','')}
🔄 Tried {max_attempts} times
❗ All attempts failed!
⏰ {__import__('datetime').datetime.now().strftime('%H:%M:%S')}""")
        log.error(f'[ANGEL] All {max_attempts} attempts failed!')
        return None

    def place_sl_target_orders(self,order_id,symbol,token,exchange,qty,entry_price,sl_price,target_price,opt_type):
        """Place SL and Target orders after entry"""
        try:
            from v30_notify import send
            import time
            time.sleep(1)

            # SL Order (Stop Loss)
            sl_order={
                'variety':'STOPLOSS',
                'tradingsymbol':symbol,
                'symboltoken':token,
                'transactiontype':'SELL',
                'exchange':exchange,
                'ordertype':'STOPLOSS_MARKET',
                'producttype':'INTRADAY',
                'duration':'DAY',
                'quantity':str(qty),
                'triggerprice':str(sl_price),
                'price':str(round(sl_price*0.95))
            }

            sl_id=self.place_order_with_retry(sl_order)
            time.sleep(1)

            # Target Order (Limit)
            target_order={
                'variety':'NORMAL',
                'tradingsymbol':symbol,
                'symboltoken':token,
                'transactiontype':'SELL',
                'exchange':exchange,
                'ordertype':'LIMIT',
                'producttype':'INTRADAY',
                'duration':'DAY',
                'quantity':str(qty),
                'price':str(target_price)
            }

            tgt_id=self.place_order_with_retry(target_order)

            if sl_id and tgt_id:
                send(f"""✅ SL & Target Set!
━━━━━━━━━━━━━━━
📊 {symbol}
🛑 SL: Rs.{sl_price} (ID:{sl_id})
🎯 Target: Rs.{target_price} (ID:{tgt_id})
📦 Qty: {qty}
⏰ {__import__('datetime').datetime.now().strftime('%H:%M:%S')}""")
                log.info(f'[ANGEL] SL:{sl_id} Target:{tgt_id} set!')
                return sl_id,tgt_id
            return None,None
        except Exception as e:
            log.error(f'[ANGEL] SL/Target error: {e}')
            return None,None

    def cancel_order(self,order_id,variety='NORMAL'):
        """Cancel existing order"""
        try:
            resp=self.obj.cancelOrder(order_id,variety)
            if resp and resp.get('status'):
                log.info(f'[ANGEL] Order cancelled: {order_id}')
                return True
            return False
        except Exception as e:
            log.error(f'[ANGEL] Cancel error: {e}')
            return False

    def get_ltp(self,exchange,symbol,token):
        try:
            resp=self.obj.ltpData(exchange,symbol,token)
            if resp and resp.get('data'):
                return float(resp['data'].get('ltp',0))
            return 0
        except:return 0

    def get_option_symbol(self,instrument,strike,opt_type,expiry):
        """Get option trading symbol"""
        # Format: NIFTY17APR2523400CE
        return f"{instrument}{expiry}{strike}{opt_type}"

# Global instance
angel_trader=AngelOneTrader()
