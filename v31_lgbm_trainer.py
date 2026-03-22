"""V31 LightGBM Trainer - Faster + Better than GBM"""
import json,os,pickle,logging
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
from datetime import datetime

logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')
log=logging.getLogger(__name__)

try:
    from v31_instrument_manager import INSTRUMENTS
except:
    INSTRUMENTS={'NIFTY':{'lot':65}}

def load_data(symbol):
    """Load all historical candles for symbol"""
    import os,json as _json
    all_candles=[]
    try:
        all_files=os.listdir("historical_data")
        sym_clean=symbol.replace("-","")
        matching=[]
        for f in all_files:
            if (f.startswith(f"{symbol}_") or f.startswith(f"{sym_clean}_")) and f.endswith("_5min.json"):
                matching.append(f)
        for fname in sorted(matching):
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

def extract_features(df,idx):
    try:
        if idx<50:return None
        w=df.iloc[max(0,idx-50):idx+1]
        c=w['close'];h=w['high'];l=w['low']
        v=w.get('volume',pd.Series([1]*len(w)))
        cur=float(c.iloc[-1])
        atr=float((h-l).tail(14).mean())
        if atr==0:return None
        delta=c.diff()
        gain=delta.clip(lower=0).rolling(14).mean()
        loss=(-delta.clip(upper=0)).rolling(14).mean()
        rsi=float((100-(100/(1+gain/loss))).iloc[-1])
        ema9=float(c.ewm(span=9).mean().iloc[-1])
        ema21=float(c.ewm(span=21).mean().iloc[-1])
        ema50=float(c.ewm(span=50).mean().iloc[-1]) if len(c)>=50 else ema21
        e12=c.ewm(span=12).mean();e26=c.ewm(span=26).mean()
        macd=float((e12-e26).iloc[-1])
        sig=float((e12-e26).ewm(span=9).mean().iloc[-1])
        sma20=float(c.rolling(20).mean().iloc[-1])
        std20=float(c.rolling(20).std().iloc[-1])
        bb_pos=(cur-sma20)/(2*std20) if std20>0 else 0
        hi14=float(h.rolling(14).max().iloc[-1])
        lo14=float(l.rolling(14).min().iloc[-1])
        pp=(cur-lo14)/(hi14-lo14) if hi14>lo14 else 0.5
        avg_vol=float(v.rolling(20).mean().iloc[-1]) or 1
        vr=float(v.iloc[-1])/avg_vol
        body=abs(float(c.iloc[-1])-float(w['open'].iloc[-1]))
        fr=float(h.iloc[-1])-float(l.iloc[-1])
        br=body/fr if fr>0 else 0
        trend=1 if cur>ema21 else -1
        ea=1 if ema9>ema21>ema50 else(-1 if ema9<ema21<ema50 else 0)
        try:dow=pd.to_datetime(w.iloc[-1]['time']).weekday()
        except:dow=2
        feats=[
            rsi/100,float(macd-sig)/atr,bb_pos,pp,vr,br,
            trend,ea,atr/cur if cur>0 else 0,
            (cur-ema9)/atr,(cur-ema21)/atr,(cur-ema50)/atr,
            float(c.pct_change(1).iloc[-1]),
            float(c.pct_change(3).iloc[-1]),
            float(c.pct_change(5).iloc[-1]),
            float((h-l).iloc[-1])/atr,
            float((h-l).iloc[-2])/atr if len(w)>2 else 1,
            float((h-l).iloc[-3])/atr if len(w)>3 else 1,
            1 if macd>sig else 0,1 if rsi>50 else 0,
            1 if cur>sma20 else 0,float(vr>1.5),dow/4,
            float(c.rolling(5).std().iloc[-1])/atr,
            float(c.rolling(10).std().iloc[-1])/atr,
            float(h.tail(5).max()-l.tail(5).min())/atr,
            float(c.diff().tail(5).mean())/atr,
            float(br>0.6),float(pp>0.7),float(pp<0.3),
        ]
        return [float(f) if not np.isnan(float(f)) else 0 for f in feats]
    except:return None

def label_outcome(df,idx,action,atr):
    try:
        entry=float(df['close'].iloc[idx])
        sl=entry-(atr*1.5) if action=='BUY' else entry+(atr*1.5)
        t1=entry+(atr*2.0) if action=='BUY' else entry-(atr*2.0)
        for i in range(idx+1,min(idx+30,len(df))):
            hi=float(df['high'].iloc[i])
            lo=float(df['low'].iloc[i])
            if action=='BUY':
                if lo<=sl:return 0
                if hi>=t1:return 1
            else:
                if hi>=sl:return 0
                if lo<=t1:return 1
        return 0
    except:return 0

def train_lgbm(symbol):
    log.info(f'[LGBM] Training {symbol}...')
    candles=load_data(symbol)
    if not candles:
        log.warning(f'[LGBM] {symbol}: No data!')
        return False
    df=to_df(candles)
    if df is None or len(df)<200:return False
    log.info(f'[LGBM] {symbol}: {len(df):,} candles')
    atr=float((df['high']-df['low']).tail(100).mean())
    X,y=[],[]
    for idx in range(50,len(df)-30,5):
        feats=extract_features(df,idx)
        if feats is None:continue
        action='BUY' if idx%20<10 else 'SELL'
        y.append(label_outcome(df,idx,action,atr))
        X.append(feats)
    if len(X)<50:return False
    X=np.array(X);y=np.array(y)
    log.info(f'[LGBM] {symbol}: {len(X)} samples WR={y.mean():.1%}')
    X_tr,X_te,y_tr,y_te=train_test_split(X,y,test_size=0.2,random_state=42)
    model=lgb.LGBMClassifier(
        n_estimators=500,
        max_depth=6,
        learning_rate=0.05,
        num_leaves=31,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbosity=-1
    )
    model.fit(X_tr,y_tr)
    acc=accuracy_score(y_te,model.predict(X_te))
    log.info(f'[LGBM] {symbol}: Accuracy={acc:.1%}')
    os.makedirs('ml_models',exist_ok=True)
    pickle.dump({'model':model,'type':'lgbm','accuracy':acc,
                 'trained':datetime.now().isoformat()},
                open(f'ml_models/{symbol}_v31_lgbm.pkl','wb'))
    log.info(f'[LGBM] {symbol}: Saved ✅')
    return True

if __name__=='__main__':
    log.info('=== V31 LightGBM Training ===')
    success=0;failed=[]
    for sym in INSTRUMENTS:
        try:
            if train_lgbm(sym):success+=1
            else:failed.append(sym)
        except Exception as e:
            log.error(f'{sym}: {e}')
            failed.append(sym)
    log.info(f'Done! {success}/{len(INSTRUMENTS)} trained')
    if failed:log.info(f'Failed: {failed}')
