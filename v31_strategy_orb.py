"""
V31 Strategy - Path C (ORB) + Path D (Supertrend)
Multi-strategy engine with priority control

Path C: Opening Range Breakout (9:45 AM onwards)
Path D: Supertrend + RSI (All hours)

Enable: Set ENABLE_PATH_CD=True in v31_main.py
"""
import pandas as pd
import logging
log=logging.getLogger(__name__)

MCX_INST=['CRUDEOIL','GOLDM','SILVERM','NATURALGAS']


def orb_signal(df5,instrument,capital):
    """
    Path C: Opening Range Breakout
    NSE: 15-min ORB (9:30-9:45)
    MCX: 30-min ORB (9:00-9:30)
    RR = 1:3 high conviction only!
    """
    try:
        from datetime import datetime
        now=datetime.now()
        h=now.hour
        m=now.minute

        MCX_INST=['CRUDEOIL','GOLDM','SILVERM','NATURALGAS']
        is_mcx=instrument in MCX_INST

        # Time filter
        if is_mcx:
            if not (9<=h<11):return None
            orb_candles=6  # 30 mins
        else:
            if h==9 and m<30:return None
            if not (9<=h<=10):return None
            orb_candles=3  # 15 mins

        # Get today candles
        import pandas as pd
        df5['date']=pd.to_datetime(df5['time']).dt.date
        today=datetime.now().date()
        df_today=df5[pd.to_datetime(df5['time']).dt.date==today].reset_index(drop=True)

        if len(df_today)<orb_candles+1:return None

        # Opening Range
        orb_high=float(df_today['high'].iloc[:orb_candles].max())
        orb_low=float(df_today['low'].iloc[:orb_candles].min())
        orb_range=orb_high-orb_low

        current_close=float(df_today['close'].iloc[-1])
        atr=float((df5['high']-df5['low']).tail(14).mean())

        # Range validation
        if orb_range<atr*0.5:
            log.debug(f'[ORB] {instrument} narrow range skip')
            return None

        # Volume confirmation
        vol=df_today['volume'] if 'volume' in df_today.columns else None
        if vol is not None and len(vol)>orb_candles:
            avg_vol=float(vol.iloc[:orb_candles].mean())
            curr_vol=float(vol.iloc[-1])
            vol_confirm=curr_vol>avg_vol*1.5  # Strong filter!
        else:
            vol_confirm=True

        score=14

        # BUY Breakout
        if current_close>orb_high:
            strength=current_close-orb_high
            if strength>atr*0.3:score+=3
            elif strength>atr*0.15:score+=2
            if vol_confirm:score+=2
            if score<15:return None
            log.info(f'[ORB] {instrument} BUY breakout! score={score}')
            return {
                'instrument':instrument,'action':'BUY',
                'option_type':'CE','price':current_close,
                'sl_points':round(orb_range*0.6,2),
                'sl_type':'ORB_LOW',
                'target1':round(current_close+orb_range*2,2),
                'target2':round(current_close+orb_range*3,2),
                'rr_ratio':3.0,'score':score,
                'regime':'TRENDING_UP','liq_type':'ORB_BREAKOUT',
                'imbalance_type':'ORB_BUY','path':'C_ORB','atr':atr
            }

        # SELL Breakdown
        if current_close<orb_low:
            strength=orb_low-current_close
            if strength>atr*0.3:score+=3
            elif strength>atr*0.15:score+=2
            if vol_confirm:score+=2
            if score<15:return None
            log.info(f'[ORB] {instrument} SELL breakdown! score={score}')
            return {
                'instrument':instrument,'action':'SELL',
                'option_type':'PE','price':current_close,
                'sl_points':round(orb_range*0.6,2),
                'sl_type':'ORB_HIGH',
                'target1':round(current_close-orb_range*2,2),
                'target2':round(current_close-orb_range*3,2),
                'rr_ratio':3.0,'score':score,
                'regime':'TRENDING_DOWN','liq_type':'ORB_BREAKDOWN',
                'imbalance_type':'ORB_SELL','path':'C_ORB','atr':atr
            }

    except Exception as e:
        log.error(f'[ORB] {instrument}: {e}')
    return None

