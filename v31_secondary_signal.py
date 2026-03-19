import numpy as np
import pandas as pd
import logging
log=logging.getLogger(__name__)

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def check_volume_profile(df5,pattern_bars=10):
    """Volume profile - skip if no volume data"""
    try:
        v=df5['volume'].values
        vol_avg=np.mean(v[-20:])
        if vol_avg<=0:return True  # No volume data = skip filter
        breakout_vol=v[-1]
        return breakout_vol>vol_avg*1.2
    except:return True

def check_confirmation_candle(df5,action,level):
    """
    Wait for confirmation:
    BUY: Close above resistance
    SELL: Close below support
    """
    if len(df5)<2:return False
    last=df5.iloc[-1]
    prev=df5.iloc[-2]
    if action=='BUY':
        return (float(last['close'])>level and
                float(prev['close'])<=level)
    else:
        return (float(last['close'])<level and
                float(prev['close'])>=level)

def is_pattern_significant(high,low,atr):
    """Pattern must be > 1.0x ATR to be significant"""
    return (high-low)>=atr*1.0

def check_trend_alignment(df5,df15,action):
    """Pattern must align with 15-min trend"""
    from v31_strategy import get_trend_v31
    t5=get_trend_v31(df5)
    t15=get_trend_v31(df15)
    if action=='BUY':
        return not(t5==-1 and t15==-1)
    return not(t5==1 and t15==1)

# ============================================================
# BREAKOUT DETECTION
# ============================================================
def detect_breakout(df5,action,atr):
    """
    Breakout above resistance / Breakdown below support
    + Volume surge confirmation
    + Confirmation candle
    """
    h=df5['high'];l=df5['low'];c=df5['close'];v=df5['volume']
    vol_avg=float(v.rolling(20).mean().iloc[-1])
    vol_avg=float(v.rolling(20).mean().iloc[-1])
    vol_spike=vol_avg<=0 or float(v.iloc[-1])>vol_avg*1.2
    if not vol_spike:return False,'NO_VOLUME'

    resistance=float(h.iloc[-20:-1].max())
    support=float(l.iloc[-20:-1].min())

    if action=='BUY':
        if check_confirmation_candle(df5,'BUY',resistance):
            return True,'BULLISH_BREAKOUT'
    else:
        if check_confirmation_candle(df5,'SELL',support):
            return True,'BEARISH_BREAKDOWN'
    return False,'NO_BREAKOUT'

