import json,os,pickle,time
import numpy as np
import pandas as pd
from datetime import datetime

INSTRUMENTS={
    'NIFTY':     {'type':'index','lot':75,'token':'99926000'},
    'BANKNIFTY': {'type':'index','lot':30,'token':'99926009'},
    'SENSEX':    {'type':'index','lot':10,'token':'99919000'},
    'FINNIFTY':  {'type':'index','lot':65,'token':'99926037'},
    'MIDCPNIFTY':{'type':'index','lot':120,'token':'99926074'},
    'CRUDEOIL':  {'type':'commodity','lot':100,'token':'472790'},
    'GOLDM':     {'type':'commodity','lot':10,'token':'477904'},
    'SILVERM':   {'type':'commodity','lot':30,'token':'457533'},
    'LT':        {'type':'stock','lot':450,'token':'11483'},
    'NTPC':      {'type':'stock','lot':4500,'token':'11630'},
    'MARUTI':    {'type':'stock','lot':100,'token':'10999'},
    'BHARTIARTL':{'type':'stock','lot':950,'token':'10604'},
    'SBIN':      {'type':'stock','lot':1500,'token':'3045'},
    'TATAMOTORS':{'type':'stock','lot':1350,'token':'3456'},
    'RELIANCE':  {'type':'stock','lot':250,'token':'2885'},
    'HINDUNILVR':{'type':'stock','lot':300,'token':'1394'},
    'TCS':       {'type':'stock','lot':150,'token':'11536'},
    'TATASTEEL': {'type':'stock','lot':5500,'token':'3499'},
}

def load_data(symbol):
    all_candles=[]
    info=INSTRUMENTS.get(symbol,{})
    token=info.get('token','')
    for year in [2022,2023,2024]:
        for fname in [
            f'historical_data/{symbol}_{year}_5min.json',
            f'historical_data/{token}_{year}_5min.json'
        ]:
            if os.path.exists(fname):
                all_candles.extend(json.load(open(fname)))
                break
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

def get_wyckoff_simple(df):
    try:
        c=df['close'].values
        v=df['volume'].values
        h=df['high'].values
        l=df['low'].values
        if len(c)<60:return 'UNKNOWN'
        recent_v=v[-20:].mean()
        old_v=v[-60:-20].mean()
        vol_dec=recent_v<old_v*0.8
        s20=pd.Series(c).rolling(20).mean().values
        s50=pd.Series(c).rolling(50).mean().values
        above_s50=c[-1]>s50[-1]
        consolidating=(h[-20:].max()-l[-20:].min())<(h[-60:-20].max()-l[-60:-20].min())*0.6
        spring=l[-20:].min()<l[-60:-20].min() and c[-1]>l[-60:-20].min()
        upthrust=h[-20:].max()>h[-60:-20].max() and c[-1]<h[-60:-20].max()
        if consolidating and not above_s50 and (vol_dec or spring):return 'ACCUM'
        elif c[-1]>s20[-1] and s20[-1]>s50[-1]:return 'MARKUP'
        elif consolidating and above_s50 and (vol_dec or upthrust):return 'DIST'
        elif c[-1]<s20[-1] and s20[-1]<s50[-1]:return 'MARK'
        return 'TRANS'
    except:return 'UNKNOWN'

