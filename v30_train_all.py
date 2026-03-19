import json,os,pickle,time
import numpy as np
import pandas as pd
from datetime import datetime

INSTRUMENTS={
    # Indices
    'NIFTY':     {'type':'index','lot':75},
    'BANKNIFTY': {'type':'index','lot':30},
    'SENSEX':    {'type':'index','lot':10},
    'FINNIFTY':  {'type':'index','lot':65},
    'MIDCPNIFTY':{'type':'index','lot':120},
    'CRUDEOIL':  {'type':'commodity','lot':100},
    'GOLDM':     {'type':'commodity','lot':10},
    'SILVERM':   {'type':'commodity','lot':30},
    # Stocks
    'LT':        {'type':'stock','lot':450},
    'NTPC':      {'type':'stock','lot':4500},
    'MARUTI':    {'type':'stock','lot':100},
    'BHARTIARTL':{'type':'stock','lot':950},
    'SBIN':      {'type':'stock','lot':1500},
    'TATAMOTORS':{'type':'stock','lot':1350},
    'RELIANCE':  {'type':'stock','lot':250},
    'HINDUNILVR':{'type':'stock','lot':300},
    'TCS':       {'type':'stock','lot':150},
    'TATASTEEL': {'type':'stock','lot':5500},
}

STOCK_TOKENS={
    'SENSEX':'99919000',
    'FINNIFTY':'99926037',
    'MIDCPNIFTY':'99926074',
    'GOLDM':'477904',
    'SILVERM':'457533',
    'LT':'11483','NTPC':'11630','MARUTI':'10999',
    'BHARTIARTL':'10604','SBIN':'3045','TATAMOTORS':'3456',
    'RELIANCE':'2885','HINDUNILVR':'1394','TCS':'11536',
    'TATASTEEL':'3499',
}

def load_data(symbol):
    all_candles=[]
    for year in [2022,2023,2024]:
        # Try direct name
        fname=f'historical_data/{symbol}_{year}_5min.json'
        if not os.path.exists(fname):
            # Try token
            token=STOCK_TOKENS.get(symbol,'')
            if token:
                fname=f'historical_data/{token}_{year}_5min.json'
        if os.path.exists(fname):
            data=json.load(open(fname))
            all_candles.extend(data)
    return all_candles

def to_df(candles):
    if not candles:return None
    df=pd.DataFrame(candles)
    if len(df.columns)==6:
        df.columns=['time','open','high','low','close','volume']
    for col in ['open','high','low','close','volume']:
        df[col]=pd.to_numeric(df[col],errors='coerce')
    return df.dropna().reset_index(drop=True)

def calc_rsi(s,p=14):
    d=s.diff()
    g=d.clip(lower=0).rolling(p).mean()
    l=-d.clip(upper=0).rolling(p).mean()
    return 100-(100/(1+g/l))

def calc_macd(s):
    e12=s.ewm(span=12).mean()
    e26=s.ewm(span=26).mean()
    m=e12-e26
    return m,m.ewm(span=9).mean()

def get_trend(df):
    try:
        c=df['close']
        s20=c.rolling(20).mean().iloc[-1]
        s50=c.rolling(50).mean().iloc[-1] if len(c)>=50 else s20
        cur=c.iloc[-1]
        if cur>s20 and s20>s50:return 1
        elif cur<s20 and s20<s50:return -1
        return 0
    except:return 0

