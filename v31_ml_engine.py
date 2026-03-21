
def get_option_premium(atr):
    """Match backtest: premium = ATR * 0.9"""
    return max(60,min(350,round(atr*0.9)))

def get_option_sl_tgt(prem,score):
    """Score-based SL and target"""
    sl=prem*0.40
    tgt=prem*1.5 if score>=22 else prem*1.0 if score>=18 else prem*0.75
    return sl,tgt

import pickle,os,json
import numpy as np
from datetime import datetime
import logging
log=logging.getLogger(__name__)

def extract_v31_features(df5,df15,action,regime,
                          liq_type,has_fvg,has_ob,
                          gamma_boost,rr,sl_pts,atr):
    try:
        c=df5['close'];h=df5['high'];l=df5['low'];v=df5['volume']
        cur=float(c.iloc[-1])
        ret1=(cur-float(c.iloc[-2]))/float(c.iloc[-2])
        ret5=(cur-float(c.iloc[-6]))/float(c.iloc[-6]) if len(c)>6 else 0
        ret10=(cur-float(c.iloc[-11]))/float(c.iloc[-11]) if len(c)>11 else 0
        atr_norm=atr/cur if cur>0 else 0
        vol_avg=float(v.rolling(20).mean().iloc[-1])
        vol_ratio=float(v.iloc[-1])/vol_avg if vol_avg>0 else 1
        d=c.diff();g=d.clip(lower=0).rolling(14).mean();ll=-d.clip(upper=0).rolling(14).mean()
        rsi=float((100-(100/(1+g/ll))).iloc[-1])
        e12=c.ewm(span=12).mean();e26=c.ewm(span=26).mean();m=e12-e26
        mh=float((m-m.ewm(span=9).mean()).iloc[-1])
        def get_trend(df):
            if len(df)<3:return 0
            c=df['close']
            if float(c.iloc[-1])>float(c.iloc[-3]):return 1
            elif float(c.iloc[-1])<float(c.iloc[-3]):return -1
            return 0
        t5=get_trend(df5);t15=get_trend(df15)
        sma20=float(c.rolling(20).mean().iloc[-1])
        std20=float(c.rolling(20).std().iloc[-1])
        bb_pos=(cur-sma20)/(2*std20) if std20>0 else 0
        lo14=float(l.rolling(14).min().iloc[-1])
        hi14=float(h.rolling(14).max().iloc[-1])
        stoch=(cur-lo14)/(hi14-lo14) if (hi14-lo14)>0 else 0.5
        vwap=float((c*v).sum()/v.sum()) if float(v.sum())>0 else sma20
        above_vwap=1 if cur>vwap else 0
        sh=float(h.tail(20).max());sl_val=float(l.tail(20).min())
        swing_rng=sh-sl_val
        swing_pos=(cur-sl_val)/swing_rng if swing_rng>0 else 0.5
        regime_enc={'TRENDING_UP':1,'TRENDING_DOWN':-1,'RANGING':0,'VOLATILE':0}.get(regime,0)
        liq_enc={'SWEEP_LOW':1,'EQUAL_LOWS':0.8,'SESSION_LOW':0.6,
                 'SWEEP_HIGH':-1,'EQUAL_HIGHS':-0.8,'SESSION_HIGH':-0.6,'NONE':0}.get(liq_type,0)
        try:hour=int(str(df5['time'].iloc[-1])[11:13])/24
        except:hour=0.4
        features=[
            ret1,ret5,ret10,atr_norm,
            rsi/100,(rsi-50)/50,
            mh/atr if atr>0 else 0,
            1 if mh>0 else -1,
            min(vol_ratio,3)/3,
            1 if vol_ratio>1.5 else 0,
            t5,t15,
            1 if t5==t15 else 0,
            bb_pos,stoch,swing_pos,above_vwap,
            1 if has_fvg else 0,
            1 if has_ob else 0,
            abs(liq_enc),
            regime_enc,
            1 if regime in ['TRENDING_UP','TRENDING_DOWN'] else 0,
            min(gamma_boost,10)/10,
            1 if gamma_boost>0 else 0,
            min(rr,10)/10,
            sl_pts/atr if atr>0 else 1,
            1 if sl_pts<atr else 0,
            1 if action=='BUY' else -1,
            liq_enc,
            hour,
        ]
        return features
    except Exception as e:
        log.error(f'[V31 ML] Features error: {e}')
        return None

