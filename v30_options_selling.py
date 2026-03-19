import logging
from datetime import datetime,timedelta
import pandas as pd
log=logging.getLogger(__name__)

class OptionsSeller:
    def __init__(self):
        self.active_positions={}

    def get_iron_condor_strikes(self,instrument,current_price,atr,df15):
        """Calculate optimal Iron Condor strikes"""
        try:
            # Step size per instrument
            steps={'NIFTY':50,'BANKNIFTY':100,'SENSEX':100,
                   'FINNIFTY':50,'MIDCPNIFTY':25}
            step=steps.get(instrument,50)

            # Range based on ATR and market structure
            range_high=df15['high'].tail(20).max()
            range_low=df15['low'].tail(20).min()
            range_size=range_high-range_low

            # OTM distance = 1.5x recent range
            otm_dist=range_size*0.6

            # Strikes
            sell_ce=round((current_price+otm_dist)/step)*step
            sell_pe=round((current_price-otm_dist)/step)*step
            buy_ce=sell_ce+step*2   # 2 strikes above sell CE
            buy_pe=sell_pe-step*2   # 2 strikes below sell PE

            return {
                'sell_ce':sell_ce,
                'sell_pe':sell_pe,
                'buy_ce':buy_ce,
                'buy_pe':buy_pe,
                'max_profit_range':(sell_pe,sell_ce),
                'breakeven_upper':sell_ce+50,
                'breakeven_lower':sell_pe-50,
            }
        except Exception as e:
            log.error(f'[SELL] Strike error: {e}')
            return None

    def get_bull_put_spread(self,instrument,current_price,atr,df15):
        """Bull Put Spread - Mildly bullish/neutral"""
        try:
            steps={'NIFTY':50,'BANKNIFTY':100,'SENSEX':100}
            step=steps.get(instrument,50)

            # Sell ATM-1 PE, Buy ATM-2 PE
            sell_pe=round((current_price-atr)/step)*step
            buy_pe=sell_pe-step*2

            return {
                'type':'BULL_PUT_SPREAD',
                'sell_pe':sell_pe,
                'buy_pe':buy_pe,
                'max_profit':None,  # Premium collected
                'max_loss':step*2,  # Spread width
            }
        except:return None

    def get_bear_call_spread(self,instrument,current_price,atr,df15):
        """Bear Call Spread - Mildly bearish/neutral"""
        try:
            steps={'NIFTY':50,'BANKNIFTY':100,'SENSEX':100}
            step=steps.get(instrument,50)

            # Sell ATM+1 CE, Buy ATM+2 CE
            sell_ce=round((current_price+atr)/step)*step
            buy_ce=sell_ce+step*2

            return {
                'type':'BEAR_CALL_SPREAD',
                'sell_ce':sell_ce,
                'buy_ce':buy_ce,
                'max_profit':None,
                'max_loss':step*2,
            }
        except:return None

    def should_sell_options(self,df5,df15,instrument):
        """Check if conditions are right for options selling"""
        try:
            from v30_momentum import detect_market_condition
            from v30_train_kairos import calc_rsi

            market=detect_market_condition(df15)
            if market!='SIDEWAYS':return False,'NOT_SIDEWAYS'

            # VIX should be moderate (not too high, not too low)
            from v30_cache import cached_vix
            vix=cached_vix()
            if vix>18:return False,f'VIX_TOO_HIGH_{vix}'
            if vix<10:return False,f'VIX_TOO_LOW_{vix}'

            # Time filter - best for selling
            now=datetime.now()
            h=now.hour
            # Best time: 10AM-2PM (avoid 9AM volatility and 3PM expiry risk)
            if h<10 or h>14:return False,f'WRONG_TIME_{h}'

            # Check range is established
            h15=df15['high'];l15=df15['low']
            range_size=h15.tail(20).max()-l15.tail(20).min()
            atr=(df5['high']-df5['low']).tail(14).mean()
            if range_size<atr*2:return False,'RANGE_TOO_SMALL'

            # RSI near middle (not extreme)
            rsi=calc_rsi(df5['close']).iloc[-1]
            if rsi<35 or rsi>65:return False,f'RSI_EXTREME_{rsi:.0f}'

            return True,'CONDITIONS_MET'

        except Exception as e:
            return False,str(e)

    def place_iron_condor(self,client,instrument,strikes,qty,capital):
        """Place Iron Condor - 4 legs"""
        try:
            if not strikes:return None
            seg='nse_fo' if instrument not in ['CRUDEOIL','GOLDM','SILVERM'] else 'mcx_fo'
            now=datetime.now()

            # Get expiry
            days_to_thu=(3-now.weekday())%7
            if days_to_thu==0:days_to_thu=7
            expiry=(now+timedelta(days=days_to_thu)).strftime('%d%b%y').upper()

            orders=[]
            legs=[
                (f'{instrument}{expiry}{strikes["sell_ce"]}CE','S',qty),
                (f'{instrument}{expiry}{strikes["sell_pe"]}PE','S',qty),
                (f'{instrument}{expiry}{strikes["buy_ce"]}CE','B',qty),
                (f'{instrument}{expiry}{strikes["buy_pe"]}PE','B',qty),
            ]

            for symbol,side,q in legs:
                try:
                    order=client.place_order(
                        exchange_segment=seg,
                        product='NRML',
                        price='0',
                        order_type='MKT',
                        quantity=str(q),
                        validity='DAY',
                        trading_symbol=symbol,
                        transaction_type=side,
                        amo='NO',
                        disclosed_quantity='0',
                        market_protection='0',
                        pf='N',
                        trigger_price='0',
                        tag='V30-CONDOR'
                    )
                    orders.append(order)
                    log.info(f'[SELL] {side} {symbol} qty={q}')
                except Exception as e:
                    log.error(f'[SELL] Leg error {symbol}: {e}')

            if orders:
                position={
                    'instrument':instrument,
                    'type':'IRON_CONDOR',
                    'strikes':strikes,
                    'qty':qty,
                    'entry_time':str(now),
                    'max_profit_range':strikes['max_profit_range']
                }
                self.active_positions[instrument]=position

                # Notify
                from v30_notify import send
                send(f"""🔵 <b>IRON CONDOR PLACED</b>
━━━━━━━━━━━━━━━
📊 {instrument} | SIDEWAYS MARKET
🔴 Sell CE: {strikes["sell_ce"]}
🔴 Sell PE: {strikes["sell_pe"]}
🟢 Buy CE: {strikes["buy_ce"]} (hedge)
🟢 Buy PE: {strikes["buy_pe"]} (hedge)
💰 Profit Zone: {strikes["sell_pe"]}-{strikes["sell_ce"]}
⏰ {now.strftime('%H:%M')}""")

            return orders

        except Exception as e:
            log.error(f'[SELL] Iron condor error: {e}')
            return None

    def manage_selling_positions(self,client,feed):
        """Manage active selling positions"""
        try:
            now=datetime.now()
            for instrument,pos in list(self.active_positions.items()):
                current=feed.get_price(instrument)
                if current<=0:continue

                strikes=pos['strikes']
                profit_low=strikes['max_profit_range'][0]
                profit_high=strikes['max_profit_range'][1]

                # Exit if price breaks range
                if current>profit_high*1.005 or current<profit_low*0.995:
                    log.info(f'[SELL] {instrument} broke range! Closing condor')
                    self.close_position(client,instrument,pos)

                # Exit at 3 PM
                if now.hour==15 and now.minute>=0:
                    log.info(f'[SELL] EOD exit condor {instrument}')
                    self.close_position(client,instrument,pos)

        except Exception as e:
            log.error(f'[SELL] Manage error: {e}')

    def close_position(self,client,instrument,pos):
        """Close all legs of position"""
        try:
            seg='nse_fo'
            now=datetime.now()
            strikes=pos['strikes']
            qty=pos['qty']
            days_to_thu=(3-now.weekday())%7
            if days_to_thu==0:days_to_thu=7
            expiry=(now+timedelta(days=days_to_thu)).strftime('%d%b%y').upper()

            # Reverse all legs
            legs=[
                (f'{instrument}{expiry}{strikes["sell_ce"]}CE','B',qty),
                (f'{instrument}{expiry}{strikes["sell_pe"]}PE','B',qty),
                (f'{instrument}{expiry}{strikes["buy_ce"]}CE','S',qty),
                (f'{instrument}{expiry}{strikes["buy_pe"]}PE','S',qty),
            ]

            for symbol,side,q in legs:
                try:
                    client.place_order(
                        exchange_segment=seg,product='NRML',
                        price='0',order_type='MKT',
                        quantity=str(q),validity='DAY',
                        trading_symbol=symbol,transaction_type=side,
                        amo='NO',disclosed_quantity='0',
                        market_protection='0',pf='N',
                        trigger_price='0',tag='V30-CONDOR-EXIT'
                    )
                except:pass

            if instrument in self.active_positions:
                del self.active_positions[instrument]
            log.info(f'[SELL] {instrument} condor closed!')

        except Exception as e:
            log.error(f'[SELL] Close error: {e}')

options_seller=OptionsSeller()
