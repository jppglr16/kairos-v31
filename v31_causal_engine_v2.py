import json,os,logging
import numpy as np
import pandas as pd
from datetime import datetime

log=logging.getLogger(__name__)
LOG_FILE='trade_log.json'

# ============================================================
# STEP 1: TRADE ATTRIBUTION LOGGER
# ============================================================
def log_trade(trade_id,features,prediction,confidence,signal={}):
    entry={
        'trade_id':trade_id,
        'time':str(datetime.now()),
        'features':features,
        'prediction':prediction,
        'confidence':round(confidence,3),
        'instrument':signal.get('instrument',''),
        'regime':signal.get('regime',''),
        'score':signal.get('score',0),
        'atr':signal.get('atr',0),
        'sl_type':signal.get('sl_type',''),
        'rr':signal.get('rr_ratio',0),
        'result':None,
        'pnl':None,
        'r_multiple':None,
        'exit_reason':None
    }
    try:
        data=json.load(open(LOG_FILE)) if os.path.exists(LOG_FILE) else []
        data.append(entry)
        json.dump(data,open(LOG_FILE,'w'),indent=2)
        log.info(f'[CAUSAL] Trade logged: {trade_id}')
    except Exception as e:
        log.error(f'[CAUSAL] Log error: {e}')

# ============================================================
# STEP 2: OUTCOME TRACKER
# ============================================================
def update_trade(trade_id,result,pnl,exit_reason,entry_price=0,exit_price=0,sl_pts=0):
    try:
        data=json.load(open(LOG_FILE)) if os.path.exists(LOG_FILE) else []
        for trade in data:
            if trade['trade_id']==trade_id:
                trade['result']=result
                trade['pnl']=round(pnl,2)
                trade['exit_reason']=exit_reason
                # Calculate R-multiple
                if sl_pts>0 and entry_price>0:
                    price_move=abs(exit_price-entry_price)
                    trade['r_multiple']=round(price_move/sl_pts,2)
                else:
                    trade['r_multiple']=1.0 if result=='WIN' else -1.0
                trade['exit_time']=str(datetime.now())
                break
        json.dump(data,open(LOG_FILE,'w'),indent=2)
        log.info(f'[CAUSAL] Trade updated: {trade_id} = {result} PnL:{pnl}')
    except Exception as e:
        log.error(f'[CAUSAL] Update error: {e}')

# ============================================================
# STEP 3: FEATURE IMPACT ENGINE (Permutation Importance)
# ============================================================
def get_feature_impact(symbol=None):
    try:
        data=json.load(open(LOG_FILE)) if os.path.exists(LOG_FILE) else []
        if symbol:
            data=[d for d in data if d.get('instrument')==symbol]

        completed=[d for d in data if d.get('result') is not None]
        if len(completed)<20:
            return {}

        # Feature names
        FEATURE_NAMES=[
            'ret1','ret5','ret10','atr_norm',
            'rsi','rsi_centered','macd','macd_sign',
            'vol_ratio','vol_spike','trend5','trend15',
            'trend_aligned','bb_pos','stoch','swing_pos',
            'above_vwap','has_fvg','has_ob','liq_abs',
            'regime','is_trending','gamma_norm','gamma_bool',
            'rr','sl_atr_ratio','sl_tight','direction',
            'liq_enc','hour'
        ]

        X=[]
        y=[]
        for d in completed:
            if d.get('features') and len(d['features'])>=30:
                X.append(d['features'][:30])
                y.append(1 if d['result']=='WIN' else 0)

        if len(X)<20:return {}

        X=np.array(X)
        y=np.array(y)

        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.inspection import permutation_importance

        model=GradientBoostingClassifier(n_estimators=50,max_depth=3)
        model.fit(X,y)

        perm=permutation_importance(model,X,y,n_repeats=10,random_state=42)
        importance=dict(zip(FEATURE_NAMES[:len(X[0])],perm.importances_mean))
        sorted_imp=sorted(importance.items(),key=lambda x:x[1],reverse=True)

        log.info(f'[CAUSAL] Top impactful features:')
        for feat,imp in sorted_imp[:5]:
            log.info(f'  {feat}: {imp:.3f}')

        return dict(sorted_imp)
    except Exception as e:
        log.error(f'[CAUSAL] Feature impact error: {e}')
        return {}

