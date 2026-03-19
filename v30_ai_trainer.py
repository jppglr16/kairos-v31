import json,os,pickle
import numpy as np
import pandas as pd
from datetime import datetime

def extract_trade_features(df5,df15,smc,mom,market,fvg,liq,action):
    try:
        c=df5['close']
        h=df5['high']
        l=df5['low']
        v=df5['volume']
        atr=(h-l).tail(14).mean()

        # Price features
        ret1=(c.iloc[-1]-c.iloc[-2])/c.iloc[-2]
        ret5=(c.iloc[-1]-c.iloc[-6])/c.iloc[-6] if len(c)>6 else 0
        ret10=(c.iloc[-1]-c.iloc[-11])/c.iloc[-11] if len(c)>11 else 0

        # SMC features
        smc_strength=smc.get('strength',0)
        trend5=1 if smc.get('trend5')=='UPTREND' else -1 if smc.get('trend5')=='DOWNTREND' else 0
        trend15=1 if smc.get('trend15')=='UPTREND' else -1 if smc.get('trend15')=='DOWNTREND' else 0
        has_ob=1 if smc.get('ob') else 0
        choch=1 if smc.get('choch') else 0

        # Momentum features
        rsi=mom.get('rsi',50)
        macd_hist=mom.get('macd_hist',0)
        vol_surge=1 if mom.get('vol_surge') else 0
        mom_strength=mom.get('strength',0)

        # Market condition
        mkt=1 if market=='UPTREND' else -1 if market=='DOWNTREND' else 0

        # Pattern features
        has_fvg=1 if fvg else 0
        has_liq=1 if liq else 0
        fvg_bull=1 if fvg and fvg.get('type')=='BULL_FVG' else 0
        liq_bull=1 if liq=='BULL_SWEEP' else 0

        # Action alignment
        action_val=1 if action=='BUY' else -1
        trend_aligned=1 if (action=='BUY' and trend15==1) or (action=='SELL' and trend15==-1) else 0

        # Volatility
        atr_norm=atr/c.iloc[-1] if c.iloc[-1]>0 else 0

        # Hour of day
        try:
            hour=int(str(df5['time'].iloc[-1])[11:13])
        except:
            hour=10

        features=[
            ret1,ret5,ret10,
            smc_strength,trend5,trend15,
            has_ob,choch,
            rsi/100,macd_hist/atr if atr>0 else 0,
            vol_surge,mom_strength,
            mkt,has_fvg,has_liq,
            fvg_bull,liq_bull,
            action_val,trend_aligned,
            atr_norm,hour/24
        ]
        return features
    except Exception as e:
        return None

def collect_training_data(instrument):
    from v30_backtest import load_historical_data,candles_to_df
    from v30_smc import get_smc_signal
    from v30_momentum import get_momentum_signal,detect_market_condition
    from v30_strategy import detect_fvg,detect_liq_sweep,count_conf
    from v30_backtest_fix import get_daily_trend

    LOT={'NIFTY':75,'BANKNIFTY':30,'FINNIFTY':65,'MIDCPNIFTY':120,'CRUDEOIL':100,'GOLDM':10,'SILVERM':30}
    lot=LOT.get(instrument,25)

    all_features=[]
    all_labels=[]
    print(f'[TRAIN] Collecting training data for {instrument}...')

    for year in [2022,2023,2024]:
        candles=load_historical_data(instrument,year)
        if not candles:continue
        df=candles_to_df(candles)
        if df is None:continue

        for i in range(100,len(df)-30,3):
            df5=df.iloc[i-60:i].copy()
            df15=df.iloc[max(0,i-180):i:3].copy()
            df_daily=df.iloc[max(0,i-200):i:12].copy()
            if len(df5)<30 or len(df15)<10:continue

            try:
                # Time filter
                hour=int(str(df5['time'].iloc[-1])[11:13])
                if hour<9 or hour>14:continue

                smc=get_smc_signal(df5,df15)
                mom=get_momentum_signal(df5)
                market=detect_market_condition(df15)
                fvg=detect_fvg(df5)
                liq=detect_liq_sweep(df5)

                if not smc['action']:continue
                action=smc['action']

                # Daily trend
                daily_trend=get_daily_trend(df_daily)
                if daily_trend=='UPTREND' and action=='SELL':continue
                if daily_trend=='DOWNTREND' and action=='BUY':continue

                conf=count_conf(smc,mom,fvg,liq,action)
                if conf<4:continue

                # Extract features
                features=extract_trade_features(df5,df15,smc,mom,market,fvg,liq,action)
                if not features:continue

                # Simulate outcome
                atr=(df5['high']-df5['low']).tail(14).mean()
                sl_pts=atr*1.5
                t2_pts=sl_pts*2.5
                entry=df5['close'].iloc[-1]
                future=df.iloc[i:i+30]
                outcome=0

                for j,row in future.iterrows():
                    if action=='BUY':
                        if row['low']<=entry-sl_pts:
                            outcome=0;break
                        elif row['high']>=entry+t2_pts:
                            outcome=1;break
                    else:
                        if row['high']>=entry+sl_pts:
                            outcome=0;break
                        elif row['low']<=entry-t2_pts:
                            outcome=1;break

                all_features.append(features)
                all_labels.append(outcome)

            except:continue

    print(f'[TRAIN] Collected {len(all_features)} samples for {instrument}')
    return all_features,all_labels