# ============================================================
# CHART PATTERNS
# ============================================================
def detect_chart_pattern(df5,action,atr):
    """
    Detect chart patterns with validation:
    - Volume profile check
    - Pattern size check
    - Confirmation candle
    """
    h=df5['high'];l=df5['low'];c=df5['close'];v=df5['volume']
    vol_avg=float(v.rolling(20).mean().iloc[-1])

    if action=='BUY':
        # ─────────────────────────────
        # BULL FLAG
        # Strong up + low vol consolidation + breakout
        # ─────────────────────────────
        if len(df5)>=15:
            pole_h=float(h.iloc[-15:-8].max())
            pole_l=float(l.iloc[-15:-8].min())
            flag_h=float(h.iloc[-8:].max())
            flag_l=float(l.iloc[-8:].min())
            pole_size=pole_h-pole_l
            flag_size=flag_h-flag_l

            if (is_pattern_significant(pole_h,pole_l,atr) and
                flag_size<pole_size*0.5 and
                check_volume_profile(df5,8) and
                float(c.iloc[-1])>flag_h*0.999):
                return True,'BULL_FLAG'

        # ─────────────────────────────
        # DOUBLE BOTTOM (W pattern)
        # Two lows at same level + neckline break
        # ─────────────────────────────
        if len(df5)>=20:
            low1_idx=df5['low'].iloc[-20:-10].idxmin()
            low2_idx=df5['low'].iloc[-10:].idxmin()
            low1=float(df5.loc[low1_idx,'low'])
            low2=float(df5.loc[low2_idx,'low'])
            neckline=float(h.iloc[-20:].max())

            if (abs(low1-low2)/max(low1,0.001)<0.005 and
                is_pattern_significant(neckline,min(low1,low2),atr) and
                float(v.iloc[-1])>vol_avg*1.3 and
                check_confirmation_candle(df5,'BUY',neckline)):
                return True,'DOUBLE_BOTTOM'

        # ─────────────────────────────
        # ASCENDING TRIANGLE
        # Flat resistance + rising lows
        # ─────────────────────────────
        if len(df5)>=20:
            highs=h.iloc[-20:].values
            lows=l.iloc[-20:].values
            flat_top=np.std(highs[-10:])<atr*0.3
            rising_lows=lows[-1]>lows[-10] and lows[-5]>lows[-10]

            if (flat_top and rising_lows and
                is_pattern_significant(max(highs),min(lows),atr) and
                float(v.iloc[-1])>vol_avg*1.4):
                return True,'ASCENDING_TRIANGLE'

        # ─────────────────────────────
        # INVERSE HEAD & SHOULDERS
        # Left shoulder + head (lower) + right shoulder
        # ─────────────────────────────
        if len(df5)>=30:
            seg=len(df5)//3
            ls=float(l.iloc[-3*seg:-2*seg].min())  # Left shoulder
            hd=float(l.iloc[-2*seg:-seg].min())    # Head
            rs=float(l.iloc[-seg:].min())           # Right shoulder
            neckline_ihs=float(h.iloc[-3*seg:].mean())

            if (hd<ls and hd<rs and  # Head is lowest
                abs(ls-rs)/max(ls,0.001)<0.01 and  # Shoulders equal
                is_pattern_significant(neckline_ihs,hd,atr) and
                float(c.iloc[-1])>neckline_ihs and
                float(v.iloc[-1])>vol_avg*1.3):
                return True,'INV_HEAD_SHOULDERS'

        # ─────────────────────────────
        # HIGHER HIGHS + HIGHER LOWS
        # ─────────────────────────────
        if (float(h.iloc[-1])>float(h.iloc[-6]) and
            float(l.iloc[-1])>float(l.iloc[-6]) and
            float(h.iloc[-6])>float(h.iloc[-11]) and
            float(v.iloc[-1])>vol_avg*1.3):
            return True,'HIGHER_HIGHS_LOWS'

    else:  # SELL patterns
        # ─────────────────────────────
        # BEAR FLAG
        # ─────────────────────────────
        if len(df5)>=15:
            pole_h=float(h.iloc[-15:-8].max())
            pole_l=float(l.iloc[-15:-8].min())
            flag_h=float(h.iloc[-8:].max())
            flag_l=float(l.iloc[-8:].min())
            pole_size=pole_h-pole_l
            flag_size=flag_h-flag_l

            if (is_pattern_significant(pole_h,pole_l,atr) and
                flag_size<pole_size*0.5 and
                check_volume_profile(df5,8) and
                float(c.iloc[-1])<flag_l*1.001):
                return True,'BEAR_FLAG'

        # ─────────────────────────────
        # DOUBLE TOP (M pattern)
        # ─────────────────────────────
        if len(df5)>=20:
            high1=float(h.iloc[-20:-10].max())
            high2=float(h.iloc[-10:].max())
            neckline_dt=float(l.iloc[-20:].min())

            if (abs(high1-high2)/max(high1,0.001)<0.005 and
                is_pattern_significant(max(high1,high2),neckline_dt,atr) and
                float(v.iloc[-1])>vol_avg*1.3 and
                check_confirmation_candle(df5,'SELL',neckline_dt)):
                return True,'DOUBLE_TOP'

        # ─────────────────────────────
        # DESCENDING TRIANGLE
        # Flat support + falling highs
        # ─────────────────────────────
        if len(df5)>=20:
            lows_dt=l.iloc[-20:].values
            highs_dt=h.iloc[-20:].values
            flat_bottom=np.std(lows_dt[-10:])<atr*0.3
            falling_highs=highs_dt[-1]<highs_dt[-10] and highs_dt[-5]<highs_dt[-10]

            if (flat_bottom and falling_highs and
                is_pattern_significant(max(highs_dt),min(lows_dt),atr) and
                float(v.iloc[-1])>vol_avg*1.4):
                return True,'DESCENDING_TRIANGLE'

        # ─────────────────────────────
        # HEAD & SHOULDERS
        # ─────────────────────────────
        if len(df5)>=30:
            seg=len(df5)//3
            ls=float(h.iloc[-3*seg:-2*seg].max())  # Left shoulder
            hd=float(h.iloc[-2*seg:-seg].max())    # Head
            rs=float(h.iloc[-seg:].max())           # Right shoulder
            neckline_hs=float(l.iloc[-3*seg:].mean())

            if (hd>ls and hd>rs and  # Head is highest
                abs(ls-rs)/max(ls,0.001)<0.01 and
                is_pattern_significant(hd,neckline_hs,atr) and
                float(c.iloc[-1])<neckline_hs and
                float(v.iloc[-1])>vol_avg*1.3):
                return True,'HEAD_SHOULDERS'

        # ─────────────────────────────
        # LOWER HIGHS + LOWER LOWS
        # ─────────────────────────────
        if (float(l.iloc[-1])<float(l.iloc[-6]) and
            float(h.iloc[-1])<float(h.iloc[-6]) and
            float(l.iloc[-6])<float(l.iloc[-11]) and
            float(v.iloc[-1])>vol_avg*1.3):
            return True,'LOWER_HIGHS_LOWS'

    return False,'NO_PATTERN'

