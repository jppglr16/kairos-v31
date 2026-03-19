import asyncio,logging,json,os
from v31_options_sell import run_sell_strategy
from datetime import datetime,timedelta
import pandas as pd

# File only logging - no duplicates
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [V31] %(message)s',
    filename='v31_log.txt',
    filemode='a'
)
log=logging.getLogger(__name__)

from v31_instrument_manager import instrument_manager,INSTRUMENTS as _INST_CONFIG
INSTRUMENTS=instrument_manager.get_all_instruments()

def get_inst_exchange(inst):
    return _INST_CONFIG.get(inst,{}).get('exch_seg','NFO')

def get_inst_token(inst):
    return _INST_CONFIG.get(inst,{}).get('token','')
from v31_options_sell import run_sell_strategy
from datetime import datetime,timedelta
import pandas as pd

# File only logging - no duplicates
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [V31] %(message)s',
    filename='v31_log.txt',
    filemode='a'
)
log=logging.getLogger(__name__)

INSTRUMENTS=['NIFTY','BANKNIFTY','SENSEX','FINNIFTY','MIDCPNIFTY',
             'CRUDEOIL','GOLDM','SILVERM',
             'LT','NTPC','MARUTI','BHARTIARTL','SBIN',
             'TATAMOTORS','RELIANCE','HINDUNILVR','TCS','TATASTEEL','NATURALGAS']
LOT={'NIFTY':65,'BANKNIFTY':30,'SENSEX':20,'FINNIFTY':60,
     'MIDCPNIFTY':120,'CRUDEOIL':100,'GOLDM':10,'SILVERM':30,
     'LT':450,'NTPC':4500,'MARUTI':100,'BHARTIARTL':950,
     'SBIN':1500,'TATAMOTORS':1350,'RELIANCE':250,
     'HINDUNILVR':300,'TCS':150,'TATASTEEL':5500,'NATURALGAS':1250}
TOKEN={'NIFTY':'99926000','BANKNIFTY':'99926009','SENSEX':'99919000',
       'FINNIFTY':'99926037','MIDCPNIFTY':'99926074',
       'CRUDEOIL':'472790','GOLDM':'477904','SILVERM':'457533',
       'LT':'11483','NTPC':'11630','MARUTI':'10999',
       'BHARTIARTL':'10604','SBIN':'3045','TATAMOTORS':'3456',
       'RELIANCE':'2885','HINDUNILVR':'1394','TCS':'11536','TATASTEEL':'3499','NATURALGAS':'475111'}

active_trades={}
signal_cooldown={}  # Prevents duplicate signals
ENABLE_PATH_CD=True   # Enabled for paper trading!
last_signals={}    # Strike+direction cooldown (30 min)
last_prices={}     # Price distance filter
used_zones=set()   # OB/FVG zone consumption
trades_today={}    # Max 2 signals per instrument per day

# Angel One MCX feed
try:
    from v31_angel_feed import angel_mcx_feed
    angel_mcx_feed.connect()
    log.info('[V31] Angel MCX feed ready!')
except Exception as ae:
    log.warning(f'[V31] Angel MCX feed failed: {ae}')
    angel_mcx_feed=None

# Angel One Trader (primary broker)
try:
    from v31_angel_trader import angel_trader
    angel_trader.connect()
    log.info('[V31] Angel One trader ready!')
except Exception as ae:
    log.warning(f'[V31] Angel trader failed: {ae}')
    angel_trader=None
active_positions={}
active_positions={}
capital=50000  # Default fallback
trade_counter=0  # Counts live trades for auto-retrain

# ============================================================
# PAPER TRADING MODE
# True  = No real orders (safe testing)
# False = Real orders on Angel One
# ============================================================
PAPER_TRADE=True  # Change to False when ready for live!
paper_pnl={}  # Track paper trade results
from v31_risk_manager import V31RiskManager
risk_mgr=V31RiskManager(capital)

# Auto-fetch latest lot sizes
try:
    from v31_lot_fetcher import get_lot_sizes
    _fresh_lots=get_lot_sizes()
    LOT.update(_fresh_lots)
    log.info(f'[V31] Lot sizes updated: {LOT}')
except Exception as le:
    log.warning(f'[V31] Lot fetch failed, using defaults: {le}')
from v31_risk_manager import V31RiskManager
risk_mgr=V31RiskManager(capital)

def get_real_capital(kotak):
    """Fetch real capital from Kotak account"""
    try:
        for seg in ['FO','CASH','ALL']:
            limits=kotak.limits(segment=seg)
            if not limits:continue
            # Check for bridge error (night time)
            if limits.get('stCode')==300015:
                log.warning('[V31] Kotak bridge error (night?), using default capital')
                return 50000
            data=limits.get('data',{})
            if not data:continue
            cash=float(
                data.get('net',0) or
                data.get('availablecash',0) or
                data.get('cashmarginavailable',0) or
                data.get('marginused',0) or 0
            )
            if cash>1000:
                log.info(f'[V31] Capital from Kotak ({seg}): Rs.{cash:,.0f}')
                return round(cash)
        return 50000
    except Exception as e:
        log.warning(f'[V31] Capital fetch failed: {e}')
        return 50000

def get_lots(instrument,capital,sl_pts=None):
    from v30_lot_config import get_lots as base_lots
    return base_lots(instrument,capital)

def get_kotak_client():
    try:
        import pyotp
        from neo_api_client import NeoAPI
        totp=pyotp.TOTP("4GUPM2UMIUHNUGGD7DPAWO7J7A").now()
        client=NeoAPI(environment="prod",access_token=None,neo_fin_key=None,consumer_key="d425cd90-3afe-4d53-a5d1-1ce97279f184")
        client.totp_login(mobile_number="+918050220481",ucc="YIK0S",totp=totp)




        log.info("Kotak connected!")
        return client
    except Exception as e:
        log.error(f'Kotak login error: {e}')
        return None