# ============================================================
# STEP 4: FAILURE PATTERN DETECTOR (KMeans Clustering)
# ============================================================
def cluster_losses(symbol=None,n_clusters=3):
    try:
        data=json.load(open(LOG_FILE)) if os.path.exists(LOG_FILE) else []
        if symbol:
            data=[d for d in data if d.get('instrument')==symbol]

        losses=[d for d in data if d.get('result')=='LOSS' and d.get('features')]
        if len(losses)<n_clusters*5:
            return {}

        X=pd.DataFrame([f for f in [d['features'][:30] for d in losses]])
        X=X.fillna(0)

        from sklearn.cluster import KMeans
        from sklearn.preprocessing import StandardScaler

        scaler=StandardScaler()
        X_scaled=scaler.fit_transform(X)

        kmeans=KMeans(n_clusters=n_clusters,random_state=42,n_init=10)
        labels=kmeans.fit_predict(X_scaled)

        clusters={}
        for i,loss in enumerate(losses):
            cluster=int(labels[i])
            if cluster not in clusters:
                clusters[cluster]=[]
            clusters[cluster].append({
                'instrument':loss.get('instrument',''),
                'regime':loss.get('regime',''),
                'score':loss.get('score',0),
                'exit_reason':loss.get('exit_reason',''),
                'time':loss.get('time','')
            })

        # Analyze each cluster
        patterns={}
        for cluster,trades in clusters.items():
            regimes=[t['regime'] for t in trades]
            exits=[t['exit_reason'] for t in trades]
            scores=[t['score'] for t in trades]

            patterns[f'cluster_{cluster}']={
                'count':len(trades),
                'dominant_regime':max(set(regimes),key=regimes.count) if regimes else '',
                'dominant_exit':max(set(exits),key=exits.count) if exits else '',
                'avg_score':round(sum(scores)/len(scores),1) if scores else 0
            }

        log.info(f'[CAUSAL] Loss clusters found: {len(patterns)}')
        return patterns
    except Exception as e:
        log.error(f'[CAUSAL] Clustering error: {e}')
        return {}

# ============================================================
# STEP 5: WIN/LOSS ANALYSIS
# ============================================================
def analyze_failures(symbol=None):
    try:
        data=json.load(open(LOG_FILE)) if os.path.exists(LOG_FILE) else []
        if symbol:
            data=[d for d in data if d.get('instrument')==symbol]

        losses=[d for d in data if d.get('result')=='LOSS']
        if len(losses)<5:
            return {}

        patterns={}
        # Regime analysis
        regimes=[d.get('regime','') for d in losses]
        from collections import Counter
        regime_counts=Counter(regimes)
        patterns['regime_failures']=dict(regime_counts)

        # Score analysis
        scores=[d.get('score',0) for d in losses]
        patterns['avg_loss_score']=round(sum(scores)/len(scores),1)

        # Exit reason
        exits=[d.get('exit_reason','') for d in losses]
        exit_counts=Counter(exits)
        patterns['exit_reasons']=dict(exit_counts)

        # Time analysis
        hours=[]
        for d in losses:
            try:
                h=int(str(d.get('time','12:00'))[11:13])
                hours.append(h)
            except:pass
        if hours:
            patterns['worst_hours']=Counter(hours).most_common(3)

        log.info(f'[CAUSAL] Failure patterns: {patterns}')
        return patterns
    except Exception as e:
        log.error(f'[CAUSAL] Analysis error: {e}')
        return {}

def analyze_wins(symbol=None):
    try:
        data=json.load(open(LOG_FILE)) if os.path.exists(LOG_FILE) else []
        if symbol:
            data=[d for d in data if d.get('instrument')==symbol]

        wins=[d for d in data if d.get('result')=='WIN']
        if len(wins)<5:return {}

        patterns={}
        regimes=[d.get('regime','') for d in wins]
        from collections import Counter
        patterns['regime_wins']=dict(Counter(regimes))
        scores=[d.get('score',0) for d in wins]
        patterns['avg_win_score']=round(sum(scores)/len(scores),1)
        r_mults=[d.get('r_multiple',0) for d in wins if d.get('r_multiple')]
        if r_mults:
            patterns['avg_r_multiple']=round(sum(r_mults)/len(r_mults),2)
        return patterns
    except Exception as e:
        log.error(f'[CAUSAL] Win analysis error: {e}')
        return {}

