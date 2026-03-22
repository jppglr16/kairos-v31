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

        # Get today candles (safe copy!)
        import pandas as pd
        df_temp=df5.copy()  # Fix 1: don't mutate!
        today=datetime.now().date()
        # Fix 2: safe time column
        if 'time' in df_temp.columns:
            df_temp['date']=pd.to_datetime(df_temp['time']).dt.date
        else:
            df_temp['date']=df_temp.index.date
        df_today=df_temp[df_temp['date']==today].reset_index(drop=True)

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

        # Fix 3: Trend filter for better accuracy
        try:
            from v31_strategy import get_trend_v31
            _trend=get_trend_v31(df5)
        except:
            _trend='NEUTRAL'

        # BUY Breakout
        if current_close>orb_high:
            strength=current_close-orb_high
            if strength>atr*0.3:score+=3
            elif strength>atr*0.15:score+=2
            if vol_confirm:score+=2
            # Trend alignment bonus
            if _trend=='UP':score+=2
            elif _trend=='DOWN':score-=1  # Reduced penalty!
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
            # Trend alignment bonus
            if _trend=='DOWN':score+=2
            elif _trend=='UP':score-=1  # Reduced penalty!
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

def supertrend_signal(df5,instrument,period=7,multiplier=3):
    """
    Path D: Supertrend Signal
    Trades only on direction FLIP
    With RSI + Volume + Time + Trend filter
    """
    try:
        import pandas as pd
        import numpy as np
        from datetime import datetime
        now=datetime.now()
        h=now.hour

        # Time filter
        MCX_INST=['CRUDEOIL','GOLDM','SILVERM','NATURALGAS']
        is_mcx=instrument in MCX_INST
        if is_mcx:
            if not (9<=h<=23):return None
        else:
            if h<9 or h>15:return None
            if 12<=h<13:return None

        if len(df5)<period*3:return None

        close=df5['close']
        high=df5['high']
        low=df5['low']
        volume=df5['volume'] if 'volume' in df5.columns else None

        # True ATR
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

        # Fix 3: Numpy vectorized direction (no loop!)
        _dir=np.where(
            close>upper_band.shift(1),1,
            np.where(close<lower_band.shift(1),-1,np.nan)
        )
        direction=pd.Series(_dir).ffill().fillna(0).astype(int)

        # RSI
        delta=close.diff()
        gain=delta.clip(lower=0).rolling(14).mean()
        loss=(-delta.clip(upper=0)).rolling(14).mean()
        rsi=100-(100/(1+gain/(loss+1e-10)))

        curr_dir=int(direction.iloc[-1])
        prev_dir=int(direction.iloc[-2])
        curr_rsi=float(rsi.iloc[-1])
        curr_close=float(close.iloc[-1])
        curr_atr=float(atr.iloc[-1])

        # Safe NaN check!
        import numpy as np
        if np.isnan(curr_rsi) or np.isnan(curr_atr):
            log.debug(f'[ST] {instrument} NaN values skip')
            return None

        # Only on FLIP
        if curr_dir==prev_dir:return None

        # Bonus: Weak flip filter
        if abs(curr_close-float(close.iloc[-3]))<curr_atr*0.5:
            log.debug(f'[ST] {instrument} weak flip skip')
            return None

        # Volume confirmation
        if volume is not None:
            avg_vol=float(volume.tail(20).mean())
            curr_vol=float(volume.iloc[-1])
            if avg_vol>0 and curr_vol<avg_vol*1.2:
                log.debug(f'[ST] {instrument} low volume skip')
                return None

        # Trend alignment
        try:
            from v31_strategy import get_trend_v31
            trend=get_trend_v31(df5)
        except:
            trend='NEUTRAL'

        # Fix 4: Base score 14
        score=14

        # BUY: Bullish flip
        if curr_dir==1:
            # Fix 5: Clean RSI scoring
            if 40<curr_rsi<65:score+=3
            elif curr_rsi<=40:score+=1
            elif curr_rsi>=70:score-=3
            # Trend
            if trend=='UP':score+=2
            elif trend=='DOWN':score-=1
            if score<15:return None

            log.info(f'[ST] {instrument} BUY flip! RSI={curr_rsi:.0f} score={score}')
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
                'path':'D_SUPERTREND',  # Fix 1: correct tag!
                'atr':curr_atr,
                'version':'V31'
            }

        # SELL: Bearish flip
        else:
            # Fix 5: Clean RSI scoring
            if 35<curr_rsi<60:score+=3
            elif curr_rsi>=60:score+=1
            elif curr_rsi<=30:score-=3
            # Trend
            if trend=='DOWN':score+=2
            elif trend=='UP':score-=1
            if score<15:return None

            log.info(f'[ST] {instrument} SELL flip! RSI={curr_rsi:.0f} score={score}')
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
                'path':'D_SUPERTREND',  # Fix 1: correct tag!
                'atr':curr_atr,
                'version':'V31'
            }

    except Exception as e:
        log.error(f'[ST] {instrument}: {e}')
    return None