def get_angel_client():
    try:
        import pyotp
        from SmartApi import SmartConnect
        obj=SmartConnect(api_key='pEOas0vU')
        totp=pyotp.TOTP('R2T2F2BMP56U44O4OMOYJZTFJI').now()
        obj.generateSession('J234619','1605',totp)
        return obj
    except Exception as e:
        log.error(f'Angel login error: {e}')
        return None

def load_candles(angel,instrument,tf=5):
    try:
        import json,os,time
        all_candles=[]
        token=TOKEN.get(instrument,'')
        for year in [2022,2023,2024]:
            for fname in [
                f'historical_data/{instrument}_{year}_5min.json',
                f'historical_data/{token}_{year}_5min.json'
            ]:
                if os.path.exists(fname):
                    all_candles.extend(json.load(open(fname)))
                    break
        now=datetime.now()
        if now.hour>=9 and now.weekday()<5:
            trade_day=now.strftime('%Y-%m-%d')
            try:
                params={
                    'exchange':'BSE' if instrument=='SENSEX' else
                              ('MCX' if instrument in ['CRUDEOIL','GOLDM','SILVERM','NATURALGAS'] else 'NSE'),
                    'symboltoken':TOKEN[instrument],
                    'interval':'FIVE_MINUTE' if tf==5 else 'FIFTEEN_MINUTE',
                    'fromdate':f'{trade_day} 09:00',
                    'todate':now.strftime('%Y-%m-%d %H:%M')
                }
                time.sleep(0.5)
                data=angel.getCandleData(params)
                if data and data.get('data'):
                    all_candles.extend(data['data'])
            except:pass
        if not all_candles:return None
        df=pd.DataFrame(all_candles)
        if len(df.columns)==6:
            df.columns=['time','open','high','low','close','volume']
        for col in ['open','high','low','close','volume']:
            df[col]=pd.to_numeric(df[col],errors='coerce')
        return df.dropna().reset_index(drop=True)
    except Exception as e:
        log.error(f'Candle load error {instrument}: {e}')
    return None

def place_trade_angel(angel,signal,capital):
    """Place trade via Angel One - supports NSE + MCX"""
    from v30_notify import send
    try:
        instrument=signal['instrument']
        action=signal['action']
        atr=signal.get('atr',50)
        price=signal.get('price',0)

        # Get lot size
        lots=get_lots(instrument,capital)
        qty=lots*LOT.get(instrument,75)

        # Capital check
        # Get real premium
        try:
            from v31_angel_options import search_option_token
            _opt='CE' if signal.get('action')=='BUY' else 'PE'
            _tok,_sym,_exch=search_option_token(angel.obj,instrument,float(signal.get('price',0)),_opt)
            if _tok:
                _ltp=angel.obj.ltpData(_exch,_sym,_tok)
                prem=float(_ltp['data'].get('ltp',0)) if _ltp and _ltp.get('data') else 0
            else:prem=0
        except:prem=0
        if not prem:prem=signal.get('real_prem',max(50,round(atr*0.9)))
        est_cost=prem*qty
        if capital<est_cost*1.2:
            log.warning(f'[ANGEL] Low capital: Rs.{capital:,}')
            return

        # Risk check (use lots not total qty)
        LOT_SIZES={'NIFTY':65,'BANKNIFTY':30,'SENSEX':20,'FINNIFTY':60,
                   'MIDCPNIFTY':120,'CRUDEOIL':100,'GOLDM':10,'SILVERM':30,
                   'NATURALGAS':1250,'LT':450,'NTPC':4500,'MARUTI':100,
                   'BHARTIARTL':950,'SBIN':1500,'TATAMOTORS':1350,
                   'RELIANCE':250,'HINDUNILVR':300,'TCS':150,'TATASTEEL':5500}
        _lot_size=LOT_SIZES.get(instrument,75)
        _n_lots=max(1,round(qty/_lot_size))
        signal_risk=signal.get('sl_points',50)*_lot_size*_n_lots
        can_trade,reason=risk_mgr.can_trade(capital,signal_risk)
        if not can_trade:
            log.warning(f'[ANGEL] Risk blocked: {reason} (risk=Rs.{signal_risk:.0f})')
            return

        # Paper trade or real trade
        if PAPER_TRADE:
            # Paper trade - Telegram already sent via notify_v31_entry
            log.info(f'[PAPER] {instrument} {action} 1 lot - notified via Telegram')
        else:
            # Real trade via Angel One - SAFE ORDER ENGINE
            if angel_trader and angel_trader.connected:
                try:
                    from v31_safe_order_engine import get_safe_engine
                    from v31_angel_options import search_option_token
                    engine=get_safe_engine(angel_trader.obj)

                    # Get option token
                    _opt='CE' if signal.get('action')=='BUY' else 'PE'
                    token,sym,exch=search_option_token(angel_trader.obj,instrument,
                        float(signal.get('price',0)),_opt)

                    if token:
                        # Add signal timestamp
                        signal['signal_time']=signal.get('signal_time',time.time())
                        order_id=engine.place_safe_order(
                            exch,sym,token,_qty,
                            signal.get('real_prem',0),signal,_opt
                        )
                        if order_id:
                            log.info(f'[ANGEL] Safe order placed! ID:{order_id}')
                        else:
                            log.warning(f'[ANGEL] Safe order failed for {instrument}')
                    else:
                        log.warning(f'[ANGEL] No token for {instrument}')
                except Exception as se:
                    log.error(f'[ANGEL] Safe engine error: {se}')
                    # Fallback to regular order
                    order_id=angel_trader.place_option_trade(signal,capital)
            else:
                log.warning('[ANGEL] Not connected!')
                send(f'⚠️ Angel One disconnected!\nCannot place {instrument} order!')

        # Track in active trades
        active_trades[instrument]={
            'signal':signal,
            'entry':price,
            'sl_points':signal['sl_points'],
            'target1':signal['target1'],
            'target2':signal['target2'],
            'action':action,
            'lots':lots,'qty':qty,
            't1_hit':False,
            'entry_time':str(datetime.now()),
            'broker':'ANGEL'
        }
        global trade_counter,paper_pnl
        trade_counter+=1

        # Track paper trade P&L
        if PAPER_TRADE:
            paper_pnl[instrument]={
                'entry':price,
                'sl':signal.get('sl_points',0),
                'target':signal.get('target2',0),
                'action':action,
                'qty':qty,
                'time':str(datetime.now())
            }

    except Exception as e:
        log.error(f'[ANGEL] Trade error: {e}')