def extract_kairos_features(df5,df15,df_daily,action):
    try:
        c=df5['close'];h=df5['high'];l=df5['low'];v=df5['volume']
        if len(c)<20:return None

        # Basic indicators
        rsi=calc_rsi(c).iloc[-1]
        macd,sig=calc_macd(c)
        macd_hist=(macd-sig).iloc[-1]
        atr=(h-l).tail(14).mean()
        if atr<=0:return None

        # Volume
        vol_avg=v.rolling(20).mean().iloc[-1]
        vol_ratio=v.iloc[-1]/vol_avg if vol_avg>0 else 1

        # Price momentum
        ret1=(c.iloc[-1]-c.iloc[-2])/c.iloc[-2]
        ret5=(c.iloc[-1]-c.iloc[-6])/c.iloc[-6] if len(c)>6 else 0
        ret10=(c.iloc[-1]-c.iloc[-11])/c.iloc[-11] if len(c)>11 else 0

        # Trends
        trend5=get_trend(df5)
        trend15=get_trend(df15)
        trend_daily=get_trend(df_daily)
        trend_aligned=1 if (action=='BUY' and trend15==1) or (action=='SELL' and trend15==-1) else 0
        all_aligned=1 if trend5==trend15==trend_daily else 0

        # MA
        sma20=c.rolling(20).mean().iloc[-1]
        sma50=c.rolling(50).mean().iloc[-1] if len(c)>=50 else sma20
        above_sma20=1 if c.iloc[-1]>sma20 else 0
        above_sma50=1 if c.iloc[-1]>sma50 else 0

        # Bollinger
        bb_std=c.rolling(20).std().iloc[-1]
        bb_upper=sma20+2*bb_std
        bb_lower=sma20-2*bb_std
        bb_pos=(c.iloc[-1]-bb_lower)/(bb_upper-bb_lower) if (bb_upper-bb_lower)>0 else 0.5

        # Stochastic
        low14=l.rolling(14).min()
        high14=h.rolling(14).max()
        stoch=((c-low14)/(high14-low14)*100).iloc[-1] if (high14-low14).iloc[-1]>0 else 50

        # Swing levels
        swing_high=h.tail(20).max()
        swing_low=l.tail(20).min()
        swing_range=swing_high-swing_low
        swing_pos=(c.iloc[-1]-swing_low)/swing_range if swing_range>0 else 0.5

        # FVG detection
        fvg_bull=0;fvg_bear=0
        for i in range(2,min(len(df5),10)):
            p2=df5.iloc[-i-2];cur=df5.iloc[-i]
            if cur['low']>p2['high']:fvg_bull=1;break
            elif cur['high']<p2['low']:fvg_bear=1;break

        # Liquidity sweep
        liq_bull=0;liq_bear=0
        if len(df5)>=10:
            rh=h.iloc[-10:-1].max();rl=l.iloc[-10:-1].min()
            last=df5.iloc[-1]
            if last['low']<rl and last['close']>rl:liq_bull=1
            elif last['high']>rh and last['close']<rh:liq_bear=1

        # Wyckoff
        wy=get_wyckoff_simple(df15)
        wy_accum=1 if wy=='ACCUM' else 0
        wy_markup=1 if wy=='MARKUP' else 0
        wy_dist=1 if wy=='DIST' else 0
        wy_mark=1 if wy=='MARK' else 0

        # ICT - OTE zone
        s_high=h.tail(20).max();s_low=l.tail(20).min()
        fib_range=s_high-s_low
        ote_low=s_high-(fib_range*0.79)
        ote_high=s_high-(fib_range*0.62)
        cur=c.iloc[-1]
        in_ote_buy=1 if ote_low<=cur<=ote_high else 0
        ote_low2=s_low+(fib_range*0.62)
        ote_high2=s_low+(fib_range*0.79)
        in_ote_sell=1 if ote_low2<=cur<=ote_high2 else 0

        # Premium/Discount
        mid=(s_high+s_low)/2
        in_discount=1 if cur<mid else 0
        in_premium=1 if cur>mid else 0

        # VWAP
        vwap=(c*v).sum()/v.sum() if v.sum()>0 else c.mean()
        above_vwap=1 if cur>vwap else 0

        # Candle pattern
        last=df5.iloc[-1]
        body=abs(last['close']-last['open'])
        candle_range=last['high']-last['low']
        body_ratio=body/candle_range if candle_range>0 else 0
        bullish_candle=1 if last['close']>last['open'] else 0

        # Action
        action_val=1 if action=='BUY' else -1
        try:hour=int(str(df5['time'].iloc[-1])[11:13])/24
        except:hour=0.4

        # KAIROS score components
        k_killzone=1 if 9<=int(hour*24)<=11 or 13<=int(hour*24)<=15 else 0
        a_align=all_aligned
        i_imbalance=fvg_bull if action=='BUY' else fvg_bear
        r_rejection=liq_bull if action=='BUY' else liq_bear
        s_smc=1 if trend_aligned else 0
        w_wyckoff=1 if (action=='BUY' and wy in ['ACCUM','MARKUP']) or (action=='SELL' and wy in ['DIST','MARK']) else 0

        kairos_score=k_killzone+a_align+i_imbalance+r_rejection+s_smc+w_wyckoff

        features=[
            # Price (3)
            ret1,ret5,ret10,
            # RSI (2)
            rsi/100,(rsi-50)/50,
            # MACD (2)
            macd_hist/atr,1 if macd_hist>0 else -1,
            # Volume (2)
            min(vol_ratio,3)/3,1 if vol_ratio>1.5 else 0,
            # Trends (4)
            trend5,trend15,trend_daily,trend_aligned,
            # MA (2)
            above_sma20,above_sma50,
            # Oscillators (3)
            bb_pos,stoch/100,swing_pos,
            # SMC (4)
            fvg_bull,fvg_bear,liq_bull,liq_bear,
            # Wyckoff (4)
            wy_accum,wy_markup,wy_dist,wy_mark,
            # ICT (4)
            in_ote_buy,in_ote_sell,in_discount,in_premium,
            # VP (1)
            above_vwap,
            # Candle (2)
            body_ratio,bullish_candle,
            # KAIROS (1)
            kairos_score/6,
            # Meta (2)
            hour,action_val,
        ]
        return features
    except:return None

