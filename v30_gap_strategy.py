import logging
import pandas as pd
from datetime import datetime
log=logging.getLogger(__name__)

def detect_gap(df5,instrument):
    try:
        if len(df5)<5:return None
        now=datetime.now()
        if now.hour!=9 or now.minute>45:return None

        # First candle of day
        today=str(df5['time'].iloc[-1])[:10]
        today_candles=df5[df5['time'].astype(str).str[:10]==today]
        if len(today_candles)<1:return None

        today_open=today_candles['open'].iloc[0]
        prev_close=df5['close'].iloc[-20] if len(df5)>=20 else df5['close'].iloc[0]

        gap_pct=((today_open-prev_close)/prev_close)*100
        gap_pts=today_open-prev_close

        if abs(gap_pct)<0.3:return None

        gap_type='UP' if gap_pct>0 else 'DOWN'
        current=df5['close'].iloc[-1]

        # Check if gap still open
        if gap_type=='UP':
            gap_filled=current<=prev_close
            action='BUY'  # Trade with gap
        else:
            gap_filled=current>=prev_close
            action='SELL'  # Trade with gap

        if gap_filled:return None

        atr=(df5['high']-df5['low']).tail(5).mean()

        log.info(f'[GAP] {instrument} Gap {gap_type} {gap_pct:.2f}% ({gap_pts:.0f} pts)')

        return {
            'instrument':instrument,
            'gap_type':gap_type,
            'gap_pct':round(gap_pct,2),
            'gap_pts':round(gap_pts,2),
            'today_open':today_open,
            'prev_close':prev_close,
            'action':action,
            'option_type':'CE' if action=='BUY' else 'PE',
            'sl_points':atr*1.0,
            'target1':abs(gap_pts)*0.5,
            'target2':abs(gap_pts),
            'strategy':'GAP',
            'confidence':75
        }
    except Exception as e:
        log.error(f'[GAP] Error: {e}')
        return None

def get_gap_signals(feed,instruments):
    gap_signals=[]
    for inst in instruments:
        if inst not in ['NIFTY','BANKNIFTY','SENSEX','FINNIFTY']:continue
        df5=feed.get_candles(inst,'5')
        if df5 is None or len(df5)<5:continue
        gap=detect_gap(df5,inst)
        if gap:
            gap_signals.append(gap)
            log.info(f'[GAP] Signal: {inst} {gap["action"]} gap={gap["gap_pct"]}%')
    return gap_signals