def place_trade(client,signal,capital):
    from v30_notify import send
    try:
        instrument=signal['instrument']
        action=signal['action']
        sl_pts=signal['sl_points']
        option_type=signal.get('option_type','CE' if action=='BUY' else 'PE')
        lots=get_lots(instrument,capital,sl_pts)
        qty=lots*LOT.get(instrument,75)

        # Capital check before placing order
        atr=signal.get('atr',50)
        est_premium=max(60,min(350,round(atr*0.9)))
        est_cost=est_premium*qty
        signal_risk=signal.get('sl_points',50)*qty

        # Full risk check
        can_trade,reason=risk_mgr.can_trade(capital,signal_risk)
        if not can_trade:
            send(f"""⚠️ <b>TRADE BLOCKED</b>
━━━━━━━━━━━━━━━
📊 {instrument}
🚫 Rule: {reason}
💰 Capital: Rs.{capital:,.0f}
📊 Daily PnL: Rs.{risk_mgr.daily_pnl:,.0f}
📉 Losses today: {risk_mgr.daily_losses}
⏰ {datetime.now().strftime("%H:%M:%S")}""")
            log.warning(f'[V31] Blocked: {reason}')
            return
        if reason=='REDUCE_SIZE':
            lots=max(1,lots//2)
            qty=lots*LOT.get(instrument,75)
            log.info(f'[V31] Lots reduced to {lots}')

        if capital<est_cost*1.2:
            msg=f"""❌ <b>ORDER SKIPPED - Low Capital</b>
━━━━━━━━━━━━━━━
📊 {instrument} {option_type}
💰 Capital: Rs.{capital:,.0f}
💸 Required: Rs.{est_cost*1.2:,.0f}
📉 Premium: Rs.{est_premium} × {qty} = Rs.{est_cost:,.0f}
⚠️ Add funds to trade!
⏰ {datetime.now().strftime("%H:%M:%S")}"""
            send(msg)
            log.warning(f'[V31] Skipped {instrument}: Low capital')

            # Still save signal for ML learning!
            try:
                import json,os
                sig_data={
                    'timestamp':str(datetime.now()),
                    'instrument':instrument,
                    'action':signal.get('action',''),
                    'score':signal.get('score',0),
                    'regime':signal.get('regime',''),
                    'hour':datetime.now().hour,
                    'ml_prob':signal.get('ml_prob',0.5),
                    'rr':signal.get('rr_ratio',2),
                    'sl_atr':signal.get('sl_points',50)/max(atr,1),
                    'skipped':True,
                    'skip_reason':'LOW_CAPITAL',
                    'outcome':None  # Will be updated by simulator
                }
                fname=f'ml_models/{instrument}_v31_skipped_signals.json'
                existing=json.load(open(fname)) if os.path.exists(fname) else []
                existing.append(sig_data)
                json.dump(existing,open(fname,'w'))

                # Add to active_trades for simulation only
                active_trades[f'{instrument}_SIM']={
                    'signal':signal,
                    'entry':signal['price'],
                    'sl_points':signal['sl_points'],
                    'target1':signal['target1'],
                    'target2':signal['target2'],
                    'action':signal.get('action',''),
                    'lots':0,'qty':0,  # 0 = simulation only
                    't1_hit':False,
                    'entry_time':str(datetime.now()),
                    'simulation':True  # Flag = no real order!
                }
                log.info(f'[V31] {instrument} saved for ML learning (simulation)')
            except Exception as e:
                log.error(f'[V31] Save skipped signal error: {e}')
            return

        from v31_notify import (notify_v31_startup,notify_v31_entry,
    notify_v31_exit,notify_v31_daily_summary,notify_v31_gamma_alert)
        msg=f"""🚀 <b>V31 TRADE ENTRY</b>
━━━━━━━━━━━━━━━
📊 {instrument} {option_type}
📈 Action: {action}
💵 Entry: {signal['price']:.1f}
🛑 SL: {sl_pts:.1f} pts ({signal['sl_type']})
🎯 T2: {signal['target2']:.1f} pts (1:{signal['rr_ratio']:.1f})
📦 Lots: {lots} | Qty: {qty}
🧠 Score: {signal['score']}/26
📊 Regime: {signal['regime']}
💧 Liq: {signal['liq_type']}
⚡ Imbalance: {signal['imbalance_type']}
🎰 Gamma: +{signal['gamma_boost']}
⏰ {datetime.now().strftime('%H:%M:%S')}"""
        send(msg)
        log.info(f'[V31] TRADE: {instrument} {action} Score:{signal["score"]} RR:1:{signal["rr_ratio"]:.1f}')

        active_trades[instrument]={
            'signal':signal,
            'entry':signal['price'],
            'sl_points':sl_pts,
            'target1':signal['target1'],
            'target2':signal['target2'],
            'action':action,
            'lots':lots,'qty':qty,
            'use_trailing':signal.get('use_trailing',False),
            't1_hit':False,
            'entry_time':str(datetime.now()),
            'features':None
        }
        # Increment trade counter
        global trade_counter,paper_pnl
        trade_counter+=1

        # Track paper trade P&L
        if PAPER_TRADE:
            paper_pnl[instrument]={
                'entry':price,
                'sl':signal.get('sl_points',0),
                'target':signal.get('target2',0),
                'action':action,
                'qty':qty,
                'time':str(datetime.now())
            }
        log.info(f'[V31] Trade #{trade_counter} (every 50)')
        # Every 50 trades = incremental retrain
        if trade_counter%50==0:
            log.info(f'[V31] 50 trades done! Starting incremental retrain...')
            import threading
            def do_retrain():
                try:
                    from v31_ml_engine import retrain_from_signals
                    sig_file=f'ml_models/{instrument}_v31_all_signals.json'
                    if os.path.exists(sig_file):
                        import json
                        sigs=json.load(open(sig_file))
                        retrain_from_signals(instrument,sigs)
                        log.info(f'[V31] Incremental retrain done for {instrument}!')
                        from v30_notify import send
                        send(f'🔄 V31 Incremental Retrain\n{instrument} model updated!\nTrade #{trade_counter} (every 50)')
                except Exception as e:
                    log.error(f'[V31] Retrain error: {e}')
            threading.Thread(target=do_retrain,daemon=True).start()
    except Exception as e:
        log.error(f'[V31] Trade error: {e}')

def manage_trades(feed):
    # Handle simulation trades (skipped due to low capital)
    sim_keys=[k for k in active_trades if k.endswith('_SIM')]
    for sim_key in sim_keys:
        trade=active_trades[sim_key]
        instrument=sim_key.replace('_SIM','')
        try:
            df5=feed.get_candles(instrument,'5')
            if df5 is None or len(df5)<2:continue
            row=df5.iloc[-1]
            entry=trade['entry']
            sl=trade['sl_points']
            t2=trade['target2']
            action=trade['action']
            outcome=None

            if action=='BUY':
                if float(row['low'])<=entry-sl:outcome=0
                elif float(row['high'])>=entry+t2:outcome=1
            else:
                if float(row['high'])>=entry+sl:outcome=0
                elif float(row['low'])<=entry-t2:outcome=1

            if outcome is not None:
                # Save outcome to ML
                import json,os
                fname=f'ml_models/{instrument}_v31_skipped_signals.json'
                if os.path.exists(fname):
                    sigs=json.load(open(fname))
                    for s in reversed(sigs):
                        if s.get('outcome') is None:
                            s['outcome']=outcome
                            break
                    json.dump(sigs,open(fname,'w'))
                result='WIN' if outcome==1 else 'LOSS'
                log.info(f'[SIM] {instrument} simulation {result}')
                del active_trades[sim_key]
        except:pass

    global capital
    global capital
    now=datetime.now()
    now=datetime.now()
    force_exit=now.hour==15 and now.minute>=10

    for instrument in list(active_trades.keys()):
        # Skip feature storage and simulation keys
        if instrument.endswith('_feat') or instrument.endswith('_SIM'):
            continue
        trade=active_trades[instrument]
        try:
            df5=feed.get_candles(instrument,'5')
            if df5 is None:continue
            current=float(df5['close'].iloc[-1])
            entry=trade['entry']
            action=trade['action']
            sl_pts=trade['sl_points']
            t1=trade['target1']
            t2=trade['target2']
            qty=trade['qty']
            pnl=0;reason=''

            if action=='BUY':
                if not trade['t1_hit'] and current>=entry+t1:
                    trade['t1_hit']=True
                    trade['sl_points']=0
                    log.info(f'[V31] {instrument} T1 hit! SL moved to breakeven')
                if current<=entry-sl_pts and not trade['t1_hit']:
                    pnl=-(sl_pts*qty);reason='SL'
                elif current>=entry+t2:
                    pnl=t2*qty;reason='T2'
                elif force_exit:
                    pnl=(current-entry)*qty;reason='EOD'
            else:
                if not trade['t1_hit'] and current<=entry-t1:
                    trade['t1_hit']=True
                    trade['sl_points']=0
                if current>=entry+sl_pts and not trade['t1_hit']:
                    pnl=-(sl_pts*qty);reason='SL'
                elif current<=entry-t2:
                    pnl=t2*qty;reason='T2'
                elif force_exit:
                    pnl=(entry-current)*qty;reason='EOD'

            if reason:
                net=pnl-25  # Brokerage
                capital+=net
                del active_trades[instrument]
                signal_cooldown.pop(instrument,None)

                # CRL outcome update
                try:
                    from v31_constrained_rl import crl_update_outcome
                    crl_update_outcome(
                        instrument,
                        trade.get('signal',{}),
                        trade.get('features',[]),
                        pnl,capital)
                except:pass

                # Update causal engine with outcome
                try:
                    from v31_causal_engine_v2 import update_trade,get_auto_adjustments
                    _tid=trade.get('signal',{}).get('trade_id','')
                    if _tid:
                        update_trade(
                            _tid,
                            result='WIN' if pnl>0 else 'LOSS',
                            pnl=pnl,
                            exit_reason=reason,
                            entry_price=trade.get('entry',0),
                            exit_price=current,
                            sl_pts=trade.get('sl_points',50)
                        )
                        # Auto-adjust filters every 20 trades
                        if trade_counter%20==0:
                            get_auto_adjustments(instrument)
                except:pass

                # Save for ML learning
                outcome=1 if pnl>0 else 0
                if trade.get('features'):
                    from v31_ml_engine import save_trade_result
                    save_trade_result(instrument,trade['features'],outcome,net)

                from v31_notify import (notify_v31_startup,notify_v31_entry,
    notify_v31_exit,notify_v31_daily_summary,notify_v31_gamma_alert)
                emoji='✅' if pnl>0 else '❌'
                send(f"""{emoji} <b>V31 TRADE EXIT</b>
━━━━━━━━━━━━━━━
📊 {instrument} | {reason}
{'📈' if pnl>0 else '📉'} PnL: {'+'if pnl>0 else ''}₹{net:,.0f}
💰 Capital: ₹{capital:,.0f}
⏰ {datetime.now().strftime('%H:%M:%S')}""")
                log.info(f'[V31] EXIT {instrument} {reason} PnL:₹{net:,.0f}')
        except Exception as e:
            log.error(f'[V31] Manage error {instrument}: {e}')

async def daily_reset():
    while True:
        now=datetime.now()
        next_reset=now.replace(hour=9,minute=0,second=0,microsecond=0)
        if now>=next_reset:next_reset+=timedelta(days=1)
        await asyncio.sleep((next_reset-now).total_seconds())
        active_trades.clear()
        log.info('[V31] Daily reset done!')

async def main():
    global capital
    log.info('='*50)
    log.info('  KAIROS V31 - GAMMA WALL + SMC SYSTEM')
    log.info('='*50)

    # Connect
    kotak=get_kotak_client()
    angel=get_angel_client()

    if not kotak:
        log.error('Kotak connection failed!')
        return


    # Fetch real capital from Kotak (once on startup)
    global capital
    real_cap=get_real_capital(kotak)
    if real_cap>1000:
        log.info(f'[V31] Real capital: Rs.{real_cap:,}')
        capital=real_cap
    capital_logged=True
    # Load capital
    try:
        from v30_risk import DailyRiskManager
        rm=DailyRiskManager(capital)
    except:pass

    # Load feed
    from v30_feed import MarketDataFeed
    feed=MarketDataFeed(kotak)
    try:
        from v30_feed import patch_feed
        patch_feed(feed)
    except:pass

    # Load historical candles from LOCAL FILES (no API calls!)
    import json as _json,pandas as _pd,os as _os
    _TOKENS={'NIFTY':'99926000','BANKNIFTY':'99926009','SENSEX':'99919000','FINNIFTY':'99926037','MIDCPNIFTY':'99926074','CRUDEOIL':'472790','GOLDM':'477904','SILVERM':'457533','LT':'11483','NTPC':'11630','MARUTI':'10999','BHARTIARTL':'10604','SBIN':'3045','TATAMOTORS':'3456','RELIANCE':'2885','HINDUNILVR':'1394','TCS':'11536','TATASTEEL':'3499','NATURALGAS':'475111'}
    log.info('Loading historical candles...')
    for inst in INSTRUMENTS:
        try:
            token=_TOKENS.get(inst,'')
            all_candles=[]
            for year in [2022,2023,2024,2025,2026]:
                for fname in [
                    f'historical_data/{inst}_{year}_5min.json',
                    f'historical_data/{token}_{year}_5min.json'
                ]:
                    if _os.path.exists(fname):
                        all_candles.extend(_json.load(open(fname)))
                        break
            if not all_candles:
                continue
            df5=_pd.DataFrame(all_candles)
            if len(df5.columns)==6:
                df5.columns=['time','open','high','low','close','volume']
            for col in ['open','high','low','close','volume']:
                df5[col]=_pd.to_numeric(df5[col],errors='coerce')
            df5=df5.dropna().reset_index(drop=True)
            df15=df5.iloc[::3].copy()
            log.info(f'  {inst}: {len(df5)} candles loaded')
            # Load into feed builders - use LATEST candles!
            if inst in feed.builders:
                df5_sorted=df5.sort_values('time').tail(500)
                for _,row in df5_sorted.iterrows():
                    feed.builders[inst]['5'].candles.append({
                        'time':str(row['time']),
                        'open':float(row['open']),
                        'high':float(row['high']),
                        'low':float(row['low']),
                        'close':float(row['close']),
                        'volume':float(row['volume'])
                    })
                df15_sorted=df15.sort_values('time').tail(200)
                for _,row in df15_sorted.iterrows():
                    feed.builders[inst]['15'].candles.append({
                        'time':str(row['time']),
                        'open':float(row['open']),
                        'high':float(row['high']),
                        'low':float(row['low']),
                        'close':float(row['close']),
                        'volume':float(row['volume'])
                    })
        except Exception as ie:
            log.error(f'[V31] Load error {inst}: {ie}')
    from v30_cache import preload_cache
    preload_cache()
    feed.start()
    log.info('[V31] LIVE! Websocket connected')

    # Notify startup
    from v31_notify import (notify_v31_startup,notify_v31_entry,
    notify_v31_exit,notify_v31_daily_summary,notify_v31_gamma_alert)
    notify_v31_startup(capital)

    asyncio.create_task(daily_reset())

    log.info('[V31] Starting main scan loop...')
    _last_capital_refresh=0
    log.info(f'[V31] Python version check OK')
    # Test market check
    try:
        from v30_holiday import is_market_open
        ok,reason=is_market_open()
        log.info(f'[V31] Market status: {ok} {reason}')
    except Exception as me:
        log.error(f'[V31] Market check error: {me}')
    log.info('[V31] Entering while loop...')
    while True:
        try:
            log.info('[V31] Loop iteration start')
            from v30_holiday import is_market_open
            ok,reason=is_market_open()
            if not ok:
                if not getattr(main,'_closed_sent',False):
                    from v30_notify import send
                    send(f"🏖 <b>Market Closed</b>\n{reason}\n⏰ V31 resumes Monday 9:15 AM")
                    main._closed_sent=True
                log.info(f"[V31] {reason} - no trading")
                await asyncio.sleep(3600)
                continue

            now=datetime.now()

            # Holiday check
            _nse_hol=_mcx_hol=False
            try:
                from v31_holidays import is_nse_holiday,is_mcx_holiday
                _nse_hol,_=is_nse_holiday(now.date())
                _mcx_hol,_=is_mcx_holiday(now.date())
            except:pass

            # Trading hours
            NSE_HOURS=list(range(9,15))
            nse_open=now.hour in NSE_HOURS and now.weekday()<5
            # MCX: 9AM to 11:30PM only
            # MCX opens 9 AM, but trade only after 3:30 PM (after NSE close)
            # Reason: Focus on NSE during market hours, MCX after close
            mcx_trade_start=15
            mcx_open=(
                (mcx_trade_start<=now.hour<23 or (now.hour==23 and now.minute<30))
                and now.weekday()<5
                and not _mcx_hol
            )

            if not nse_open and not mcx_open:
                await asyncio.sleep(60)
                continue

            if now.hour==9 and now.minute<15:
                await asyncio.sleep(60)
                continue

            # Refresh capital every hour
            import time as _time
            if _time.time()-_last_capital_refresh>3600:
                try:
                    if angel_trader and angel_trader.connected:
                        rms=angel_trader.obj.rmsLimit()
                        if rms and rms.get('data'):
                            capital=float(rms['data'].get('availablecash',capital) or capital)
                            log.info(f'[ANGEL] Available margin: Rs.{capital:,.0f}')
                    _last_capital_refresh=_time.time()
                except:pass

            for inst_idx,instrument in enumerate(INSTRUMENTS):
                if inst_idx>0:
                    import time as _sleep_time
                    _sleep_time.sleep(1.5)

                inst_cfg=_INST_CONFIG.get(instrument,{})
                inst_type=inst_cfg.get('type','STOCK')

                # Route MCX vs NSE
                MCX_INST=[k for k,v in _INST_CONFIG.items() if v.get('type')=='COMMODITY']
                if instrument in MCX_INST:
                    if not mcx_open:continue
                else:
                    if not nse_open:continue

                try:
                    # Load candles
                    if instrument in MCX_INST and angel_mcx_feed:
                        df5=angel_mcx_feed.get_candles(instrument,5)
                        df15=angel_mcx_feed.get_candles(instrument,15)
                        df_daily=df15
                    else:
                        df5=load_candles(angel,instrument,5)
                        df15=load_candles(angel,instrument,15)
                        df_daily=df15

                    if df5 is None or len(df5)<30:continue
                    if df15 is None or len(df15)<10:continue

                    # Skip GOLDM/SILVERM unless near expiry
                    if instrument in ['GOLDM','SILVERM'] and capital<200000:
                        try:
                            from v31_angel_options import get_expiry_str
                            import datetime as _expdt
                            _exp=get_expiry_str(instrument)
                            _exp_dt=_expdt.datetime.strptime(_exp,'%d%b%y')
                            _days=(_exp_dt.date()-_expdt.datetime.now().date()).days
                            if _days>10:
                                _est_cost=capital*0.4
                                log.info(f'[V31] {instrument} skipped - {_days}d to expiry, need Rs.{_est_cost:,.0f}')
                                continue
                        except:
                            continue

                    # Skip CRUDEOIL if too expensive
                    if instrument=='CRUDEOIL':
                        try:
                            from v31_angel_options import get_expiry_str
                            import datetime as _expdt
                            _exp=get_expiry_str(instrument)
                            _exp_dt=_expdt.datetime.strptime(_exp,'%d%b%y')
                            _days=(_exp_dt.date()-_expdt.datetime.now().date()).days
                            if _days>10 and capital<150000:
                                log.info(f'[V31] CRUDEOIL skipped - {_days}d to expiry, need Rs.1.5L')
                                continue
                        except:pass

                    # Signal Manager daily limit check
                    from v31_signal_manager import signal_manager
                    if signal_manager._get_daily_total(instrument)>=8:
                        log.info(f'[V31] {instrument} max signals reached today (2)')
                        continue

                    # Generate signal (Path A)
                    from v31_strategy import generate_v31_signal,notify_v31_signal
                    signal=generate_v31_signal(
                        df5,df15,df_daily,
                        instrument,capital,feed,kotak
                    )

                    # Path B: VWAP Rejection
                    if not signal:
                        try:
                            from v31_strategy import vwap_rejection_signal
                            _atr=float((df5["high"]-df5["low"]).tail(14).mean())
                            signal=vwap_rejection_signal(df5,instrument,_atr)
                            if signal:
                                signal["timestamp"]=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                log.info(f"[V31] {instrument} PATH B VWAP Score:{signal['score']}")
                        except Exception as _ve:
                            log.debug(f"[V31] VWAP err: {_ve}")

                    # Path C: ORB Breakout
                    if not signal and ENABLE_PATH_CD:
                        try:
                            from v31_strategy_orb import orb_signal
                            signal=orb_signal(df5,instrument,capital)
                            if signal:
                                signal['timestamp']=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                log.info(f'[V31] {instrument} PATH C ORB Score:{signal["score"]}')
                        except Exception as _oe:
                            log.debug(f'[V31] ORB err: {_oe}')

                    # Path D: Supertrend
                    if not signal and ENABLE_PATH_CD:
                        try:
                            from v31_strategy_orb import supertrend_signal
                            signal=supertrend_signal(df5,instrument)
                            if signal:
                                signal['timestamp']=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                log.info(f'[V31] {instrument} PATH D ST Score:{signal["score"]}')
                        except Exception as _se:
                            log.debug(f'[V31] ST err: {_se}')

                    if not signal:continue

                    log.info(f'[V31] SIGNAL: {instrument} {signal.get("action")} Score:{signal.get("score")} RR:1:{signal.get("rr_ratio")} SL:{signal.get("sl_points",0):.1f}({signal.get("sl_type","")}) Liq:{signal.get("liq_type","")} Gamma:{signal.get("gamma_boost",0)}')

                    # Expiry safety
                    try:
                        from v31_angel_options import get_expiry_str
                        import datetime as _expdt2
                        _exp_str=get_expiry_str(instrument)
                        _exp_dt=_expdt2.datetime.strptime(_exp_str,'%d%b%y')
                        _days_to_exp=(_exp_dt.date()-_expdt2.datetime.now().date()).days
                        if _days_to_exp==0:
                            log.info(f'[V31] {instrument} EXPIRY TODAY - skipping!')
                            continue
                        elif _days_to_exp==1:
                            log.info(f'[V31] {instrument} expiry tomorrow - extra caution')
                    except:pass

                    # Causal engine
                    try:
                        from v31_causal_engine_v2 import causal_engine_v2
                        causal_engine_v2.log_trade(instrument,signal)
                    except:pass

                    # ML filter
                    try:
                        from v31_ml_engine import (extract_v31_features,get_v31_ml_prob)
                        atr=float((df5['high']-df5['low']).tail(14).mean())
                        features=extract_v31_features(
                            df5,df15,signal['action'],
                            signal['regime'],signal['liq_type'],
                            signal['imbalance_type']!='',
                            False,signal['gamma_boost'],
                            signal['rr_ratio'],signal['sl_points'],atr
                        )
                        if features:
                            regime=signal.get('regime','TRENDING')
                            prob=get_v31_ml_prob(instrument,features,regime)
                            signal['ml_prob']=prob
                    except Exception as _mle:
                        log.debug(f'[V31 ML] Features error: {_mle}')

                    # Online Learning
                    try:
                        from v31_online_learning import online_learner
                        _ol_prob=online_learner.predict(instrument,signal)
                        signal['ol_prob']=_ol_prob
                    except:pass

                    # Adaptive weighting
                    try:
                        _ml_p=signal.get('ml_prob',0.5)
                        _ol_p=signal.get('ol_prob',0.5)
                        _w_ml=0.5;_w_ol=0.5
                        _final_p=_ml_p*_w_ml+_ol_p*_w_ol
                        signal['adaptive_prob']=_final_p
                        log.info(f'[ADAPTIVE] {instrument}: ml={_ml_p:.2f}({_w_ml}) online={_ol_p:.2f}({_w_ol}) final={_final_p:.2f}')
                    except:pass

                    # Uncertainty
                    try:
                        from v31_uncertainty import estimate_uncertainty
                        unc=estimate_uncertainty(instrument,signal)
                        signal['uncertainty']=unc
                        unc_val=unc.get('uncertainty',0.5) if isinstance(unc,dict) else 0.5
                        unc_thresh=0.40
                        log.info(f'[UNC] {instrument}: conf={1-unc_val:.2f} unc={unc_val:.2f}')
                        if unc_val>unc_thresh:
                            log.info(f'[V31] {instrument} UNCERTAINTY blocked ({unc_val:.2f}>{unc_thresh})')
                            continue
                    except:pass

                    # MMT
                    try:
                        from v31_mmt import mmt_filter
                        _mmt_p=mmt_filter.predict(instrument,df5,signal)
                        signal['mmt_prob']=_mmt_p
                        log.info(f'[MMT] {instrument} models built!')
                    except:pass

                    # Dynamic Ensemble
                    try:
                        from v31_dynamic_ensemble import dynamic_ensemble
                        _ml_p=signal.get('ml_prob',0.5)
                        _meta_p=signal.get('adaptive_prob',0.5)
                        _mmt_p=signal.get('mmt_prob',0.5)
                        _crl_ok=True
                        ensemble_result=dynamic_ensemble.get_ensemble_prob(
                            instrument,_ml_p,_meta_p,_mmt_p,_crl_ok
                        )
                        ensemble_prob=ensemble_result.get('prob',0.5) if isinstance(ensemble_result,dict) else float(ensemble_result)
                        ens_details=ensemble_result.get('details',{}) if isinstance(ensemble_result,dict) else {}
                        signal['ensemble_prob']=ensemble_prob
                        signal['ens_details']=ens_details
                        log.info(f'[V31] {instrument} ENSEMBLE={ensemble_prob:.2f} details={ens_details}')

                        trained=[f for f in __import__('os').listdir('ml_models') if f.endswith('.pkl')]
                        ens_thresh=0.35 if len(trained)>=10 else 0.25
                        if ensemble_prob<ens_thresh:
                            log.info(f'[V31] {instrument} ENSEMBLE blocked ({ensemble_prob:.2f})<{ens_thresh}')
                            continue

                        # LOW AGREEMENT filter (disabled until training complete)
                        if False:  # Disabled until training complete
                            _agree=[v.get('prob',0.5) for v in ens_details.values() if isinstance(v,dict)]
                            _agr_pct=sum(1 for p in _agree if p>0.5)/len(_agree) if _agree else 1.0
                            if _agr_pct<0.40:
                                log.info(f'[V31] {instrument} LOW AGREEMENT blocked ({_agr_pct:.0%})')
                                continue

                    except Exception as ee:
                        log.debug(f'[V31] Ensemble err: {ee}')

                    # Online learner update
                    try:
                        from v31_online_learning import online_learner
                        online_learner.update(instrument,signal)
                        log.info(f'[OL] {instrument} new model created!')
                    except:pass

                    # CRL
                    try:
                        from v31_constrained_rl import crl_agent
                        _crl=crl_agent.should_trade(instrument,signal)
                        if not _crl:
                            log.info(f'[V31] {instrument} CRL blocked')
                            continue
                    except:pass

                    # Execution optimizer
                    try:
                        from v31_execution_optimizer import optimize_execution
                        _unc=signal.get('uncertainty',{})
                        _qty_tmp=1
                        exec_params=optimize_execution(
                            instrument,df5,signal,
                            signal.get('atr',50),
                            _qty_tmp,_unc,capital
                        )
                        if exec_params.get('optimal_qty',0)>0:
                            pass
                        signal['exec_params']=exec_params
                        log.info(f'[EXEC] {instrument} order type: {exec_params.get("order_type")} ({exec_params.get("reason","")})')
                    except:pass

                    # Signal Manager V2 - 7-step check
                    _action=signal.get('action','BUY')
                    _score=signal.get('score',18)
                    try:
                        _sm_ok,_sm_reason=signal_manager.can_trade(instrument,_action,_score)
                        if not _sm_ok:
                            log.info(f'[SM] {instrument} BLOCKED: {_sm_reason}')
                            try:
                                from v31_trade_logger import log_decision
                                log_decision(instrument,signal,'BLOCKED',_sm_reason)
                            except:pass
                            continue
                        log.info(f'[SM] {instrument} {_action} ALLOWED: {_sm_reason}')
                    except Exception as _sme:
                        log.debug(f'[SM] Error: {_sme}')

                    _price=float(signal.get('price',0))

                    # Lot sizing
                    try:
                        from v30_lot_config import get_lots_kelly
                        _ml_p=signal.get('ml_prob',0.5)
                        _rr=signal.get('rr_ratio',2.0)
                        _prem=signal.get('real_prem',50)
                        _lots=get_lots_kelly(instrument,capital,_ml_p,_rr,_prem)
                    except:
                        _lots=get_lots(instrument,capital)
                    _lots=1  # Hard cap: 1 lot for safety!
                    _qty=_lots

                    signal_cooldown[instrument]=_dt.datetime.now().timestamp()
                    signal['signal_time']=_time.time()

                    # Record in Signal Manager
                    try:
                        signal_manager.record_trade(instrument,_action)
                    except:pass

                    # Log decision
                    try:
                        from v31_trade_logger import log_decision
                        log_decision(instrument,signal,'TAKEN','All filters passed')
                    except:pass

                    # Get option result for tracking
                    _opt_result=None
                    try:
                        from v31_option_engine import get_option
                        _opt_type='CE' if signal.get('action')=='BUY' else 'PE'
                        _opt_result=get_option(instrument,float(signal.get('price',0)),_opt_type)
                    except:pass

                    # Liquidity check
                    _is_liquid=True
                    try:
                        if _opt_result and angel_trader and angel_trader.connected:
                            from v31_option_engine import is_liquid
                            _prem=signal.get('real_prem',0)
                            if _prem>0:
                                _is_liquid=is_liquid(
                                    angel_trader.obj,
                                    _opt_result.get('segment','NFO'),
                                    _opt_result.get('symbol',''),
                                    _opt_result.get('token',''),
                                    _prem
                                )
                                if not _is_liquid:
                                    log.info(f'[V31] {instrument} ILLIQUID - skipping order!')
                    except:pass

                    # NOTIFY TELEGRAM
                    notified=notify_v31_entry(signal,_qty,instrument)
                    if not notified:
                        log.info(f'[V31] {instrument} skipped by notify (too expensive)')
                        try:
                            from v31_trade_logger import log_decision
                            log_decision(instrument,signal,'BLOCKED','TOO_EXPENSIVE')
                        except:pass
                        continue

                    # Track position
                    try:
                        from v31_exit_monitor import exit_monitor
                        _prem=signal.get('real_prem',0)
                        if _prem>0 and _opt_result and _is_liquid:
                            exit_monitor.add_position(signal,_qty,_prem,_opt_result)
                    except:pass

                    # Execute trade
                    try:
                        from v31_angel_trader import angel_trader,place_trade_angel
                        if PAPER_TRADE:
                            log.info(f'[PAPER] {instrument} {_action} 1 lot - notified via Telegram')
                        else:
                            if angel_trader and angel_trader.connected:
                                order_id=place_trade_angel(signal,_qty,capital,instrument,angel_trader)
                                if order_id:
                                    log.info(f'[ANGEL] Order placed! ID:{order_id}')
                                else:
                                    log.warning(f'[ANGEL] Order failed for {instrument}')
                            else:
                                log.warning('[ANGEL] Not connected!')
                    except Exception as _exe:
                        log.error(f'[ANGEL] Execute error: {_exe}')

                    # Sell strategy check
                    try:
                        if capital>=100000:
                            from v31_options_sell import run_sell_strategy
                            run_sell_strategy(instrument,df5,df15,capital,angel_trader)
                    except Exception as _se:
                        log.debug(f'[SELL] Signal error {instrument}: {_se}')

                except Exception as _scan_e:
                    log.error(f'[V31] Error {instrument}: {_scan_e}')
                    import traceback
                    log.debug(traceback.format_exc())

            await asyncio.sleep(60)

        except Exception as _loop_e:
            log.error(f'[V31] Main loop error: {_loop_e}')
            await asyncio.sleep(30)

if __name__=='__main__':
    import asyncio
    asyncio.run(main())
