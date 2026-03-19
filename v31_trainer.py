import json,os,pickle
import numpy as np
import pandas as pd
from datetime import datetime
import logging
log=logging.getLogger(__name__)

# Load from instrument manager (all 36 instruments!)
try:
    from v31_instrument_manager import INSTRUMENTS as _IM
    INSTRUMENTS={k:{'lot':v['lot'],'token':v['token']} for k,v in _IM.items()}
    log.info(f'Loaded {len(INSTRUMENTS)} instruments from manager')
except:
    INSTRUMENTS={
        'NIFTY':{'lot':65,'token':'99926000'},
        'BANKNIFTY':{'lot':30,'token':'99926009'},
        'NATURALGAS':{'lot':1250,'token':'234230'},
    }

def load_data(symbol):
    all_candles=[]
    token=INSTRUMENTS.get(symbol,{}).get('token','')
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

def get_wyckoff(df):
    c=df['close']
    if len(c)<3:return 'RANGING'
    if float(c.iloc[-1])>float(c.iloc[-3]):return 'MARKUP'
    elif float(c.iloc[-1])<float(c.iloc[-3]):return 'MARKDOWN'
    return 'RANGING'

def collect_v31_signals(symbol):
    """
    Collect ALL V31 signals from 3 years:
    Both winners and losers with full context
    """
    from v31_scoring import calc_v31_score
    from v31_strategy import get_market_regime,get_trend_v31
    from v30_rr_filter import find_tight_sl,find_best_target

    candles=load_data(symbol)
    if not candles:return []
    df=to_df(candles)
    if df is None or len(df)<200:return []

    signals=[]
    lot=INSTRUMENTS[symbol]['lot']
    print(f'[TRAIN] {symbol}: {len(df)} candles...')

    for i in range(100,len(df)-30,2):
        df5=df.iloc[i-60:i].copy()
        df15=df.iloc[max(0,i-180):i:3].copy()
        df_daily=df.iloc[max(0,i-300):i:12].copy()
        if len(df5)<30 or len(df15)<10:continue

        try:
            hour=int(str(df5['time'].iloc[-1])[11:13])
            if hour not in [10,11,13,14]:continue

            c=df5['close'];h=df5['high'];l=df5['low'];v=df5['volume']
            atr=float((h-l).tail(14).mean())
            if atr<=0:continue

            # Volatility filter
            avg_atr=float((h-l).rolling(20).mean().iloc[-1])
            if atr<avg_atr*0.7:continue

            regime,_=get_market_regime(df5,df15,df_daily)
            if regime=='VOLATILE':continue

            # Try both actions
            for action in ['BUY','SELL']:
                wy=get_wyckoff(df15)
                score,components,has_liq,has_fvg=calc_v31_score(
                    df5,df15,action,regime,wy,atr)

                if score<12:continue

                # Get SL and target
                sl_type,raw_sl,_=find_tight_sl(df5,df15,action,atr)
                if raw_sl<atr*0.5:raw_sl=atr*0.75
                if raw_sl>atr*2.0:continue

                is_trending=regime in ['TRENDING_UP','TRENDING_DOWN']
                _,target,rr=find_best_target(
                    df5,df15,action,float(c.iloc[-1]),raw_sl,atr,is_trending)
                if rr<2.0:continue

                entry=float(c.iloc[-1])
                future=df.iloc[i:i+30]

                # Simulate outcome
                outcome=0;exit_price=entry;exit_reason='TO'
                for _,row in future.iterrows():
                    if action=='BUY':
                        if row['low']<=entry-raw_sl:
                            outcome=0;exit_price=entry-raw_sl
                            exit_reason='SL';break
                        elif row['high']>=entry+raw_sl*rr:
                            outcome=1;exit_price=entry+raw_sl*rr
                            exit_reason='T2';break
                    else:
                        if row['high']>=entry+raw_sl:
                            outcome=0;exit_price=entry+raw_sl
                            exit_reason='SL';break
                        elif row['low']<=entry-raw_sl*rr:
                            outcome=1;exit_price=entry-raw_sl*rr
                            exit_reason='T2';break

                pnl=(exit_price-entry)*lot if action=='BUY' else (entry-exit_price)*lot
                if outcome==0:pnl=-abs(pnl)

                # Store complete signal
                t5=get_trend_v31(df5);t15=get_trend_v31(df15)
                vwap=float((c*v).sum()/v.sum()) if float(v.sum())>0 else float(c.mean())

                signal={
                    'symbol':symbol,
                    'action':action,
                    'score':score,
                    'regime':regime,
                    'wyckoff':wy,
                    'hour':hour,
                    'liq_sweep':components.get('liq_sweep',0),
                    'bos_choch':components.get('bos_choch',0),
                    'fvg':components.get('fvg',0),
                    'ote':components.get('ote',0),
                    'trend':components.get('trend',0),
                    'vwap':components.get('vwap',0),
                    'gamma':components.get('gamma',0),
                    'trend5':t5,'trend15':t15,
                    'above_vwap':1 if float(c.iloc[-1])>vwap else 0,
                    'atr':atr,'sl_pts':raw_sl,'rr':rr,
                    'sl_atr_ratio':raw_sl/atr,
                    'outcome':outcome,'pnl':pnl,
                    'exit_reason':exit_reason,
                    'timestamp':str(df5['time'].iloc[-1])
                }
                signals.append(signal)

        except:continue

    wins=sum(1 for s in signals if s['outcome']==1)
    total=len(signals)
    print(f'[TRAIN] {symbol}: {total} signals WR:{wins/total*100:.1f}%' if total>0 else f'[TRAIN] {symbol}: 0 signals')
    return signals