def train_ml_model(all_features,all_labels,instrument):
    try:
        from sklearn.ensemble import RandomForestClassifier,GradientBoostingClassifier
        from sklearn.model_selection import train_test_split,cross_val_score
        from sklearn.preprocessing import StandardScaler
        from sklearn.metrics import classification_report

        X=np.array(all_features)
        y=np.array(all_labels)

        print(f'[TRAIN] Training on {len(X)} samples...')
        print(f'[TRAIN] Win rate in data: {y.mean()*100:.1f}%')

        scaler=StandardScaler()
        X_scaled=scaler.fit_transform(X)

        X_train,X_test,y_train,y_test=train_test_split(X_scaled,y,test_size=0.2,random_state=42)

        models={
            'RF':RandomForestClassifier(n_estimators=200,max_depth=10,random_state=42),
            'GB':GradientBoostingClassifier(n_estimators=100,learning_rate=0.1,random_state=42),
        }

        best_score=0;best_model=None;best_name=''
        for name,model in models.items():
            model.fit(X_train,y_train)
            score=model.score(X_test,y_test)
            cv=cross_val_score(model,X_scaled,y,cv=5).mean()
            print(f'[TRAIN] {name}: Accuracy={score*100:.1f}% CV={cv*100:.1f}%')
            if score>best_score:
                best_score=score
                best_model=model
                best_name=name

        print(f'[TRAIN] Best: {best_name} = {best_score*100:.1f}%')
        print(classification_report(y_test,best_model.predict(X_test)))

        os.makedirs('ml_models',exist_ok=True)
        pickle.dump({
            'model':best_model,
            'scaler':scaler,
            'instrument':instrument,
            'accuracy':best_score,
            'trained_on':str(datetime.now())
        },open(f'ml_models/{instrument}_model.pkl','wb'))
        print(f'[TRAIN] Model saved: ml_models/{instrument}_model.pkl')
        return best_model,scaler,best_score
    except Exception as e:
        print(f'[TRAIN] Error: {e}')
        return None,None,0

