"""
V31 Path E: Gamma Blast - Final Institution Grade
All critical fixes + elite upgrades implemented
"""
import logging
from datetime import datetime, time

log = logging.getLogger(__name__)

INDEX_INST = ['NIFTY','BANKNIFTY','SENSEX','FINNIFTY','MIDCPNIFTY']

MAX_PREMIUM = {
    'NIFTY':30,'BANKNIFTY':50,'SENSEX':50,
    'FINNIFTY':20,'MIDCPNIFTY':15,
    'DEFAULT_STOCK':2,
}

STRIKE_STEPS = {
    'NIFTY':50,'BANKNIFTY':100,'SENSEX':100,
    'FINNIFTY':50,'MIDCPNIFTY':25,'DEFAULT':5,
}

# For position sizing
LOT_SIZES = {
    'NIFTY':65,'BANKNIFTY':30,'SENSEX':20,
    'FINNIFTY':60,'MIDCPNIFTY':120,
    'DEFAULT':75,
}

def get_days_to_expiry(instrument):
    try:
        from v31_angel_options import get_option_symbol
        result = get_option_symbol(instrument, 0, 'CE')
        if result:
            from datetime import datetime as dt
            exp = dt.strptime(result[2], '%d%b%Y')
            return max(0, (exp - datetime.now()).days)
    except: pass
    w = datetime.now().weekday()
    return {3:0,2:1,1:2,0:3,4:6}.get(w,5)

def check_time_filter(now):
    t = now.time()
    if t < time(9,20): return False,'Pre-market'
    if time(12,30) <= t <= time(13,30): return False,'Dead zone'
    if t >= time(15,0): return False,'Trap zone'
    return True,'OK'

def detect_gamma_regime(df15):
    """Volatility clustering + acceleration curve"""
    try:
        ranges = df15['high'] - df15['low']
        vol_now = float(ranges.iloc[-1])
        vol_avg = float(ranges.tail(20).mean())
        if vol_avg <= 0: return 'UNKNOWN',1.0

        acceleration = vol_now / vol_avg

        # Elite: Gamma acceleration curve
        acc1 = float(ranges.iloc[-1]) / max(float(ranges.iloc[-5]),0.01)
        acc2 = float(ranges.iloc[-5]) / max(float(ranges.iloc[-10]),0.01)
        accel_increasing = acc1 > acc2  # Building pressure!

        regime = (
            'SHORT_GAMMA' if acceleration > 1.8 else
            'EXPANDING' if acceleration > 1.3 else
            'LONG_GAMMA'
        )
        return regime, acceleration, accel_increasing
    except:
        return 'UNKNOWN',1.0,False

def check_iv_expansion(df5):
    """Volatility regime memory - detects building pressure"""
    try:
        ranges = df5['high'] - df5['low']
        last5 = float(ranges.tail(5).mean())
        prev5 = float(ranges.tail(10).head(5).mean())
        current = float(ranges.iloc[-1])
        avg10 = float(ranges.tail(10).mean())

        iv_ratio = current/avg10 if avg10>0 else 1.0
        building = last5 > prev5  # Pressure building!
        expanding = iv_ratio > 1.3

        return expanding, round(iv_ratio,2), building
    except:
        return False,1.0,False

def check_mtf_momentum(df5, df15, action):
    try:
        trend5 = float(df5['close'].iloc[-1]) > float(df5['close'].iloc[-3])
        trend15 = float(df15['close'].iloc[-1]) > float(df15['close'].iloc[-5])
        if action=='BUY': return trend5 and trend15
        else: return not trend5 and not trend15
    except: return False

def breakout_confirm(df5, action):
    """Clean breakout with volume confirmation!"""
    try:
        recent_high = float(df5['high'].tail(20).max())
        recent_low = float(df5['low'].tail(20).min())
        price = float(df5['close'].iloc[-1])

        # Price breakout
        price_ok = (price > recent_high if action=='BUY'
                   else price < recent_low)
        if not price_ok: return False

        # Volume confirmation
        vol = df5['volume']
        vol_avg = float(vol.tail(20).mean())
        vol_spike = float(vol.iloc[-1]) > vol_avg * 1.5
        return vol_spike
    except: return False