# Best model per instrument (use highest accuracy)
def load_v31_model(symbol):
    """Smart model selection - loads best accuracy model"""
    candidates=[
        f'ml_models/{symbol}_v31_lgbm.pkl',  # LightGBM
        f'ml_models/{symbol}_v31_ml.pkl',    # GBM (Colab)
        f'ml_models/{symbol}_v31_model.pkl', # GBM local
        f'ml_models/{symbol}_model.pkl',     # Old GBM
    ]

    best_model=None
    best_acc=0

    for f in candidates:
        if os.path.exists(f):
            try:
                data=pickle.load(open(f,'rb'))
                if not isinstance(data,dict):continue
                acc=data.get('accuracy',0)
                # Prefer recent 5-year models for indices
                # (more relevant than 10-year)
                INDICES=['NIFTY','BANKNIFTY','FINNIFTY',
                         'MIDCPNIFTY','SENSEX']
                if symbol in INDICES and 'lgbm' in f and acc<0.65:
                    log.debug(f'[ML] {symbol} skipping weak LGBM {acc:.1%}')
                    continue
                if acc>best_acc:
                    best_acc=acc
                    best_model=data
                    log.debug(f'[ML] {symbol} candidate: {f} acc={acc:.1%}')
            except:pass

    if best_model:
        log.debug(f'[ML] {symbol} using best model acc={best_acc:.1%}')
        return best_model

    # Fallback
    if os.path.exists('ml_models/NIFTY_model.pkl'):
        try:return pickle.load(open('ml_models/NIFTY_model.pkl','rb'))
        except:pass
    return None

def get_v31_ml_prob(symbol,features,regime='TRENDING'):
    try:
        data=load_v31_model(symbol)
        if not data:return 0.5
        model=data['model'];scaler=data['scaler']
        n=model.n_features_in_
        f=features[:n] if len(features)>=n else features+[0]*(n-len(features))
        return float(model.predict_proba(scaler.transform([f]))[0][1])
    except:return 0.5

def train_v31_model(symbol,features_list,labels):
    try:
        from sklearn.ensemble import RandomForestClassifier,GradientBoostingClassifier
        from sklearn.model_selection import train_test_split
        from sklearn.preprocessing import StandardScaler
        from sklearn.utils import resample
        X=np.array(features_list);y=np.array(labels)
        wins=sum(y==1);losses=sum(y==0)
        if wins<20 or losses<20:
            log.warning(f'[V31 ML] {symbol}: Not enough data')
            return None,None,0
        X_l=X[y==0];y_l=y[y==0]
        X_w=X[y==1];y_w=y[y==1]
        n=min(len(X_l),len(X_w)*2)
        X_ld,y_ld=resample(X_l,y_l,n_samples=n,random_state=42)
        X_wu,y_wu=resample(X_w,y_w,n_samples=n,random_state=42)
        X_b=np.vstack([X_ld,X_wu]);y_b=np.hstack([y_ld,y_wu])
        sc=StandardScaler();X_sc=sc.fit_transform(X_b)
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
            log.info(f'[V31 ML] {name}: Acc={score*100:.1f}% WP={wp} LP={lp}')
            if score>best_score and wp>5 and lp>5:
                best_score=score;best_model=model;best_name=name
        if not best_model:
            best_model=RandomForestClassifier(n_estimators=100,random_state=42)
            best_model.fit(X_tr,y_tr)
            best_score=best_model.score(X_te,y_te)
        os.makedirs('ml_models',exist_ok=True)
        pickle.dump({
            'model':best_model,'scaler':sc,
            'symbol':symbol,'accuracy':best_score,
            'type':'V31_KAIROS',
            'trained_on':str(datetime.now())
        },open(f'ml_models/{symbol}_v31_model.pkl','wb'))
        log.info(f'[V31 ML] ✅ {symbol}: {best_name} {best_score*100:.1f}% saved!')
        return best_model,sc,best_score
    except Exception as e:
        log.error(f'[V31 ML] Train error: {e}')
        return None,None,0