def mine_failures_v31(signals,symbol):
    """
    Analyze ALL failure trades:
    Why did SL hit?
    What could make it a winner?
    Find pattern corrections
    """
    failures=[s for s in signals if s['outcome']==0]
    if not failures:return {}

    print(f'[MINE] {symbol}: Analyzing {len(failures)} failures...')

    # Pattern analysis
    failure_patterns={
        'counter_trend':0,
        'no_fvg':0,
        'no_liq':0,
        'wrong_wyckoff':0,
        'sl_too_tight':0,
        'bad_session':0,
        'low_score':0,
        'ranging_market':0,
    }

    corrections=[]
    for f in failures:
        reasons=[]
        fixes=[]

        # Check each failure reason
        if f['trend5']!=f['trend15']:
            failure_patterns['counter_trend']+=1
            reasons.append('TREND_CONFLICT')
            fixes.append('Wait for both 5min and 15min trends to align')

        if f['fvg']==0:
            failure_patterns['no_fvg']+=1
            reasons.append('NO_FVG')
            fixes.append('Only enter when FVG present as entry confirmation')

        if f['liq_sweep']==0:
            failure_patterns['no_liq']+=1
            reasons.append('NO_LIQ_SWEEP')
            fixes.append('Require liquidity sweep before entry')

        if f['action']=='BUY' and f['wyckoff'] in ['DIST','MARK']:
            failure_patterns['wrong_wyckoff']+=1
            reasons.append(f'WRONG_WYCKOFF_{f["wyckoff"]}')
            fixes.append('Never buy in Distribution or Markdown phase')

        if f['sl_atr_ratio']<0.8:
            failure_patterns['sl_too_tight']+=1
            reasons.append(f'SL_TIGHT_{f["sl_atr_ratio"]:.2f}x')
            fixes.append(f'Use minimum 0.8x ATR SL instead of {f["sl_atr_ratio"]:.2f}x')

        if f['hour'] in [9,15]:
            failure_patterns['bad_session']+=1
            reasons.append(f'BAD_HOUR_{f["hour"]}')
            fixes.append('Avoid 9AM and 3PM - too much noise')

        if f['score']<18:
            failure_patterns['low_score']+=1
            reasons.append(f'LOW_SCORE_{f["score"]}')
            fixes.append('Minimum score 18 required')

        if f['regime']=='RANGING':
            failure_patterns['ranging_market']+=1
            reasons.append('RANGING_MARKET')
            fixes.append('In ranging market: require gamma wall confirmation')

        # What WOULD have made this a winner?
        better_params={}
        if f['sl_atr_ratio']<0.8:
            better_params['sl_multiplier']=max(0.8,f['sl_atr_ratio']+0.2)
        if f['fvg']==0:
            better_params['require_fvg']=True
        if f['regime']=='RANGING':
            better_params['require_gamma_in_ranging']=True

        corrections.append({
            'failure':f,
            'reasons':reasons,
            'fixes':fixes,
            'better_params':better_params
        })

    # Find top failure patterns
    total_failures=len(failures)
    analysis={
        'total_failures':total_failures,
        'failure_patterns':{k:round(v/total_failures*100,1)
                           for k,v in failure_patterns.items()},
        'top_reason':max(failure_patterns,key=failure_patterns.get),
        'corrections':corrections[:100]  # Keep top 100
    }

    print(f'[MINE] {symbol} failure analysis:')
    for pattern,pct in sorted(analysis['failure_patterns'].items(),
                               key=lambda x:-x[1])[:5]:
        print(f'  {pattern}: {pct}%')

    return analysis

