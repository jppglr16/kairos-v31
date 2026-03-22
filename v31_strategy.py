import logging
from datetime import datetime
import numpy as np
import pandas as pd
log=logging.getLogger(__name__)

def detect_hh_hl(df5):
    """Detect Higher Highs / Higher Lows = Uptrend"""
    try:
        h=df5['high'].values
        l=df5['low'].values
        n=len(h)
        if n<10:return False,False
        # Check last 3 swings
        hh=h[-1]>h[-5]>h[-10]  # Higher highs
        hl=l[-1]>l[-5]>l[-10]  # Higher lows
        lh=h[-1]<h[-5]<h[-10]  # Lower highs
        ll=l[-1]<l[-5]<l[-10]  # Lower lows
        return (hh and hl),(lh and ll)
    except:return False,False

def get_market_regime(df5,df15,df_daily):
    """
    Market Regime Detection:
    1. TRENDING_UP
    2. TRENDING_DOWN
    3. RANGING
    4. VOLATILE
    """
    try:
        c=df15['close'];h=df15['high'];l=df15['low']
        atr=float((h-l).tail(14).mean())
        atr_avg=float((h-l).rolling(20).mean().iloc[-1])

        # Volatility check - match backtest
        # ATR filter - use % based for stocks
        cur_price=float(df5['close'].iloc[-1]) if len(df5)>0 else 100
        atr_pct=atr/cur_price*100 if cur_price>0 else 0
        if atr_pct<0.15:return 'RANGING',0

        # Detect trend structure
        is_uptrend,is_downtrend=detect_hh_hl(df5)
        has_structure=is_uptrend or is_downtrend

        # Advanced regime classification
        if has_structure:
            if atr>atr_avg*1.3:
                regime='TRENDING_HIGH_VOL'  # Strong trend + high volatility
            else:
                regime='TRENDING'           # Normal trend
        elif atr<atr_avg*0.7:
            regime='RANGING'               # Low volatility = sideways
        elif atr>atr_avg*1.5:
            regime='VOLATILE'              # No structure + high vol = chop
        else:
            regime='RANGING'              # Default ranging

        # Trend via HH+HL or LH+LL
        swing_highs=[];swing_lows=[]
        for i in range(3,min(len(df15)-3,40)):
            if h.iloc[i]==h.iloc[i-3:i+4].max():
                swing_highs.append(float(h.iloc[i]))
            if l.iloc[i]==l.iloc[i-3:i+4].min():
                swing_lows.append(float(l.iloc[i]))

        hh=hl=lh=ll=False
        if len(swing_highs)>=2:
            hh=swing_highs[-1]>swing_highs[-2]
            lh=swing_highs[-1]<swing_highs[-2]
        if len(swing_lows)>=2:
            hl=swing_lows[-1]>swing_lows[-2]
            ll=swing_lows[-1]<swing_lows[-2]

        # EMA confirmation
        ema20=float(c.ewm(span=20).mean().iloc[-1])
        ema50=float(c.ewm(span=50).mean().iloc[-1]) if len(c)>=50 else ema20
        cur=float(c.iloc[-1])

        if hh and hl and cur>ema20 and ema20>ema50:
            if regime=='TRENDING_HIGH_VOL':
                return 'TRENDING_UP_HV',atr
            return 'TRENDING_UP',atr
        elif lh and ll and cur<ema20 and ema20<ema50:
            if regime=='TRENDING_HIGH_VOL':
                return 'TRENDING_DOWN_HV',atr
            return 'TRENDING_DOWN',atr
        elif atr>atr_avg*1.5:
            return 'VOLATILE',atr
        return 'RANGING',atr

    except:return 'RANGING',0

