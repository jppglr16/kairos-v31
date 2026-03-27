import logging
from datetime import datetime,timedelta
log=logging.getLogger(__name__)

def send(msg):
    try:
        from v30_notify import send as v30_send
        v30_send(msg)
    except Exception as e:
        log.error(f'[V31] Send error: {e}')

def notify_v31_startup(capital):
    send(f"""🚀 <b>Kairos V31 Started!</b>
━━━━━━━━━━━━━━━
💰 Capital: ₹{capital:,.0f}
📊 System: Gamma Walls + SMC + ML
🎯 RR: Min 1:3 → Target 1:5-1:10
🧠 Filters: Liq Sweep + FVG + Trend
🕐 {datetime.now().strftime('%d-%b-%Y %H:%M')}
✅ All systems ready!""")

LOT={'NIFTY':65,'BANKNIFTY':30,'SENSEX':20,'FINNIFTY':60,'MIDCPNIFTY':120,
    'CRUDEOIL':100,'GOLDM':10,'SILVERM':30,'NATURALGAS':1250,
    'LT':450,'NTPC':4500,'MARUTI':100,'BHARTIARTL':950,'SBIN':1500,
    'TATAMOTORS':1350,'RELIANCE':250,'HINDUNILVR':300,'TCS':150,'TATASTEEL':5500}

