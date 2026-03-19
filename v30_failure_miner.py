import json,os,pickle
import numpy as np
import pandas as pd
from datetime import datetime
import logging
log=logging.getLogger(__name__)

class FailureMiner:
    def __init__(self):
        self.corrections_file='failure_corrections.json'
        self.corrections=self.load()

    def load(self):
        if os.path.exists(self.corrections_file):
            return json.load(open(self.corrections_file))
        return {
            'total_analyzed':0,
            'corrected':0,
            'patterns':[],
            'improvements':{},
            'parameter_suggestions':{}
        }

    def save(self):
        json.dump(self.corrections,open(self.corrections_file,'w'),indent=2)

    def find_better_entry(self,df,action,entry,sl,atr):
        """Find where trade would have WON"""
        try:
            h=df['high'].values
            l=df['low'].values
            c=df['close'].values

            best_entry=None
            best_entry_type=None

            if action=='BUY':
                # Look for FVG support below entry
                for i in range(len(df)-5,len(df)-1):
                    if i<2:continue
                    p2=df.iloc[i-2];cur=df.iloc[i]
                    if cur['low']>p2['high']:
                        fvg_mid=(cur['low']+p2['high'])/2
                        if fvg_mid<entry:
                            best_entry=fvg_mid
                            best_entry_type='FVG_SUPPORT'
                            break

                # Order block below entry
                for i in range(len(df)-10,len(df)-1):
                    if i<0:continue
                    candle=df.iloc[i]
                    if candle['close']<candle['open']:  # Bearish candle
                        ob_level=candle['low']
                        if ob_level<entry and ob_level>entry-atr*2:
                            if best_entry is None or ob_level>best_entry:
                                best_entry=ob_level
                                best_entry_type='ORDER_BLOCK'

                # Swing low
                swing_low=min(l[-20:]) if len(l)>=20 else min(l)
                if swing_low<entry and (best_entry is None or swing_low>best_entry):
                    best_entry=swing_low
                    best_entry_type='SWING_LOW'

            else:  # SELL
                # FVG resistance above entry
                for i in range(len(df)-5,len(df)-1):
                    if i<2:continue
                    p2=df.iloc[i-2];cur=df.iloc[i]
                    if cur['high']<p2['low']:
                        fvg_mid=(cur['high']+p2['low'])/2
                        if fvg_mid>entry:
                            best_entry=fvg_mid
                            best_entry_type='FVG_RESISTANCE'
                            break

                swing_high=max(h[-20:]) if len(h)>=20 else max(h)
                if swing_high>entry and (best_entry is None or swing_high<best_entry):
                    best_entry=swing_high
                    best_entry_type='SWING_HIGH'

            return best_entry,best_entry_type
        except:return None,None

    def simulate_corrected_trade(self,df,action,
                                  new_entry,new_sl_mult,atr,future_df):
        """Simulate if corrected entry would have won"""
        try:
            sl=atr*new_sl_mult
            t2=atr*2.5

            for _,row in future_df.iterrows():
                if action=='BUY':
                    if row['low']<=new_entry-sl:return 'LOSS',row['low']
                    elif row['high']>=new_entry+t2:return 'WIN',row['high']
                else:
                    if row['high']>=new_entry+sl:return 'LOSS',row['high']
                    elif row['low']<=new_entry-t2:return 'WIN',row['low']
            return 'TIMEOUT',future_df['close'].iloc[-1]
        except:return 'ERROR',0

    def analyze_3year_failures(self,instrument):
        """Analyze all failures from 3 year backtest"""
        try:
            # Load historical data
            from v30_train_kairos import load_data,to_df,calc_rsi,calc_macd,get_trend

            candles=load_data(instrument)
            if not candles:return []
            df=to_df(candles)
            if df is None:return []

            corrections=[]
            failures_analyzed=0
            failures_corrected=0

            print(f'[MINER] Analyzing {instrument} failures...')

            for i in range(100,len(df)-60,3):
                df5=df.iloc[i-60:i].copy()
                df15=df.iloc[max(0,i-180):i:3].copy()
                df_daily=df.iloc[max(0,i-300):i:12].copy()
                if len(df5)<30:continue

                try:
                    hour=int(str(df5['time'].iloc[-1])[11:13])
                    if hour<9 or hour>15:continue

                    c=df5['close'];h=df5['high'];l=df5['low']
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

                    # Original trade
                    sl_orig=atr*1.5
                    t2_orig=atr*2.5
                    entry=c.iloc[-1]
                    future=df.iloc[i:i+30]

                    orig_outcome='TIMEOUT'
                    for _,row in future.iterrows():
                        if action=='BUY':
                            if row['low']<=entry-sl_orig:orig_outcome='LOSS';break
                            elif row['high']>=entry+t2_orig:orig_outcome='WIN';break
                        else:
                            if row['high']>=entry+sl_orig:orig_outcome='LOSS';break
                            elif row['low']<=entry-t2_orig:orig_outcome='WIN';break

                    # Only analyze FAILURES
                    if orig_outcome!='LOSS':continue
                    failures_analyzed+=1

                    # Try to find better entry
                    better_entry,entry_type=self.find_better_entry(df5,action,entry,sl_orig,atr)

                    # Try different SL multipliers
                    best_correction=None
                    best_outcome=None

                    for sl_mult in [1.8,2.0,2.2,2.5]:
                        outcome,_=self.simulate_corrected_trade(
                            df5,action,
                            better_entry if better_entry else entry,
                            sl_mult,atr,future
                        )
                        if outcome=='WIN':
                            best_correction={'sl_mult':sl_mult,'entry_type':entry_type}
                            best_outcome='WIN'
                            break

                    if best_outcome=='WIN':
                        failures_corrected+=1
                        correction={
                            'instrument':instrument,
                            'action':action,
                            'original_entry':round(entry,2),
                            'better_entry':round(better_entry,2) if better_entry else round(entry,2),
                            'entry_type':entry_type,
                            'original_sl_mult':1.5,
                            'better_sl_mult':best_correction['sl_mult'],
                            'atr':round(atr,2),
                            'rsi':round(rsi,2),
                            'trend15':trend15,
                            'hour':hour,
                            'market_condition':'TRENDING' if abs(trend15)==1 else 'SIDEWAYS',
                        }
                        corrections.append(correction)

                except:continue

            correction_rate=failures_corrected/failures_analyzed*100 if failures_analyzed>0 else 0
            print(f'[MINER] {instrument}: Analyzed={failures_analyzed} Corrected={failures_corrected} Rate={correction_rate:.1f}%')

            # Generate parameter suggestions
            if corrections:
                avg_sl=np.mean([c['better_sl_mult'] for c in corrections])
                entry_types={}
                for c in corrections:
                    et=c.get('entry_type','UNKNOWN')
                    entry_types[et]=entry_types.get(et,0)+1

                best_entry_type=max(entry_types,key=entry_types.get)

                suggestions={
                    'sl_multiplier':round(avg_sl,2),
                    'best_entry_type':best_entry_type,
                    'correction_rate':correction_rate,
                    'corrections_count':len(corrections)
                }
                self.corrections['parameter_suggestions'][instrument]=suggestions
                print(f'[MINER] {instrument} Suggestions: SL={avg_sl:.2f}x Entry={best_entry_type}')

            self.corrections['total_analyzed']+=failures_analyzed
            self.corrections['corrected']+=failures_corrected
            self.corrections['patterns'].extend(corrections[-100:])
            self.save()
            return corrections

        except Exception as e:
            log.error(f'[MINER] Error {instrument}: {e}')
            return []

    def train_on_corrections(self,instrument,corrections):
        """Train ML model on corrected entries"""
        try:
            if len(corrections)<20:
                print(f'[MINER] {instrument}: Not enough corrections ({len(corrections)})')
                return

            from v30_train_kairos import to_df,load_data,extract_kairos_features,get_trend,calc_rsi,calc_macd
            from sklearn.ensemble import RandomForestClassifier
            from sklearn.preprocessing import StandardScaler
            from sklearn.utils import resample
            import pickle

            candles=load_data(instrument)
            if not candles:return
            df=to_df(candles)
            if df is None:return

            correction_features=[]
            correction_labels=[]

            print(f'[MINER] Training on {len(corrections)} corrections...')

            for i in range(100,len(df)-30,3):
                df5=df.iloc[i-60:i].copy()
                df15=df.iloc[max(0,i-180):i:3].copy()
                df_daily=df.iloc[max(0,i-300):i:12].copy()
                if len(df5)<30:continue

                try:
                    c=df5['close'];h=df5['high'];l=df5['low']
                    atr=(h-l).tail(14).mean()
                    if atr<=0:continue

                    rsi=calc_rsi(c).iloc[-1]
                    macd,sig=calc_macd(c)
                    macd_hist=(macd-sig).iloc[-1]
                    trend_d=get_trend(df_daily)
                    trend15=get_trend(df15)

                    buy_score=0;sell_score=0
                    if trend_d==1:buy_score+=2
                    elif trend_d==-1:sell_score+=2
                    if rsi<45:buy_score+=2
                    elif rsi>55:sell_score+=2
                    if macd_hist>0:buy_score+=1
                    elif macd_hist<0:sell_score+=1

                    if buy_score>=4:action='BUY'
                    elif sell_score>=4:action='SELL'
                    else:continue

                    feats=extract_kairos_features(df5,df15,df_daily,action)
                    if not feats:continue

                    # Simulate with corrected parameters
                    suggestions=self.corrections['parameter_suggestions'].get(instrument,{})
                    sl_mult=suggestions.get('sl_multiplier',1.8)
                    sl=atr*sl_mult
                    t2=atr*2.5
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

                    correction_features.append(feats)
                    correction_labels.append(outcome)
                except:continue

            if len(correction_features)<50:
                print(f'[MINER] Not enough correction features')
                return

            wins=sum(correction_labels)
            total=len(correction_labels)
            print(f'[MINER] Correction dataset: {total} samples WR:{wins/total*100:.1f}%')

            # Balance and train
            X=np.array(correction_features)
            y=np.array(correction_labels)
            X_l=X[y==0];y_l=y[y==0]
            X_w=X[y==1];y_w=y[y==1]
            n=min(len(X_l),len(X_w)*2)
            X_ld,y_ld=resample(X_l,y_l,n_samples=n,random_state=42)
            X_wu,y_wu=resample(X_w,y_w,n_samples=n,random_state=42)
            X_b=np.vstack([X_ld,X_wu])
            y_b=np.hstack([y_ld,y_wu])

            sc=StandardScaler()
            X_sc=sc.fit_transform(X_b)

            model=RandomForestClassifier(n_estimators=200,max_depth=10,random_state=42)
            model.fit(X_sc,y_b)
            score=model.score(X_sc,y_b)

            # Save corrected model
            pickle.dump({
                'model':model,'scaler':sc,
                'symbol':instrument,
                'accuracy':score,
                'type':'FAILURE_CORRECTED',
                'corrections_used':len(corrections),
                'trained_on':str(datetime.now())
            },open(f'ml_models/{instrument}_model.pkl','wb'))

            print(f'[MINER] ✅ {instrument}: Corrected model saved! Acc={score*100:.1f}%')

        except Exception as e:
            log.error(f'[MINER] Train error: {e}')

    def run_full_mining(self):
        """Run failure mining for all instruments"""
        from v30_train_kairos import INSTRUMENTS

        print('\n'+'='*60)
        print('  FAILURE PATTERN MINING')
        print('  Analyzing 3 year failures...')
        print('='*60)

        all_corrections={}
        for symbol in INSTRUMENTS.keys():
            print(f'\nMining {symbol}...')
            corrections=self.analyze_3year_failures(symbol)
            if corrections:
                all_corrections[symbol]=corrections
                self.train_on_corrections(symbol,corrections)

        # Summary
        total=self.corrections['total_analyzed']
        corrected=self.corrections['corrected']
        print(f'\n{"="*60}')
        print(f'  MINING COMPLETE!')
        print(f'  Total failures analyzed: {total}')
        print(f'  Correctable: {corrected} ({corrected/total*100:.1f}% if total>0 else "N/A")%')
        print(f'\n  Parameter Suggestions:')
        for inst,sugg in self.corrections['parameter_suggestions'].items():
            print(f'  {inst}:')
            print(f'    SL multiplier: {sugg["sl_multiplier"]}x')
            print(f'    Best entry: {sugg["best_entry_type"]}')
            print(f'    Correction rate: {sugg["correction_rate"]:.1f}%')
        print('='*60)

        # Send summary to Telegram
        self.notify_mining_results()
        return all_corrections

    def notify_mining_results(self):
        try:
            from v30_notify import send
            total=self.corrections['total_analyzed']
            corrected=self.corrections['corrected']
            rate=corrected/total*100 if total>0 else 0
            msg=f"""🔬 <b>FAILURE MINING COMPLETE</b>
━━━━━━━━━━━━━━━
📊 Failures Analyzed: {total}
✅ Correctable: {corrected} ({rate:.1f}%)

<b>Key Improvements:</b>
"""
            for inst,sugg in list(self.corrections['parameter_suggestions'].items())[:5]:
                msg+=f'• {inst}: SL={sugg["sl_multiplier"]}x Entry={sugg["best_entry_type"]}\n'
            msg+='\n🚀 Models retrained with corrections!'
            send(msg)
        except:pass

miner=FailureMiner()
