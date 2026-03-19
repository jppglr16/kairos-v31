import logging
from datetime import datetime,timedelta
import pandas as pd
log=logging.getLogger(__name__)

# Selling priority
SELL_PRIORITY=['SENSEX','NIFTY','FINNIFTY','MIDCPNIFTY']

# Lot sizes
LOTS={'SENSEX':20,'NIFTY':75,'FINNIFTY':65,'MIDCPNIFTY':120}

def can_sell(capital,is_expiry=False,instrument='NIFTY'):
    """
    Capital rules:
    < Rs.10,000    → Buy only
    Rs.10-50k      → Buy + Expiry selling only
    Rs.50-1,00,000 → Buy + SENSEX selling only
    > Rs.1,00,000  → Full strategy all instruments
    """
    if is_expiry:return True  # Always sell on expiry!
    if capital<10000:return False
    if capital<50000:return False  # Expiry only
    if capital<100000:
        return instrument=='SENSEX'  # SENSEX only
    return True  # Full strategy

def can_buy_only(capital):
    return capital<10000

def get_allowed_instruments(capital,is_expiry=False):
    """Get allowed instruments based on capital"""
    if is_expiry:
        return ['SENSEX','NIFTY','FINNIFTY','MIDCPNIFTY']
    if capital<50000:return []
    if capital<100000:return ['SENSEX']
    return ['SENSEX','NIFTY','FINNIFTY','MIDCPNIFTY']

def get_sell_lots(capital,instrument):
    MARGIN={"SENSEX":12000,"NIFTY":60000,"FINNIFTY":25000,"MIDCPNIFTY":15000}
    margin=MARGIN.get(instrument,30000)
    affordable=int((capital*0.40)/margin)  # Max 40% capital
    return max(1,min(2,affordable))  # Hard cap: 1-2 lots only

def is_sideways(df5,df15,atr):
    """Check if market is sideways"""
    try:
        c=df15['close'];h=df15['high'];l=df15['low']
        # Price range check
        range20=float(h.tail(20).max()-l.tail(20).min())
        avg_range=float((h-l).tail(20).mean())*10
        if range20<avg_range*1.5:return True
        # EMA check
        ema20=float(c.ewm(span=20).mean().iloc[-1])
        ema50=float(c.ewm(span=50).mean().iloc[-1]) if len(c)>=50 else ema20
        cur=float(c.iloc[-1])
        if abs(cur-ema20)/ema20<0.005:return True
        return False
    except:return False

def is_expiry_day(instrument=None):
    """Check if today is expiry for specific instrument"""
    try:
        from v31_options_sell import get_expiry_str
        from datetime import datetime
        today=datetime.now().date()
        if instrument:
            exp_str=get_expiry_str(instrument)
            exp_dt=datetime.strptime(exp_str,'%d%b%y').date()
            return exp_dt==today
        # Generic check - any major expiry today
        for inst in ['NIFTY','BANKNIFTY','SENSEX']:
            exp_str=get_expiry_str(inst)
            exp_dt=datetime.strptime(exp_str,'%d%b%y').date()
            if exp_dt==today:return True
        return False
    except:
        return datetime.now().weekday()==3  # Fallback: Thursday

def get_sell_strikes(instrument,current_price,atr,option_type):
    """
    Find strike with ~₹200 premium (sell)
    Find strike with ~₹15 premium (hedge buy)
    """
    steps={'SENSEX':200,'NIFTY':50,'FINNIFTY':50,'MIDCPNIFTY':25}
    step=steps.get(instrument,50)

    # Sell strike: 2-3 ATR away from current
    if option_type=='CE':
        sell_strike=round((current_price+atr*2.5)/step)*step
        hedge_strike=sell_strike+step*3
    else:
        sell_strike=round((current_price-atr*2.5)/step)*step
        hedge_strike=sell_strike-step*3

    return sell_strike,hedge_strike

def get_expiry_str(instrument):
    """Get nearest expiry string from master file"""
    try:
        from v31_angel_options import get_expiry_str as _get_exp
        return _get_exp(instrument)
    except:
        now=datetime.now()
        days_ahead=3-now.weekday()
        if days_ahead<=0:days_ahead+=7
        expiry=now+timedelta(days=days_ahead)
        return expiry.strftime('%d%b%y').upper()

