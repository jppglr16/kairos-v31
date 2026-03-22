"""
V31 Fresh ML Trainer
Trains GradientBoostingClassifier for all 36 instruments
Uses v31_strategy signals + outcome labeling
"""
import json,os,pickle,logging
import numpy as np
import pandas as pd
from datetime import datetime
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score

logging.basicConfig(level=logging.INFO,
    format='%(asctime)s %(message)s')
log=logging.getLogger(__name__)

# ============================================================
# LOAD INSTRUMENTS
# ============================================================
try:
    from v31_instrument_manager import INSTRUMENTS
    log.info(f'Loaded {len(INSTRUMENTS)} instruments')
except:
    INSTRUMENTS={'NIFTY':{'lot':65},'BANKNIFTY':{'lot':30}}

# ============================================================
# LOAD DATA
# ============================================================
def load_data(symbol):
    """Load historical candles - scans all matching files"""
    import os,json as _json
    all_candles=[]
    try:
        all_files=os.listdir("historical_data")
        matching=sorted([f for f in all_files
                  if f.startswith(f"{symbol}_")
                  and f.endswith("_5min.json")])
        for fname in matching:
            fpath=f"historical_data/{fname}"
            try:
                data=_json.load(open(fpath))
                all_candles.extend(data)
            except:pass
        if all_candles:
            unique={}
            for c in all_candles:
                unique[c[0]]=c
            all_candles=sorted(unique.values(),key=lambda x:x[0])
    except:pass
    return all_candles

def to_df(candles):
    if not candles:return None
    df=pd.DataFrame(candles)
    if len(df.columns)>=6:
        df.columns=['time','open','high','low','close','volume']+list(df.columns[6:])
    for col in ['open','high','low','close','volume']:
        if col in df.columns:
            df[col]=pd.to_numeric(df[col],errors='coerce')
    return df.dropna(subset=['open','high','low','close']).reset_index(drop=True)

# ============================================================
# FEATURE EXTRACTION
# ============================================================
def extract_features(df, idx):
    """Extract 30 features from candle data at index idx"""
    try:
        if idx<50:return None
        window=df.iloc[max(0,idx-50):idx+1]
        c=window['close']
        h=window['high']
        l=window['low']
        v=window.get('volume',pd.Series([1]*len(window)))

        cur=float(c.iloc[-1])
        atr=float((h-l).tail(14).mean())
        if atr==0:return None

        # RSI
        delta=c.diff()
        gain=delta.clip(lower=0).rolling(14).mean()
        loss=(-delta.clip(upper=0)).rolling(14).mean()
        rsi=float((100-(100/(1+gain/loss))).iloc[-1])

        # EMAs
        ema9=float(c.ewm(span=9).mean().iloc[-1])
        ema21=float(c.ewm(span=21).mean().iloc[-1])
        ema50=float(c.ewm(span=50).mean().iloc[-1]) if len(c)>=50 else ema21

        # MACD
        e12=c.ewm(span=12).mean()
        e26=c.ewm(span=26).mean()
        macd=float((e12-e26).iloc[-1])
        signal_line=float((e12-e26).ewm(span=9).mean().iloc[-1])
        macd_hist=macd-signal_line

        # Bollinger
        sma20=float(c.rolling(20).mean().iloc[-1])
        std20=float(c.rolling(20).std().iloc[-1])
        bb_pos=(cur-sma20)/(2*std20) if std20>0 else 0

        # Price position
        hi14=float(h.rolling(14).max().iloc[-1])
        lo14=float(l.rolling(14).min().iloc[-1])
        price_pos=(cur-lo14)/(hi14-lo14) if hi14>lo14 else 0.5

        # Volume
        avg_vol=float(v.rolling(20).mean().iloc[-1]) if float(v.rolling(20).mean().iloc[-1])>0 else 1
        vol_ratio=float(v.iloc[-1])/avg_vol

        # Candle patterns
        body=abs(float(c.iloc[-1])-float(window['open'].iloc[-1]))
        full_range=float(h.iloc[-1])-float(l.iloc[-1])
        body_ratio=body/full_range if full_range>0 else 0

        # Trend
        trend=1 if cur>ema21 else -1
        ema_align=1 if ema9>ema21>ema50 else (-1 if ema9<ema21<ema50 else 0)

        # ATR ratio
        atr_ratio=atr/cur if cur>0 else 0

        # Day of week
        try:
            dow=pd.to_datetime(window.iloc[-1]['time']).weekday()
        except:
            dow=2

        features=[
            rsi/100, macd_hist/atr, bb_pos,
            price_pos, vol_ratio, body_ratio,
            trend, ema_align, atr_ratio,
            (cur-ema9)/atr, (cur-ema21)/atr, (cur-ema50)/atr,
            float(c.pct_change(1).iloc[-1]),
            float(c.pct_change(3).iloc[-1]),
            float(c.pct_change(5).iloc[-1]),
            float((h-l).iloc[-1])/atr,
            float((h-l).iloc[-2])/atr if len(window)>2 else 1,
            float((h-l).iloc[-3])/atr if len(window)>3 else 1,
            1 if macd>signal_line else 0,
            1 if rsi>50 else 0,
            1 if cur>sma20 else 0,
            vol_ratio>1.5,
            dow/4,
            float(c.rolling(5).std().iloc[-1])/atr,
            float(c.rolling(10).std().iloc[-1])/atr,
            float(h.tail(5).max()-l.tail(5).min())/atr,
            float(c.diff().tail(5).mean())/atr,
            1 if body_ratio>0.6 else 0,
            price_pos>0.7,
            price_pos<0.3,
        ]
        # S/R Features (7 new!)
        try:
            from v31_support_resistance import sr_engine
            _price=float(c.iloc[-1])
            _hl=window["high"]-window["low"]
            _hc=(window["high"]-window["close"].shift()).abs()
            _lc=(window["low"]-window["close"].shift()).abs()
            import pandas as _pd
            _tr=_pd.concat([_hl,_hc,_lc],axis=1).max(axis=1)
            _atr_raw=_tr.rolling(14).mean().iloc[-1]
            if __import__("pandas").isna(_atr_raw):
                _atr_raw=float((_hl).tail(14).mean())
            _atr=max(float(_atr_raw),1e-6)
            _levels=sr_engine.get_all_levels(window,_price)
            _r1=_levels.get("R1",_price+_atr)
            _s1=_levels.get("S1",_price-_atr)
            _pdh=_levels.get("PDH",_price+_atr)
            _pdl=_levels.get("PDL",_price-_atr)
            _pp=_levels.get("PP",_price)
            _rr=_levels.get("round_resistance",_price+_atr)
            _rs=_levels.get("round_support",_price-_atr)
            _dr1=max(min((_r1-_price)/_atr,5.0),-5.0)
            _ds1=max(min((_price-_s1)/_atr,5.0),-5.0)
            _dpdh=max(min((_pdh-_price)/_atr,5.0),-5.0)
            _dpdl=max(min((_price-_pdl)/_atr,5.0),-5.0)
            _app=1.0 if _price>_pp else 0.0
            _nr=1.0 if abs(_price-_rr)<_atr or abs(_price-_rs)<_atr else 0.0
            _bz=1.0 if (_price>_r1 or _price<_s1) else 0.0
            features.extend([_dr1,_ds1,_dpdh,_dpdl,_app,_nr,_bz])
        except:
            features.extend([1.0,1.0,1.0,1.0,0.5,0.0,0.0])

        return [float(f) if not np.isnan(float(f)) else 0 for f in features]
    except:
        return None