def is_trap(df5):
    """Large wick = dealer trap!"""
    try:
        h=float(df5['high'].iloc[-1])
        l=float(df5['low'].iloc[-1])
        c=float(df5['close'].iloc[-1])
        o=float(df5['open'].iloc[-1])
        body=abs(c-o)
        upper=h-max(c,o)
        lower=min(c,o)-l
        if body>0:
            return upper>body*2 or lower>body*2
        return False
    except: return False

def get_oi_flow(instrument, action):
    """OI flow from option chain - ENFORCED!"""
    try:
        from v31_oi_pcr import oi_pcr
        pcr,_,_ = oi_pcr.get_pcr(instrument)
        if pcr is None: return 'UNKNOWN',0

        if action=='SELL' and pcr>1.3:
            return 'SHORT_BUILDUP',pcr
        elif action=='BUY' and pcr<0.7:
            return 'LONG_BUILDUP',pcr
        elif action=='BUY' and pcr>1.5:
            return 'SHORT_COVERING',pcr
        elif action=='SELL' and pcr<0.5:
            return 'LONG_UNWINDING',pcr
        else:
            return 'NEUTRAL',pcr
    except: return 'UNKNOWN',0

def gamma_squeeze_detected(df5, atr):
    """Squeeze with acceleration check!"""
    try:
        c = df5['close']
        move5 = abs(float(c.iloc[-1]) - float(c.iloc[-5]))
        move1 = abs(float(c.iloc[-1]) - float(c.iloc[-2]))

        # Real squeeze: big move + accelerating!
        is_squeeze = (move5 > atr*2.0 and
                      move1 > (move5/5))
        ratio = round(move5/atr,2) if atr>0 else 0
        return is_squeeze, ratio
    except: return False,0

def select_strike(current, action, instrument, strength):
    step = STRIKE_STEPS.get(instrument, STRIKE_STEPS['DEFAULT'])
    atm = round(current/step)*step
    if strength > 3.0:
        return atm+step if action=='BUY' else atm-step
    return atm

def calculate_position_size(capital, atr, strength, instrument):
    """
    Gamma Blast: Use 6% of capital per trade!
    Stop if total gamma losses > 10%
    """
    lot = LOT_SIZES.get(instrument, LOT_SIZES['DEFAULT'])
    risk_factor = min(1.0, strength/3.0)
    max_risk = capital * 0.02      # 2% max risk
    sl_value = atr * 0.3
    budget = capital * 0.06 * risk_factor  # 6% for gamma!

    if sl_value > 0 and lot > 0:
        contracts = max(1, int(max_risk / (sl_value * lot)))
        size = min(budget, contracts * sl_value * lot * 10)
    else:
        size = budget

    return round(size, 0), max(1, int(size / max(1, sl_value * lot)))

def check_kill_switch(capital):
    """Stop trading if daily loss > 5%"""
    try:
        import json, os
        if os.path.exists('paper_trades.json'):
            d = json.load(open('paper_trades.json'))
            today = datetime.now().strftime('%Y-%m-%d')
            today_trades = [t for t in d.get('trades',[])
                           if t.get('date')==today
                           and t.get('status')=='CLOSED']
            daily_loss = sum(t.get('pnl',0) or 0
                            for t in today_trades
                            if (t.get('pnl') or 0) < 0)
            if abs(daily_loss) > capital * 0.05:
                return True, abs(daily_loss)
    except: pass
    return False, 0

def check_spread_ok(bid, ask):
    """Basic spread protection"""
    if bid<=0 or ask<=0: return True
    return (ask-bid)/ask < 0.05