def check_fvg_sell_opportunity(signal,capital):
    """
    When FVG/OB detected in directional signal:
    Also check if selling opportunity exists
    
    BUY signal near support FVG = Sell PE also
    SELL signal near resistance FVG = Sell CE also
    """
    try:
        if capital<100000:return None  # Need Rs.1L+

        instrument=signal.get('instrument','')
        action=signal.get('action','')
        imbalance=signal.get('imbalance_type','')
        score=signal.get('score',0)

        # Only on strong signals
        if score<20:return None

        # BUY signal near FVG support = Sell PE
        if action=='BUY' and 'BULL' in imbalance:
            return {
                'type':'SELL_PE_WITH_BUY',
                'instrument':instrument,
                'action':'SELL',
                'option_type':'PE',
                'reason':f'FVG support sell PE with BUY signal',
                'score':score
            }
        # SELL signal near FVG resistance = Sell CE
        elif action=='SELL' and 'BEAR' in imbalance:
            return {
                'type':'SELL_CE_WITH_SELL',
                'instrument':instrument,
                'action':'SELL',
                'option_type':'CE',
                'reason':f'FVG resistance sell CE with SELL signal',
                'score':score
            }
        return None
    except:return None

def check_sell_conditions(df5,df15,instrument,capital,atr):
    """
    Less confirmation needed for selling:
    1. Market sideways OR near gamma wall
    2. VIX in range (10-18)
    3. Time: 10AM-2PM
    4. Not too close to expiry (avoid last 30 mins)
    """
    try:
        now=datetime.now()
        h=now.hour;m=now.minute

        # Time filter
        if h<10 or h>14:return False,'WRONG_TIME'
        if h==15 and m>0:return False,'TOO_LATE'

        # VIX check
        try:
            from v30_cache import cached_vix
            vix=cached_vix()
            if vix>20:return False,f'VIX_HIGH_{vix}'
            if vix<8:return False,f'VIX_LOW_{vix}'
        except:pass

        # Market check
        sideways=is_sideways(df5,df15,atr)
        if not sideways:return False,'NOT_SIDEWAYS'

        # Capital check
        expiry_day=is_expiry_day()
        if not can_sell(capital,expiry_day):
            return False,f"CAPITAL_LOW_{capital}"

        return True,'CONDITIONS_MET'
    except Exception as e:
        return False,str(e)