def collect_kairos_training(symbol):
    candles=load_data(symbol)
    if not candles:
        print(f'[TRAIN] No data: {symbol}')
        return [],[]

    df=to_df(candles)
    if df is None or len(df)<200:
        print(f'[TRAIN] Insufficient: {symbol}')
        return [],[]

    features_list=[];labels=[]
    print(f'[TRAIN] {symbol}: {len(df)} candles...')

    for i in range(100,len(df)-30,2):
        df5=df.iloc[i-60:i].copy()
        df15=df.iloc[max(0,i-180):i:3].copy()
        df_daily=df.iloc[max(0,i-300):i:12].copy()
        if len(df5)<30 or len(df15)<10:continue

        try:
            hour=int(str(df5['time'].iloc[-1])[11:13])
            if hour<9 or hour>15:continue

            c=df5['close'];h=df5['high'];l=df5['low'];v=df5['volume']
            rsi=calc_rsi(c).iloc[-1]
            macd,sig=calc_macd(c)
            macd_hist=(macd-sig).iloc[-1]
            atr=(h-l).tail(14).mean()
            if atr<=0:continue

            trend_d=get_trend(df_daily)
            trend15=get_trend(df15)
            trend5=get_trend(df5)

            # Generate signal
            buy_score=0;sell_score=0
            if trend_d==1:buy_score+=2
            elif trend_d==-1:sell_score+=2
            if trend15==1:buy_score+=2
            elif trend15==-1:sell_score+=2
            if trend5==1:buy_score+=1
            elif trend5==-1:sell_score+=1
            if rsi<45:buy_score+=2
            elif rsi>55:sell_score+=2
            if macd_hist>0:buy_score+=1
            elif macd_hist<0:sell_score+=1

            if buy_score>=4 and buy_score>sell_score:
                action='BUY'
            elif sell_score>=4 and sell_score>buy_score:
                action='SELL'
            else:continue

            # Trend filter
            if trend_d==1 and action=='SELL':continue
            if trend_d==-1 and action=='BUY':continue

            # Extract full KAIROS features
            feats=extract_kairos_features(df5,df15,df_daily,action)
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

    wins=sum(labels);total=len(labels)
    print(f'[TRAIN] {symbol}: {total} samples WR:{wins/total*100:.1f}%' if total>0 else f'[TRAIN] {symbol}: 0 samples')
    return features_list,labels

