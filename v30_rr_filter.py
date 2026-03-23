import numpy as np
import logging
log=logging.getLogger(__name__)

MIN_RR=3.0
MAX_RR=10.0

def find_tight_sl(df5, df15, action, atr):
    """Find best SL from FVG / OB / Swing - below/above zone with buffer"""
    try:
        c = df5['close']
        h = df5['high']
        l = df5['low']
        current = float(c.iloc[-1])
        candidates = []
        min_sl = atr * 0.3   # Minimum viable SL
        max_sl = atr * 1.8   # Maximum SL
        buffer = atr * 0.10  # Buffer beyond zone (stop-hunt protection)
        slippage = atr * 0.025  # 50% of original - buffer already covers most

        if action == 'BUY':

            # 1. FVG support - SL just below FVG bottom
            for i in range(len(df5)-5, len(df5)-1):
                if i < 2: continue
                p2 = df5.iloc[i-2]
                cur = df5.iloc[i]
                if float(cur['low']) > float(p2['high']):
                    fvg_bottom = float(cur['low']) - buffer
                    sl_pts = current - fvg_bottom
                    if 0 < sl_pts < atr * 2.0:
                        candidates.append(('FVG', sl_pts, fvg_bottom, 1))  # Priority 1

            # 2. OB low - SL just below OB
            for i in range(len(df5)-10, len(df5)-3):
                if i < 0: continue
                candle = df5.iloc[i]
                if float(candle['close']) < float(candle['open']):
                    ob_low = float(candle['low']) - buffer
                    sl_pts = current - ob_low
                    if 0 < sl_pts < atr * 2.0:
                        candidates.append(('OB', sl_pts, ob_low, 2))  # Priority 2

            # 3. Swing low
            swing_low = float(l.tail(8).min()) - buffer
            sl_swing = current - swing_low
            if 0 < sl_swing < atr * 3:
                candidates.append(('SWING_LOW', sl_swing, swing_low, 3))  # Priority 3

            # 4. Micro swing
            micro_low = float(l.tail(3).min()) - buffer
            sl_micro = current - micro_low
            if 0 < sl_micro < atr * 1.0:
                candidates.append(('MICRO_LOW', sl_micro, micro_low, 4))  # Priority 4

        else:  # SELL

            # 1. FVG resistance - SL just above FVG top
            for i in range(len(df5)-5, len(df5)-1):
                if i < 2: continue
                p2 = df5.iloc[i-2]
                cur = df5.iloc[i]
                if float(cur['high']) < float(p2['low']):
                    fvg_top = float(cur['high']) + buffer
                    sl_pts = fvg_top - current
                    if 0 < sl_pts < atr * 2.0:
                        candidates.append(('FVG', sl_pts, fvg_top, 1))

            # 2. OB high - SL just above OB
            for i in range(len(df5)-10, len(df5)-3):
                if i < 0: continue
                candle = df5.iloc[i]
                if float(candle['close']) > float(candle['open']):
                    ob_high = float(candle['high']) + buffer
                    sl_pts = ob_high - current
                    if 0 < sl_pts < atr * 2.0:
                        candidates.append(('OB', sl_pts, ob_high, 2))

            # 3. Swing high
            swing_high = float(h.tail(8).max()) + buffer
            sl_swing = swing_high - current
            if 0 < sl_swing < atr * 3:
                candidates.append(('SWING_HIGH', sl_swing, swing_high, 3))

            # 4. Micro swing
            micro_high = float(h.tail(3).max()) + buffer
            sl_micro = micro_high - current
            if 0 < sl_micro < atr * 1.0:
                candidates.append(('MICRO_HIGH', sl_micro, micro_high, 4))

        # Apply min/max SL filter
        candidates=[c for c in candidates if min_sl < c[1] < max_sl]

        # Sort by priority first, then tighter SL
        candidates.sort(key=lambda x: (x[3], x[1]))

        # Remove duplicate SL levels (4-value tuples)
        filtered=[]
        seen=set()
        for c in candidates:
            key=round(c[2],1)
            if key not in seen:
                seen.add(key)
                filtered.append(c)
        candidates=filtered

        # No candidates = use ATR fallback
        if not candidates:
            if action == 'BUY':
                return 'ATR', min_sl, current - min_sl
            else:
                return 'ATR', min_sl, current + min_sl

        # Pick tightest valid SL
        if not candidates:
            return ('ATR_SAFE',min_sl,current-min_sl) if action=='BUY' else ('ATR_SAFE',min_sl,current+min_sl)

        best = min(filtered if filtered else candidates, key=lambda x: (x[3] if len(x)>3 else 9, x[1]))

        # Reject if too tight (noise filter)
        if best[1] < atr * 0.3:
            log.info(f'[SL] Too tight ({best[1]:.2f} < {atr*0.3:.2f}) - using ATR safe')
            if action == 'BUY':
                return 'ATR_SAFE', min_sl, current - min_sl
            else:
                return 'ATR_SAFE', min_sl, current + min_sl

        log.info(f'[SL] Best SL: {best[0]} = {best[1]:.2f} pts @ {best[2]:.2f}')
        return best[0],best[1],best[2]  # type, pts, price

    except Exception as e:
        log.error(f'SL error: {e}')
        return 'ATR', atr * 0.8, 0