def build_meta_layer(all_signals,all_analyses):
    """
    Build Meta Layer from all learnings:
    1. Optimal parameters per regime
    2. Best entry conditions
    3. Hour performance
    4. Score thresholds
    """
    print(f'\n[META] Building meta layer from {sum(len(s) for s in all_signals.values())} signals...')

    meta={
        'version':'V31',
        'created':str(datetime.now()),
        'total_signals':0,
        'total_wins':0,
        'optimal_params':{},
        'regime_performance':{},
        'hour_performance':{},
        'score_performance':{},
        'failure_patterns':{},
        'warm_params':{}
    }

    all_sigs=[s for signals in all_signals.values() for s in signals]
    meta['total_signals']=len(all_sigs)
    meta['total_wins']=sum(1 for s in all_sigs if s['outcome']==1)

    # Regime performance
    for regime in ['TRENDING_UP','TRENDING_DOWN','RANGING']:
        reg_sigs=[s for s in all_sigs if s['regime']==regime]
        if reg_sigs:
            wins=sum(1 for s in reg_sigs if s['outcome']==1)
            meta['regime_performance'][regime]={
                'count':len(reg_sigs),
                'win_rate':round(wins/len(reg_sigs)*100,1)
            }

    # Hour performance
    for hour in range(9,16):
        h_sigs=[s for s in all_sigs if s['hour']==hour]
        if h_sigs:
            wins=sum(1 for s in h_sigs if s['outcome']==1)
            meta['hour_performance'][str(hour)]={
                'count':len(h_sigs),
                'win_rate':round(wins/len(h_sigs)*100,1)
            }

    # Score performance
    for score_range in [(12,15),(15,18),(18,22),(22,26),(26,43)]:
        lo,hi=score_range
        s_sigs=[s for s in all_sigs if lo<=s['score']<hi]
        if s_sigs:
            wins=sum(1 for s in s_sigs if s['outcome']==1)
            key=f'{lo}-{hi}'
            meta['score_performance'][key]={
                'count':len(s_sigs),
                'win_rate':round(wins/len(s_sigs)*100,1)
            }

    # Aggregate failure patterns
    all_patterns={}
    for analysis in all_analyses.values():
        for pattern,pct in analysis.get('failure_patterns',{}).items():
            if pattern not in all_patterns:
                all_patterns[pattern]=[]
            all_patterns[pattern].append(pct)
    meta['failure_patterns']={k:round(np.mean(v),1)
                               for k,v in all_patterns.items()}

    # Optimal parameters from meta analysis
    best_hours=[h for h,data in meta['hour_performance'].items()
                if data['win_rate']>50]
    avoid_hours=[h for h,data in meta['hour_performance'].items()
                 if data['win_rate']<40]

    # Find optimal score threshold
    best_score_range=max(meta['score_performance'].items(),
                         key=lambda x:x[1]['win_rate'],
                         default=('18-22',{'win_rate':50}))

    meta['warm_params']={
        'best_hours':[int(h) for h in best_hours],
        'avoid_hours':[int(h) for h in avoid_hours],
        'optimal_score_threshold':18,
        'best_regime':max(meta['regime_performance'].items(),
                         key=lambda x:x[1]['win_rate'],
                         default=('TRENDING_UP',{'win_rate':50}))[0],
        'require_fvg_pct':meta['failure_patterns'].get('no_fvg',0),
        'sl_min_atr':0.8,
        'adaptive_ml_threshold':0.55,
    }

    print(f'\n[META] Summary:')
    print(f'  Total signals: {meta["total_signals"]}')
    wr=meta["total_wins"]/meta["total_signals"]*100 if meta["total_signals"]>0 else 0
    print(f'  Overall WR: {wr:.1f}%')
    print(f'  Best hours: {meta["warm_params"]["best_hours"]}')
    print(f'  Avoid hours: {meta["warm_params"]["avoid_hours"]}')
    print(f'\n  Regime performance:')
    for r,d in meta['regime_performance'].items():
        print(f'    {r}: WR={d["win_rate"]}% ({d["count"]} trades)')
    print(f'\n  Score performance:')
    for r,d in sorted(meta['score_performance'].items()):
        print(f'    Score {r}: WR={d["win_rate"]}% ({d["count"]} trades)')
    print(f'\n  Top failure reasons:')
    for p,pct in sorted(meta['failure_patterns'].items(),key=lambda x:-x[1])[:5]:
        print(f'    {p}: {pct}%')

    os.makedirs('ml_models',exist_ok=True)
    json.dump(meta,open('ml_models/v31_meta_layer.json','w'),indent=2)
    print(f'\n[META] Saved to ml_models/v31_meta_layer.json')
    return meta

