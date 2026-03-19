import json,os,pickle
import numpy as np
import pandas as pd
from datetime import datetime
from collections import defaultdict
import logging
log=logging.getLogger(__name__)

class MetaLearner:
    """
    Master AI that:
    1. Learns from all failure patterns
    2. Dynamically adjusts ALL thresholds
    3. Finds optimal confirmation count per market regime
    4. Continuously improves entry quality
    """
    def __init__(self):
        self.file='meta_learner.json'
        self.state=self.load()

    def load(self):
        if os.path.exists(self.file):
            return json.load(open(self.file))
        return {
            # Dynamic thresholds per instrument
            'thresholds':{},
            # Signal importance weights
            'signal_weights':{},
            # Market regime performance
            'regime_performance':{},
            # Confirmation optimization
            'confirmation_optimizer':{},
            # Entry quality scores
            'entry_quality':{},
            # Auto-discovered rules
            'discovered_rules':[],
            'version':1,
            'last_updated':str(datetime.now())
        }

    def save(self):
        self.state['last_updated']=str(datetime.now())
        json.dump(self.state,open(self.file,'w'),indent=2)

    def init_instrument(self,instrument):
        if instrument not in self.state['thresholds']:
            self.state['thresholds'][instrument]={
                # Signal thresholds (dynamically adjusted)
                'min_kairos':15,
                'min_confirmation':4,
                'min_smc_strength':2,
                'min_momentum_strength':1,
                'min_ml_prob':0.40,
                'sl_multiplier':1.5,
                'target_multiplier':2.5,
                # Per market regime
                'trending_kairos':12,
                'sideways_kairos':20,
                'volatile_kairos':18,
                # Signal weights
                'fvg_weight':1.0,
                'ob_weight':1.0,
                'liq_weight':1.0,
                'wyckoff_weight':1.0,
                # Stats
                'total_analyzed':0,
                'improvements_applied':0
            }

    def analyze_failure_deeply(self,instrument,signal,df5,df15,
                                entry,sl_hit_price,atr):
        """Deep analysis of why trade failed"""
        try:
            self.init_instrument(instrument)
            t=self.state['thresholds'][instrument]
            analysis={
                'instrument':instrument,
                'timestamp':str(datetime.now()),
                'action':signal.get('action'),
                'reasons':[],
                'threshold_suggestions':{},
                'signal_quality_issues':[],
                'optimal_params':{}
            }

            # 1. Check signal strength
            kairos=signal.get('kairos_score',0)
            conf=signal.get('confirmation_count',0)
            smc_str=signal.get('smc_strength',0)
            mom_str=signal.get('momentum_strength',0)
            ml_prob=signal.get('ml_prob',0.5)
            wy=signal.get('wyckoff_phase','UNKNOWN')
            market=signal.get('market_condition','')
            action=signal.get('action','BUY')

            # Analysis 1: KAIROS too low?
            if kairos<18:
                analysis['reasons'].append(f'LOW_KAIROS_{kairos}')
                analysis['threshold_suggestions']['min_kairos']=max(t['min_kairos'],kairos+3)
                analysis['signal_quality_issues'].append({
                    'issue':'KAIROS score too low',
                    'current':kairos,
                    'recommended':18,
                    'action':'Increase min_kairos threshold'
                })

            # Analysis 2: Confirmation count
            if conf<5:
                analysis['reasons'].append(f'LOW_CONFIRMATION_{conf}')
                analysis['threshold_suggestions']['min_confirmation']=5
                analysis['signal_quality_issues'].append({
                    'issue':'Not enough confirmations',
                    'current':conf,
                    'recommended':5,
                    'action':'Require more signal alignment'
                })

            # Analysis 3: SL too tight?
            sl_pts=abs(entry-sl_hit_price)
            sl_atr_ratio=sl_pts/atr if atr>0 else 1.5
            if sl_atr_ratio<1.3:
                new_mult=round(min(2.5,t['sl_multiplier']+0.15),2)
                analysis['reasons'].append(f'SL_TOO_TIGHT_{sl_atr_ratio:.2f}x')
                analysis['threshold_suggestions']['sl_multiplier']=new_mult
                analysis['signal_quality_issues'].append({
                    'issue':'SL inside noise zone',
                    'current_ratio':sl_atr_ratio,
                    'recommended_ratio':1.5,
                    'action':f'Use SL = ATR × {new_mult}'
                })

            # Analysis 4: Wyckoff phase wrong?
            if action=='BUY' and wy in ['DIST','MARK','TRANS']:
                analysis['reasons'].append(f'WRONG_WYCKOFF_{wy}')
                t['wyckoff_weight']=min(2.0,t['wyckoff_weight']+0.1)
                analysis['signal_quality_issues'].append({
                    'issue':f'Wrong Wyckoff phase: {wy}',
                    'action':'Only BUY in ACCUM/MARKUP phases',
                    'wyckoff_weight_increased':True
                })

            # Analysis 5: ML probability too low?
            if ml_prob<0.45:
                analysis['reasons'].append(f'LOW_ML_PROB_{ml_prob:.2f}')
                new_min=min(0.55,t['min_ml_prob']+0.05)
                analysis['threshold_suggestions']['min_ml_prob']=new_min
                analysis['signal_quality_issues'].append({
                    'issue':'ML confidence too low',
                    'current':ml_prob,
                    'recommended':0.50,
                    'action':f'Increase min ML prob to {new_min}'
                })

            # Analysis 6: Market condition?
            if market=='SIDEWAYS':
                t['sideways_kairos']=min(25,t['sideways_kairos']+1)
                analysis['reasons'].append('SIDEWAYS_MARKET')
                analysis['signal_quality_issues'].append({
                    'issue':'Trading in sideways market',
                    'action':f'Require KAIROS>{t["sideways_kairos"]} in sideways'
                })

            # Find optimal parameters for this type of trade
            optimal=self.find_optimal_params(
                instrument,action,market,kairos,conf,atr
            )
            analysis['optimal_params']=optimal

            # Store analysis
            if instrument not in self.state['entry_quality']:
                self.state['entry_quality'][instrument]=[]
            self.state['entry_quality'][instrument].append(analysis)
            if len(self.state['entry_quality'][instrument])>200:
                self.state['entry_quality'][instrument]=\
                    self.state['entry_quality'][instrument][-200:]

            t['total_analyzed']+=1
            self.save()
            return analysis

        except Exception as e:
            log.error(f'[META] Analysis error: {e}')
            return {}

    def find_optimal_params(self,instrument,action,market,
                            kairos,conf,atr):
        """Find what parameters would have made this a winning trade"""
        try:
            corrections={}

            # Load failure corrections
            if os.path.exists('failure_corrections.json'):
                fc=json.load(open('failure_corrections.json'))
                sugg=fc.get('parameter_suggestions',{}).get(instrument,{})
                if sugg:
                    corrections['sl_multiplier']=sugg.get('sl_multiplier',1.5)
                    corrections['best_entry_type']=sugg.get('best_entry_type','FVG')

            # Market-specific optimization
            if market=='TRENDING':
                corrections['min_kairos']=12
                corrections['sl_multiplier']=corrections.get('sl_multiplier',1.5)
            elif market=='SIDEWAYS':
                corrections['min_kairos']=20
                corrections['sl_multiplier']=corrections.get('sl_multiplier',2.0)

            return corrections
        except:return {}

    def auto_adjust_thresholds(self,instrument,trade_results):
        """
        Automatically adjust thresholds based on results
        Uses sliding window of last 20 trades
        """
        try:
            self.init_instrument(instrument)
            t=self.state['thresholds'][instrument]

            if len(trade_results)<5:return

            wins=[r for r in trade_results if r['pnl']>0]
            losses=[r for r in trade_results if r['pnl']<=0]
            wr=len(wins)/len(trade_results)

            # Analyze losing trades
            loss_kairos=[r.get('kairos',0) for r in losses]
            loss_conf=[r.get('conf',0) for r in losses]
            win_kairos=[r.get('kairos',0) for r in wins]
            win_conf=[r.get('conf',0) for r in wins]

            adjustments={}

            # If wins have higher KAIROS → increase threshold
            if win_kairos and loss_kairos:
                avg_win_kairos=np.mean(win_kairos)
                avg_loss_kairos=np.mean(loss_kairos)
                if avg_win_kairos>avg_loss_kairos+3:
                    new_min=int(avg_loss_kairos+2)
                    if new_min>t['min_kairos']:
                        t['min_kairos']=new_min
                        adjustments['min_kairos']=new_min
                        log.info(f'[META] {instrument} KAIROS raised to {new_min}')

            # If wins have higher confirmations → increase
            if win_conf and loss_conf:
                avg_win_conf=np.mean(win_conf)
                avg_loss_conf=np.mean(loss_conf)
                if avg_win_conf>avg_loss_conf+1:
                    new_min=int(avg_loss_conf+1)
                    if new_min>t['min_confirmation']:
                        t['min_confirmation']=new_min
                        adjustments['min_confirmation']=new_min

            # Win rate too low → be more selective
            if wr<0.40 and len(trade_results)>=10:
                t['min_kairos']=min(22,t['min_kairos']+1)
                t['min_ml_prob']=min(0.55,t['min_ml_prob']+0.02)
                adjustments['action']='BE_MORE_SELECTIVE'
                log.info(f'[META] {instrument} Win rate low ({wr:.1f}%) - being more selective')

            # Win rate high → be less strict (more trades)
            elif wr>0.65 and len(trade_results)>=10:
                t['min_kairos']=max(10,t['min_kairos']-1)
                adjustments['action']='BE_MORE_AGGRESSIVE'
                log.info(f'[META] {instrument} Win rate high ({wr:.1f}%) - being more aggressive')

            if adjustments:
                t['improvements_applied']+=1
                log.info(f'[META] {instrument} Thresholds updated: {adjustments}')

            self.save()
            return adjustments

        except Exception as e:
            log.error(f'[META] Threshold adjust error: {e}')
            return {}

    def discover_rules(self):
        """Automatically discover new trading rules from data"""
        try:
            rules=[]

            if not os.path.exists('failure_corrections.json'):return rules
            corrections=json.load(open('failure_corrections.json'))
            patterns=corrections.get('patterns',[])

            if len(patterns)<50:return rules

            df=pd.DataFrame(patterns)

            # Rule 1: Best entry types
            if 'entry_type' in df.columns:
                entry_counts=df['entry_type'].value_counts()
                best_entry=entry_counts.index[0]
                rules.append({
                    'rule':f'BEST_ENTRY_TYPE',
                    'value':best_entry,
                    'confidence':entry_counts.iloc[0]/len(df)
                })

            # Rule 2: Best SL range
            if 'better_sl_mult' in df.columns:
                avg_sl=df['better_sl_mult'].mean()
                rules.append({
                    'rule':'OPTIMAL_SL_MULTIPLIER',
                    'value':round(avg_sl,2),
                    'confidence':0.8
                })

            # Rule 3: Best hours
            if 'hour' in df.columns:
                hour_counts=df['hour'].value_counts()
                worst_hours=hour_counts.tail(3).index.tolist()
                rules.append({
                    'rule':'AVOID_HOURS',
                    'value':worst_hours,
                    'confidence':0.7
                })

            # Rule 4: Best market conditions
            if 'market_condition' in df.columns:
                mkt_counts=df['market_condition'].value_counts()
                best_mkt=mkt_counts.index[0]
                rules.append({
                    'rule':'BEST_MARKET_CONDITION',
                    'value':best_mkt,
                    'confidence':mkt_counts.iloc[0]/len(df)
                })

            # Save discovered rules
            self.state['discovered_rules']=rules
            self.save()

            log.info(f'[META] Discovered {len(rules)} new rules!')
            for r in rules:
                log.info(f'[META] Rule: {r["rule"]} = {r["value"]} (conf:{r["confidence"]:.2f})')

            return rules

        except Exception as e:
            log.error(f'[META] Rule discovery error: {e}')
            return []

    def get_optimal_thresholds(self,instrument,market_condition):
        """Get current optimal thresholds for instrument"""
        self.init_instrument(instrument)
        t=self.state['thresholds'][instrument]

        # Market-specific thresholds
        if market_condition=='TRENDING':
            kairos=t.get('trending_kairos',t['min_kairos'])
        elif market_condition=='SIDEWAYS':
            kairos=t.get('sideways_kairos',t['min_kairos']+5)
        else:
            kairos=t['min_kairos']

        return {
            'min_kairos':kairos,
            'min_confirmation':t['min_confirmation'],
            'min_ml_prob':t['min_ml_prob'],
            'sl_multiplier':t['sl_multiplier'],
            'target_multiplier':t['target_multiplier'],
            'fvg_weight':t['fvg_weight'],
            'ob_weight':t['ob_weight'],
            'wyckoff_weight':t['wyckoff_weight']
        }

    def get_weekly_insights(self):
        """Generate weekly insights report"""
        try:
            insights=[]

            # Check all instruments
            for instrument,analyses in self.state['entry_quality'].items():
                if len(analyses)<5:continue

                recent=analyses[-20:]
                reasons=[]
                for a in recent:
                    reasons.extend(a.get('reasons',[]))

                from collections import Counter
                top_reasons=Counter(reasons).most_common(3)

                t=self.state['thresholds'].get(instrument,{})
                insights.append({
                    'instrument':instrument,
                    'top_failure_reasons':top_reasons,
                    'current_kairos':t.get('min_kairos',15),
                    'current_sl':t.get('sl_multiplier',1.5),
                    'improvements':t.get('improvements_applied',0)
                })

            return insights

        except:return []

    def send_insights_telegram(self):
        """Send insights to Telegram"""
        try:
            from v30_notify import send
            insights=self.get_weekly_insights()
            if not insights:return

            msg='🧠 <b>META LEARNER INSIGHTS</b>\n━━━━━━━━━━━━━━━\n'
            for ins in insights[:5]:
                msg+=f'\n📊 <b>{ins["instrument"]}</b>\n'
                msg+=f'KAIROS: {ins["current_kairos"]} | SL: {ins["current_sl"]}x\n'
                if ins['top_failure_reasons']:
                    msg+='Top failures:\n'
                    for reason,count in ins['top_failure_reasons']:
                        msg+=f'• {reason}: {count}x\n'
            send(msg)
        except:pass

meta=MetaLearner()