# ============================================================
# STEP 6: AUTO INSIGHT GENERATOR
# ============================================================
def generate_insights(symbol=None):
    try:
        data=json.load(open(LOG_FILE)) if os.path.exists(LOG_FILE) else []
        if symbol:
            data=[d for d in data if d.get('instrument')==symbol]

        wins=[d for d in data if d.get('result')=='WIN' and d.get('features')]
        losses=[d for d in data if d.get('result')=='LOSS' and d.get('features')]

        if len(wins)<5 or len(losses)<5:
            return {}

        FEATURE_NAMES=['ret1','ret5','ret10','atr_norm','rsi','rsi_c','macd',
                       'macd_s','vol_ratio','vol_spike','t5','t15','t_align',
                       'bb','stoch','swing','vwap','fvg','ob','liq',
                       'regime','trending','gamma','gamma_b','rr','sl_r',
                       'sl_t','dir','liq_e','hour']

        insights={}
        for i,feat in enumerate(FEATURE_NAMES):
            try:
                win_vals=[d['features'][i] for d in wins if len(d['features'])>i]
                loss_vals=[d['features'][i] for d in losses if len(d['features'])>i]
                if not win_vals or not loss_vals:continue
                win_avg=sum(win_vals)/len(win_vals)
                loss_avg=sum(loss_vals)/len(loss_vals)
                if abs(win_avg-loss_avg)>0.15:
                    insights[feat]={
                        'win_avg':round(win_avg,3),
                        'loss_avg':round(loss_avg,3),
                        'diff':round(win_avg-loss_avg,3)
                    }
            except:pass

        # Sort by difference
        sorted_insights=dict(sorted(insights.items(),
                             key=lambda x:abs(x[1]['diff']),reverse=True))

        # Save insights
        fname=f'ml_models/{symbol}_insights.json' if symbol else 'ml_models/global_insights.json'
        json.dump(sorted_insights,open(fname,'w'),indent=2)

        log.info(f'[CAUSAL] Generated {len(sorted_insights)} insights!')
        return sorted_insights
    except Exception as e:
        log.error(f'[CAUSAL] Insight error: {e}')
        return {}

# ============================================================
# STEP 7: AUTO FEEDBACK LOOP
# ============================================================
def get_auto_adjustments(symbol):
    """
    Auto-adjust filters based on patterns
    Returns adjusted thresholds
    """
    try:
        insights=generate_insights(symbol)
        patterns=analyze_failures(symbol)
        clusters=cluster_losses(symbol)

        adjustments={
            'min_score':15,    # Default
            'min_ml_prob':0.35, # Default
            'avoid_regimes':[],
            'avoid_hours':[],
            'min_rr':2.0,
        }

        if not insights and not patterns:
            return adjustments

        # Adjust score threshold
        avg_loss_score=patterns.get('avg_loss_score',0)
        if avg_loss_score>15:
            adjustments['min_score']=max(15,round(avg_loss_score+2))
            log.info(f'[CAUSAL] Score threshold raised to {adjustments["min_score"]}')

        # Avoid losing regimes
        regime_failures=patterns.get('regime_failures',{})
        total_failures=sum(regime_failures.values())
        for regime,count in regime_failures.items():
            if total_failures>0 and count/total_failures>0.5:
                adjustments['avoid_regimes'].append(regime)
                log.info(f'[CAUSAL] Avoiding regime: {regime}')

        # Avoid bad hours
        worst_hours=patterns.get('worst_hours',[])
        for hour,count in worst_hours[:2]:
            if count>3:
                adjustments['avoid_hours'].append(hour)

        # Save adjustments
        fname=f'ml_models/{symbol}_adjustments.json'
        json.dump(adjustments,open(fname,'w'),indent=2)
        return adjustments

    except Exception as e:
        log.error(f'[CAUSAL] Adjustment error: {e}')
        return {}

def causal_filter_v2(symbol,signal):
    """
    Main filter using causal insights
    Returns (should_take, reason)
    """
    try:
        fname=f'ml_models/{symbol}_adjustments.json'
        if not os.path.exists(fname):
            return True,'NO_ADJUSTMENTS'

        adj=json.load(open(fname))
        regime=signal.get('regime','')
        score=signal.get('score',0)

        # Check regime
        if regime in adj.get('avoid_regimes',[]):
            return False,f'CAUSAL_BAD_REGIME_{regime}'

        # Check score
        min_score=adj.get('min_score',15)
        if score<min_score:
            return False,f'CAUSAL_LOW_SCORE_{score}<{min_score}'

        # Check hour
        from datetime import datetime
        hour=datetime.now().hour
        if hour in adj.get('avoid_hours',[]):
            return False,f'CAUSAL_BAD_HOUR_{hour}'

        return True,'CAUSAL_OK'
    except:
        return True,'ERROR'

