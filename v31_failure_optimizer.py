import json,os,pickle
import numpy as np
import pandas as pd
from datetime import datetime
import logging
log=logging.getLogger(__name__)

INSTRUMENTS={
    'NIFTY':{'lot':75,'token':'99926000'},
    'BANKNIFTY':{'lot':30,'token':'99926009'},
    'SENSEX':{'lot':20,'token':'99919000'},
    'FINNIFTY':{'lot':65,'token':'99926037'},
    'MIDCPNIFTY':{'lot':120,'token':'99926074'},
    'CRUDEOIL':{'lot':100,'token':'472790'},
    'GOLDM':{'lot':10,'token':'477904'},
    'SILVERM':{'lot':30,'token':'457533'},
    'LT':{'lot':450,'token':'11483'},
    'NTPC':{'lot':4500,'token':'11630'},
    'MARUTI':{'lot':100,'token':'10999'},
    'BHARTIARTL':{'lot':950,'token':'10604'},
    'SBIN':{'lot':1500,'token':'3045'},
    'TATAMOTORS':{'lot':1350,'token':'3456'},
    'RELIANCE':{'lot':250,'token':'2885'},
    'HINDUNILVR':{'lot':300,'token':'1394'},
    'TCS':{'lot':150,'token':'11536'},
    'TATASTEEL':{'lot':5500,'token':'3499'},
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

# ============================================================
# STEP 1: OPTIMAL SL FINDER
# Try multiple SL multipliers and find which works best
# ============================================================
def find_optimal_sl(entry,action,atr,future_df,rr_target=2.0):
    """
    For each failed trade, try different SL values:
    0.5x, 0.75x, 1.0x, 1.25x, 1.5x, 2.0x ATR
    Find which SL would have survived to hit target
    """
    sl_multipliers=[0.5,0.75,1.0,1.25,1.5,2.0]
    results={}

    for mult in sl_multipliers:
        sl_pts=atr*mult
        target=sl_pts*rr_target
        outcome='TO'
        pnl=0

        for _,row in future_df.iterrows():
            if action=='BUY':
                if row['low']<=entry-sl_pts:
                    outcome='SL';pnl=-sl_pts;break
                elif row['high']>=entry+target:
                    outcome='WIN';pnl=target;break
            else:
                if row['high']>=entry+sl_pts:
                    outcome='SL';pnl=-sl_pts;break
                elif row['low']<=entry-target:
                    outcome='WIN';pnl=target;break

        results[mult]={'outcome':outcome,'pnl':pnl,'sl_pts':sl_pts}

    # Find tightest SL that wins
    winning_mults=[m for m,r in results.items() if r['outcome']=='WIN']
    if winning_mults:
        best_mult=min(winning_mults)  # Tightest winning SL
        return best_mult,results[best_mult],results
    return None,None,results

# ============================================================
# STEP 2: OPTIMAL ENTRY FINDER
# Check if waiting for better entry improves outcome
# ============================================================
def find_optimal_entry(df5,action,atr,future_df,raw_sl):
    """
    Fine-tune entry:
    1. FVG retest entry (wait for price to pull back to FVG)
    2. OB retest entry (wait for price to retest OB)
    3. 50% retracement entry
    """
    from v31_strategy import detect_fvg_v31,detect_ob_v31
    entries=[]
    current=float(df5['close'].iloc[-1])

    # Entry 1: Current price (immediate)
    entries.append({
        'type':'IMMEDIATE',
        'price':current,
        'delay':0
    })

    # Entry 2: FVG retest
    has_fvg,fvg=detect_fvg_v31(df5,action,atr)
    if has_fvg and fvg:
        if action=='BUY':
            fvg_entry=fvg.get('bottom',current)
        else:
            fvg_entry=fvg.get('top',current)
        entries.append({
            'type':'FVG_RETEST',
            'price':fvg_entry,
            'delay':2  # Wait 2 candles
        })

    # Entry 3: 0.5% pullback
    if action=='BUY':
        pullback=current*(1-0.005)
    else:
        pullback=current*(1+0.005)
    entries.append({
        'type':'PULLBACK_0.5%',
        'price':pullback,
        'delay':3
    })

    # Simulate each entry
    results=[]
    for entry_info in entries:
        entry_price=entry_info['price']
        delay=entry_info['delay']
        sl_pts=raw_sl
        target=sl_pts*2.0
        outcome='TO';pnl=0

        future_slice=future_df.iloc[delay:]
        for _,row in future_slice.iterrows():
            if action=='BUY':
                if row['low']<=entry_price-sl_pts:
                    outcome='SL';pnl=-sl_pts;break
                elif row['high']>=entry_price+target:
                    outcome='WIN';pnl=target;break
            else:
                if row['high']>=entry_price+sl_pts:
                    outcome='SL';pnl=-sl_pts;break
                elif row['low']<=entry_price-target:
                    outcome='WIN';pnl=target;break

        results.append({
            'entry_type':entry_info['type'],
            'entry_price':entry_price,
            'outcome':outcome,
            'pnl':pnl
        })

    # Find best entry
    winning=[r for r in results if r['outcome']=='WIN']
    if winning:
        return winning[0],results
    return results[0],results

# ============================================================
# STEP 3: OPTIMAL TARGET FINDER
# Find best RR ratio for each trade
# ============================================================
def find_optimal_target(entry,action,atr,future_df,sl_pts):
    """
    Test different RR ratios:
    1:1, 1:1.5, 1:2, 1:3, 1:5
    Find best achievable target
    """
    rr_ratios=[1.0,1.5,2.0,3.0,5.0]
    results={}

    for rr in rr_ratios:
        target=sl_pts*rr
        outcome='TO';pnl=0

        for _,row in future_df.iterrows():
            if action=='BUY':
                if row['low']<=entry-sl_pts:
                    outcome='SL';pnl=-sl_pts;break
                elif row['high']>=entry+target:
                    outcome='WIN';pnl=target;break
            else:
                if row['high']>=entry+sl_pts:
                    outcome='SL';pnl=-sl_pts;break
                elif row['low']<=entry-target:
                    outcome='WIN';pnl=target;break

        results[rr]={'outcome':outcome,'pnl':pnl,'target':target}

    # Find max achievable RR
    winning_rr=[rr for rr,r in results.items() if r['outcome']=='WIN']
    if winning_rr:
        best_rr=max(winning_rr)
        return best_rr,results[best_rr],results
    return None,None,results

# ============================================================
# STEP 4: FAILURE ANALYSIS
# Deep analysis of WHY trade failed
# ============================================================
def analyze_failure(signal,df5,df15,action,atr,future_df):
    """
    Comprehensive failure analysis:
    1. Was SL too tight?
    2. Was entry bad?
    3. Was trend wrong?
    4. Was session bad?
    5. What would have worked?
    """
    reasons=[]
    corrections={}

    # Check SL tightness
    sl_atr=signal.get('sl_atr',1.0)
    if sl_atr<0.75:
        reasons.append('SL_TOO_TIGHT')
        corrections['optimal_sl_mult']=1.0

    # Check session
    hour=signal.get('hour',10)
    if hour in [9,15]:
        reasons.append('BAD_SESSION')
        corrections['avoid_hours']=[9,15]

    # Check trend alignment
    t5=signal.get('trend5',0)
    t15=signal.get('trend15',0)
    if t5!=t15:
        reasons.append('TREND_CONFLICT_5_15')
        corrections['require_trend_alignment']=True

    # Check score
    score=signal.get('score',0)
    if score<18:
        reasons.append(f'LOW_SCORE_{score}')
        corrections['min_score']=18

    # Check FVG
    if not signal.get('fvg',False):
        reasons.append('NO_FVG')
        corrections['require_fvg']=True

    # Check regime
    regime=signal.get('regime','')
    if regime=='RANGING':
        reasons.append('RANGING_MARKET')
        corrections['avoid_ranging']=True

    # Find what would have worked
    opt_sl_mult,opt_sl_result,all_sl=find_optimal_sl(
        float(df5['close'].iloc[-1]),action,atr,future_df)

    opt_rr,opt_rr_result,all_rr=find_optimal_target(
        float(df5['close'].iloc[-1]),action,atr,
        atr*(opt_sl_mult or 1.0),future_df)

    opt_entry,all_entries=find_optimal_entry(
        df5,action,atr,future_df,atr*1.0)

    # Build correction
    correction={
        'original_outcome':'LOSS',
        'failure_reasons':reasons,
        'corrections':corrections,
        'optimal_sl_mult':opt_sl_mult,
        'optimal_sl_worked':opt_sl_result is not None,
        'optimal_rr':opt_rr,
        'optimal_entry_type':opt_entry.get('entry_type','IMMEDIATE'),
        'would_win_with_fixes':opt_sl_result is not None and opt_sl_result.get('outcome')=='WIN',
        'score':score,'regime':regime,'hour':hour
    }

    return correction

# ============================================================
# STEP 5: RETRAIN WITH CORRECTED DATA
# ============================================================
def retrain_with_corrections(symbol,original_signals,corrections):
    """
    Create enhanced training data:
    - Original wins = positive examples
    - Corrected failures = additional positive examples
    - Unchanged losses = negative examples
    """
    enhanced_features=[]
    enhanced_labels=[]

    for i,(sig,corr) in enumerate(zip(original_signals,corrections)):
        if corr is None:continue

        # Base features
        features=[
            sig.get('score',0)/43,
            1 if sig.get('regime')=='TRENDING_UP' else -1 if sig.get('regime')=='TRENDING_DOWN' else 0,
            sig.get('hour',10)/24,
            sig.get('liq',0)/5,
            sig.get('bos',0)/4,
            sig.get('fvg',0)/4,
            sig.get('ml_prob',0.5),
            sig.get('rr',2)/10,
            sig.get('sl_atr',1),
            sig.get('trend5',0),
            sig.get('trend15',0),
            1 if sig.get('trend5')==sig.get('trend15') else 0,
            sig.get('gamma_blast',0)*1.0,
            sig.get('trap_score',0)/9,
            # Correction features
            corr.get('optimal_sl_mult',1.0)/2,
            corr.get('optimal_rr',2)/5 if corr.get('optimal_rr') else 0,
            1 if corr.get('optimal_entry_type')=='FVG_RETEST' else 0,
            len(corr.get('failure_reasons',[]))/10,
            1 if corr.get('would_win_with_fixes') else 0,
        ]

        original_outcome=sig.get('outcome',0)

        # If failure but corrections would have won → teach model
        if original_outcome==0 and corr.get('would_win_with_fixes'):
            # This trade CAN be profitable with right parameters
            enhanced_features.append(features)
            enhanced_labels.append(1)  # Teach: this setup works!

            # Also add corrected version as strong positive
            corrected_features=features.copy()
            corrected_features[8]=corr.get('optimal_sl_mult',1.0)/2  # Better SL
            corrected_features[9]=corr.get('optimal_rr',2)/5  # Better RR
            enhanced_features.append(corrected_features)
            enhanced_labels.append(1)
        else:
            enhanced_features.append(features)
            enhanced_labels.append(original_outcome)

    if not enhanced_features:
        print(f'[OPT] {symbol}: No data!')
        return None

    wins=sum(enhanced_labels)
    total=len(enhanced_labels)
    print(f'[OPT] {symbol}: {total} samples WR:{wins/total*100:.1f}%')

    # Train enhanced model
    from v31_ml_engine import train_v31_model
    model,sc,acc=train_v31_model(symbol,enhanced_features,enhanced_labels)
    if model:
        print(f'[OPT] ✅ {symbol}: Enhanced model acc={acc*100:.1f}%')
    return model

# ============================================================
# MAIN OPTIMIZER
# ============================================================
def run_failure_optimizer():
    print('\n'+'='*65)
    print('  V31 FAILURE OPTIMIZER')
    print('  Analyze failures → Find corrections → Retrain ML')
    print('='*65)

    all_improvements={}

    for symbol in INSTRUMENTS:
        sig_file=f'ml_models/{symbol}_v31_all_signals.json'
        if not os.path.exists(sig_file):
            print(f'[OPT] {symbol}: No signals yet - skip')
            continue

        signals=json.load(open(sig_file))
        failures=[s for s in signals if s.get('outcome')==0]
        wins=[s for s in signals if s.get('outcome')==1]

        print(f'\n[OPT] {symbol}: {len(signals)} signals '
              f'({len(wins)}W/{len(failures)}L)')

        if len(failures)<10:
            print(f'[OPT] {symbol}: Not enough failures')
            continue

        # Load candle data
        candles=load_data(symbol)
        if not candles:continue
        df=to_df(candles)
        if df is None:continue

        corrections=[]
        correctable=0

        # Analyze each failure
        for sig in failures[:200]:  # Process up to 200 failures
            try:
                # Find candle position
                timestamp=sig.get('timestamp','')
                if not timestamp:corrections.append(None);continue

                # Find matching candle
                matches=df[df['time'].astype(str).str.startswith(
                    timestamp[:16])]
                if matches.empty:corrections.append(None);continue

                idx=matches.index[0]
                if idx<60 or idx+36>=len(df):
                    corrections.append(None);continue

                df5=df.iloc[idx-60:idx].copy()
                df15=df.iloc[max(0,idx-180):idx:3].copy()
                future=df.iloc[idx:idx+36].copy()

                atr=float((df5['high']-df5['low']).tail(14).mean())
                if atr<=0:corrections.append(None);continue

                action=sig.get('action','BUY')

                # Analyze failure
                correction=analyze_failure(
                    sig,df5,df15,action,atr,future)
                corrections.append(correction)

                if correction.get('would_win_with_fixes'):
                    correctable+=1

            except Exception as e:
                corrections.append(None)
                continue

        pct=round(correctable/len(failures)*100,1) if failures else 0
        print(f'[OPT] {symbol}: {correctable}/{len(failures)} '
              f'({pct}%) correctable')

        # Collect top failure reasons
        all_reasons={}
        for c in corrections:
            if c:
                for r in c.get('failure_reasons',[]):
                    all_reasons[r]=all_reasons.get(r,0)+1

        print(f'[OPT] Top failure reasons:')
        for r,cnt in sorted(all_reasons.items(),key=lambda x:-x[1])[:5]:
            print(f'  {r}: {cnt} ({cnt/len(failures)*100:.0f}%)')

        # Optimal parameter suggestions
        opt_sl_mults=[c['optimal_sl_mult'] for c in corrections
                      if c and c.get('optimal_sl_mult')]
        opt_rrs=[c['optimal_rr'] for c in corrections
                 if c and c.get('optimal_rr')]

        suggestions={}
        if opt_sl_mults:
            suggestions['optimal_sl_mult']=round(np.median(opt_sl_mults),2)
            print(f'[OPT] Optimal SL: {suggestions["optimal_sl_mult"]}x ATR')
        if opt_rrs:
            suggestions['optimal_rr']=round(np.median(opt_rrs),1)
            print(f'[OPT] Optimal RR: 1:{suggestions["optimal_rr"]}')

        # Save analysis
        analysis={
            'symbol':symbol,
            'total_failures':len(failures),
            'correctable':correctable,
            'correctable_pct':pct,
            'top_reasons':all_reasons,
            'suggestions':suggestions,
            'corrections':[c for c in corrections if c][:50]
        }
        json.dump(analysis,
                  open(f'ml_models/{symbol}_v31_failure_analysis.json','w'),
                  indent=2,default=str)

        all_improvements[symbol]={
            'correctable_pct':pct,
            'suggestions':suggestions
        }

        # Retrain with corrected data
        if correctable>=10:
            print(f'[OPT] Retraining {symbol} with corrections...')
            retrain_with_corrections(symbol,failures[:200],corrections)

    # Summary
    print('\n'+'='*65)
    print('  OPTIMIZATION COMPLETE')
    print('='*65)
    for sym,imp in all_improvements.items():
        print(f'{sym}: {imp["correctable_pct"]}% correctable '
              f'SL:{imp["suggestions"].get("optimal_sl_mult","?")}x '
              f'RR:{imp["suggestions"].get("optimal_rr","?")}')

    # Save meta
    json.dump(all_improvements,
              open('ml_models/v31_optimization_results.json','w'),
              indent=2)
    print('\n✅ Saved to ml_models/v31_optimization_results.json')
    return all_improvements

if __name__=='__main__':
    run_failure_optimizer()
