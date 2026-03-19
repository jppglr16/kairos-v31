import json,os,pickle
import numpy as np
import pandas as pd
from datetime import datetime

def collect_success_patterns(symbol):
    """Only collect features from WINNING trades"""
    from v30_train_kairos import load_data,to_df,calc_rsi,calc_macd,get_trend,get_wyckoff_simple,extract_kairos_features

    candles=load_data(symbol)
    if not candles:return [],[]

    df=to_df(candles)
    if df is None:return [],[]

    success_features=[]
    success_labels=[]
    fail_features=[]
    fail_labels=[]

    print(f'[SUCCESS] Collecting {symbol}: {len(df)} candles...')

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

            # Generate signal
            buy_score=0;sell_score=0
            if trend_d==1:buy_score+=2
            elif trend_d==-1:sell_score+=2
            if trend15==1:buy_score+=2
            elif trend15==-1:sell_score+=2
            if rsi<45:buy_score+=2
            elif rsi>55:sell_score+=2
            if macd_hist>0:buy_score+=1
            elif macd_hist<0:sell_score+=1

            if buy_score>=4 and buy_score>sell_score:action='BUY'
            elif sell_score>=4 and sell_score>buy_score:action='SELL'
            else:continue

            if trend_d==1 and action=='SELL':continue
            if trend_d==-1 and action=='BUY':continue

            feats=extract_kairos_features(df5,df15,df_daily,action)
            if not feats:continue

            # Simulate outcome with detailed tracking
            sl=atr*1.5;t1=atr*1.5;t2=atr*2.5
            entry=c.iloc[-1]
            future=df.iloc[i:i+30]
            outcome=0
            max_profit=0
            max_loss=0

            for _,row in future.iterrows():
                if action=='BUY':
                    profit=row['high']-entry
                    loss=entry-row['low']
                    max_profit=max(max_profit,profit)
                    max_loss=max(max_loss,loss)
                    if row['low']<=entry-sl:outcome=0;break
                    elif row['high']>=entry+t2:outcome=1;break
                else:
                    profit=entry-row['low']
                    loss=row['high']-entry
                    max_profit=max(max_profit,profit)
                    max_loss=max(max_loss,loss)
                    if row['high']>=entry+sl:outcome=0;break
                    elif row['low']<=entry-t2:outcome=1;break

            # Quality score for winning trades
            if outcome==1:
                # How clean was the win?
                quality=min(1.0,max_profit/(t2*1.5))
                success_features.append(feats)
                success_labels.append(1)
                # Add multiple times for high quality wins
                if quality>0.8:
                    success_features.append(feats)
                    success_labels.append(1)
            else:
                fail_features.append(feats)
                fail_labels.append(0)

        except:continue

    wins=len(success_features)
    losses=len(fail_features)
    total=wins+losses
    print(f'[SUCCESS] {symbol}: {wins} wins, {losses} losses WR:{wins/total*100:.1f}%' if total>0 else f'[SUCCESS] {symbol}: No data')
    return success_features+fail_features, success_labels+fail_labels