# ============================================================
# DAILY REPORT
# ============================================================
# ============================================================
# CONFIDENCE AUTO-TUNING
# ============================================================
def get_optimal_confidence_threshold(symbol):
    """
    Auto-tune ML confidence threshold
    Based on historical performance
    """
    try:
        data=json.load(open(LOG_FILE)) if os.path.exists(LOG_FILE) else []
        if symbol:
            data=[d for d in data if d.get('instrument')==symbol]

        completed=[d for d in data if d.get('result') and d.get('confidence')]
        if len(completed)<30:
            return 0.35  # Default

        # Test different thresholds
        thresholds=[0.30,0.35,0.40,0.45,0.50,0.55,0.60]
        best_threshold=0.35
        best_wr=0

        for thresh in thresholds:
            filtered=[d for d in completed if d['confidence']>=thresh]
            if len(filtered)<10:continue
            wins=sum(1 for d in filtered if d['result']=='WIN')
            wr=wins/len(filtered)
            # Reward both WR and trade count
            score=wr*(len(filtered)/len(completed))
            if score>best_wr:
                best_wr=score
                best_threshold=thresh

        log.info(f'[CAUSAL] {symbol} optimal threshold: {best_threshold} (WR:{best_wr:.2f})')

        # Save threshold
        adj_file=f'ml_models/{symbol}_adjustments.json'
        adj=json.load(open(adj_file)) if os.path.exists(adj_file) else {}
        adj['min_ml_prob']=best_threshold
        json.dump(adj,open(adj_file,'w'),indent=2)

        return best_threshold
    except Exception as e:
        log.error(f'[CAUSAL] Confidence tuning error: {e}')
        return 0.35

# ============================================================
# RL INTEGRATION
# ============================================================
def get_rl_causal_reward(trade_result,signal,features):
    """
    Calculate RL reward based on causal factors
    Rewards good decisions, penalizes bad ones
    """
    try:
        base_reward=1.0 if trade_result=='WIN' else -1.0
        regime=signal.get('regime','')
        score=signal.get('score',0)
        confidence=signal.get('ml_prob',0.5)

        # Bonus for high score wins
        if trade_result=='WIN' and score>=22:
            base_reward*=1.5
        # Penalty for low confidence wins (lucky!)
        if trade_result=='WIN' and confidence<0.4:
            base_reward*=0.5
        # Penalty for ranging losses
        if trade_result=='LOSS' and regime=='RANGING':
            base_reward*=1.5  # Extra penalty
        # Bonus for avoiding bad setups
        if trade_result=='WIN' and regime in ['TRENDING_UP','TRENDING_UP_HV']:
            base_reward*=1.2

        return round(base_reward,2)
    except:
        return 1.0 if trade_result=='WIN' else -1.0

def update_rl_from_causal(symbol,trade_result,signal,features):
    """
    Feed causal insights back to RL agent
    """
    try:
        from v31_rl_engine import QLearningAgent
        import pickle
        fname=f'ml_models/{symbol}_v31_rl.pkl'
        if not os.path.exists(fname):return

        agent=pickle.load(open(fname,'rb'))
        reward=get_rl_causal_reward(trade_result,signal,features)

        # Update RL with causal reward
        if hasattr(agent,'update_from_outcome'):
            agent.update_from_outcome(features,reward)
            pickle.dump(agent,open(fname,'wb'))
            log.info(f'[CAUSAL→RL] {symbol} reward={reward}')
    except Exception as e:
        log.debug(f'[CAUSAL→RL] Error: {e}')

def daily_causal_report():
    """Send causal insights to Telegram"""
    try:
        data=json.load(open(LOG_FILE)) if os.path.exists(LOG_FILE) else []
        today=datetime.now().strftime('%Y-%m-%d')
        today_trades=[d for d in data if d.get('time','').startswith(today)]
        completed=[d for d in today_trades if d.get('result')]

        if not completed:return

        wins=[d for d in completed if d['result']=='WIN']
        losses=[d for d in completed if d['result']=='LOSS']
        total_pnl=sum(d.get('pnl',0) for d in completed)

        msg=f"""🧠 <b>Causal Analysis Report</b>
━━━━━━━━━━━━━━━
📅 {today}
📊 Trades: {len(completed)} | ✅ {len(wins)} | ❌ {len(losses)}
💰 PnL: Rs.{total_pnl:,.0f}"""

        if losses:
            patterns=analyze_failures()
            top_regime=max(patterns.get('regime_failures',{'':0}).items(),
                          key=lambda x:x[1],default=('N/A',0))
            msg+=f'\n\n🔴 Main failure: {top_regime[0]}'

        if wins:
            win_patterns=analyze_wins()
            msg+=f'\n🟢 Win regime: {list(win_patterns.get("regime_wins",{}).keys())[:1]}'
            msg+=f'\n📈 Avg R: {win_patterns.get("avg_r_multiple",0):.1f}'

        from v30_notify import send
        send(msg)
    except Exception as e:
        log.error(f'[CAUSAL] Report error: {e}')