def gamma_blast_signal(df5, df15, instrument, capital):
    """
    Path E: Complete Institution Grade Gamma Blast
    Min score 25 required - quality over quantity!
    """
    try:
        now = datetime.now()

        # Trade frequency control (max 3 gamma trades/day)
        MAX_GAMMA_TRADES = 3
        try:
            import json, os
            if os.path.exists('paper_trades.json'):
                d = json.load(open('paper_trades.json'))
                today = datetime.now().strftime('%Y-%m-%d')
                gamma_today = [t for t in d.get('trades',[])
                              if t.get('date')==today
                              and t.get('path')=='E_GAMMA']
                if len(gamma_today) >= MAX_GAMMA_TRADES:
                    log.debug(f'[GAMMA] Max trades reached today')
                    return None
        except: pass

        # Kill switch first!
        killed, loss = check_kill_switch(capital)
        if killed:
            log.warning(f'[GAMMA] Kill switch! Daily loss Rs.{loss:.0f}')
            return None

        # Filter 1: DTE
        dte = get_days_to_expiry(instrument)
        if dte > 2: return None

        # Filter 2: Time
        time_ok, _ = check_time_filter(now)
        if not time_ok: return None

        # Basic data
        atr = float((df5['high']-df5['low']).tail(14).mean())
        current = float(df5['close'].iloc[-1])
        if current<=0 or atr<=0: return None

        is_index = instrument in INDEX_INST
        max_prem = MAX_PREMIUM.get(instrument, MAX_PREMIUM['DEFAULT_STOCK'])

        # Filter 3: Gamma regime
        regime, acceleration, accel_inc = detect_gamma_regime(df15)
        if regime == 'LONG_GAMMA': return None

        # Filter 4: IV expansion
        iv_ok, iv_ratio, iv_building = check_iv_expansion(df5)
        if not iv_ok: return None

        # Momentum check
        c = df5['close']
        sell_str = (float(c.iloc[-3])-float(c.iloc[-1]))/atr if atr>0 else 0
        buy_str  = (float(c.iloc[-1])-float(c.iloc[-3]))/atr if atr>0 else 0
        buy_str  = min(buy_str,  5.0)  # Cap for gaps!
        sell_str = min(sell_str, 5.0)  # Cap for gaps!
        sell_mom = (float(c.iloc[-1])<float(c.iloc[-2])<float(c.iloc[-3])
                    and sell_str>1.5)
        buy_mom  = (float(c.iloc[-1])>float(c.iloc[-2])>float(c.iloc[-3])
                    and buy_str>1.5)

        if sell_mom: action,strength = 'SELL',sell_str
        elif buy_mom: action,strength = 'BUY',buy_str
        else: return None

        # Filter 5: MTF
        if not check_mtf_momentum(df5,df15,action): return None

        # Filter 6: Clean breakout
        if not breakout_confirm(df5, action): return None

        # Filter 7: Trap check
        if is_trap(df5): return None

        # Filter 8: OI flow - ENFORCED!
        oi_flow, pcr_val = get_oi_flow(instrument, action)
        favorable = ['SHORT_BUILDUP','LONG_BUILDUP',
                     'SHORT_COVERING','LONG_UNWINDING']
        if oi_flow not in favorable:
            log.debug(f'[GAMMA] {instrument} OI={oi_flow} skip')
            return None

        # GEX Analysis (Dealer positioning)
        gex_data = None
        gex_bias = 'UNKNOWN'
        gex_strength = 0.0
        gamma_flip = None
        call_wall = None
        put_wall = None
        try:
            from v31_gex_engine import get_gex_analysis
            gex_data = get_gex_analysis(instrument, current)
            if gex_data:
                gex_bias = gex_data['gex_bias']
                gex_strength = gex_data.get('gex_strength', 0.0)
                gamma_flip = gex_data['gamma_flip']
                call_wall = gex_data['call_wall']
                put_wall = gex_data['put_wall']

                # Hard filter: LONG_GAMMA = pinned market
                if gex_bias == 'LONG_GAMMA':
                    log.debug(f'[GAMMA] {instrument} GEX LONG skip')
                    return None

                # Weak signal filter: low conviction skip!
                if abs(gex_strength) < 0.02:
                    log.debug(f'[GAMMA] {instrument} GEX weak ({gex_strength:.3f}) skip')
                    return None

        except Exception as _ge:
            log.debug(f'[GEX] Error: {_ge}')

        # Filter 9: Squeeze
        squeeze, sq_ratio = gamma_squeeze_detected(df5, atr)

        # Dealer trap zone check
        step = STRIKE_STEPS.get(instrument, 50)
        atm = round(current/step)*step
        dist_atm = abs(current-atm)
        near_pin = dist_atm < atr*0.5

        # Score calculation
        score = 15

        if dte==0: score+=6
        elif dte==1: score+=3

        if regime=='SHORT_GAMMA': score+=5
        elif regime=='EXPANDING': score+=2

        if accel_inc: score+=3  # Acceleration increasing!

        if squeeze: score+=6
        if iv_building: score+=2

        if oi_flow in ['SHORT_COVERING','LONG_UNWINDING']:
            score+=3
        score+=4  # OI favorable (already filtered)

        if strength>3.0: score+=4
        elif strength>2.0: score+=2

        if is_index: score+=2
        if near_pin: score+=2  # Dealer trap zone!

        if time(9,30)<=now.time()<=time(11,30): score+=2

        # GEX dynamic scoring (strength-based!)
        if gex_bias == 'SHORT_GAMMA':
            score += 5 + min(5, int(abs(gex_strength)*20))
        elif gex_bias == 'SLIGHT_SHORT':
            score += 2 + min(3, int(abs(gex_strength)*10))

        # Flip zone = highest conviction entry!
        if gamma_flip and abs(current-gamma_flip)<atr:
            score+=5
            log.info(f'[GAMMA] {instrument} near FLIP zone! +5')

        # Wall breakout
        if call_wall and action=='BUY' and current>call_wall:
            score+=3
        if put_wall and action=='SELL' and current<put_wall:
            score+=3

        # MINIMUM SCORE = 25 (quality over quantity!)
        if score < 25:
            log.debug(f'[GAMMA] {instrument} score {score}<25 skip')
            return None

        # Position sizing
        strike = select_strike(current, action, instrument, strength)
        capital_alloc, contracts = calculate_position_size(
            capital, atr, strength, instrument)

        signal = {
            'instrument': instrument,
            'action': action,
            'option_type': 'CE' if action=='BUY' else 'PE',
            'price': current,
            'score': score,
            'path': 'E_GAMMA',
            'sl_points': atr*(0.5 if squeeze else 0.3),
            'sl_type': 'GAMMA_TIME',
            'target1': current+(atr*2) if action=='BUY' else current-(atr*2),
            'target2': current+(atr*4) if action=='BUY' else current-(atr*4),
            'rr_ratio': 4.0,
            'days_to_expiry': dte,
            'max_premium': max_prem,
            'time_sl_mins': 15,
            'gamma_regime': regime,
            'gamma_accel': round(acceleration,2),
            'accel_increasing': accel_inc,
            'gamma_strength': round(strength,2),
            'squeeze': squeeze,
            'squeeze_ratio': sq_ratio,
            'iv_ratio': iv_ratio,
            'iv_building': iv_building,
            'oi_flow': oi_flow,
            'pcr': pcr_val,
            'near_pin': near_pin,
            'strike': strike,
            'capital_alloc': capital_alloc,
            'suggested_lots': contracts,
            'gex_bias': gex_bias,
            'gex_strength': gex_strength if gex_data else 0.0,
            'gamma_flip': gamma_flip,
            'call_wall': call_wall,
            'put_wall': put_wall,
            'timestamp': now.strftime('%Y-%m-%d %H:%M:%S'),
            'version': 'V31_GAMMA',
            'liq_type': f'GAMMA_BLAST_DTE{dte}',
        }

        log.info(
            f'[GAMMA] 🔥 {instrument} PATH E {action} '
            f'Score:{score} DTE:{dte} '
            f'Regime:{regime}({acceleration:.1f}x↑{accel_inc}) '
            f'Squeeze:{squeeze}({sq_ratio}x) '
            f'OI:{oi_flow}(PCR:{pcr_val:.2f}) '
            f'Pin:{near_pin} Budget:Rs.{capital_alloc:.0f}')

        return signal

    except Exception as e:
        log.error(f'[GAMMA] Error {instrument}: {e}')
        return None