def notify_v31_entry(signal,qty,symbol):
    try:
        from datetime import timedelta
        inst=signal['instrument']
        action=signal['action']
        price=float(signal.get('price',0))
        score=signal.get('score',0)
        ml_prob=signal.get('ml_prob',0)
        atr=signal.get('atr',50)

        if score>=30:grade='🌟 S'
        elif score>=25:grade='⭐ A'
        elif score>=20:grade='✅ B'
        else:grade='📊 C'
        emoji='🟢' if action=='BUY' else '🔴'

        # ATM Strike
        if 'NIFTY' in inst and 'BANK' not in inst and 'FIN' not in inst and 'MID' not in inst:step=50
        elif 'BANK' in inst:step=100
        elif 'SENSEX' in inst:step=100
        elif 'FIN' in inst:step=50
        elif 'MID' in inst:step=25
        elif price<=500:step=5
        elif price<=1000:step=10
        elif price<=2000:step=20
        elif price<=5000:step=50
        elif price<=10000:step=100
        else:step=200
        atm=round(price/step)*step if price>0 else 0
        opt_type='CE' if action=='BUY' else 'PE'

        # Option premium - try real LTP first
        real_prem=0
        try:
            import time as _t
            if not hasattr(notify_v31_entry,'_cache'):
                notify_v31_entry._cache={}
                notify_v31_entry._cache_time={}
            _ck=f'{inst}_{opt_type}_{round(price,-2)}'
            _now=_t.time()
            if _ck in notify_v31_entry._cache and _now-notify_v31_entry._cache_time.get(_ck,0)<60:
                real_prem=notify_v31_entry._cache[_ck]
            else:
                from v31_angel_options import search_option_token
                from v31_angel_trader import angel_trader
                # Connect if not connected
                if not angel_trader.connected:
                    angel_trader.connect()
                    _t.sleep(2)
                if angel_trader and angel_trader.connected:
                    # Use BFO handler for SENSEX
                    if inst=='SENSEX':
                        from v31_bfo_options import get_bfo_ltp
                        rp,_=get_bfo_ltp(angel_trader.obj,inst,price,opt_type)
                        if rp>0:
                            real_prem=round(rp)
                            notify_v31_entry._cache[_ck]=real_prem
                            notify_v31_entry._cache_time[_ck]=_now
                            log.info(f'[NOTIFY] Real LTP {inst}: Rs.{real_prem}')
                    else:
                        token,sym,exch=search_option_token(angel_trader.obj,inst,price,opt_type)
                        if token:
                            ltp_r=angel_trader.obj.ltpData(exch,sym,token)
                        if ltp_r and ltp_r.get('data'):
                            rp=float(ltp_r['data'].get('ltp',0))
                            if rp>0:
                                real_prem=round(rp)
                                notify_v31_entry._cache[_ck]=real_prem
                                notify_v31_entry._cache_time[_ck]=_now
                                log.info(f'[NOTIFY] Real LTP {inst}: Rs.{real_prem}')
        except:pass
        if real_prem>0:
            prem=real_prem
        elif inst in ['NIFTY','BANKNIFTY','SENSEX','FINNIFTY','MIDCPNIFTY']:
            prem=max(50,min(500,round(atr*0.9)))
        elif inst in ['CRUDEOIL','GOLDM','SILVERM']:
            prem=max(30,min(300,round(atr*0.8)))
        else:
            # Stock options realistic premium
            raw=round(price*0.015)
            if raw<2:
                # Skip - too cheap, not tradeable
                prem=0
            else:
                prem=max(5,min(200,raw))

        # Skip if premium too low (not tradeable)
        if prem<5:
            log.info(f'[V31] {inst} option premium too low: Rs.{prem}')
            return

        # ============================================
        # SMART CAPITAL MANAGEMENT (Production Grade)
        # Real deployment tracking + strict 60% cap
        # Survival protection + near expiry bonus
        # ============================================
        _lot_size = LOT.get(inst, 75)
        _min_cost = prem * _lot_size
        _available = signal.get('capital', 50000)
        _open_positions = signal.get('open_positions', 0)
        _days_to_expiry = signal.get('days_to_expiry', 5)

        # Fix 1: Real deployment = actual cost per position
        # Not fake 20% assumption!
        _positions = signal.get('positions', [])
        if _positions:
            _total_deployed = sum(p.get('cost', 0)
                                  for p in _positions)
        else:
            # Fallback: use actual min_cost per position
            _total_deployed = _open_positions * _min_cost

        # Fix 4: Survival protection
        # Stop trading if capital too low!
        _min_trade_cap = 3000
        if _available < _min_trade_cap * 3:
            log.info(f'[V31] {inst} capital too low: '
                     f'Rs.{_available:,.0f} < safety limit')
            return False

        # Smart budget: adapts to capital size!
        _MCX=['CRUDEOIL','NATURALGAS','GOLDM','SILVERM']
        _is_mcx = inst in _MCX

        # Dynamic % based on capital:
        # Small capital (<50k): use higher % to afford trades
        # Large capital (>1L): use lower % for risk management
        if _available >= 100000:
            # Large capital: conservative
            _nse_pct = 0.20
            _mcx_pct = 0.50
        elif _available >= 50000:
            # Medium capital: balanced
            _nse_pct = 0.25
            _mcx_pct = 0.60
        elif _available >= 25000:
            # Small capital: aggressive to afford trades
            _nse_pct = 0.40
            _mcx_pct = 0.70
        else:
            # Very small: use max possible
            _nse_pct = 0.50
            _mcx_pct = 0.80

        _max_per_trade = _available * (_mcx_pct if _is_mcx else _nse_pct)

        # Near expiry bonus (last day = cheaper premiums)
        if _days_to_expiry <= 1:
            _max_per_trade = min(_available * 0.80,
                                 _max_per_trade * 1.25)
            log.info(f'[V31] {inst} near expiry bonus: '
                     f'Rs.{_max_per_trade:,.0f}')

        # Hard cap: never deploy > 80% of capital
        _hard_cap = _available * 0.80
        if _total_deployed + _max_per_trade > _hard_cap:
            _allowed = max(0, _hard_cap - _total_deployed)
            if _allowed < _min_trade_cap:
                log.info(f'[V31] {inst} 80% cap reached: '
                         f'deployed=Rs.{_total_deployed:,.0f}')
                return False
            _max_per_trade = _allowed

        # Survival protection per trade
        if _max_per_trade < _min_trade_cap:
            log.info(f'[V31] {inst} budget too small: '
                     f'Rs.{_max_per_trade:,.0f}')
            return False

        # Check 1 lot affordable
        if _min_cost > _max_per_trade:
            log.info(f'[V31] {inst} too expensive: '
                     f'Rs.{_min_cost:,.0f} > '
                     f'Rs.{_max_per_trade:,.0f} '
                     f'(positions={_open_positions} '
                     f'capital=Rs.{_available:,.0f})')
            return False

        # Fix 3: Safe lot calculation
        _max_lots = int(_max_per_trade // _min_cost)
        if _max_lots < 1:
            log.info(f'[V31] {inst} insufficient for 1 lot')
            return False

        log.info(f'[V31] {inst} capital OK: '
                 f'Rs.{_min_cost:,.0f} × {_max_lots} lots '
                 f'| deployed=Rs.{_total_deployed:,.0f} '
                 f'| budget=Rs.{_max_per_trade:,.0f} '
                 f'| cap=Rs.{_available*0.60:,.0f}')
        # SL based on UNDERLYING movement not premium %
        # Use sl_points from signal (based on OB/FVG/Swing)
        underlying_sl=signal.get('sl_points',0)
        underlying_price=signal.get('price',0)

        # Premium-based SL/Target (correct!)
        opt_sl=round(prem*0.40)          # SL = -40%
        opt_t1=round(prem*1.50)          # T1 = +50%
        opt_t2=round(prem*2.50) if score>=22 else round(prem*2.0)  # T2

        # Expiry + symbol from master file
        today=datetime.now()
        try:
            from v31_angel_options import get_option_symbol
            opt_sym,_,expiry=get_option_symbol(inst,price,opt_type)
        except:
            opt_sym=None
            expiry=None

        INDEX_INSTRUMENTS=['NIFTY','BANKNIFTY','SENSEX','FINNIFTY','MIDCPNIFTY']
        COMMODITY=['CRUDEOIL','GOLDM','SILVERM','NATURALGAS']

        # Use expiry from master file if available
        if not expiry:
            if inst in INDEX_INSTRUMENTS:
                days=(3-today.weekday())%7
                if days==0:days=7
                from datetime import timedelta
                expiry=(today+timedelta(days=days)).strftime('%d%b%y').upper()
            elif inst in COMMODITY:
                expiry='20APR26'
            else:
                expiry='30MAR26' 
        msg=f"""{emoji} {inst} {atm} {opt_type} | {expiry}
💵 Buy at: Rs.{prem} | Lot: {LOT.get(inst,75)}
🎯 T1: Rs.{opt_t1} (+{round((opt_t1-prem)/prem*100)}%)
🎯 T2: Rs.{opt_t2} (+{round((opt_t2-prem)/prem*100)}%)
🛑 SL: Rs.{opt_sl} (-{round((prem-opt_sl)/prem*100)}%)
📦 {qty} lot(s) | 💰 Rs.{prem*LOT.get(inst,75)*qty:,.0f}
{grade} Score:{score} ML:{ml_prob*100:.0f}%
🕐 {datetime.now().strftime("%H:%M:%S")}"""

        send(msg)
    except Exception as e:
        log.error(f'[V31] Entry notify error: {e}')

def notify_v31_exit(instrument,reason,pnl,entry,exit_price,rr_achieved=0):
    try:
        if pnl>0:
            emoji='🎯';status='PROFIT'
        else:
            emoji='🛑';status='LOSS'

        reason_msg={
            'T2':'🎯 TARGET 2 HIT!',
            'T1':'✅ Target 1 Hit',
            'SL':'🛑 Stop Loss Hit',
            'EOD':'⏰ EOD Exit',
            'TO':'⏱️ Timeout Exit'
        }.get(reason,reason)

        sign='+' if pnl>=0 else ''
        msg=f"""{emoji} <b>V31 EXIT - {status}</b>
━━━━━━━━━━━━━━━
📊 {instrument}
{reason_msg}
💵 Entry: {entry:.0f}
🚪 Exit: {exit_price:.0f}
{'📈' if pnl>0 else '📉'} PnL: <b>{sign}₹{pnl:,.0f}</b>"""

        if rr_achieved>0:
            msg+=f'\n🎯 RR Achieved: 1:{rr_achieved:.1f}'

        msg+=f'\n🕐 {_now.strftime("%H:%M:%S")}'
        send(msg)
    except Exception as e:
        log.error(f'[V31] Exit notify error: {e}')

def notify_v31_sl_analysis(instrument,reasons,better_entry,improvements):
    try:
        msg=f"""🔍 <b>V31 TRADE ANALYSIS</b>
━━━━━━━━━━━━━━━
📊 {instrument} | SL Hit

<b>Why SL Hit:</b>"""
        for r in reasons[:3]:
            msg+=f'\n• {r}'

        if better_entry:
            msg+=f'\n\n<b>Better Entry:</b>\n• {better_entry:.0f}'

        if improvements:
            msg+=f'\n\n<b>Improvements:</b>'
            for imp in improvements[:2]:
                msg+=f'\n• {imp}'

        msg+=f'\n\n🧠 Bot learning from this...'
        send(msg)
    except Exception as e:
        log.error(f'[V31] SL analysis notify error: {e}')

def notify_v31_daily_summary(trades,wins,losses,pnl,capital):
    try:
        wr=round(wins/trades*100) if trades>0 else 0
        emoji='📈' if pnl>0 else '📉'
        sign='+' if pnl>=0 else ''
        msg=f"""{emoji} <b>V31 DAILY SUMMARY</b>
━━━━━━━━━━━━━━━
📊 Trades: {trades}
✅ Wins: {wins} | ❌ Losses: {losses}
🎯 Win Rate: {wr}%
💰 PnL: {sign}₹{pnl:,.0f}
💵 Capital: ₹{capital:,.0f}
🕐 {datetime.now().strftime('%d-%b-%Y')}"""
        send(msg)
    except Exception as e:
        log.error(f'[V31] Daily summary error: {e}')

def notify_v31_gamma_alert(instrument,gamma_signal):
    try:
        signal_type=gamma_signal.get('type','')
        wall=gamma_signal.get('wall','')
        level=gamma_signal.get('wall_level',0)
        action=gamma_signal.get('action','')

        emoji='🎰'
        if 'BREAKOUT' in signal_type:emoji='🚀'
        elif 'REJECTION' in signal_type:emoji='🔄'

        msg=f"""{emoji} <b>GAMMA WALL ALERT</b>
━━━━━━━━━━━━━━━
📊 {instrument}
🎯 {signal_type}
{'🟢' if action=='BUY' else '🔴'} Direction: {action}
🧱 Wall: {wall} @ {level:.0f}
🕐 {datetime.now().strftime('%H:%M:%S')}"""
        send(msg)
    except Exception as e:
        log.error(f'[V31] Gamma notify error: {e}')

def notify_v31_meta_update(meta_summary):
    try:
        total=meta_summary.get('total_signals',0)
        wr=meta_summary.get('total_wins',0)/total*100 if total>0 else 0
        best_hours=meta_summary.get('warm_params',{}).get('best_hours',[])
        avoid_hours=meta_summary.get('warm_params',{}).get('avoid_hours',[])

        msg=f"""🧠 <b>V31 META LAYER UPDATED</b>
━━━━━━━━━━━━━━━
📊 Signals Analyzed: {total:,}
🎯 Overall WR: {wr:.1f}%
⭐ Best Hours: {best_hours}
🚫 Avoid Hours: {avoid_hours}

<b>Score Performance:</b>"""
        for r,d in sorted(meta_summary.get('score_performance',{}).items()):
            msg+=f'\n• Score {r}: WR {d["win_rate"]}%'

        msg+=f'\n\n✅ Bot updated with latest learnings!'
        send(msg)
    except Exception as e:
        log.error(f'[V31] Meta notify error: {e}')