# ============================================================
# CANDLESTICK PATTERNS
# ============================================================
def detect_candlestick_pattern(df5,action,atr):
    """
    Detect candlestick patterns with:
    - Volume confirmation
    - Pattern size validation
    """
    if len(df5)<3:return False,'NO_PATTERN'

    c1=df5.iloc[-3];c2=df5.iloc[-2];c3=df5.iloc[-1]
    v=df5['volume']
    vol_avg=float(v.rolling(20).mean().iloc[-1])
    vol_avg=float(v.rolling(20).mean().iloc[-1])
    vol_ok=vol_avg<=0 or float(c3['volume'])>vol_avg*1.0
    if not vol_ok:return False,'NO_VOLUME'

    o3=float(c3['open']);c3_=float(c3['close'])
    h3=float(c3['high']);l3=float(c3['low'])
    body3=abs(c3_-o3)
    range3=h3-l3

    # Pattern must be significant
    if range3<atr*0.3:return False,'TOO_SMALL'

    if action=='BUY':
        # Hammer: Small body top, long lower wick > 2x body
        lower_wick=min(o3,c3_)-l3
        upper_wick=h3-max(o3,c3_)
        if (body3<range3*0.35 and
            lower_wick>body3*2 and
            upper_wick<body3*0.5 and
            range3>=atr*0.5):
            return True,'HAMMER'

        # Bullish Engulfing
        o2=float(c2['open']);c2_=float(c2['close'])
        if (c2_<o2 and c3_>o3 and
            o3<=c2_ and c3_>=o2 and
            body3>abs(c2_-o2)*1.1 and
            range3>=atr*0.4):
            return True,'BULLISH_ENGULFING'

        # Morning Star (3 candles)
        o1=float(c1['open']);c1_=float(c1['close'])
        body1=abs(c1_-o1);body2=abs(float(c2['close'])-float(c2['open']))
        if (c1_<o1 and body1>atr*0.4 and  # Strong bearish
            body2<atr*0.2 and  # Small doji
            c3_>o3 and  # Bullish
            c3_>((o1+c1_)/2) and  # Closes above midpoint
            float(v.iloc[-1])>vol_avg*1.3):
            return True,'MORNING_STAR'

        # Piercing Line
        o2=float(c2['open']);c2_=float(c2['close'])
        if (c2_<o2 and c3_>o3 and
            o3<c2_ and
            c3_>((o2+c2_)/2) and
            c3_<o2 and
            body3>atr*0.3):
            return True,'PIERCING_LINE'

    else:  # SELL
        # Shooting Star: Small body bottom, long upper wick
        upper_wick=h3-max(o3,c3_)
        lower_wick=min(o3,c3_)-l3
        if (body3<range3*0.35 and
            upper_wick>body3*2 and
            lower_wick<body3*0.5 and
            range3>=atr*0.5):
            return True,'SHOOTING_STAR'

        # Bearish Engulfing
        o2=float(c2['open']);c2_=float(c2['close'])
        if (c2_>o2 and c3_<o3 and
            o3>=c2_ and c3_<=o2 and
            body3>abs(c2_-o2)*1.1 and
            range3>=atr*0.4):
            return True,'BEARISH_ENGULFING'

        # Evening Star (3 candles)
        o1=float(c1['open']);c1_=float(c1['close'])
        body1=abs(c1_-o1);body2=abs(float(c2['close'])-float(c2['open']))
        if (c1_>o1 and body1>atr*0.4 and  # Strong bullish
            body2<atr*0.2 and  # Small doji
            c3_<o3 and  # Bearish
            c3_<((o1+c1_)/2) and
            float(v.iloc[-1])>vol_avg*1.3):
            return True,'EVENING_STAR'

        # Dark Cloud Cover
        o2=float(c2['open']);c2_=float(c2['close'])
        if (c2_>o2 and c3_<o3 and
            o3>c2_ and
            c3_<((o2+c2_)/2) and
            c3_>o2 and
            body3>atr*0.3):
            return True,'DARK_CLOUD_COVER'

    return False,'NO_PATTERN'

# ============================================================
# MAIN SECONDARY SIGNAL
# ============================================================
def get_secondary_signal(df5,df15,action,atr):
    """
    Secondary signal:
    Need 2/3 confirmations + trend alignment
    1. Breakout
    2. Chart pattern
    3. Candlestick pattern
    """
    # Trend alignment check
    if not check_trend_alignment(df5,df15,action):
        return False,[],'TREND_MISALIGN'

    confirmations=[]
    pattern_info=[]

    # Breakout check
    bo,bo_type=detect_breakout(df5,action,atr)
    if bo:
        confirmations.append('BREAKOUT')
        pattern_info.append(bo_type)

    # Chart pattern check
    cp,cp_type=detect_chart_pattern(df5,action,atr)
    if cp:
        confirmations.append('CHART')
        pattern_info.append(cp_type)

    # Candlestick check
    cs,cs_type=detect_candlestick_pattern(df5,action,atr)
    if cs:
        confirmations.append('CANDLE')
        pattern_info.append(cs_type)

    # Check 15-min patterns too
    if len(df15)>=20:
        atr15=float((df15['high']-df15['low']).tail(14).mean())
        bo15,bo15t=detect_breakout(df15,action,atr15)
        cp15,cp15t=detect_chart_pattern(df15,action,atr15)
        if bo15:confirmations.append('BREAKOUT_15M');pattern_info.append(bo15t)
        if cp15:confirmations.append('CHART_15M');pattern_info.append(cp15t)

    # Need >= 2 confirmations
    if len(confirmations)>=2:
        log.info(f'[SEC] Secondary signal: {confirmations} {pattern_info}')
        return True,confirmations,pattern_info

    return False,confirmations,'INSUFFICIENT'
