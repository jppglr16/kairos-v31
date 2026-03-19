import numpy as np
import logging
log=logging.getLogger(__name__)

# ============================================================
# ENSEMBLE VOTING SYSTEM
# Combines: V31 ML + RL Agent + Transformer + Rules
# Need 3/4 votes to execute trade
# ============================================================

def get_ensemble_decision(symbol,df5,df15,action,
                           score,atr,ml_prob):
    """
    4-way ensemble voting:
    1. V31 ML model
    2. RL agent
    3. Transformer
    4. Rule-based V31

    Need >= 3 votes to trade!
    Returns: (should_trade, confidence, votes_detail)
    """
    votes={}
    confidences={}

    # ============================================================
    # VOTE 1: V31 ML Model
    # ============================================================
    try:
        ml_vote=ml_prob>=0.45
        votes['v31_ml']=ml_vote
        confidences['v31_ml']=ml_prob
    except:
        votes['v31_ml']=False
        confidences['v31_ml']=0.0

    # ============================================================
    # VOTE 2: RL Agent
    # ============================================================
    try:
        from v31_rl_engine import get_rl_signal
        rl_action,rl_conf=get_rl_signal(symbol,df5,
                                         float(df5['close'].iloc[-1]))
        # RL: 1=BUY, 2=SELL
        if action=='BUY':
            rl_vote=rl_action==1 and rl_conf>0.4
        else:
            rl_vote=rl_action==2 and rl_conf>0.4
        votes['rl_agent']=rl_vote
        confidences['rl_agent']=rl_conf
    except:
        votes['rl_agent']=False
        confidences['rl_agent']=0.0

    # ============================================================
    # VOTE 3: Transformer
    # ============================================================
    try:
        from v31_transformer import get_transformer_signal
        tf_dir,tf_conf=get_transformer_signal(symbol,df5)
        # Transformer: 1=UP, 0=DOWN, 2=FLAT
        if action=='BUY':
            tf_vote=tf_dir==1 and tf_conf>0.4
        else:
            tf_vote=tf_dir==0 and tf_conf>0.4
        votes['transformer']=tf_vote
        confidences['transformer']=tf_conf
    except:
        votes['transformer']=False
        confidences['transformer']=0.0

    # ============================================================
    # VOTE 4: Rule-based V31 (KAIROS score)
    # ============================================================
    try:
        rule_vote=score>=18
        rule_conf=min(1.0,score/43)
        votes['rule_based']=rule_vote
        confidences['rule_based']=rule_conf
    except:
        votes['rule_based']=False
        confidences['rule_based']=0.0

    # ============================================================
    # FINAL DECISION
    # ============================================================
    yes_votes=sum(1 for v in votes.values() if v)
    total_conf=np.mean(list(confidences.values()))

    # Need 3/4 votes minimum
    should_trade=yes_votes>=3

    # Extra: if all 4 agree = Grade S
    grade_s=yes_votes==4

    result={
        'should_trade':should_trade,
        'yes_votes':yes_votes,
        'total_votes':4,
        'confidence':round(total_conf,3),
        'grade_s':grade_s,
        'votes':votes,
        'confidences':confidences,
        'verdict':f'{yes_votes}/4 votes {"✅ TRADE" if should_trade else "❌ SKIP"}'
    }

    log.info(f'[ENSEMBLE] {symbol} {action}: {result["verdict"]} '
             f'(conf:{total_conf:.2f})')

    return should_trade,total_conf,result

def get_adaptive_rr(ensemble_result,base_rr=2.0):
    """
    Adjust RR based on ensemble confidence:
    All 4 agree → Higher target!
    3/4 agree → Standard target
    """
    yes_votes=ensemble_result.get('yes_votes',0)
    conf=ensemble_result.get('confidence',0.5)

    if yes_votes==4 and conf>0.7:
        return base_rr*1.5  # Boost target by 50%!
    elif yes_votes==4:
        return base_rr*1.2
    else:
        return base_rr

def train_all_models(symbol,df):
    """Train all models for one instrument"""
    print(f'\n[ENSEMBLE] Training all models for {symbol}...')

    # Train RL
    try:
        from v31_rl_engine import train_rl_agent
        train_rl_agent(symbol,df,episodes=30)
        print(f'[ENSEMBLE] RL trained for {symbol} ✅')
    except Exception as e:
        print(f'[ENSEMBLE] RL failed {symbol}: {e}')

    # Train Transformer
    try:
        from v31_transformer import train_transformer
        train_transformer(symbol,df)
        print(f'[ENSEMBLE] Transformer trained for {symbol} ✅')
    except Exception as e:
        print(f'[ENSEMBLE] Transformer failed {symbol}: {e}')

    print(f'[ENSEMBLE] {symbol} complete!')

def run_ensemble_training():
    """Train all ensemble models for all instruments"""
    import json,pandas as pd

    INSTRUMENTS={
        'NIFTY':'99926000','BANKNIFTY':'99926009',
        'SENSEX':'99919000','FINNIFTY':'99926037',
        'MIDCPNIFTY':'99926074','CRUDEOIL':'472790',
        'GOLDM':'477904','SILVERM':'457533','NATURALGAS':'475111',
        'LT':'11483','NTPC':'11630','MARUTI':'10999',
        'BHARTIARTL':'10604','SBIN':'3045',
        'TATAMOTORS':'3456','RELIANCE':'2885',
        'HINDUNILVR':'1394','TCS':'11536','TATASTEEL':'3499'
    }

    print('\n'+'='*60)
    print('  V31 ENSEMBLE TRAINING (RL + Transformer)')
    print('='*60)

    for symbol,token in INSTRUMENTS.items():
        candles=[]
        for year in [2022,2023,2024]:
            for fname in [
                f'historical_data/{symbol}_{year}_5min.json',
                f'historical_data/{token}_{year}_5min.json'
            ]:
                import os
                if os.path.exists(fname):
                    candles.extend(json.load(open(fname)))
                    break

        if not candles:
            print(f'[ENSEMBLE] {symbol}: No data')
            continue

        df=pd.DataFrame(candles)
        if len(df.columns)==6:
            df.columns=['time','open','high','low','close','volume']
        for col in ['open','high','low','close','volume']:
            df[col]=pd.to_numeric(df[col],errors='coerce')
        df=df.dropna().reset_index(drop=True)

        print(f'\n[ENSEMBLE] {symbol}: {len(df)} candles')
        train_all_models(symbol,df)

    print('\n✅ Ensemble training complete!')
    from v30_notify import send
    send('🤖 V31 Ensemble Training Complete!\nRL + Transformer ready!')

if __name__=='__main__':
    run_ensemble_training()