def train_v31_ml_from_signals(symbol,signals):
    """Train V31 ML model from collected signals"""
    if len(signals)<50:
        print(f'[TRAIN ML] {symbol}: Not enough signals ({len(signals)})')
        return None

    features=[]
    labels=[]

    for s in signals:
        f=[
            s['score']/43,
            1 if s['regime']=='TRENDING_UP' else -1 if s['regime']=='TRENDING_DOWN' else 0,
            s['hour']/24,
            s['liq_sweep']/5,
            s['bos_choch']/4,
            s['fvg']/4,
            s['ote']/3,
            s['trend']/4,
            s['vwap']/2,
            s['gamma']/13,
            s['trend5'],
            s['trend15'],
            1 if s['trend5']==s['trend15'] else 0,
            s['above_vwap'],
            s['sl_atr_ratio'],
            s['rr']/10,
            1 if s['wyckoff'] in ['ACCUM','MARKUP'] else -1 if s['wyckoff'] in ['DIST','MARK'] else 0,
            1 if s['action']=='BUY' else -1,
            1 if s['regime'] in ['TRENDING_UP','TRENDING_DOWN'] else 0,
            s['liq_sweep']/5+s['bos_choch']/4,  # Structure strength
            s['fvg']/4+s['ote']/3,               # Entry strength
        ]
        features.append(f)
        labels.append(s['outcome'])

    from v31_ml_engine import train_v31_model
    model,sc,acc=train_v31_model(symbol,features,labels)
    if model:
        print(f'[TRAIN ML] ✅ {symbol}: Acc={acc*100:.1f}%')
    return model

def apply_meta_to_v31(meta):
    """Apply meta layer learnings to V31 parameters"""
    try:
        warm_params=meta.get('warm_params',{})

        from v30_adaptive_learner import brain
        for inst in INSTRUMENTS:
            brain.init_instrument(inst)
            b=brain.brain['instruments'][inst]

            # Apply best hours from meta
            best_h=warm_params.get('best_hours',[10,11,13,14])
            avoid_h=warm_params.get('avoid_hours',[9,15])
            b['best_hours']=best_h
            b['avoid_hours']=avoid_h

            # Apply optimal score threshold
            b['min_kairos']=warm_params.get('optimal_score_threshold',18)

            # Apply SL minimum
            b['sl_multiplier']=warm_params.get('sl_min_atr',0.8)

        brain.save()
        print(f'[META] Applied meta layer to {len(INSTRUMENTS)} instruments!')
        print(f'  Best hours: {warm_params.get("best_hours")}')
        print(f'  Avoid hours: {warm_params.get("avoid_hours")}')
        print(f'  Score threshold: {warm_params.get("optimal_score_threshold")}')

    except Exception as e:
        print(f'[META] Apply error: {e}')