def find_best_target(df5, df15, action, entry, sl_points, atr, is_trending=True):
    """Find best target using RR from FVG/OB/Swing"""
    try:
        c = df5['close']
        h = df5['high']
        l = df5['low']
        targets = []

        if action == 'BUY':
            # Swing highs as targets
            for lookback in [5, 10, 20]:
                t = float(h.tail(lookback).max())
                dist = t - entry
                if dist > 0:
                    rr = dist / sl_points
                    if MIN_RR <= rr <= MAX_RR:
                        targets.append((rr, t))

            # BUY FVG targets (resistance above)
            for i in range(len(df5)-15, len(df5)-1):
                if i < 2: continue
                p2 = df5.iloc[i-2]
                cur = df5.iloc[i]
                if float(cur['high']) < float(p2['low']):
                    t = float(p2['low'])
                    dist = t - entry
                    if dist > 0:
                        rr = dist / sl_points
                        if MIN_RR <= rr <= MAX_RR:
                            targets.append((rr, t))

            # S/R based targets (most accurate!)
            try:
                from v31_support_resistance import sr_engine
                price=float(df5['close'].iloc[-1])
                atr_val=float((df5['high']-df5['low']).tail(14).mean())
                levels=sr_engine.get_all_levels(df5,price)

                if action=='BUY':
                    # Use resistance levels as targets
                    for level_name in ['R1','R2','PDH','round_resistance']:
                        level_val=levels.get(level_name,0)
                        if level_val and level_val>entry:
                            dist=level_val-entry
                            if dist>0:
                                rr=dist/sl_points
                                if rr>=1.0:
                                    targets.append((rr,level_val))
                else:
                    # Use support levels as targets
                    for level_name in ['S1','S2','PDL','round_support']:
                        level_val=levels.get(level_name,0)
                        if level_val and level_val<entry:
                            dist=entry-level_val
                            if dist>0:
                                rr=dist/sl_points
                                if rr>=1.0:
                                    targets.append((rr,level_val))
            except:pass

            # Fix 1: Fallback ONLY if no S/R targets found
            if not targets:
                for rr in [2.0,3.0,5.0]:
                    t=entry+sl_points*rr
                    targets.append((rr,t))

        else:  # SELL
            # Swing lows as targets
            for lookback in [5, 10, 20]:
                t = float(l.tail(lookback).min())
                dist = entry - t
                if dist > 0:
                    rr = dist / sl_points
                    if MIN_RR <= rr <= MAX_RR:
                        targets.append((rr, t))

            # SELL FVG targets (support below)
            for i in range(len(df5)-15, len(df5)-1):
                if i < 2: continue
                p2 = df5.iloc[i-2]
                cur = df5.iloc[i]
                if float(cur['low']) > float(p2['high']):
                    t = float(p2['high'])
                    dist = entry - t
                    if dist > 0:
                        rr = dist / sl_points
                        if MIN_RR <= rr <= MAX_RR:
                            targets.append((rr, t))

            # RR-based fallback
            for rr in [3.0, 5.0, 8.0]:
                t = entry - sl_points * rr
                targets.append((rr, t))

        if not targets:
            t1 = entry + sl_points*3 if action=='BUY' else entry - sl_points*3
            t2 = entry + sl_points*5 if action=='BUY' else entry - sl_points*5
            return t1, t2, 3.0

        # Sort by RR, pick safe T1 and runner T2
        targets.sort(key=lambda x: x[0])
        t1 = targets[0][1]   # Lowest RR = safe target
        t2 = targets[-1][1]  # Highest RR = runner
        best_rr = targets[0][0]

        return t1, t2, best_rr

    except Exception as e:
        log.error(f'Target error: {e}')
        t1 = entry + sl_points*3 if action=='BUY' else entry - sl_points*3
        t2 = entry + sl_points*5 if action=='BUY' else entry - sl_points*5
        return t1, t2, 3.0


def apply_rr_filter(signal,df5,df15,atr):
    """Compatibility function for ML engine"""
    try:
        action=signal.get('action','BUY')
        sl_type,sl_pts,sl_price=find_tight_sl(df5,df15,action,atr)
        entry=signal.get('price',0)
        t1,t2=find_best_target(df5,df15,action,entry,sl_pts,atr)
        rr=abs(t1-entry)/max(sl_pts,0.01)
        return {
            'sl_points':sl_pts,
            'sl_price':sl_price,
            'target1':t1,
            'target2':t2,
            'rr_ratio':round(rr,2)
        }
    except Exception as e:
        return None