def detect_liquidity_sweep_v31(df5,action,atr):
    """
    Precise Liquidity Sweep:
    - 30-50 candle lookback
    - Equal highs/lows (0.1% tolerance)
    - Session highs/lows
    - Must close back above/below swept level
    """
    try:
        h=df5['high'];l=df5['low'];c=df5['close']
        last=df5.iloc[-1]
        lookback=min(50,len(df5)-5)

        if action=='BUY':
            # Standard sweep
            rl=float(l.iloc[-lookback:-1].min())
            if float(last['low'])<rl and float(last['close'])>rl:
                return True,'SWEEP_LOW',rl

            # Equal lows sweep
            for i in range(2,lookback):
                prev_l=float(l.iloc[-i])
                if abs(float(last['low'])-prev_l)/prev_l<0.001:
                    if float(last['close'])>prev_l:
                        return True,'EQUAL_LOWS',prev_l

            # Session low sweep (first 6 candles)
            if len(l)>=6:
                sess_l=float(l.iloc[:6].min())
                if float(last['low'])<sess_l and float(last['close'])>sess_l:
                    return True,'SESSION_LOW',sess_l

        else:  # SELL
            rh=float(h.iloc[-lookback:-1].max())
            if float(last['high'])>rh and float(last['close'])<rh:
                return True,'SWEEP_HIGH',rh

            # Equal highs
            for i in range(2,lookback):
                prev_h=float(h.iloc[-i])
                if abs(float(last['high'])-prev_h)/prev_h<0.001:
                    if float(last['close'])<prev_h:
                        return True,'EQUAL_HIGHS',prev_h

            # Session high sweep
            if len(h)>=6:
                sess_h=float(h.iloc[:6].max())
                if float(last['high'])>sess_h and float(last['close'])<sess_h:
                    return True,'SESSION_HIGH',sess_h

        return False,'NONE',0

    except:return False,'NONE',0

def detect_fvg_v31(df5,action,atr):
    """
    Precise FVG:
    BULL FVG: Candle1.high < Candle3.low
    BEAR FVG: Candle1.low > Candle3.high
    Noise filter: gap > ATR * 0.2
    """
    try:
        min_gap=atr*0.2
        fvgs=[]
        for i in range(2,min(len(df5),20)):
            c1=df5.iloc[-i-2]
            c3=df5.iloc[-i]
            if action=='BUY':
                gap=float(c3['low'])-float(c1['high'])
                if gap>min_gap:
                    fvgs.append({
                        'type':'BULL_FVG',
                        'top':float(c3['low']),
                        'bottom':float(c1['high']),
                        'size':gap,
                        'strength':gap/atr
                    })
            else:
                gap=float(c1['low'])-float(c3['high'])
                if gap>min_gap:
                    fvgs.append({
                        'type':'BEAR_FVG',
                        'top':float(c1['low']),
                        'bottom':float(c3['high']),
                        'size':gap,
                        'strength':gap/atr
                    })
        if fvgs:
            fvgs.sort(key=lambda x:-x['strength'])
            return True,fvgs[0]
        return False,None
    except:return False,None

def detect_ob_v31(df5,action,atr):
    """
    Order Block Detection:
    Last opposite candle before big move
    """
    try:
        for i in range(2,min(len(df5),15)):
            candle=df5.iloc[-i]
            if action=='BUY':
                # Last bearish candle before bullish move
                if float(candle['close'])<float(candle['open']):
                    next_candles=df5.iloc[-i+1:]
                    if len(next_candles)>0:
                        move=float(next_candles['close'].max())-float(candle['low'])
                        if move>atr*1.5:
                            return True,{
                                'type':'BULLISH_OB',
                                'top':float(candle['open']),
                                'bottom':float(candle['low']),
                                'strength':move/atr
                            }
            else:
                if float(candle['close'])>float(candle['open']):
                    next_candles=df5.iloc[-i+1:]
                    if len(next_candles)>0:
                        move=float(candle['high'])-float(next_candles['close'].min())
                        if move>atr*1.5:
                            return True,{
                                'type':'BEARISH_OB',
                                'top':float(candle['high']),
                                'bottom':float(candle['close']),
                                'strength':move/atr
                            }
        return False,None
    except:return False,None

def get_trend_v31(df):
    """HH+HL or LH+LL trend detection with EMA"""
    try:
        c=df['close'];h=df['high'];l=df['low']
        if len(c)<15:return 0
        swing_highs=[];swing_lows=[]
        for i in range(2,min(len(df)-2,30)):
            if float(h.iloc[i])==float(h.iloc[i-2:i+3].max()):
                swing_highs.append(float(h.iloc[i]))
            if float(l.iloc[i])==float(l.iloc[i-2:i+3].min()):
                swing_lows.append(float(l.iloc[i]))
        hh=hl=lh=ll=False
        if len(swing_highs)>=2:
            hh=swing_highs[-1]>swing_highs[-2]
            lh=swing_highs[-1]<swing_highs[-2]
        if len(swing_lows)>=2:
            hl=swing_lows[-1]>swing_lows[-2]
            ll=swing_lows[-1]<swing_lows[-2]
        ema20=float(c.ewm(span=20).mean().iloc[-1])
        cur=float(c.iloc[-1])
        if (hh or hl) and cur>ema20:return 1
        elif (lh or ll) and cur<ema20:return -1
        return 0
    except:return 0