def extract_features(df5,df15,action):
    try:
        c=df5['close'];h=df5['high'];l=df5['low'];v=df5['volume']
        if len(c)<20:return None

        rsi=calc_rsi(c).iloc[-1]
        macd,sig=calc_macd(c)
        macd_hist=(macd-sig).iloc[-1]
        atr=(h-l).tail(14).mean()
        vol_avg=v.rolling(20).mean().iloc[-1]
        vol_ratio=v.iloc[-1]/vol_avg if vol_avg>0 else 1

        # Price features
        ret1=(c.iloc[-1]-c.iloc[-2])/c.iloc[-2]
        ret5=(c.iloc[-1]-c.iloc[-6])/c.iloc[-6] if len(c)>6 else 0
        ret10=(c.iloc[-1]-c.iloc[-11])/c.iloc[-11] if len(c)>11 else 0
        ret20=(c.iloc[-1]-c.iloc[-21])/c.iloc[-21] if len(c)>21 else 0

        # Trend features
        trend5=get_trend(df5)
        trend15=get_trend(df15)
        trend_aligned=1 if (action=='BUY' and trend15==1) or (action=='SELL' and trend15==-1) else 0

        # Momentum features
        sma20=c.rolling(20).mean().iloc[-1]
        sma50=c.rolling(50).mean().iloc[-1] if len(c)>=50 else sma20
        above_sma20=1 if c.iloc[-1]>sma20 else 0
        above_sma50=1 if c.iloc[-1]>sma50 else 0

        # Volatility
        atr_norm=atr/c.iloc[-1] if c.iloc[-1]>0 else 0
        bb_std=c.rolling(20).std().iloc[-1]
        bb_upper=sma20+2*bb_std
        bb_lower=sma20-2*bb_std
        bb_position=(c.iloc[-1]-bb_lower)/(bb_upper-bb_lower) if (bb_upper-bb_lower)>0 else 0.5

        # Candle pattern
        last=df5.iloc[-1]
        body=abs(last['close']-last['open'])
        candle_range=last['high']-last['low']
        body_ratio=body/candle_range if candle_range>0 else 0
        bullish=1 if last['close']>last['open'] else 0

        # Swing levels
        swing_high=h.tail(20).max()
        swing_low=l.tail(20).min()
        swing_range=swing_high-swing_low
        swing_pos=(c.iloc[-1]-swing_low)/swing_range if swing_range>0 else 0.5

        # FVG
        fvg=0
        for i in range(len(df5)-3,len(df5)-1):
            if i<2:continue
            p2=df5.iloc[i-2];cur=df5.iloc[i]
            if action=='BUY' and cur['low']>p2['high']:fvg=1;break
            elif action=='SELL' and cur['high']<p2['low']:fvg=1;break

        # Stochastic
        low14=l.rolling(14).min()
        high14=h.rolling(14).max()
        stoch=((c-low14)/(high14-low14)*100).iloc[-1] if (high14-low14).iloc[-1]>0 else 50

        # Hour
        try:hour=int(str(df5['time'].iloc[-1])[11:13])/24
        except:hour=0.4

        # Action
        action_val=1 if action=='BUY' else -1

        features=[
            # Price momentum (4)
            ret1,ret5,ret10,ret20,
            # RSI (2)
            rsi/100,(rsi-50)/50,
            # MACD (2)
            macd_hist/atr if atr>0 else 0,
            1 if macd_hist>0 else -1,
            # Volume (2)
            min(vol_ratio,3)/3,
            1 if vol_ratio>1.5 else 0,
            # Trend (3)
            trend5,trend15,trend_aligned,
            # MA position (2)
            above_sma20,above_sma50,
            # Volatility (3)
            atr_norm,bb_position,body_ratio,
            # Pattern (3)
            bullish,swing_pos,fvg,
            # Oscillators (2)
            stoch/100,
            1 if stoch<20 else -1 if stoch>80 else 0,
            # Meta (2)
            hour,action_val,
        ]
        return features
    except:return None

def collect_training_data(symbol,lot):
    candles=load_data(symbol)
    if not candles:
        print(f'[TRAIN] No data for {symbol}')
        return [],[]

    df=to_df(candles)
    if df is None or len(df)<200:
        print(f'[TRAIN] Insufficient data for {symbol}')
        return [],[]

    features_list=[]
    labels=[]
    print(f'[TRAIN] Collecting {symbol}: {len(df)} candles...')

    for i in range(100,len(df)-30,3):
        df5=df.iloc[i-60:i].copy()
        df15=df.iloc[max(0,i-180):i:3].copy()
        df_daily=df.iloc[max(0,i-300):i:12].copy()
        if len(df5)<30 or len(df15)<10:continue

        try:
            hour=int(str(df5['time'].iloc[-1])[11:13])
            if hour<9 or hour>14:continue

            c=df5['close'];h=df5['high'];l=df5['low'];v=df5['volume']
            rsi=calc_rsi(c).iloc[-1]
            macd,sig=calc_macd(c)
            macd_hist=(macd-sig).iloc[-1]
            atr=(h-l).tail(14).mean()
            if atr<=0:continue

            # Daily trend
            trend_d=get_trend(df_daily)
            trend15=get_trend(df15)

            # Signal
            buy_score=0;sell_score=0
            if trend_d==1:buy_score+=3
            elif trend_d==-1:sell_score+=3
            if trend15==1:buy_score+=2
            elif trend15==-1:sell_score+=2
            if rsi<40:buy_score+=3
            elif rsi>60:sell_score+=3
            if macd_hist>0:buy_score+=2
            elif macd_hist<0:sell_score+=2

            if buy_score>=4 and buy_score>sell_score:action='BUY'
            elif sell_score>=4 and sell_score>buy_score:action='SELL'
            else:continue

            # Trend filter
            if trend_d==1 and action=='SELL':continue
            if trend_d==-1 and action=='BUY':continue

            # Extract features
            feats=extract_features(df5,df15,action)
            if not feats:continue

            # Simulate outcome
            sl=atr*1.5;t2=atr*2.5
            entry=c.iloc[-1]
            future=df.iloc[i:i+30]
            outcome=0
            for _,row in future.iterrows():
                if action=='BUY':
                    if row['low']<=entry-sl:outcome=0;break
                    elif row['high']>=entry+t2:outcome=1;break
                else:
                    if row['high']>=entry+sl:outcome=0;break
                    elif row['low']<=entry-t2:outcome=1;break

            features_list.append(feats)
            labels.append(outcome)
        except:continue

    wins=sum(labels)
    total=len(labels)
    print(f'[TRAIN] {symbol}: {total} samples | WR:{wins/total*100:.1f}%' if total>0 else f'[TRAIN] {symbol}: No samples')
    return features_list,labels

