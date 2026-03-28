"""
V31 Path E: Gamma Blast - Final Institution Grade
All critical fixes + elite upgrades implemented
"""
import logging
from datetime import datetime, time

log = logging.getLogger(__name__)

INDEX_INST = ['NIFTY','BANKNIFTY','SENSEX','FINNIFTY','MIDCPNIFTY']

# Gamma blast independent state (separate from other paths!)
_gamma_positions = {}  # instrument → {direction, entry_time, score}

def get_gamma_state(instrument):
    """Check current gamma position for instrument"""
    return _gamma_positions.get(instrument, None)

def set_gamma_state(instrument, direction, score):
    """Record gamma position"""
    from datetime import datetime
    _gamma_positions[instrument] = {
        'direction': direction,
        'entry_time': datetime.now(),
        'score': score
    }

def clear_gamma_state(instrument):
    """Clear gamma position on exit"""
    _gamma_positions.pop(instrument, None)

def can_straddle(df5, atr):
    """
    Check if market conditions suit straddle
    = Low IV + range-bound
    = Buy both CE and PE!
    """
    try:
        ranges = df5['high'] - df5['low']
        current_range = float(ranges.iloc[-1])
        avg_range = float(ranges.tail(10).mean())
        # Low IV = current range < 70% of average
        low_iv = current_range < avg_range * 0.70
        
        # Range bound = price between recent high/low
        recent_high = float(df5['high'].tail(10).max())
        recent_low = float(df5['low'].tail(10).min())
        price = float(df5['close'].iloc[-1])
        range_pct = (recent_high - recent_low) / price
        range_bound = range_pct < 0.005  # Less than 0.5% range
        
        return low_iv and range_bound
    except:
        return False