def get_sell_signal(df5,df15,instrument,capital,active_positions):
    """
    Generate sell signal for sideways market:
    
    Single direction:
    Near top of range → Sell CE + Buy hedge CE
    Near bottom of range → Sell PE + Buy hedge PE
    
    Iron Condor (truly sideways):
    Sell CE + Sell PE + Buy CE hedge + Buy PE hedge
    """
    try:
        if instrument not in SELL_PRIORITY:return None
        if instrument in active_positions:return None

        c=df5['close'];h=df5['high'];l=df5['low']
        atr=float((h-l).tail(14).mean())
        current=float(c.iloc[-1])

        expiry=is_expiry_day()
        if expiry:
            # Expiry day: relax conditions
            sideways=is_sideways(df5,df15,atr)
            if not sideways:
                # Even on trending expiry day - sell far OTM
                log.info(f"[SELL] Expiry trending: sell far OTM {instrument}")
            ok=True  # Allow sell on expiry day
        else:
            ok,reason=check_sell_conditions(df5,df15,instrument,capital,atr)
        if not ok:log.debug(f"[SELL] {instrument}: {reason}");return None

        # Range analysis
        high20=float(h.tail(20).max())
        low20=float(l.tail(20).min())
        range_size=high20-low20
        if range_size<=0:return None
        pos=(current-low20)/range_size

        expiry=get_expiry_str(instrument)
        sell_ce,hedge_ce=get_sell_strikes(instrument,current,atr,'CE')
        sell_pe,hedge_pe=get_sell_strikes(instrument,current,atr,'PE')
        lots=get_sell_lots(capital,instrument)

        # Determine strategy
        if pos>=0.70:
            # Near top - Sell CE only
            strategy='SELL_CE'
            signal={
                'type':'SELL_CE',
                'instrument':instrument,
                'action':'SELL',
                'sell_strike':sell_ce,
                'hedge_strike':hedge_ce,
                'option_type':'CE',
                'expiry':expiry,
                'lots':lots,
                'current_price':current,
                'reason':f'Near range top {pos*100:.0f}%',
                'min_confirmation':True  # Less confirmation needed
            }
        elif pos<=0.30:
            # Near bottom - Sell PE only
            strategy='SELL_PE'
            signal={
                'type':'SELL_PE',
                'instrument':instrument,
                'action':'SELL',
                'sell_strike':sell_pe,
                'hedge_strike':hedge_pe,
                'option_type':'PE',
                'expiry':expiry,
                'lots':lots,
                'current_price':current,
                'reason':f'Near range bottom {pos*100:.0f}%',
                'min_confirmation':True
            }
        else:
            # Middle - Iron Condor
            strategy='IRON_CONDOR'
            signal={
                'type':'IRON_CONDOR',
                'instrument':instrument,
                'action':'SELL_BOTH',
                'sell_ce':sell_ce,
                'hedge_ce':hedge_ce,
                'sell_pe':sell_pe,
                'hedge_pe':hedge_pe,
                'expiry':expiry,
                'lots':lots,
                'current_price':current,
                'profit_zone':(sell_pe,sell_ce),
                'reason':f'Sideways middle {pos*100:.0f}%',
                'min_confirmation':True
            }

        # Add Straddle on expiry day (ATM sell both CE+PE)
        if is_expiry_day():
            signal['expiry_day']=True
            signal['lots']=min(lots+1,8)
            signal['reason']+=' | EXPIRY_DAY'
            # Switch to STRADDLE on expiry for max premium
            atm=round(current/step)*step if (step:=50) else round(current/50)*50
            signal={
                'type':'STRADDLE',
                'instrument':instrument,
                'action':'SELL_BOTH',
                'sell_ce':atm,
                'sell_pe':atm,
                'sell_strike':atm,
                'hedge_strike':atm+step*4,
                'option_type':'CE',
                'sell_strike':atm,
                'hedge_strike':atm+step*4,
                'option_type':'CE',
                'hedge_ce':atm+step*4,
                'hedge_pe':atm-step*4,
                'expiry':expiry,
                'lots':signal['lots'],
                'current_price':current,
                'reason':f'EXPIRY STRADDLE ATM={atm}',
                'expiry_day':True
            }
            log.info(f'[SELL] EXPIRY STRADDLE for {instrument} ATM={atm}!')

        # Add STRANGLE for high volatility sideways
        elif atr/current*100>0.5 and 0.30<pos<0.70:
            step=50
            if 'BANK' in instrument:step=100
            elif 'SENSEX' in instrument:step=100
            otm_ce=round((current+atr*1.5)/step)*step
            otm_pe=round((current-atr*1.5)/step)*step
            signal={
                'type':'STRANGLE',
                'instrument':instrument,
                'action':'SELL_BOTH',
                'sell_ce':otm_ce,
                'sell_pe':otm_pe,
                'hedge_ce':otm_ce+step*3,
                'hedge_pe':otm_pe-step*3,
                'expiry':expiry,
                'lots':lots,
                'current_price':current,
                'reason':f'STRANGLE OTM CE={otm_ce} PE={otm_pe}'
            }
            log.info(f'[SELL] STRANGLE for {instrument}!')

        log.info(f'[SELL] {instrument} {strategy} '
                f'pos={pos*100:.0f}% lots={signal["lots"]}')
        return signal

    except Exception as e:
        log.error(f'[SELL] Signal error {instrument}: {e}')
        return None

def place_sell_order(client,instrument,signal,active_positions):
    """Place sell order + hedge"""
    try:
        seg='bse_fo' if instrument=='SENSEX' else 'nse_fo'
        lots=signal['lots']
        base_lot=LOTS.get(instrument,75)
        qty=lots*base_lot
        expiry=signal['expiry']
        orders=[]

        if signal['type']=='IRON_CONDOR':
            legs=[
                (f'{instrument}{expiry}{signal["sell_ce"]}CE','S',qty,'SELL_CE'),
                (f'{instrument}{expiry}{signal["sell_pe"]}PE','S',qty,'SELL_PE'),
                (f'{instrument}{expiry}{signal["hedge_ce"]}CE','B',qty,'HEDGE_CE'),
                (f'{instrument}{expiry}{signal["hedge_pe"]}PE','B',qty,'HEDGE_PE'),
            ]
        else:
            otype=signal.get('option_type',signal.get('opt_type','CE'))
            legs=[
                (f'{instrument}{expiry}{signal["sell_strike"]}{otype}','S',qty,'SELL'),
                (f'{instrument}{expiry}{signal["hedge_strike"]}{otype}','B',qty,'HEDGE'),
            ]

        for symbol,side,q,tag in legs:
            try:
                order=client.place_order(
                    exchange_segment=seg,product='NRML',
                    price='0',order_type='MKT',
                    quantity=str(q),validity='DAY',
                    trading_symbol=symbol,transaction_type=side,
                    amo='NO',disclosed_quantity='0',
                    market_protection='0',pf='N',
                    trigger_price='0',tag=f'V31-{tag}'
                )
                orders.append(order)
                log.info(f'[SELL] {side} {symbol} qty={q}')
            except Exception as e:
                log.error(f'[SELL] Order error {symbol}: {e}')

        if orders:
            active_positions[instrument]=signal
            active_positions[instrument]['entry_time']=str(datetime.now())
            _notify_sell_entry(signal,qty)

        return orders
    except Exception as e:
        log.error(f'[SELL] Place error: {e}')
        return None