def run_full_v31_training():
    """
    Complete V31 training pipeline:
    1. Collect all signals (3 years)
    2. Mine failures
    3. Build meta layer
    4. Train ML models
    5. Apply warm start
    """
    print('\n'+'='*65)
    print('  KAIROS V31 COMPLETE TRAINING PIPELINE')
    print('  Signals → Mining → Meta Layer → ML → Warm Start')
    print('='*65)

    all_signals={}
    all_analyses={}

    # Step 1: Collect signals
    print('\n--- STEP 1: Collecting 3-year signals ---')
    for symbol in INSTRUMENTS:
        signals=collect_v31_signals(symbol)
        if signals:
            all_signals[symbol]=signals
            json.dump(signals,open(f'ml_models/{symbol}_v31_all_signals.json','w'))

    total=sum(len(s) for s in all_signals.values())
    wins=sum(sum(1 for s in sigs if s['outcome']==1)
             for sigs in all_signals.values())
    print(f'\n[STEP 1] Total: {total} signals WR:{wins/total*100:.1f}%' if total>0 else '[STEP 1] No signals')

    # Step 2: Mine failures
    print('\n--- STEP 2: Mining failure trades ---')
    for symbol,signals in all_signals.items():
        analysis=mine_failures_v31(signals,symbol)
        if analysis:
            all_analyses[symbol]=analysis
            json.dump(analysis,open(f'ml_models/{symbol}_v31_failure_analysis.json','w'),
                     default=str)

    # Step 3: Build meta layer
    print('\n--- STEP 3: Building meta layer ---')
    meta=build_meta_layer(all_signals,all_analyses)

    # Step 4: Train ML models
    print('\n--- STEP 4: Training ML models ---')
    for symbol,signals in all_signals.items():
        print(f'\n[ML] Training {symbol}...')
        train_v31_ml_from_signals(symbol,signals)

    # Step 5: Apply warm start
    print('\n--- STEP 5: Applying warm start ---')
    apply_meta_to_v31(meta)

    # Summary
    print('\n'+'='*65)
    print('  V31 TRAINING COMPLETE!')
    print('='*65)
    print(f'  Instruments trained: {len(all_signals)}')
    print(f'  Total signals: {total}')
    print(f'  Overall WR: {wins/total*100:.1f}%' if total>0 else '')
    print(f'  ML models: ml_models/*_v31_model.pkl')
    print(f'  Meta layer: ml_models/v31_meta_layer.json')
    print(f'  Failure analyses: ml_models/*_v31_failure_analysis.json')
    print('\n✅ V31 ready to trade with pre-trained brain!')
    return meta

if __name__=='__main__':
    # Step 1-5: Collect signals, mine, meta, train ML
    run_full_v31_training()

    # Step 6: Run failure optimizer
    print('\n[OPTIMIZER] Starting failure optimization...')
    from v31_failure_optimizer import run_failure_optimizer
    run_failure_optimizer()
    print('\n✅ Full training + optimization complete!')


# Auto-tune score thresholds after training
try:
    from v31_score_tuner import update_threshold
    import json,os
    for fname in os.listdir('ml_models'):
        if 'v31_all_signals' in fname and 'bt' not in fname:
            inst=fname.replace('_v31_all_signals.json','')
            signals=json.load(open(f'ml_models/{fname}'))
            thresh=update_threshold(inst,signals)
            print(f'{inst}: optimal score threshold = {thresh}')
except Exception as e:
    print(f'Score tuning error: {e}')