def train_balanced_model(symbol,features,labels):
    try:
        from sklearn.ensemble import RandomForestClassifier,GradientBoostingClassifier
        from sklearn.model_selection import train_test_split,cross_val_score
        from sklearn.preprocessing import StandardScaler
        from sklearn.utils import resample
        from sklearn.metrics import classification_report,confusion_matrix

        X=np.array(features)
        y=np.array(labels)
        wins=sum(y==1);losses=sum(y==0)
        print(f'[ML] {symbol}: {wins} wins, {losses} losses WR:{wins/len(y)*100:.1f}%')

        if wins<10 or losses<10:
            print(f'[ML] {symbol}: Not enough samples!')
            return None,None,0

        # Balance classes
        X_loss=X[y==0];y_loss=y[y==0]
        X_win=X[y==1];y_win=y[y==1]

        # Oversample minority to 50/50
        n=min(len(X_loss),len(X_win)*3)
        X_loss_dn,y_loss_dn=resample(X_loss,y_loss,n_samples=n,random_state=42)
        X_win_up,y_win_up=resample(X_win,y_win,n_samples=n,random_state=42)
        X_bal=np.vstack([X_loss_dn,X_win_up])
        y_bal=np.hstack([y_loss_dn,y_win_up])
        print(f'[ML] Balanced: {sum(y_bal==1)} wins, {sum(y_bal==0)} losses')

        scaler=StandardScaler()
        X_sc=scaler.fit_transform(X_bal)
        X_tr,X_te,y_tr,y_te=train_test_split(X_sc,y_bal,test_size=0.2,random_state=42)

        models={
            'RF':RandomForestClassifier(n_estimators=200,max_depth=8,min_samples_leaf=5,random_state=42),
            'GB':GradientBoostingClassifier(n_estimators=100,learning_rate=0.05,max_depth=4,random_state=42),
        }

        best_score=0;best_model=None;best_name=''
        for name,model in models.items():
            model.fit(X_tr,y_tr)
            score=model.score(X_te,y_te)
            preds=model.predict(X_te)
            win_preds=sum(preds==1)
            loss_preds=sum(preds==0)
            print(f'[ML] {name}: Acc={score*100:.1f}% WinPred={win_preds} LossPred={loss_preds}')
            if score>best_score and win_preds>5 and loss_preds>5:
                best_score=score;best_model=model;best_name=name

        if not best_model:
            best_model=models['RF'];best_name='RF'
            best_score=models['RF'].score(X_te,y_te)

        # Print classification report
        preds=best_model.predict(X_te)
        print(f'[ML] {symbol} Best:{best_name} Acc:{best_score*100:.1f}%')
        cm=confusion_matrix(y_te,preds)
        print(f'[ML] Confusion Matrix:\n{cm}')

        os.makedirs('ml_models',exist_ok=True)
        pickle.dump({
            'model':best_model,
            'scaler':scaler,
            'symbol':symbol,
            'accuracy':best_score,
            'feature_count':len(features[0]),
            'trained_on':str(datetime.now()),
            'wins_in_training':int(wins),
            'losses_in_training':int(losses),
        },open(f'ml_models/{symbol}_model.pkl','wb'))
        print(f'[ML] ✅ Saved: ml_models/{symbol}_model.pkl')
        return best_model,scaler,best_score

    except Exception as e:
        print(f'[ML] Error {symbol}: {e}')
        return None,None,0

def train_all_instruments():
    print('\n'+'='*60)
    print('  BALANCED ML TRAINING FOR ALL INSTRUMENTS')
    print('='*60)

    results={}
    for symbol,info in INSTRUMENTS.items():
        print(f'\n{"─"*40}')
        print(f'  Training: {symbol} ({info["type"]})')
        print(f'{"─"*40}')

        # Check if data exists
        features,labels=collect_training_data(symbol,info['lot'])

        if len(features)<50:
            print(f'[SKIP] {symbol}: Insufficient data ({len(features)} samples)')
            continue

        # Train balanced model
        model,scaler,acc=train_balanced_model(symbol,features,labels)

        if model:
            results[symbol]={
                'accuracy':acc,
                'samples':len(features),
                'type':info['type']
            }
            print(f'✅ {symbol}: {acc*100:.1f}% accuracy')
        else:
            print(f'❌ {symbol}: Training failed')

        time.sleep(1)

    # Summary
    print('\n'+'='*60)
    print('  TRAINING SUMMARY')
    print('='*60)
    for sym,r in sorted(results.items(),key=lambda x:-x[1]['accuracy']):
        print(f'  {sym}: {r["accuracy"]*100:.1f}% ({r["samples"]} samples) [{r["type"]}]')

    print(f'\n✅ Trained {len(results)}/{len(INSTRUMENTS)} models!')
    return results

if __name__=='__main__':
    train_all_instruments()