def train_kairos_model(symbol,features,labels):
    try:
        from sklearn.ensemble import RandomForestClassifier,GradientBoostingClassifier
        from sklearn.model_selection import train_test_split
        from sklearn.preprocessing import StandardScaler
        from sklearn.utils import resample

        X=np.array(features);y=np.array(labels)
        wins=sum(y==1);losses=sum(y==0)
        if wins<20 or losses<20:
            print(f'[ML] {symbol}: Need more samples (wins:{wins} losses:{losses})')
            return None,None,0

        # Balance
        X_l=X[y==0];y_l=y[y==0]
        X_w=X[y==1];y_w=y[y==1]
        n=min(len(X_l),len(X_w)*2)
        X_ld,y_ld=resample(X_l,y_l,n_samples=n,random_state=42)
        X_wu,y_wu=resample(X_w,y_w,n_samples=n,random_state=42)
        X_b=np.vstack([X_ld,X_wu])
        y_b=np.hstack([y_ld,y_wu])
        print(f'[ML] {symbol} Balanced: {sum(y_b==1)} wins {sum(y_b==0)} losses')

        sc=StandardScaler()
        X_sc=sc.fit_transform(X_b)
        X_tr,X_te,y_tr,y_te=train_test_split(X_sc,y_b,test_size=0.2,random_state=42)

        best_score=0;best_model=None;best_name=''
        for name,model in [
            ('RF',RandomForestClassifier(n_estimators=200,max_depth=8,min_samples_leaf=3,random_state=42)),
            ('GB',GradientBoostingClassifier(n_estimators=100,learning_rate=0.05,max_depth=4,random_state=42))
        ]:
            model.fit(X_tr,y_tr)
            score=model.score(X_te,y_te)
            preds=model.predict(X_te)
            wp=sum(preds==1);lp=sum(preds==0)
            print(f'[ML] {name}: Acc={score*100:.1f}% WP={wp} LP={lp}')
            if score>best_score and wp>5 and lp>5:
                best_score=score;best_model=model;best_name=name

        if not best_model:
            best_model=RandomForestClassifier(n_estimators=100,random_state=42)
            best_model.fit(X_tr,y_tr)
            best_score=best_model.score(X_te,y_te)
            best_name='RF_fallback'

        os.makedirs('ml_models',exist_ok=True)
        pickle.dump({
            'model':best_model,'scaler':sc,
            'symbol':symbol,'accuracy':best_score,
            'feature_count':len(features[0]),
            'trained_on':str(datetime.now()),
            'type':'KAIROS_BALANCED'
        },open(f'ml_models/{symbol}_model.pkl','wb'))
        print(f'[ML] ✅ {symbol}: {best_name} {best_score*100:.1f}% saved!')
        return best_model,sc,best_score
    except Exception as e:
        print(f'[ML] Error {symbol}: {e}')
        return None,None,0

def train_all():
    print('\n'+'='*60)
    print('  KAIROS+WYCKOFF+ICT+VP ML TRAINING')
    print('  All 18 Instruments - Balanced Approach')
    print('='*60)

    results={}
    for symbol,info in INSTRUMENTS.items():
        print(f'\n{"─"*40}')
        print(f'  {symbol} ({info["type"]})')
        print(f'{"─"*40}')
        features,labels=collect_kairos_training(symbol)
        if len(features)<50:
            print(f'[SKIP] {symbol}: Only {len(features)} samples')
            continue
        model,sc,acc=train_kairos_model(symbol,features,labels)
        if model:
            results[symbol]={'accuracy':acc,'samples':len(features),'type':info['type']}

    print('\n'+'='*60)
    print('  TRAINING COMPLETE!')
    print('='*60)
    for sym,r in sorted(results.items(),key=lambda x:-x[1]['accuracy']):
        print(f'  {sym}: {r["accuracy"]*100:.1f}% ({r["samples"]} samples)')
    print(f'\n✅ {len(results)}/{len(INSTRUMENTS)} models trained!')
    return results

if __name__=='__main__':
    train_all()
