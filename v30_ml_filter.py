"""
v30_ml_filter.py - ML Signal Filter for Kairos V30
Improves win rate by filtering low-quality signals using RandomForest
Auto-learns from trade outcomes over time
"""

import os, json, pickle, logging
import numpy as np
import pandas as pd
from datetime import datetime

log = logging.getLogger(__name__)

MODEL_FILE = 'v30_ml_model.pkl'
DATA_FILE  = 'v30_ml_data.json'
MIN_TRADES_FOR_ML = 30        # use ML only after 30 recorded trades
ML_CONFIDENCE_THRESHOLD = 0.58  # only trade if ML says >= 58% win prob

# ── Feature Engineering ────────────────────────────────────────────────────────

def _rsi(series, period=14):
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))

def _atr(df, period=14):
    hl  = df['high'] - df['low']
    hc  = (df['high'] - df['close'].shift()).abs()
    lc  = (df['low']  - df['close'].shift()).abs()
    tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def extract_features(df5, df15, signal):
    """Extract ~25 technical features from candle data + signal metadata."""
    feats = {}
    try:
        # ── 5-min features ──────────────────────────────────────────────────
        c5  = df5['close']
        rsi5 = _rsi(c5, 14).iloc[-1]
        ema9  = c5.ewm(span=9,  adjust=False).mean().iloc[-1]
        ema21 = c5.ewm(span=21, adjust=False).mean().iloc[-1]
        ema50 = c5.ewm(span=50, adjust=False).mean().iloc[-1]
        atr5  = _atr(df5, 14).iloc[-1]
        price = c5.iloc[-1]
        vol5  = df5['volume'].iloc[-5:].mean() / (df5['volume'].iloc[-20:-5].mean() + 1e-9)

        # Bollinger
        ma20  = c5.rolling(20).mean().iloc[-1]
        std20 = c5.rolling(20).std().iloc[-1]
        bb_pos = (price - (ma20 - 2*std20)) / (4*std20 + 1e-9)  # 0=lower, 1=upper

        # Candle body ratio
        last = df5.iloc[-1]
        body  = abs(last['close'] - last['open'])
        total = last['high'] - last['low'] + 1e-9
        body_ratio = body / total

        # Momentum
        mom5  = (price - c5.iloc[-6]) / (c5.iloc[-6] + 1e-9)
        mom20 = (price - c5.iloc[-21]) / (c5.iloc[-21] + 1e-9)

        feats.update({
            'rsi5':       float(rsi5),
            'ema_align5': float(1 if ema9 > ema21 > ema50 else -1 if ema9 < ema21 < ema50 else 0),
            'price_vs_ema9':  float((price - ema9)  / (atr5 + 1e-9)),
            'price_vs_ema21': float((price - ema21) / (atr5 + 1e-9)),
            'bb_pos':     float(bb_pos),
            'vol_ratio5': float(min(vol5, 5.0)),
            'body_ratio': float(body_ratio),
            'mom5':       float(mom5 * 100),
            'mom20':      float(mom20 * 100),
            'atr_pct5':   float(atr5 / (price + 1e-9) * 100),
        })

        # ── 15-min features ─────────────────────────────────────────────────
        c15   = df15['close']
        rsi15 = _rsi(c15, 14).iloc[-1]
        ema9_15  = c15.ewm(span=9,  adjust=False).mean().iloc[-1]
        ema21_15 = c15.ewm(span=21, adjust=False).mean().iloc[-1]
        ema50_15 = c15.ewm(span=50, adjust=False).mean().iloc[-1]
        atr15 = _atr(df15, 14).iloc[-1]
        vol15 = df15['volume'].iloc[-3:].mean() / (df15['volume'].iloc[-10:-3].mean() + 1e-9)

        # MACD on 15m
        ema12 = c15.ewm(span=12, adjust=False).mean()
        ema26 = c15.ewm(span=26, adjust=False).mean()
        macd  = ema12 - ema26
        signal_line = macd.ewm(span=9, adjust=False).mean()
        macd_hist = macd.iloc[-1] - signal_line.iloc[-1]

        feats.update({
            'rsi15':       float(rsi15),
            'ema_align15': float(1 if ema9_15 > ema21_15 > ema50_15 else -1 if ema9_15 < ema21_15 < ema50_15 else 0),
            'macd_hist':   float(macd_hist / (atr15 + 1e-9)),
            'vol_ratio15': float(min(vol15, 5.0)),
            'atr_pct15':   float(atr15 / (c15.iloc[-1] + 1e-9) * 100),
            'trend_align': float(1 if feats['ema_align5'] == feats['ema_align15'] else 0),
        })

        # ── Signal metadata ─────────────────────────────────────────────────
        now = datetime.now()
        feats.update({
            'confidence':  float(signal.get('confidence', 50)),
            'hour':        float(now.hour + now.minute / 60),
            'is_call':     float(1 if signal.get('option_type') == 'CE' else 0),
            'sl_ratio':    float(signal.get('sl_points', 50) / (atr5 + 1e-9)),
            'target_ratio':float(signal.get('target1', 100) / (signal.get('sl_points', 50) + 1e-9)),
        })

    except Exception as e:
        log.warning(f'[ML] Feature extraction error: {e}')

    return feats

