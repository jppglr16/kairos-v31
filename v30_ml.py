import numpy as np
import pandas as pd
import json,os
from datetime import datetime

def extract_features(df5, df15):
    try:
        f = {}
        c5 = df5['close'].values
        h5 = df5['high'].values
        l5 = df5['low'].values
        v5 = df5['volume'].values

        # Price features
        f['ret_1'] = (c5[-1]-c5[-2])/c5[-2]
        f['ret_3'] = (c5[-1]-c5[-4])/c5[-4]
        f['ret_5'] = (c5[-1]-c5[-6])/c5[-6]

        # Volatility
        f['atr'] = np.mean(h5[-14:]-l5[-14:])
        f['atr_norm'] = f['atr']/c5[-1]

        # Volume
        f['vol_ratio'] = v5[-1]/np.mean(v5[-20:]) if np.mean(v5[-20:])>0 else 1

        # RSI
        d = np.diff(c5)
        g = np.where(d>0,d,0)
        l = np.where(d<0,-d,0)
        rsi = 100-(100/(1+np.mean(g[-14:])/np.mean(l[-14:]))) if np.mean(l[-14:])>0 else 50
        f['rsi'] = rsi
        f['rsi_norm'] = (rsi-50)/50

        # MACD
        ema12 = pd.Series(c5).ewm(span=12).mean().values
        ema26 = pd.Series(c5).ewm(span=26).mean().values
        macd = ema12-ema26
        f['macd'] = macd[-1]
        f['macd_signal'] = pd.Series(macd).ewm(span=9).mean().values[-1]
        f['macd_hist'] = f['macd']-f['macd_signal']

        # Trend strength
        c15 = df15['close'].values
        f['trend15'] = (c15[-1]-c15[-5])/c15[-5] if len(c15)>=5 else 0
        f['trend5'] = (c5[-1]-c5[-5])/c5[-5] if len(c5)>=5 else 0

        # Candle pattern
        f['body'] = abs(df5['close'].iloc[-1]-df5['open'].iloc[-1])
        f['upper_wick'] = h5[-1]-max(df5['close'].iloc[-1],df5['open'].iloc[-1])
        f['lower_wick'] = min(df5['close'].iloc[-1],df5['open'].iloc[-1])-l5[-1]
        f['bullish_candle'] = 1 if df5['close'].iloc[-1]>df5['open'].iloc[-1] else 0

        # Hour of day
        f['hour'] = datetime.now().hour
        f['is_morning'] = 1 if 9<=f['hour']<=11 else 0
        f['is_afternoon'] = 1 if 12<=f['hour']<=14 else 0

        return f
    except Exception as e:
        print(f'[ML] Feature error: {e}')
        return None

def rule_based_predict(features, oi_data=None, sentiment=0):
    if not features: return 0.5, 'NEUTRAL'
    score = 0.5

    # RSI signal
    if features['rsi'] < 35: score += 0.1
    elif features['rsi'] > 65: score -= 0.1

    # MACD signal
    if features['macd_hist'] > 0: score += 0.08
    else: score -= 0.08

    # Trend alignment
    if features['trend15'] > 0 and features['trend5'] > 0: score += 0.1
    elif features['trend15'] < 0 and features['trend5'] < 0: score -= 0.1

    # Volume confirmation
    if features['vol_ratio'] > 1.5: score += 0.05

    # Sentiment
    score += sentiment * 0.1

    # OI/PCR
    if oi_data:
        if oi_data.get('pcr_bias') == 'BULLISH': score += 0.1
        elif oi_data.get('pcr_bias') == 'BEARISH': score -= 0.1
        if oi_data.get('oi_bias') == 'BULLISH': score += 0.08
        elif oi_data.get('oi_bias') == 'BEARISH': score -= 0.08

    score = max(0.1, min(0.9, score))
    if score > 0.6: direction = 'BULLISH'
    elif score < 0.4: direction = 'BEARISH'
    else: direction = 'NEUTRAL'

    return score, direction

def train_from_history():
    try:
        if not os.path.exists('v30_trades.json'): return None
        trades = json.load(open('v30_trades.json'))
        if len(trades) < 10:
            print(f'[ML] Only {len(trades)} trades - need 10+ to train')
            return None
        print(f'[ML] Training on {len(trades)} trades...')
        # Will implement sklearn model after 10+ trades
        return None
    except Exception as e:
        print(f'[ML] Train error: {e}')
        return None