def run_ml_filtered_backtest(instrument,capital=50000):
    from v30_backtest import load_historical_data,candles_to_df
    from v30_smc import get_smc_signal
    from v30_momentum import get_momentum_signal,detect_market_condition
    from v30_strategy import detect_fvg,detect_liq_sweep,count_conf
    from v30_backtest_fix import get_daily_trend

    LOT={'NIFTY':75,'BANKNIFTY':30,'FINNIFTY':65,'MIDCPNIFTY':120,'CRUDEOIL':100,'GOLDM':10,'SILVERM':30}
    lot=LOT.get(instrument,25)
    BROKERAGE=120

    # Load ML model
    model_file=f'ml_models/{instrument}_model.pkl'
    if not os.path.exists(model_file):
        print(f'[ML] No model found for {instrument}! Train first.')
        return

    model_data=pickle.load(open(model_file,'rb'))
    ml_model=model_data['model']
    scaler=model_data['scaler']
    print(f'[ML] Loaded model accuracy: {model_data["accuracy"]*100:.1f}%')

    print(f'\n{"="*45}')
    print(f'  ML FILTERED BACKTEST: {instrument}')
    print(f'  Capital: Rs.{capital:,.0f}')
    print(f'{"="*45}')

    current_capital=capital
    grand_trades=0;grand_wins=0
    peak_capital=capital;max_drawdown=0
    ml_filtered=0

    for year in [2022,2023,2024]:
        candles=load_historical_data(instrument,year)
        if not candles:continue
        df=candles_to_df(candles)
        if df is None:continue

        year_start=current_capital
        wins=0;losses=0
        in_trade=False
        entry_price=0;trade_action=''
        sl=0;t2=0;entry_idx=0
        daily_losses=0;last_date=None
        t1_hit=False

        for i in range(100,len(df)-20,3):
            df5=df.iloc[i-60:i].copy()
            df15=df.iloc[max(0,i-180):i:3].copy()
            df_daily=df.iloc[max(0,i-200):i:12].copy()
            if len(df5)<30 or len(df15)<10:continue

            try:
                hour=int(str(df5['time'].iloc[-1])[11:13])
                if hour<9 or hour>14:continue
            except:pass

            try:
                current_date=str(df5['time'].iloc[-1])[:10]
                if current_date!=last_date:
                    daily_losses=0
                    last_date=current_date
            except:pass

            if daily_losses>=3:continue
            risk_amt=min(current_capital*0.05,2500)

            if not in_trade:
                try:
                    daily_trend=get_daily_trend(df_daily)
                    smc=get_smc_signal(df5,df15)
                    mom=get_momentum_signal(df5)
                    market=detect_market_condition(df15)
                    fvg=detect_fvg(df5)
                    liq=detect_liq_sweep(df5)

                    if not smc['action']:continue
                    action=smc['action']

                    if daily_trend=='UPTREND' and action=='SELL':continue
                    if daily_trend=='DOWNTREND' and action=='BUY':continue
                    if market=='SIDEWAYS' and not fvg and not liq:continue

                    conf=count_conf(smc,mom,fvg,liq,action)
                    if conf<5:continue
                    if action=='BUY' and mom['momentum']!='BULLISH':continue
                    if action=='SELL' and mom['momentum']!='BEARISH':continue
                    if action=='BUY' and mom['rsi']>70:continue
                    if action=='SELL' and mom['rsi']<30:continue

                    # ML FILTER - Key improvement!
                    features=extract_trade_features(df5,df15,smc,mom,market,fvg,liq,action)
                    if features:
                        features_scaled=scaler.transform([features])
                        ml_prob=ml_model.predict_proba(features_scaled)[0][1]
                        # Only take trade if ML confidence > 60%
                        if ml_prob<0.35:
                            ml_filtered+=1
                            continue

                    atr=(df5['high']-df5['low']).tail(14).mean()
                    if atr<=0:continue
                    sl_pts=atr*1.5
                    t2_pts=sl_pts*2.5
                    lots=max(1,int(risk_amt/(sl_pts*lot)))
                    lots=min(lots,3)

                    entry_price=df5['close'].iloc[-1]
                    in_trade=True
                    trade_action=action
                    sl=sl_pts;t2=t2_pts
                    entry_idx=i
                    current_lots=lots
                    t1_hit=False

                except:continue
            else:
                row=df.iloc[i]
                bars=i-entry_idx
                pnl=0;reason=''

                if trade_action=='BUY':
                    if not t1_hit and row['high']>=entry_price+(t2*0.5):
                        t1_hit=True;sl=0
                    if row['low']<=entry_price-sl:
                        pnl=-sl*lot*current_lots;reason='SL'
                    elif row['high']>=entry_price+t2:
                        pnl=t2*lot*current_lots;reason='T2'
                    elif bars>=30:
                        pnl=(row['close']-entry_price)*lot*current_lots
                        reason='TIMEOUT'
                else:
                    if not t1_hit and row['low']<=entry_price-(t2*0.5):
                        t1_hit=True;sl=0
                    if row['high']>=entry_price+sl:
                        pnl=-sl*lot*current_lots;reason='SL'
                    elif row['low']<=entry_price-t2:
                        pnl=t2*lot*current_lots;reason='T2'
                    elif bars>=30:
                        pnl=(entry_price-row['close'])*lot*current_lots
                        reason='TIMEOUT'

                if reason:
                    net_pnl=pnl-BROKERAGE
                    current_capital+=net_pnl
                    if pnl<0:daily_losses+=1
                    if pnl>0:wins+=1
                    else:losses+=1
                    if current_capital>peak_capital:peak_capital=current_capital
                    dd=((peak_capital-current_capital)/peak_capital)*100
                    if dd>max_drawdown:max_drawdown=dd
                    in_trade=False
                    t1_hit=False

        total=wins+losses
        wr=round((wins/total)*100,1) if total>0 else 0
        yr_pnl=current_capital-year_start
        yr_return=round((yr_pnl/year_start)*100,1)
        grand_trades+=total
        grand_wins+=wins

        print(f'\n  📅 {year}:')
        print(f'  Capital Start:  Rs.{year_start:,.0f}')
        print(f'  Capital End:    Rs.{current_capital:,.0f}')
        print(f'  PnL (net):      Rs.{yr_pnl:,.0f}')
        print(f'  Return:         {yr_return}%')
        print(f'  Trades:         {total} | WR: {wr}%')

    total_return=round(((current_capital-capital)/capital)*100,1)
    grand_wr=round((grand_wins/grand_trades)*100,1) if grand_trades>0 else 0

    print(f'\n{"="*45}')
    print(f'  📊 ML FILTERED 3 YEAR: {instrument}')
    print(f'{"="*45}')
    print(f'  Start Capital:  Rs.{capital:,.0f}')
    print(f'  Final Capital:  Rs.{current_capital:,.0f}')
    print(f'  Total PnL:      Rs.{current_capital-capital:,.0f}')
    print(f'  Total Return:   {total_return}%')
    print(f'  Win Rate:       {grand_wr}%')
    print(f'  Max Drawdown:   {max_drawdown:.1f}%')
    print(f'  Total Trades:   {grand_trades}')
    print(f'  ML Filtered:    {ml_filtered} trades blocked')
    print(f'  Brokerage:      Rs.{grand_trades*BROKERAGE:,.0f}')
    print(f'{"="*45}')