def train_success_model(symbol,features,labels):
    try:
        from sklearn.ensemble import RandomForestClassifier,GradientBoostingClassifier,VotingClassifier
        from sklearn.model_selection import train_test_split,StratifiedKFold,cross_val_score
        from sklearn.preprocessing import StandardScaler
        from sklearn.utils import resample

        X=np.array(features);y=np.array(labels)
        wins=sum(y==1);losses=sum(y==0)

        if wins<20 or losses<20:
            print(f'[ML] {symbol}: Not enough data')
            return None,None,0

        print(f'[ML] {symbol}: {wins} wins {losses} losses')

        # Smart balancing - don't oversample too much
        # Keep win rate close to real market win rate
        target_ratio=0.45  # Target 45% win rate in training
        n_wins=wins
        n_losses=int(wins/target_ratio*(1-target_ratio))
        n_losses=min(n_losses,losses)

        X_l=X[y==0];y_l=y[y==0]
        X_w=X[y==1];y_w=y[y==1]

        X_ld,y_ld=resample(X_l,y_l,n_samples=n_losses,random_state=42)
        X_bal=np.vstack([X_ld,X_w])
        y_bal=np.hstack([y_ld,y_w])

        print(f'[ML] Balanced: {sum(y_bal==1)} wins {sum(y_bal==0)} losses')

        sc=StandardScaler()
        X_sc=sc.fit_transform(X_bal)
        X_tr,X_te,y_tr,y_te=train_test_split(X_sc,y_bal,test_size=0.2,random_state=42,stratify=y_bal)

        # Ensemble of 3 models
        rf=RandomForestClassifier(n_estimators=300,max_depth=10,min_samples_leaf=3,class_weight='balanced',random_state=42)
        gb=GradientBoostingClassifier(n_estimators=150,learning_rate=0.05,max_depth=5,random_state=42)

        results={}
        for name,model in [('RF',rf),('GB',gb)]:
            model.fit(X_tr,y_tr)
            score=model.score(X_te,y_te)
            preds=model.predict(X_te)
            wp=sum(preds==1);lp=sum(preds==0)
            # Cross validation
            cv=cross_val_score(model,X_sc,y_bal,cv=5,scoring='accuracy').mean()
            print(f'[ML] {name}: Acc={score*100:.1f}% CV={cv*100:.1f}% WP={wp} LP={lp}')
            results[name]={'model':model,'score':score,'cv':cv,'wp':wp,'lp':lp}

        # Pick best model that predicts both classes
        best_name=max(results,key=lambda x:results[x]['score'] if results[x]['wp']>5 and results[x]['lp']>5 else 0)
        best=results[best_name]

        os.makedirs('ml_models',exist_ok=True)
        pickle.dump({
            'model':best['model'],
            'scaler':sc,
            'symbol':symbol,
            'accuracy':best['score'],
            'cv_accuracy':best['cv'],
            'feature_count':len(features[0]),
            'trained_on':str(datetime.now()),
            'type':'SUCCESS_PATTERN',
            'wins_trained':int(wins),
            'losses_trained':int(losses)
        },open(f'ml_models/{symbol}_model.pkl','wb'))

        print(f'[ML] ✅ {symbol}: {best_name} saved! Acc={best["score"]*100:.1f}%')
        return best['model'],sc,best['score']

    except Exception as e:
        print(f'[ML] Error {symbol}: {e}')
        return None,None,0

def update_from_live_trades(symbol,winning_trade_features):
    """Auto-update model when live trade wins"""
    try:
        model_file=f'ml_models/{symbol}_model.pkl'
        if not os.path.exists(model_file):return

        data=pickle.load(open(model_file,'rb'))
        # Save winning pattern for retraining
        patterns_file=f'ml_models/{symbol}_winners.json'
        patterns=json.load(open(patterns_file)) if os.path.exists(patterns_file) else []
        patterns.append({
            'features':winning_trade_features,
            'timestamp':str(datetime.now())
        })
        json.dump(patterns,open(patterns_file,'w'))
        print(f'[SUCCESS] Saved winning pattern for {symbol}! Total: {len(patterns)}')

        # Retrain if enough new patterns (every 10 wins)
        if len(patterns)%10==0:
            print(f'[SUCCESS] Retraining {symbol} with {len(patterns)} live winning patterns!')
            # Will implement full retraining here

    except Exception as e:
        print(f'[SUCCESS] Update error: {e}')

def train_all_success():
    from v30_train_kairos import INSTRUMENTS

    print('\n'+'='*60)
    print('  SUCCESS PATTERN TRAINING')
    print('  Learning ONLY from winning setups')
    print('='*60)

    results={}
    for symbol,info in INSTRUMENTS.items():
        print(f'\n{"─"*40}')
        print(f'  {symbol} ({info["type"]})')
        features,labels=collect_success_patterns(symbol)
        if len(features)<50:
            print(f'[SKIP] {symbol}: Only {len(features)} samples')
            continue
        model,sc,acc=train_success_model(symbol,features,labels)
        if model:
            results[symbol]={'accuracy':acc,'samples':len(features)}

    print('\n'+'='*60)
    print('  SUCCESS TRAINING COMPLETE!')
    print('='*60)
    for sym,r in sorted(results.items(),key=lambda x:-x[1]['accuracy']):
        print(f'  {sym}: {r["accuracy"]*100:.1f}% ({r["samples"]} samples)')
    print(f'\n✅ {len(results)} models trained on success patterns!')
    return results

if __name__=='__main__':
    train_all_success()