def save_trade_result(symbol,features,outcome,pnl):
    try:
        fname=f'ml_models/{symbol}_v31_trades.json'
        trades=json.load(open(fname)) if os.path.exists(fname) else []
        trades.append({'features':features,'outcome':int(outcome),
                       'pnl':float(pnl),'timestamp':str(datetime.now())})
        if len(trades)>2000:trades=trades[-2000:]
        json.dump(trades,open(fname,'w'))
        if len(trades)%100==0:
            features_list=[t['features'] for t in trades]
            labels=[t['outcome'] for t in trades]
            train_v31_model(symbol,features_list,labels)
            log.info(f'[V31 ML] {symbol} auto-retrained with {len(trades)} trades!')
    except Exception as e:
        log.error(f'[V31 ML] Save error: {e}')

def save_signal_for_learning(symbol,signal_data,outcome,pnl):
    """
    Store EVERY signal with full context for ML learning:
    - KAIROS score
    - Market regime
    - Session
    - Gamma wall distance
    - OI trap value
    - Outcome (WIN/LOSS)
    """
    try:
        fname=f'ml_models/{symbol}_v31_signals.json'
        signals=json.load(open(fname)) if os.path.exists(fname) else []
        signals.append({
            'kairos_score':signal_data.get('score',0),
            'regime':signal_data.get('regime',''),
            'session':signal_data.get('session',0),
            'gamma_boost':signal_data.get('gamma_boost',0),
            'oi_trap':signal_data.get('oi_trap',0),
            'liq_type':signal_data.get('liq_type',''),
            'fvg_present':signal_data.get('fvg_present',False),
            'ote_present':signal_data.get('ote_present',False),
            'rr_ratio':signal_data.get('rr_ratio',0),
            'sl_atr_ratio':signal_data.get('sl_atr_ratio',0),
            'trend_aligned':signal_data.get('trend_aligned',False),
            'ml_prob':signal_data.get('ml_prob',0.5),
            'outcome':int(outcome),
            'pnl':float(pnl),
            'timestamp':str(datetime.now())
        })
        if len(signals)>5000:signals=signals[-5000:]
        json.dump(signals,open(fname,'w'))

        # Auto-retrain every 50 signals
        if len(signals)%50==0 and len(signals)>=100:
            log.info(f'[V31 ML] {symbol}: Auto-retraining with {len(signals)} signals...')
            retrain_from_signals(symbol,signals)

    except Exception as e:
        log.error(f'[V31 ML] Save signal error: {e}')

def retrain_from_signals(symbol,signals):
    """Retrain ML from full signal history"""
    try:
        if len(signals)<50:return
        features=[]
        labels=[]
        for s in signals:
            f=[
                s.get('kairos_score',0)/43,
                1 if s.get('regime')=='TRENDING_UP' else -1 if s.get('regime')=='TRENDING_DOWN' else 0,
                s.get('session',0)/4,
                s.get('gamma_boost',0)/13,
                s.get('oi_trap',0),
                1 if s.get('liq_type') not in ['NONE',''] else 0,
                1 if s.get('fvg_present') else 0,
                1 if s.get('ote_present') else 0,
                s.get('rr_ratio',0)/10,
                s.get('sl_atr_ratio',1),
                1 if s.get('trend_aligned') else 0,
                s.get('ml_prob',0.5),
            ]
            features.append(f)
            labels.append(s.get('outcome',0))

        model,sc,acc=train_v31_model(symbol,features,labels)
        if model:
            log.info(f'[V31 ML] {symbol} retrained! Acc={acc*100:.1f}%')
    except Exception as e:
        log.error(f'[V31 ML] Retrain error: {e}')