def vwap_rejection_signal(df5,instrument,atr):
    """Path B: VWAP rejection signal (clean production version)"""
    try:
        if len(df5)<5:return None

        close=df5['close']
        high=df5['high']
        low=df5['low']
        volume=df5['volume'] if 'volume' in df5.columns else None

        # Rolling VWAP (last 20 candles - realistic!)
        if volume is not None and float(volume.tail(20).sum())>0:
            typical=(high+low+close)/3
            vwap=float((typical.tail(20)*volume.tail(20)).sum()/volume.tail(20).sum())
        else:
            vwap=float((high.tail(20)+low.tail(20)+close.tail(20)).mean()/3)

        price=float(close.iloc[-1])
        prev_price=float(close.iloc[-2])

        # Noise filter (0.3 ATR minimum distance)
        if abs(price-vwap)<0.3*atr:
            return None

        score=14

        # BUY: VWAP Reclaim
        if prev_price<vwap and price>vwap:
            if float(low.iloc[-1])<vwap:
                if float(close.iloc[-1])>float(close.iloc[-2]):
                    score+=2
                if volume is not None:
                    vol_avg=float(volume.iloc[-5:-1].mean())
                    if vol_avg>0 and float(volume.iloc[-1])>vol_avg*1.3:
                        score+=2
                return {
                    'instrument':instrument,'action':'BUY',
                    'option_type':'CE','price':price,'vwap':vwap,
                    'sl_points':round(atr*1.5,2),'sl_type':'VWAP_ATR',
                    'target1':round(price+atr*2,2),
                    'target2':round(price+atr*4,2),
                    'rr_ratio':2.0,'score':score,
                    'regime':'VWAP_REJECT','liq_type':'VWAP_CROSS',
                    'imbalance_type':'VWAP_BUY','path':'B',
                    'atr':atr,'version':'V31'
                }

        # SELL: VWAP Breakdown
        if prev_price>vwap and price<vwap:
            if float(high.iloc[-1])>vwap:
                if float(close.iloc[-1])<float(close.iloc[-2]):
                    score+=2
                if volume is not None:
                    vol_avg=float(volume.iloc[-5:-1].mean())
                    if vol_avg>0 and float(volume.iloc[-1])>vol_avg*1.3:
                        score+=2
                return {
                    'instrument':instrument,'action':'SELL',
                    'option_type':'PE','price':price,'vwap':vwap,
                    'sl_points':round(atr*1.5,2),'sl_type':'VWAP_ATR',
                    'target1':round(price-atr*2,2),
                    'target2':round(price-atr*4,2),
                    'rr_ratio':2.0,'score':score,
                    'regime':'VWAP_REJECT','liq_type':'VWAP_CROSS',
                    'imbalance_type':'VWAP_SELL','path':'B',
                    'atr':atr,'version':'V31'
                }

    except Exception as e:
        log.error(f'[PathB] {instrument}: {e}')
    return None