# ── Data Store ─────────────────────────────────────────────────────────────────

def load_ml_data():
    if os.path.exists(DATA_FILE):
        try:
            return json.load(open(DATA_FILE))
        except:
            pass
    return {'features': [], 'labels': []}

def save_ml_data(data):
    try:
        json.dump(data, open(DATA_FILE, 'w'))
    except Exception as e:
        log.error(f'[ML] Save data error: {e}')

def record_trade_result(features, won: bool):
    """Call this after a trade closes to teach the ML model."""
    if not features:
        return
    data = load_ml_data()
    data['features'].append(features)
    data['labels'].append(1 if won else 0)
    save_ml_data(data)
    # Retrain if enough data
    n = len(data['labels'])
    if n >= MIN_TRADES_FOR_ML and n % 5 == 0:
        train_model(data)
    log.info(f'[ML] Recorded trade result: {"WIN" if won else "LOSS"} | Total: {n}')

# ── Model Training ─────────────────────────────────────────────────────────────

def train_model(data=None):
    try:
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import Pipeline
        from sklearn.model_selection import cross_val_score

        if data is None:
            data = load_ml_data()

        if len(data['labels']) < MIN_TRADES_FOR_ML:
            log.info(f'[ML] Not enough data ({len(data["labels"])}/{MIN_TRADES_FOR_ML})')
            return None

        # Build feature matrix
        all_keys = sorted(set(k for f in data['features'] for k in f))
        X = np.array([[f.get(k, 0.0) for k in all_keys] for f in data['features']])
        y = np.array(data['labels'])

        model = Pipeline([
            ('scaler', StandardScaler()),
            ('clf', GradientBoostingClassifier(
                n_estimators=100,
                max_depth=3,
                learning_rate=0.1,
                subsample=0.8,
                random_state=42
            ))
        ])

        # Cross-validate
        if len(y) >= 50:
            scores = cross_val_score(model, X, y, cv=5, scoring='accuracy')
            log.info(f'[ML] CV Accuracy: {scores.mean():.2%} ± {scores.std():.2%}')

        model.fit(X, y)

        # Save model + feature keys
        pickle.dump({'model': model, 'keys': all_keys}, open(MODEL_FILE, 'wb'))
        log.info(f'[ML] Model trained on {len(y)} trades | Win rate: {y.mean():.1%}')
        return model

    except Exception as e:
        log.error(f'[ML] Training error: {e}')
        return None

def load_model():
    if os.path.exists(MODEL_FILE):
        try:
            return pickle.load(open(MODEL_FILE, 'rb'))
        except:
            pass
    return None

# ── Signal Filter (Main API) ───────────────────────────────────────────────────

def ml_should_trade(df5, df15, signal) -> bool:
    """
    Returns True if ML approves the signal, False to skip.
    Falls back to rule-based filter if not enough data yet.
    """
    features = extract_features(df5, df15, signal)
    signal['_ml_features'] = features   # store for later outcome recording

    data = load_ml_data()
    n    = len(data['labels'])

    # ── Phase 1: Rule-based filter (< MIN_TRADES_FOR_ML trades) ────────────
    if n < MIN_TRADES_FOR_ML:
        result = _rule_based_filter(features, signal)
        log.info(f'[ML] Rule filter (trades={n}): {"PASS" if result else "SKIP"} | {signal["instrument"]}')
        return result

    # ── Phase 2: ML filter ──────────────────────────────────────────────────
    bundle = load_model()
    if bundle is None:
        bundle_new = train_model(data)
        if bundle_new is None:
            return _rule_based_filter(features, signal)
        bundle = load_model()

    try:
        model = bundle['model']
        keys  = bundle['keys']
        X     = np.array([[features.get(k, 0.0) for k in keys]])
        prob  = model.predict_proba(X)[0][1]   # probability of WIN
        signal['_ml_prob'] = float(prob)

        result = prob >= ML_CONFIDENCE_THRESHOLD
        log.info(f'[ML] Prob={prob:.1%} | {"✅ PASS" if result else "❌ SKIP"} | {signal["instrument"]} {signal.get("option_type")}')
        return result

    except Exception as e:
        log.error(f'[ML] Predict error: {e}')
        return _rule_based_filter(features, signal)