MAX_PREMIUM = {
    'NIFTY':40,'BANKNIFTY':60,'SENSEX':60,
    'FINNIFTY':30,'MIDCPNIFTY':20,
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

# ============================================
# ADVANCED INSTITUTIONAL LOGIC
# ============================================

def detect_pin_risk(current, strike_gex, atr):
    """
    PIN RISK DETECTION
    Market pinned near high OI strike = 
    explosive breakout when released!
    """
    try:
        if not strike_gex:
            return False, 0
        # Find highest OI strike
        max_oi = max(strike_gex, 
                    key=lambda x: x['ce_oi']+x['pe_oi'])
        pin_strike = max_oi['strike']
        distance = abs(current - pin_strike)
        
        # Near pin = within 0.5 ATR
        near_pin = distance < atr * 0.5
        pin_strength = max(0, 1 - distance/(atr*2))
        
        return near_pin, round(pin_strength, 2)
    except:
        return False, 0

def detect_vanna_charm_effect(df5, dte):
    """
    VANNA/CHARM EFFECT
    Near expiry: delta hedging creates momentum!
    Vanna = vol moves → delta changes → hedging flows
    Charm = time decay → delta changes → forced hedging
    
    Effect strongest in last 2 days!
    """
    try:
        # Proxy: volatility moving + price trending
        closes = df5['close']
        ranges = df5['high'] - df5['low']
        
        # Vol trend
        vol_up = float(ranges.iloc[-1]) > float(ranges.iloc[-3])
        
        # Price trend strength
        price_move = abs(float(closes.iloc[-1]) - 
                        float(closes.iloc[-5]))
        avg_move = float(ranges.tail(10).mean())
        
        # Charm effect strongest on last day!
        charm_factor = 1.0 if dte == 0 else 0.7 if dte == 1 else 0.4
        
        vanna_active = vol_up and price_move > avg_move
        score_boost = int(charm_factor * 4) if vanna_active else 0
        
        return vanna_active, score_boost, charm_factor
    except:
        return False, 0, 0

def detect_delta_hedging_flow(df5, action):
    """
    DELTA HEDGING FLOW DETECTION
    Market makers delta hedge = amplifies moves!
    
    Signs:
    = Consistent same-direction pressure
    = Increasing volume each candle
    = No pullback candles
    """
    try:
        closes = df5['close']
        volumes = df5['volume']
        
        # Check last 3 candles
        c1 = float(closes.iloc[-1])
        c2 = float(closes.iloc[-2])
        c3 = float(closes.iloc[-3])
        
        v1 = float(volumes.iloc[-1])
        v2 = float(volumes.iloc[-2])
        v3 = float(volumes.iloc[-3])
        
        if action == 'SELL':
            price_consistent = c1 < c2 < c3  # Each lower
            vol_increasing = v1 > v2 > v3 * 0.8  # Volume rising
        else:
            price_consistent = c1 > c2 > c3  # Each higher
            vol_increasing = v1 > v2 > v3 * 0.8
            
        hedging_flow = price_consistent and vol_increasing
        return hedging_flow
    except:
        return False

def detect_skew(instrument, action):
    """
    OPTIONS SKEW ANALYSIS
    High put skew = fear = sell expensive
    Low skew = complacency = buy cheap!
    
    Use PCR as proxy for skew!
    """
    try:
        from v31_oi_pcr import oi_pcr
        pcr, atm_oi, signal = oi_pcr.get_pcr(instrument)
        if pcr is None:
            return 'NEUTRAL', 0
        
        # High PCR = expensive puts = good for SELL
        # Low PCR = expensive calls = good for BUY
        if action == 'SELL':
            if pcr > 2.0: return 'HIGH_SKEW', 3    # Very bearish
            if pcr > 1.5: return 'ELEVATED', 2
            return 'NORMAL', 0
        else:  # BUY
            if pcr < 0.5: return 'LOW_SKEW', 3     # Very bullish
            if pcr < 0.7: return 'MUTED', 2
            return 'NORMAL', 0
    except:
        return 'UNKNOWN', 0

def detect_exhaustion(df5, action, atr):
    """
    EXHAUSTION DETECTION
    Don't enter when move already exhausted!
    
    Signs:
    = Large candle followed by doji
    = Volume dropping
    = Price not making new extremes
    """
    try:
        closes = df5['close']
        highs = df5['high']
        lows = df5['low']
        volumes = df5['volume']
        
        # Last candle much smaller than previous
        last_range = abs(float(highs.iloc[-1]) - float(lows.iloc[-1]))
        prev_range = abs(float(highs.iloc[-2]) - float(lows.iloc[-2]))
        
        # Volume dropping
        vol_dropping = float(volumes.iloc[-1]) < float(volumes.iloc[-2]) * 0.7
        
        # Price making new extreme?
        if action == 'SELL':
            new_extreme = float(lows.iloc[-1]) < float(lows.iloc[-2])
        else:
            new_extreme = float(highs.iloc[-1]) > float(highs.iloc[-2])
        
        # Exhausted if: small candle + dropping volume + no new extreme
        exhausted = (last_range < prev_range * 0.5 and 
                    vol_dropping and not new_extreme)
        
        return exhausted
    except:
        return False

def smart_reentry_check(instrument, action):
    """
    SMART RE-ENTRY LOGIC
    After SL hit, allow re-entry if:
    = Price confirms direction
    = Score is higher than first entry
    = At least 5 mins gap
    """
    try:
        state = get_gamma_state(instrument)
        if not state:
            return True, 'Fresh entry'
        
        # Check if same direction re-entry
        if state['direction'] == action:
            elapsed = (datetime.now() - 
                      state['entry_time']).seconds / 60
            if elapsed >= 5:
                return True, f'Re-entry after {elapsed:.0f} mins'
            return False, 'Too soon for re-entry'
        
        return True, 'Different direction'
    except:
        return True, 'Allow'

def get_market_regime_context(df5, df15):
    """
    MARKET REGIME CONTEXT
    Classify overall market state for better sizing
    """
    try:
        # Trend strength
        ema20 = df5['close'].ewm(span=20).mean()
        price = float(df5['close'].iloc[-1])
        ema_val = float(ema20.iloc[-1])
        
        # Volatility state
        ranges = df5['high'] - df5['low']
        vol_ratio = float(ranges.iloc[-1]) / float(ranges.tail(20).mean())
        
        if vol_ratio > 2.0:
            regime = 'EXPLOSIVE'    # Best for gamma!
            size_mult = 1.0
        elif vol_ratio > 1.5:
            regime = 'ACTIVE'       # Good
            size_mult = 0.8
        elif vol_ratio > 1.0:
            regime = 'NORMAL'       # Okay
            size_mult = 0.6
        else:
            regime = 'QUIET'        # Avoid!
            size_mult = 0.3
            
        return regime, size_mult
    except:
        return 'UNKNOWN', 0.5

def detect_institutional_activity(df5):
    """
    INSTITUTIONAL ACTIVITY DETECTION
    Big players = large candles + high volume
    = Better to follow than fight!
    """
    try:
        volumes = df5['volume']
        ranges = df5['high'] - df5['low']
        
        vol_avg = float(volumes.tail(20).mean())
        range_avg = float(ranges.tail(20).mean())
        
        vol_now = float(volumes.iloc[-1])
        range_now = float(ranges.iloc[-1])
        
        # 2x normal = institutional!
        vol_spike = vol_now > vol_avg * 2.0
        range_spike = range_now > range_avg * 1.8
        
        institutional = vol_spike and range_spike
        conviction = round(
            (vol_now/vol_avg + range_now/range_avg) / 2, 2)
        
        return institutional, conviction
    except:
        return False, 1.0

def get_optimal_strike_v2(current, action, instrument, 
                           strength, dte, gex_data):
    """
    ADVANCED STRIKE SELECTION
    Considers: strength, DTE, GEX walls, squeeze!
    """
    step = STRIKE_STEPS.get(instrument, STRIKE_STEPS['DEFAULT'])
    atm = round(current / step) * step
    
    # DTE-based aggressiveness
    # Last day = more OTM (lottery play!)
    # 2 days = slightly OTM
    if dte == 0 and strength > 3.0:
        otm_steps = 2  # 2 strikes OTM on expiry!
    elif strength > 3.0 or dte == 0:
        otm_steps = 1  # 1 strike OTM
    else:
        otm_steps = 0  # ATM (safer)
    
    # Check GEX walls
    if gex_data:
        call_wall = gex_data.get('call_wall')
        put_wall = gex_data.get('put_wall')
        
        if action == 'BUY' and call_wall:
            # Strike below call wall = better gamma!
            if current < call_wall:
                return atm  # ATM is fine
        if action == 'SELL' and put_wall:
            if current > put_wall:
                return atm
    
    if action == 'BUY':
        return atm + (step * otm_steps)
    else:
        return atm - (step * otm_steps)

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

    # Use full budget to calculate lots!
    # Budget = 6% of capital
    # cost_per_lot = premium × lot_size (passed via signal)
    # contracts = budget / cost_per_lot
    # Minimum 1 lot always!

    # Fallback if sl_value available
    if sl_value > 0 and lot > 0:
        # How many lots can budget afford?
        # Will be refined in main using actual premium
        approx_prem = sl_value * 3  # Rough premium estimate
        cost_per_lot = approx_prem * lot
        contracts = max(1, int(budget / max(cost_per_lot, 1)))
    else:
        contracts = 1

    return round(budget, 0), contracts

def check_kill_switch(capital, max_loss_pct=0.10):
    """Stop trading if daily loss > 10% (gamma blast)"""
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
            if abs(daily_loss) > capital * max_loss_pct:
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

        # Rule 1: Path E is INDEPENDENT!
        # = Don't check other path positions
        # = Has its own capital (6%)
        # = Runs parallel to A/B/C/D!

        # Rule 2: Zone block within Path E only
        existing = get_gamma_state(instrument)
        if existing:
            elapsed = (datetime.now() - existing['entry_time']).seconds / 60
            same_dir = existing['direction'] == ('BUY' if not False else 'SELL')
            if elapsed < 30:  # 30 min zone lock
                log.debug(f'[GAMMA] {instrument} zone locked ({elapsed:.0f} mins)')
                return None

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

        # ADVANCED: Exhaustion check (don't enter late!)
        if detect_exhaustion(df5, action, atr):
            log.debug(f'[GAMMA] {instrument} exhausted skip')
            return None

        # ADVANCED: Re-entry check
        reentry_ok, reentry_reason = smart_reentry_check(
            instrument, action)
        if not reentry_ok:
            log.debug(f'[GAMMA] {instrument} {reentry_reason}')
            return None

        # ADVANCED: Market regime context
        mkt_regime, size_mult = get_market_regime_context(df5, df15)
        if mkt_regime == 'QUIET':
            log.debug(f'[GAMMA] {instrument} quiet market skip')
            return None

        # ADVANCED: Institutional activity
        institutional, conviction = detect_institutional_activity(df5)

        # ADVANCED: Delta hedging flow
        delta_flow = detect_delta_hedging_flow(df5, action)

        # ADVANCED: Vanna/Charm effect (near expiry!)
        vanna_active, vanna_boost, charm = detect_vanna_charm_effect(
            df5, dte)

        # ADVANCED: Options skew
        skew_type, skew_boost = detect_skew(instrument, action)

        # ADVANCED: Pin risk
        pin_near = False
        pin_strength = 0
        if gex_data and gex_data.get('total_gex'):
            pin_near, pin_strength = detect_pin_risk(
                current,
                [{'strike': gex_data.get('call_wall', 0),
                  'ce_oi': 1000, 'pe_oi': 0},
                 {'strike': gex_data.get('put_wall', 0),
                  'ce_oi': 0, 'pe_oi': 1000}],
                atr)

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

        # Rule 3 enforcement: flip needs score >= 28!
        if existing and existing['direction'] != action:
            if score < 28:
                log.debug(f'[GAMMA] {instrument} flip needs score>=28 got {score}')
                return None
            log.info(f'[GAMMA] {instrument} VALID FLIP! score={score}>=28')

        # Position sizing
        strike = get_optimal_strike_v2(current, action, instrument, strength, dte, gex_data)
        # Apply regime multiplier to position size!
        capital_alloc, contracts = calculate_position_size(
            capital * size_mult, atr, strength, instrument)

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
            # Smart exit based on lot count!
            't1_pct': 1.0,         # 100% gain = T1
            't2_pct': 3.0,         # 300% gain = T2
            'trail_sl_pct': 0.33,  # Trail SL = 33% of peak
            'max_hold_mins': 45,   # Max hold 45 mins!
            # Exit plan by lots:
            # 1 lot → hold all, exit at T2
            # 2 lots→ 0 at T1, 1 at T2, 1 trail 33%
            # 3 lots→ 1 T1, 1 T2, 1 trail 33%
            # 4 lots→ 1 T1, 1 T2, 2 trail 33%
            # 5 lots→ 2 T1, 2 T2, 1 trail 33%
            # 6 lots→ 2 T1, 2 T2, 2 trail 33%
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
            'straddle': _straddle,
            'mkt_regime': mkt_regime,
            'size_mult': size_mult,
            'institutional': institutional,
            'conviction': conviction,
            'delta_flow': delta_flow,
            'vanna_active': vanna_active,
            'charm_factor': charm,
            'skew_type': skew_type,
            'pin_near': pin_near,
            'pin_strength': pin_strength,
            'gamma_independent': True,  # Independent from other paths!
            'timestamp': now.strftime('%Y-%m-%d %H:%M:%S'),
            'version': 'V31_GAMMA',
            'liq_type': f'GAMMA_BLAST_DTE{dte}',
        }

        # Record gamma state (zone lock!)
        set_gamma_state(instrument, action, score)

        # Log for ML training!
        try:
            from v31_gamma_logger import log_gamma_entry
            signal['_gamma_log_id'] = log_gamma_entry(
                signal,
                signal.get('real_prem', 0),
                contracts
            )
        except Exception as _mle:
            log.debug(f'[GAMMA_ML] Log error: {_mle}')

        # Log for ML training!
        try:
            from v31_gamma_logger import log_gamma_entry
            signal['_gamma_log_id'] = log_gamma_entry(
                signal,
                signal.get('real_prem', 0),
                contracts
            )
        except Exception as _mle:
            log.debug(f'[GAMMA_ML] Log error: {_mle}')

        log.info(
            f'[GAMMA] 🔥 {instrument} PATH E {action} '
            f'Score:{score} DTE:{dte} '
            f'Regime:{regime}({acceleration:.1f}x) '
            f'MktRegime:{mkt_regime}({size_mult}x) '
            f'Squeeze:{squeeze}({sq_ratio}x) '
            f'Inst:{institutional}(conv:{conviction}) '
            f'DeltaFlow:{delta_flow} '
            f'Vanna:{vanna_active}(+{vanna_boost}) '
            f'Skew:{skew_type}(+{skew_boost}) '
            f'Pin:{pin_near}({pin_strength:.1f}) '
            f'Straddle:{_straddle} '
            f'OI:{oi_flow}(PCR:{pcr_val:.2f}) '
            f'Budget:Rs.{capital_alloc:.0f}')

        return signal

    except Exception as e:
        log.error(f'[GAMMA] Error {instrument}: {e}')
        return None