def generate_v31_signal(df5,df15,df_daily,instrument,capital,
                         feed=None,client=None):
    """
    Kairos V31 Signal Generation:
    
    Market Regime
    → Liquidity Sweep
    → FVG / OB (Imbalance)
    → Trend Alignment
    → Gamma Wall Confirmation
    → ML Filter
    → Execute
    """
    try:
        now=datetime.now()
        h=now.hour

        # Time filter
        # Time filter - NSE hours only for NSE, MCX has different hours
        MCX_INST=['CRUDEOIL','GOLDM','SILVERM','NATURALGAS']
        if instrument not in MCX_INST:
            if h<9 or h>15:return None
            if 12<=h<13:return None  # Avoid lunch only

        c=df5['close'];hi=df5['high'];lo=df5['low'];v=df5['volume']
        atr=float((hi-lo).tail(14).mean())
        if atr<=0:return None

        current=float(c.iloc[-1])

        # Volatility check
        avg_atr=float((hi-lo).rolling(20).mean().iloc[-1])
        vol_ratio=atr/max(avg_atr,0.001)  # Fix 4: reusable metric!
        if vol_ratio<0.75:
            log.debug(f'[V31] {instrument} low volatility ({vol_ratio:.2f}) skip')
            return None

        # STEP 1: Market Regime
        regime,regime_atr=get_market_regime(df5,df15,df_daily)
        # Fix 2: Volatile = scalp mode, not skip!
        strategy_mode='SCALP' if regime=='VOLATILE' else 'NORMAL'
        if regime=='VOLATILE':
            log.debug(f'[V31] {instrument} VOLATILE regime - SCALP mode')

        # STEP 2: Trend Alignment
        trend5=get_trend_v31(df5)
        trend15=get_trend_v31(df15)
        trend_daily=get_trend_v31(df_daily)

        # Determine signal direction from regime
        if regime=='TRENDING_UP':
            action='BUY'
        elif regime=='TRENDING_DOWN':
            action='SELL'
        else:
            # Ranging: need gamma walls to determine
            action=None

        # STEP 3: Liquidity Sweep (MANDATORY)
        liq_score_adj=0
        if action:
            has_liq,liq_type,liq_level=detect_liquidity_sweep_v31(df5,action,atr)
            if not has_liq:
                # Try opposite direction in ranging
                if regime=='RANGING':
                    opp='SELL' if action=='BUY' else 'BUY'
                    has_liq,liq_type,liq_level=detect_liquidity_sweep_v31(df5,opp,atr)
                    if has_liq:action=opp
                if not has_liq:
                    # Fix 3: Soft penalty not hard block!
                    liq_score_adj=-3
                    has_liq=False
                    liq_type='NONE'
                    liq_level=current
                    log.debug(f'[V31] {instrument} no liq sweep, -3 penalty')
            else:
                liq_score_adj=+3  # Bonus for sweep confirmation!
        else:
            # Ranging: try both directions
            has_liq_b,liq_type_b,liq_level_b=detect_liquidity_sweep_v31(df5,'BUY',atr)
            has_liq_s,liq_type_s,liq_level_s=detect_liquidity_sweep_v31(df5,'SELL',atr)
            if has_liq_b:action='BUY';has_liq=True;liq_type=liq_type_b;liq_level=liq_level_b
            elif has_liq_s:action='SELL';has_liq=True;liq_type=liq_type_s;liq_level=liq_level_s
            else:return None

        # Safe initialization
        liq_score_adj=0
        trend_score_adj=0
        # Fix 1: Trend alignment - SEPARATE variable!
        if action=='BUY':
            if trend5=='UP' and trend15=='UP':
                trend_score_adj+=2  # Aligned bonus!
            elif trend5!='UP' or trend15!='UP':
                trend_score_adj-=2  # Misaligned penalty!
                log.debug(f'[V31] {instrument} BUY misaligned 5m={trend5} 15m={trend15}')
        elif action=='SELL':
            if trend5=='DOWN' and trend15=='DOWN':
                trend_score_adj+=2
            elif trend5!='DOWN' or trend15!='DOWN':
                trend_score_adj-=2
                log.debug(f'[V31] {instrument} SELL misaligned 5m={trend5} 15m={trend15}')

        # STEP 4: Imbalance - FVG or OB (at least one MANDATORY)
        has_fvg,fvg_data=detect_fvg_v31(df5,action,atr)
        has_ob,ob_data=detect_ob_v31(df5,action,atr)
        if not has_fvg and not has_ob:return None
        imbalance=fvg_data if has_fvg else ob_data

        # STEP 5: Trend confirmation
        if action=='BUY':
            trend_aligned=(trend5==1 or trend15==1)
            trend_against=(trend5==-1 and trend15==-1 and trend_daily==-1)
        else:
            trend_aligned=(trend5==-1 or trend15==-1)
            trend_against=(trend5==1 and trend15==1 and trend_daily==1)

        if trend_against:return None  # Never trade against all timeframes

        # STEP 6: Gamma Wall Confirmation
        gamma_boost=0
        gamma_info=None
        oi_trap_info=None
        try:
            if instrument in ['NIFTY','BANKNIFTY','SENSEX','FINNIFTY','MIDCPNIFTY']:
                try:
                    from v31_gamma import check_gamma_signal,check_oi_trap
                    gamma_sig=check_gamma_signal(instrument,current,df5,atr)
                except:
                    gamma_sig=None
                if gamma_sig:
                    if gamma_sig['action']==action:
                        gamma_boost+=gamma_sig['strength']
                        gamma_info=gamma_sig
                    elif gamma_sig['type']=='GAMMA_BREAKOUT':
                        gamma_boost+=3  # Breakout confirmation

                oi_trap=check_oi_trap(instrument,current,df5)
                if oi_trap and oi_trap['action']==action:
                    gamma_boost+=oi_trap['strength']
                    oi_trap_info=oi_trap
        except Exception as e:
            log.debug(f'[V31] Gamma error: {e}')

        # STEP 7: Structured Score Calculation
        # Fix 1: Define trend_aligned properly!
        trend_aligned=(
            (action=='BUY' and trend5=='UP' and trend15=='UP') or
            (action=='SELL' and trend5=='DOWN' and trend15=='DOWN')
        )

        score_components={
            "base":5,
            "fvg":4 if has_fvg else 0,
            "ob":3 if has_ob else 0,
            "trend":3 if trend_aligned else 0,  # Fix 2: reduced to 3
            "liquidity":locals().get("liq_score_adj",0),
            "trend_adj":locals().get("trend_score_adj",0),
        }

        score=sum(score_components.values())
        MCX_INSTRUMENTS=["CRUDEOIL","GOLDM","SILVERM","NATURALGAS"]
        is_mcx=instrument in MCX_INSTRUMENTS

        # Daily trend bonus only (not duplicate!)
        if trend_daily==trend5:score+=1  # Reduced weight

        if not is_mcx:
            score+=gamma_boost

        # Session scoring
        if is_mcx:
            if 21<=h<=23:score+=4
            elif 18<=h<=21:score+=3
            elif 9<=h<=11:score+=2
            atr_pct=atr/current*100 if current>0 else 0
            if atr_pct>0.5:score+=3
            elif atr_pct>0.3:score+=2
            elif atr_pct>0.2:score+=1
        else:
            if h==10 or h==11:score+=3
            elif h==13 or h==14:score+=2
            elif 9<=h<10:score+=2  # Morning bonus!

        # VWAP
        try:
            vwap=float((c*v).sum()/v.sum())
            if action=="BUY" and current>vwap:score+=2
            elif action=="SELL" and current<vwap:score+=2
        except:pass

        # Fix 3: Cap + normalize
        score=min(score,30)
        score_pct=score/30  # 0.0 to 1.0

        # Position sizing from score
        if score_pct>0.80:
            suggested_lots=2  # High conviction!
        elif score_pct>0.60:
            suggested_lots=1  # Normal
        else:
            log.debug(f"[V31] {instrument} weak score {score}/30 skip")
            return None  # Skip weak trades!

        # SL/T1 tuning based on score
        sl_multiplier=1.0
        t1_multiplier=1.0
        if score_pct>0.75:
            sl_multiplier=1.2  # Wider SL for strong signals
            t1_multiplier=1.3  # Bigger target!
        elif score_pct<0.50:
            sl_multiplier=0.8  # Tighter SL for weak signals
            t1_multiplier=0.7

        # Entry timing filter (last candle direction)
        last=df5.iloc[-1]
        last_bullish=float(last['close'])>float(last['open'])
        weak_entry=False
        if action=='BUY' and not last_bullish:
            log.debug(f'[V31] {instrument} BUY on bearish candle - weak entry')
            score-=2
            weak_entry=True
        elif action=='SELL' and last_bullish:
            log.debug(f'[V31] {instrument} SELL on bullish candle - weak entry')
            score-=2
            weak_entry=True

        score=max(score,0)

        # Fix 1: Recompute score_pct AFTER penalties!
        score_pct=score/30

        # Fix 2: Smoother lot scaling
        if score_pct>0.85:
            suggested_lots=3  # Very high conviction!
        elif score_pct>0.70:
            suggested_lots=2
        elif score_pct>0.55:
            suggested_lots=1
        else:
            log.debug(f"[V31] {instrument} weak score {score:.0f}/30 skip")
            return None

        # Fix 3: Weak entry reduces lots too!
        if weak_entry:
            suggested_lots=max(1,suggested_lots-1)
            log.debug(f'[V31] {instrument} weak entry: lots reduced to {suggested_lots}')

        log.debug(f"[V31] {instrument} score={score}/30 ({score_pct:.0%}) lots={suggested_lots}")

        # STEP 8: Smart SL from structure
        from v30_rr_filter import find_tight_sl,find_best_target
        sl_type,sl_pts,sl_price=find_tight_sl(df5,df15,action,atr)
        if sl_pts<atr*0.5:
            sl_pts=atr*0.75  # Minimum SL
        if sl_pts>atr*2.0:return None  # SL too wide

        # STEP 9: Target based on trend
        is_trending=regime in ['TRENDING_UP','TRENDING_DOWN']
        tgt_type,target,rr=find_best_target(
            df5,df15,action,current,sl_pts,atr,is_trending)
        if rr<3.0:return None  # Minimum 1:3 RR

        # Build signal
        # Trap detection
        trap_detected=None
        trap_score_val=0
        try:
            from v31_trap import get_full_trap_score
            cur_price=float(df5['close'].iloc[-1])
            trap_score_val,trap_detected=get_full_trap_score(
                instrument,df5,action,atr,cur_price)
            score+=trap_score_val
        except Exception as te:
            log.debug(f'[V31] Trap error: {te}')

        signal={
            'instrument':instrument,
            'action':action,
            'option_type':'CE' if action=='BUY' else 'PE',
            'price':current,
            'sl_points':sl_pts,
            'sl_type':sl_type,
            'target1':sl_pts*1.5,
            'target2':sl_pts*rr,
            'rr_ratio':rr,
            'score':score,
            'regime':regime,
            'liq_type':liq_type,
            'imbalance_type':imbalance.get('type','') if imbalance else '',
            'trend_aligned':trend_aligned,
            'gamma_boost':gamma_boost,
            'gamma_info':gamma_info,
            'oi_trap':oi_trap_info,
            'use_trailing':is_trending,
            'hold_overnight':False,
            'timestamp':str(now),
            'version':'V31',
            'trap_type':trap_detected.get('type','') if trap_detected else '',
            'trap_score':trap_score_val
        }

        log.info(f'[V31] SIGNAL: {instrument} {action} '
                f'Score:{score} RR:1:{rr:.1f} '
                f'SL:{sl_pts:.1f}({sl_type}) '
                f'Liq:{liq_type} '
                f'Gamma:{gamma_boost}')

        return signal

    except Exception as e:
        log.error(f'[V31] Error {instrument}: {e}')
        return None