def _rule_based_filter(features, signal) -> bool:
    """
    Strong rule-based filter used before ML has enough data.
    Only trades high-quality setups.
    """
    is_call  = signal.get('option_type') == 'CE'
    rsi5     = features.get('rsi5', 50)
    rsi15    = features.get('rsi15', 50)
    align5   = features.get('ema_align5', 0)
    align15  = features.get('ema_align15', 0)
    macd_h   = features.get('macd_hist', 0)
    vol5     = features.get('vol_ratio5', 1)
    vol15    = features.get('vol_ratio15', 1)
    conf     = features.get('confidence', 50)
    hour     = features.get('hour', 12)
    tgt_rat  = features.get('target_ratio', 1)
    bb       = features.get('bb_pos', 0.5)
    trend_ok = features.get('trend_align', 0)

    reasons_skip = []

    # 1. Minimum signal confidence
    if conf < 55:
        reasons_skip.append(f'low_conf={conf:.0f}')

    # 2. RSI extremes — avoid chasing
    if is_call  and rsi5 > 75: reasons_skip.append(f'rsi5_overbought={rsi5:.0f}')
    if not is_call and rsi5 < 25: reasons_skip.append(f'rsi5_oversold={rsi5:.0f}')

    # 3. Trend alignment: both TFs should agree
    if is_call  and align5 < 0:  reasons_skip.append('5m_bearish')
    if not is_call and align5 > 0: reasons_skip.append('5m_bullish')
    if is_call  and align15 < 0: reasons_skip.append('15m_bearish')
    if not is_call and align15 > 0: reasons_skip.append('15m_bullish')

    # 4. MACD confirmation
    if is_call  and macd_h < -0.3: reasons_skip.append(f'macd_bearish={macd_h:.2f}')
    if not is_call and macd_h > 0.3:  reasons_skip.append(f'macd_bullish={macd_h:.2f}')

    # 5. Volume confirmation
    if vol5 < 0.8:
        reasons_skip.append(f'low_volume={vol5:.2f}')

    # 6. Avoid first 15 min (9:15–9:30) and last 30 min (14:45–15:15)
    if hour < 9.5 or hour > 14.75:
        reasons_skip.append(f'bad_time={hour:.2f}')

    # 7. Reward/risk must be at least 1.5
    if tgt_rat < 1.5:
        reasons_skip.append(f'poor_rr={tgt_rat:.2f}')

    # 8. Avoid BB extremes (already stretched)
    if is_call  and bb > 0.85: reasons_skip.append(f'bb_extended={bb:.2f}')
    if not is_call and bb < 0.15: reasons_skip.append(f'bb_extended={bb:.2f}')

    if reasons_skip:
        log.info(f'[ML] SKIP {signal["instrument"]}: {", ".join(reasons_skip)}')
        return False

    return True

# ── Convenience wrapper for exit_trade ────────────────────────────────────────

def ml_record_outcome(trade, pnl):
    """Call after trade closes to record WIN/LOSS for model learning."""
    features = trade.get('signal', {}).get('_ml_features', {})
    if features:
        record_trade_result(features, won=(pnl > 0))

# ── Model Status ───────────────────────────────────────────────────────────────

def ml_status():
    data  = load_ml_data()
    n     = len(data['labels'])
    wins  = sum(data['labels'])
    model = load_model()
    return {
        'trades_recorded': n,
        'historical_winrate': f'{wins/n:.1%}' if n > 0 else 'N/A',
        'ml_active': model is not None and n >= MIN_TRADES_FOR_ML,
        'mode': 'ML' if (model and n >= MIN_TRADES_FOR_ML) else 'Rules',
        'trades_until_ml': max(0, MIN_TRADES_FOR_ML - n),
    }
