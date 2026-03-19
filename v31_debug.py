import json,os
import pandas as pd
import numpy as np

def load_data(symbol):
    all_candles=[]
    TOKENS={'NIFTY':'99926000','BANKNIFTY':'99926009','SENSEX':'99919000'}
    token=TOKENS.get(symbol,'')
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
    df=pd.DataFrame(candles)
    if len(df.columns)==6:df.columns=['time','open','high','low','close','volume']
    for col in ['open','high','low','close','volume']:
        df[col]=pd.to_numeric(df[col],errors='coerce')
    return df.dropna().reset_index(drop=True)

def debug_filters(symbol='NIFTY',max_iter=500):
    from v31_scoring import calc_v31_score
    from v31_strategy import get_market_regime,get_trend_v31,detect_liquidity_sweep_v31,detect_fvg_v31,detect_ob_v31
    from v31_trap import get_full_trap_score
    from v30_final_backtest import get_wyckoff
    from v30_rr_filter import find_tight_sl,find_best_target

    candles=load_data(symbol)
    df=to_df(candles)
    print(f'\n{"="*60}')
    print(f'  DEBUG: {symbol} ({len(df)} candles)')
    print(f'{"="*60}')

    # Counters
    total=0
    blocks={
        'wrong_hour':0,
        'daily_limit':0,
        'low_volatility':0,
        'volatile_regime':0,
        'no_direction':0,
        'trend_against':0,
        'no_liq_sweep':0,
        'no_fvg_ob':0,
        'low_score':0,
        'low_delta':0,
        'bad_rr':0,
        'low_ml':0,
        'passed':0
    }

    # Detailed counts
    liq_types={'SWEEP_LOW':0,'SWEEP_HIGH':0,'EQUAL_LOWS':0,
               'EQUAL_HIGHS':0,'SESSION_LOW':0,'SESSION_HIGH':0,'NONE':0}
    fvg_count=0;ob_count=0;bos_count=0
    score_dist={f'{i}-{i+5}':0 for i in range(0,50,5)}
    regime_dist={'TRENDING_UP':0,'TRENDING_DOWN':0,'RANGING':0,'VOLATILE':0}
    daily_trades=0;daily_losses=0;last_date=None

    for i in range(100,min(len(df)-30,max_iter*3),3):
        df5=df.iloc[i-60:i].copy()
        df15=df.iloc[max(0,i-180):i:3].copy()
        df_daily=df.iloc[max(0,i-300):i:12].copy()
        if len(df5)<30:continue
        total+=1

        try:
            # Hour check
            hour=int(str(df5['time'].iloc[-1])[11:13])
            if hour not in [9,10,11,12,13,14]:
                blocks['wrong_hour']+=1;continue

            curr_date=str(df5['time'].iloc[-1])[:10]
            if curr_date!=last_date:
                daily_trades=0;daily_losses=0;last_date=curr_date
            if daily_trades>=4:blocks['daily_limit']+=1;continue

            c=df5['close'];h=df5['high'];l=df5['low']
            atr=float((h-l).tail(14).mean())
            cur=float(c.iloc[-1])
            if atr<=0:continue

            # ATR filter
            atr_pct=atr/cur*100
            avg_atr=float((h-l).rolling(20).mean().iloc[-1])
            if atr_pct<0.10 or atr<avg_atr*0.7:
                blocks['low_volatility']+=1;continue

            # Regime
            regime,_=get_market_regime(df5,df15,df_daily)
            regime_dist[regime]=regime_dist.get(regime,0)+1
            if regime=='VOLATILE':blocks['volatile_regime']+=1;continue

            # Direction
            if regime=='TRENDING_UP':action='BUY'
            elif regime=='TRENDING_DOWN':action='SELL'
            else:
                hb,_,_=detect_liquidity_sweep_v31(df5,'BUY',atr)
                hs,_,_=detect_liquidity_sweep_v31(df5,'SELL',atr)
                if hb:action='BUY'
                elif hs:action='SELL'
                else:blocks['no_direction']+=1;continue

            # Trend
            t5=get_trend_v31(df5);t15=get_trend_v31(df15)
            if action=='BUY' and t5==-1 and t15==-1:
                blocks['trend_against']+=1;continue
            if action=='SELL' and t5==1 and t15==1:
                blocks['trend_against']+=1;continue

            # Liquidity sweep
            swept,liq_type,liq_level=detect_liquidity_sweep_v31(df5,action,atr)
            liq_types[liq_type]=liq_types.get(liq_type,0)+1

            # FVG/OB
            has_fvg,_=detect_fvg_v31(df5,action,atr)
            has_ob,_=detect_ob_v31(df5,action,atr)
            if has_fvg:fvg_count+=1
            if has_ob:ob_count+=1

            # BOS
            try:
                rh=float(h.tail(20).max());rl=float(l.tail(20).min())
                ph=float(h.tail(40).iloc[:20].max());pl=float(l.tail(40).iloc[:20].min())
                if (action=='BUY' and rh>ph) or (action=='SELL' and rl<pl):
                    bos_count+=1
            except:pass

            # Score
            wy=get_wyckoff(df15)
            score,components,has_liq,has_fvg2=calc_v31_score(
                df5,df15,action,regime,wy,atr)
            trap_s,_=get_full_trap_score(symbol,df5,action,atr,cur)
            score+=trap_s

            for k in score_dist:
                lo,hi=map(int,k.split('-'))
                if lo<=score<hi:score_dist[k]+=1;break

            if score<15:blocks['low_score']+=1;continue

            # RR filter
            sl_type,raw_sl,_=find_tight_sl(df5,df15,action,atr)
            if raw_sl<atr*0.75:raw_sl=atr*0.75
            if raw_sl>atr*2.0:blocks['bad_rr']+=1;continue
            _,target,rr=find_best_target(
                df5,df15,action,cur,raw_sl,atr,True)
            if rr<1.5:blocks['bad_rr']+=1;continue

            blocks['passed']+=1
            daily_trades+=1

        except Exception as e:
            pass

    # Print results
    print(f'\nTotal iterations: {total}')
    print(f'Passed: {blocks["passed"]} ({blocks["passed"]/total*100:.1f}%)')

    print(f'\n--- FILTER BLOCKS ---')
    for k,v in sorted(blocks.items(),key=lambda x:-x[1]):
        if k!='passed' and v>0:
            pct=v/total*100
            bar='█'*int(pct/2)
            print(f'  {k:<20} {v:>5} ({pct:>5.1f}%) {bar}')

    print(f'\n--- REGIME DISTRIBUTION ---')
    for r,v in regime_dist.items():
        if v>0:print(f'  {r:<20} {v:>5} ({v/total*100:.1f}%)')

    print(f'\n--- LIQUIDITY SWEEP TYPES ---')
    for lt,v in sorted(liq_types.items(),key=lambda x:-x[1]):
        if v>0:print(f'  {lt:<20} {v:>5}')
    print(f'  FVG detected:         {fvg_count:>5}')
    print(f'  OB detected:          {ob_count:>5}')
    print(f'  BOS detected:         {bos_count:>5}')

    print(f'\n--- SCORE DISTRIBUTION ---')
    for k,v in score_dist.items():
        if v>0:
            bar='█'*v
            print(f'  Score {k:<8} {v:>5} {bar}')

    print(f'\n--- KEY INSIGHTS ---')
    top_block=max({k:v for k,v in blocks.items() if k!='passed'},key=blocks.get)
    print(f'  Biggest blocker: {top_block} ({blocks[top_block]} trades)')
    if blocks['no_liq_sweep']>blocks['passed']*2:
        print(f'  ⚠️ Liquidity sweep too strict - consider relaxing')
    if blocks['low_score']>blocks['passed']*2:
        print(f'  ⚠️ Score threshold too high - consider lowering')
    if blocks['bad_rr']>blocks['passed']:
        print(f'  ⚠️ RR filter too strict')
    print(f'\n  Liq sweep rate: {(total-blocks["no_liq_sweep"])/total*100:.1f}%')
    print(f'  FVG rate: {fvg_count/total*100:.1f}%')
    print(f'  BOS rate: {bos_count/total*100:.1f}%')

if __name__=='__main__':
    for sym in ['NIFTY','BANKNIFTY','SENSEX']:
        debug_filters(sym,500)
        print()