# ============================================================
# LABEL OUTCOMES
# ============================================================
def label_outcome(df, entry_idx, action, atr):
    """Check if trade was win or loss"""
    try:
        entry=float(df['close'].iloc[entry_idx])
        sl=entry-(atr*1.5) if action=='BUY' else entry+(atr*1.5)
        t1=entry+(atr*2.0) if action=='BUY' else entry-(atr*2.0)

        # Check next 30 candles
        for i in range(entry_idx+1, min(entry_idx+30, len(df))):
            hi=float(df['high'].iloc[i])
            lo=float(df['low'].iloc[i])
            if action=='BUY':
                if lo<=sl:return 0  # SL hit
                if hi>=t1:return 1  # Target hit
            else:
                if hi>=sl:return 0
                if lo<=t1:return 1
        return 0  # Time exit = loss
    except:
        return 0

# ============================================================
# TRAIN ONE INSTRUMENT
# ============================================================
def train_instrument(symbol):
    log.info(f'Training {symbol}...')

    candles=load_data(symbol)
    if not candles:
        log.warning(f'{symbol}: No data!')
        return False

    df=to_df(candles)
    if df is None or len(df)<200:
        log.warning(f'{symbol}: Not enough data ({len(df) if df is not None else 0} candles)')
        return False

    log.info(f'{symbol}: {len(df)} candles loaded')

    # Generate features + labels
    X,y=[],[]
    atr_global=float((df['high']-df['low']).tail(100).mean())

    # Sample every 10 candles for speed
    for idx in range(50, len(df)-30, 10):
        features=extract_features(df,idx)
        if features is None:continue

        # Alternate BUY/SELL
        action='BUY' if idx%20<10 else 'SELL'
        label=label_outcome(df,idx,action,atr_global)

        X.append(features)
        y.append(label)

    if len(X)<50:
        log.warning(f'{symbol}: Not enough samples ({len(X)})')
        return False

    X=np.array(X)
    y=np.array(y)

    log.info(f'{symbol}: {len(X)} samples | WR={y.mean():.1%}')

    # Train/test split
    X_train,X_test,y_train,y_test=train_test_split(
        X,y,test_size=0.2,random_state=42)

    # Scale
    scaler=StandardScaler()
    X_train=scaler.fit_transform(X_train)
    X_test=scaler.transform(X_test)

    # Train
    model=GradientBoostingClassifier(
        n_estimators=500,
        max_depth=5,
        learning_rate=0.05,
        random_state=42
    )
    model.fit(X_train,y_train)

    # Evaluate
    acc=accuracy_score(y_test,model.predict(X_test))
    log.info(f'{symbol}: Accuracy={acc:.1%}')

    # Save
    os.makedirs('ml_models',exist_ok=True)
    model_path=f'ml_models/{symbol}_v31_ml.pkl'
    pickle.dump({'model':model,'scaler':scaler,'accuracy':acc,
                 'trained':datetime.now().isoformat()},
                open(model_path,'wb'))
    log.info(f'{symbol}: Saved to {model_path} ✅')
    return True

# ============================================================
# MAIN
# ============================================================
if __name__=='__main__':
    log.info('=== V31 Fresh ML Training ===')
    log.info(f'Instruments: {len(INSTRUMENTS)}')

    success=0
    failed=[]

    for symbol in INSTRUMENTS:
        try:
            ok=train_instrument(symbol)
            if ok:
                success+=1
            else:
                failed.append(symbol)
        except Exception as e:
            log.error(f'{symbol}: Error {e}')
            failed.append(symbol)

    log.info(f'=== Training Complete ===')
    log.info(f'Success: {success}/{len(INSTRUMENTS)}')
    if failed:
        log.info(f'Failed: {failed}')