def manage_sell_positions(client,feed,active_positions):
    """Monitor sell positions"""
    try:
        now=datetime.now()
        for instrument in list(active_positions.keys()):
            pos=active_positions[instrument]
            if not isinstance(pos,dict):continue
            if pos.get('type') not in ['SELL_CE','SELL_PE','IRON_CONDOR']:continue

            current=float(feed.get_price(instrument))
            if current<=0:continue

            # Exit conditions
            should_exit=False;exit_reason=''

            # EOD exit
            if now.hour==15 and now.minute>=0:
                should_exit=True;exit_reason='EOD'

            # Range break for iron condor
            if pos['type']=='IRON_CONDOR':
                pz=pos.get('profit_zone',(0,999999))
                if current>pz[1]*1.005:
                    should_exit=True;exit_reason='CE_BREAK'
                elif current<pz[0]*0.995:
                    should_exit=True;exit_reason='PE_BREAK'

            # Directional break
            elif pos['type']=='SELL_CE':
                if current>=pos['sell_strike']*1.003:
                    should_exit=True;exit_reason='STRIKE_BREACH'
            elif pos['type']=='SELL_PE':
                if current<=pos['sell_strike']*0.997:
                    should_exit=True;exit_reason='STRIKE_BREACH'

            if should_exit:
                log.info(f'[SELL] Closing {instrument}: {exit_reason}')
                _close_sell_position(client,instrument,pos,active_positions)

    except Exception as e:
        log.error(f'[SELL] Manage error: {e}')

def _close_sell_position(client,instrument,pos,active_positions):
    """Close all legs"""
    try:
        seg='bse_fo' if instrument=='SENSEX' else 'nse_fo'
        lots=pos.get('lots',3)
        base_lot=LOTS.get(instrument,75)
        qty=lots*base_lot
        expiry=pos.get('expiry','')

        if pos['type']=='IRON_CONDOR':
            legs=[
                (f'{instrument}{expiry}{pos["sell_ce"]}CE','B',qty),
                (f'{instrument}{expiry}{pos["sell_pe"]}PE','B',qty),
                (f'{instrument}{expiry}{pos["hedge_ce"]}CE','S',qty),
                (f'{instrument}{expiry}{pos["hedge_pe"]}PE','S',qty),
            ]
        else:
            otype=pos['option_type']
            legs=[
                (f'{instrument}{expiry}{pos["sell_strike"]}{otype}','B',qty),
                (f'{instrument}{expiry}{pos["hedge_strike"]}{otype}','S',qty),
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
                    trigger_price='0',tag='V31-EXIT'
                )
            except:pass

        if instrument in active_positions:
            del active_positions[instrument]
        _notify_sell_exit(instrument,pos)

    except Exception as e:
        log.error(f'[SELL] Close error: {e}')