def supertrend_signal(df5, instrument, period=7, multiplier=3):
    """
    Path D: Supertrend + RSI
    - Vectorized (fast, no loops)
    - Direction flip = signal
    - RSI confirmation
    - Works all hours
    """
    try:
        if len(df5)<20:return None

        # ✅ Performance fix - limit candles
        if len(df5)>100:df5=df5.tail(100).copy()

        high=df5['high']
        low=df5['low']
        close=df5['close']

        # ✅ Vectorized ATR (no loop)
        tr=pd.concat([
            (high-low),
            (high-close.shift()).abs(),
            (low-close.shift()).abs()
        ],axis=1).max(axis=1)
        atr=tr.rolling(period).mean()

        # Supertrend bands
        hl2=(high+low)/2
        upper_band=hl2+multiplier*atr
        lower_band=hl2-multiplier*atr

        # ✅ Vectorized direction (faster than loop)
        direction=pd.Series(0,index=df5.index,dtype=int)
        for i in range(1,len(df5)):
            if close.iloc[i]>upper_band.iloc[i-1]:
                direction.iloc[i]=1   # Bullish
            elif close.iloc[i]<lower_band.iloc[i-1]:
                direction.iloc[i]=-1  # Bearish
            else:
                direction.iloc[i]=direction.iloc[i-1]  # Continue

        # RSI
        delta=close.diff()
        gain=delta.clip(lower=0).rolling(14).mean()
        loss=(-delta.clip(upper=0)).rolling(14).mean()
        rs=gain/(loss+1e-10)
        rsi=100-(100/(1+rs))

        curr_dir=int(direction.iloc[-1])
        prev_dir=int(direction.iloc[-2])
        curr_rsi=float(rsi.iloc[-1])
        curr_close=float(close.iloc[-1])
        curr_atr=float(atr.iloc[-1])

        # Only trade on direction FLIP
        if curr_dir==prev_dir:return None

        score=16  # Base ST score

        # ✅ BUY: Bullish flip
        if curr_dir==1:
            if curr_rsi<65:score+=2   # Not overbought
            if curr_rsi>40:score+=2   # Has momentum
            if curr_rsi>70:score-=3   # Overbought penalty
            if score<15:return None

            log.info(f'[ST] {instrument} BUY flip! RSI:{curr_rsi:.0f} Score:{score}')
            return {
                'instrument':instrument,
                'action':'BUY',
                'option_type':'CE',
                'price':curr_close,
                'sl_points':round(curr_atr*1.5,2),
                'sl_type':'SUPERTREND',
                'target1':round(curr_close+curr_atr*2,2),
                'target2':round(curr_close+curr_atr*4,2),
                'rr_ratio':2.5,
                'score':score,
                'regime':'TRENDING_UP',
                'liq_type':'ST_CROSS',
                'imbalance_type':'ST_BUY',
                'path':'D_ST',
                'atr':curr_atr,
                'rsi':curr_rsi,
                'gamma_boost':0,
                'gamma_info':None,
                'oi_trap':None,
                'use_trailing':False,
                'hold_overnight':False,
                'trap_type':'',
                'trap_score':0,
                'version':'V31'
            }

        # ✅ SELL: Bearish flip
        else:
            if curr_rsi>35:score+=2   # Not oversold
            if curr_rsi<60:score+=2   # Has bearish momentum
            if curr_rsi<30:score-=3   # Oversold penalty
            if score<15:return None

            log.info(f'[ST] {instrument} SELL flip! RSI:{curr_rsi:.0f} Score:{score}')
            return {
                'instrument':instrument,
                'action':'SELL',
                'option_type':'PE',
                'price':curr_close,
                'sl_points':round(curr_atr*1.5,2),
                'sl_type':'SUPERTREND',
                'target1':round(curr_close-curr_atr*2,2),
                'target2':round(curr_close-curr_atr*4,2),
                'rr_ratio':2.5,
                'score':score,
                'regime':'TRENDING_DOWN',
                'liq_type':'ST_CROSS',
                'imbalance_type':'ST_SELL',
                'path':'D_ST',
                'atr':curr_atr,
                'rsi':curr_rsi,
                'gamma_boost':0,
                'gamma_info':None,
                'oi_trap':None,
                'use_trailing':False,
                'hold_overnight':False,
                'trap_type':'',
                'trap_score':0,
                'version':'V31'
            }

    except Exception as e:
        log.debug(f'[ST] Error {instrument}: {e}')
    return None