def notify_v31_signal(signal):
    """Send V31 signal details to Telegram"""
    try:
        from v30_notify import send
        action=signal.get('action','')
        instrument=signal.get('instrument','')
        score=signal.get('score',0)
        regime=signal.get('regime','')
        liq=signal.get('liq_type','')
        fvg=signal.get('imbalance_type','')
        rr=signal.get('rr_ratio',0)
        sl=signal.get('sl_points',0)
        sl_type=signal.get('sl_type','')
        gamma=signal.get('gamma_boost',0)
        oi_trap=signal.get('oi_trap')
        ml_prob=signal.get('ml_prob',0)
        price=signal.get('price',0)

        # Grade
        if score>=30:grade='🌟 S'
        elif score>=25:grade='⭐ A'
        elif score>=20:grade='✅ B'
        else:grade='📊 C'

        # Regime emoji
        regime_emoji={
            'TRENDING_UP':'📈',
            'TRENDING_DOWN':'📉',
            'RANGING':'↔️',
            'VOLATILE':'⚡'
        }.get(regime,'📊')

        msg=f"""🎯 <b>KAIROS V31 SIGNAL</b>
━━━━━━━━━━━━━━━
{'🟢' if action=='BUY' else '🔴'} <b>{instrument}</b> {'BUY CE' if action=='BUY' else 'SELL PE'}
{grade} | Score: {score}/43

💵 Entry: {price:.1f}
🛑 SL: {sl:.1f} pts ({sl_type})
🎯 Target: 1:{rr:.1f} RR
{'📈' if action=='BUY' else '📉'} T2: {price+sl*rr:.1f if action=='BUY' else price-sl*rr:.1f}

{regime_emoji} Regime: {regime}
💧 Liq Sweep: {liq}
📦 Imbalance: {fvg if fvg else 'OTE Zone'}
🤖 ML Prob: {ml_prob*100:.1f}%"""

        if gamma>0:
            msg+=f'\n🎰 Gamma Boost: +{gamma}'
        if oi_trap:
            msg+=f'\n⚡ OI Trap: {oi_trap.get("type","")} ({oi_trap.get("reason","")})'

        msg+=f'\n⏰ {datetime.now().strftime("%H:%M:%S")}'
        send(msg)
        return True
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f'[V31] Notify error: {e}')
        return False