def _notify_sell_entry(signal,qty):
    """Telegram notification for sell entry"""
    try:
        from v30_notify import send
        inst=signal['instrument']
        stype=signal['type']
        lots=signal['lots']
        expiry=signal['expiry']
        expiry_tag='🎯 EXPIRY DAY!' if signal.get('expiry_day') else ''

        if stype=='IRON_CONDOR':
            # Get real LTP for sell strikes
            try:
                from v31_angel_trader import angel_trader
                import json as _json
                if not angel_trader.connected:angel_trader.connect()
                _lookup=_json.load(open('angel_options_lookup.json'))
                _exch='BFO' if 'SENSEX' in instrument else 'NFO'
                _exp=signal.get('expiry','')

                def _get_ltp(sym):
                    if sym in _lookup:
                        r=angel_trader.obj.ltpData(_exch,sym,_lookup[sym]['token'])
                        return float(r['data']['ltp']) if r and r.get('data') else 200
                    return 200

                if signal.get('type')=='IRON_CONDOR':
                    ce_sym=f"{instrument}{_exp}{signal['sell_ce']}CE"
                    pe_sym=f"{instrument}{_exp}{signal['sell_pe']}PE"
                    hce_sym=f"{instrument}{_exp}{signal['hedge_ce']}CE"
                    hpe_sym=f"{instrument}{_exp}{signal['hedge_pe']}PE"
                    sell_ce_p=_get_ltp(ce_sym)
                    sell_pe_p=_get_ltp(pe_sym)
                    hedge_ce_p=_get_ltp(hce_sym)
                    hedge_pe_p=_get_ltp(hpe_sym)
                    prem_est=(sell_ce_p+sell_pe_p-hedge_ce_p-hedge_pe_p)*qty
                else:
                    s_sym=f"{instrument}{_exp}{signal.get('sell_strike',signal.get('sell_ce',''))}CE"
                    h_sym=f"{instrument}{_exp}{signal.get('hedge_strike',signal.get('hedge_ce',''))}CE"
                    sell_p=_get_ltp(s_sym)
                    hedge_p=_get_ltp(h_sym)
                    prem_est=(sell_p-hedge_p)*qty
            except:
                prem_est=(200+200-15-15)*qty
            msg=f"""🔵 <b>V31 IRON CONDOR</b> {expiry_tag}
━━━━━━━━━━━━━━━
📊 {inst} | SIDEWAYS MARKET
📦 Lots: {lots} | Qty: {qty}

🔴 Sell CE: {signal['sell_ce']} @ ₹{sell_ce_p:.0f}
🔴 Sell PE: {signal['sell_pe']} @ ₹{sell_pe_p:.0f}
🟢 Hedge CE: {signal['hedge_ce']} @ ₹{hedge_ce_p:.0f}
🟢 Hedge PE: {signal['hedge_pe']} @ ₹{hedge_pe_p:.0f}

💰 Premium: ~₹{prem_est:,.0f}
📈 Profit Zone: {signal['sell_pe']}-{signal['sell_ce']}
📌 {signal['reason']}
⏰ {datetime.now().strftime('%H:%M:%S')}"""
        else:
            otype=signal.get('option_type',signal.get('opt_type','CE'))
            prem_est=(200-15)*qty
            msg=f"""🔴 <b>V31 SELL {otype} + HEDGE</b> {expiry_tag}
━━━━━━━━━━━━━━━
📊 {inst}
📦 Lots: {lots} | Qty: {qty}

🔴 Sell {otype}: {signal['sell_strike']} @ ~₹200
🟢 Hedge {otype}: {signal['hedge_strike']} @ ~₹15

💰 Net Premium: ~₹{prem_est:,.0f}
📌 {signal['reason']}
⏰ {datetime.now().strftime('%H:%M:%S')}"""
        send(msg)
    except Exception as e:
        log.error(f'[SELL] Notify error: {e}')

def _notify_sell_exit(instrument,pos):
    """Telegram for sell exit"""
    try:
        from v30_notify import send
        send(f"""✅ <b>V31 SELL CLOSED</b>
📊 {instrument} | {pos.get('type','')}
⏰ {datetime.now().strftime('%H:%M:%S')}""")
    except:pass

# Main function called from v31_main.py
def run_sell_strategy(client,feed,capital,active_trades,active_positions):
    """Called every 60 seconds from main loop"""
    try:
        now=datetime.now()
        if now.hour<10 or now.hour>14:return

        # Manage existing positions
        manage_sell_positions(client,feed,active_positions)

        # Scan for new opportunities
        for instrument in SELL_PRIORITY:
            if instrument in active_trades:continue
            if instrument in active_positions:continue

            df5=feed.get_candles(instrument,'5')
            df15=feed.get_candles(instrument,'15')
            if df5 is None or df15 is None:continue
            if len(df5)<20:continue

            signal=get_sell_signal(df5,df15,instrument,capital,active_positions)
            if signal:
                place_sell_order(client,instrument,signal,active_positions)
                break  # One at a time

    except Exception as e:
        log.error(f'[SELL] Strategy error: {e}')
