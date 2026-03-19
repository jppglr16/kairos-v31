import json,os,pickle
import numpy as np
import pandas as pd
from datetime import datetime
import logging
log=logging.getLogger(__name__)

class PostTradeAnalyzer:
    def __init__(self):
        self.analysis_file='trade_analysis.json'
        self.lessons_file='ai_lessons.json'
        self.load()

    def load(self):
        self.analyses=json.load(open(self.analysis_file)) if os.path.exists(self.analysis_file) else []
        self.lessons=json.load(open(self.lessons_file)) if os.path.exists(self.lessons_file) else {
            'sl_patterns':[],
            'target_miss_patterns':[],
            'good_entry_patterns':[],
            'bad_entry_patterns':[],
            'improvements':[]
        }

    def save(self):
        json.dump(self.analyses,open(self.analysis_file,'w'),indent=2)
        json.dump(self.lessons,open(self.lessons_file,'w'),indent=2)

    def analyze_sl_hit(self,signal,df5,df15,entry_price,sl_price,exit_price):
        """Why did SL hit? What was wrong with entry?"""
        try:
            c=df5['close'];h=df5['high'];l=df5['low']
            atr=(h-l).tail(14).mean()
            reasons=[]
            improvements=[]

            # Check 1: Was entry against trend?
            from v30_train_kairos import get_trend
            trend15=get_trend(df15)
            action=signal.get('action')
            if action=='BUY' and trend15==-1:
                reasons.append('COUNTER_TREND_ENTRY')
                improvements.append('Wait for trend alignment before entry')

            # Check 2: Was entry at resistance?
            swing_high=h.tail(20).max()
            if action=='BUY' and entry_price>=swing_high*0.998:
                reasons.append('ENTRY_AT_RESISTANCE')
                improvements.append('Enter on pullback, not at swing high')

            # Check 3: Was SL too tight?
            sl_pts=entry_price-sl_price
            if sl_pts<atr*1.0:
                reasons.append('SL_TOO_TIGHT')
                improvements.append(f'Use wider SL: {atr*1.5:.0f} pts instead of {sl_pts:.0f}')

            # Check 4: Was there no FVG support?
            fvg_present=signal.get('confirmation_count',0)>4
            if not fvg_present:
                reasons.append('NO_FVG_SUPPORT')
                improvements.append('Only enter when FVG present as support')

            # Check 5: Was volume low?
            vol_surge=signal.get('momentum_strength',0)>=2
            if not vol_surge:
                reasons.append('LOW_VOLUME_ENTRY')
                improvements.append('Wait for volume surge confirmation')

            # Check 6: Was Wyckoff phase wrong?
            wy=signal.get('wyckoff_phase','UNKNOWN')
            if action=='BUY' and wy in ['DIST','MARK']:
                reasons.append(f'WRONG_WYCKOFF_PHASE_{wy}')
                improvements.append('Only buy in ACCUM or MARKUP phase')

            # Check 7: KAIROS score
            kairos=signal.get('kairos_score',0)
            if kairos<15:
                reasons.append(f'LOW_KAIROS_SCORE_{kairos}')
                improvements.append('Minimum KAIROS score 18 for safer entry')

            # Find better entry point
            better_entry=self.find_better_entry(df5,action,atr)

            analysis={
                'type':'SL_HIT',
                'instrument':signal.get('instrument'),
                'action':action,
                'entry':entry_price,
                'sl':sl_price,
                'exit':exit_price,
                'loss':exit_price-entry_price if action=='BUY' else entry_price-exit_price,
                'reasons':reasons,
                'improvements':improvements,
                'better_entry':better_entry,
                'kairos_score':kairos,
                'wyckoff':wy,
                'timestamp':str(datetime.now())
            }

            self.analyses.append(analysis)
            self.update_lessons('sl',reasons,improvements)
            self.save()

            # Log analysis
            log.info(f'[LEARN] SL Analysis for {signal.get("instrument")}:')
            for r in reasons:log.info(f'[LEARN]   Reason: {r}')
            for imp in improvements:log.info(f'[LEARN]   Fix: {imp}')

            # Send to Telegram
            self.notify_analysis(analysis)
            return analysis

        except Exception as e:
            log.error(f'[LEARN] SL analysis error: {e}')
            return None

    def analyze_target_miss(self,signal,df5,df15,entry_price,current_price):
        """Why did target miss? When should we have exited?"""
        try:
            c=df5['close'];h=df5['high'];l=df5['low']
            atr=(h-l).tail(14).mean()
            reasons=[]
            improvements=[]
            action=signal.get('action')

            profit_pts=current_price-entry_price if action=='BUY' else entry_price-current_price
            t1=signal.get('target1',atr*1.5)
            t2=signal.get('target2',atr*2.5)

            # Check if market condition changed
            from v30_momentum import detect_market_condition
            current_market=detect_market_condition(df15)
            entry_market=signal.get('market_condition','')

            if entry_market=='TRENDING' and current_market=='SIDEWAYS':
                reasons.append('MARKET_TURNED_SIDEWAYS')
                improvements.append('Exit when market changes from TRENDING to SIDEWAYS')

            # Was target too ambitious?
            if t2>atr*3:
                reasons.append('TARGET_TOO_FAR')
                improvements.append(f'Reduce T2 to {atr*2:.0f} pts (current: {t2:.0f})')

            # Should have exited at T1?
            if profit_pts>=t1 and profit_pts<t2:
                reasons.append('SHOULD_EXIT_AT_T1')
                improvements.append('Consider exiting 50% at T1 and trailing rest')

            analysis={
                'type':'TARGET_MISS',
                'instrument':signal.get('instrument'),
                'action':action,
                'entry':entry_price,
                'current':current_price,
                'profit_pts':profit_pts,
                't1':t1,'t2':t2,
                'reasons':reasons,
                'improvements':improvements,
                'timestamp':str(datetime.now())
            }

            self.analyses.append(analysis)
            self.update_lessons('target',reasons,improvements)
            self.save()
            return analysis

        except Exception as e:
            log.error(f'[LEARN] Target analysis error: {e}')
            return None

    def find_better_entry(self,df5,action,atr):
        """Find where the ideal entry should have been"""
        try:
            c=df5['close'];h=df5['high'];l=df5['low']
            current=c.iloc[-1]

            if action=='BUY':
                # Better entry = at FVG or Order Block
                for i in range(len(df5)-3,len(df5)-1):
                    p2=df5.iloc[i-2];cur=df5.iloc[i]
                    if cur['low']>p2['high']:
                        fvg_mid=(cur['low']+p2['high'])/2
                        if fvg_mid<current:
                            return round(fvg_mid,2)
                # Fallback: recent swing low
                return round(l.tail(10).min(),2)
            else:
                # Better entry at FVG or swing high
                for i in range(len(df5)-3,len(df5)-1):
                    p2=df5.iloc[i-2];cur=df5.iloc[i]
                    if cur['high']<p2['low']:
                        fvg_mid=(cur['high']+p2['low'])/2
                        if fvg_mid>current:
                            return round(fvg_mid,2)
                return round(h.tail(10).max(),2)
        except:return 0

    def update_lessons(self,lesson_type,reasons,improvements):
        """Update AI lessons from trade analysis"""
        try:
            if lesson_type=='sl':
                for r in reasons:
                    if r not in self.lessons['sl_patterns']:
                        self.lessons['sl_patterns'].append(r)
                for imp in improvements:
                    if imp not in self.lessons['improvements']:
                        self.lessons['improvements'].append(imp)
            elif lesson_type=='target':
                for r in reasons:
                    if r not in self.lessons['target_miss_patterns']:
                        self.lessons['target_miss_patterns'].append(r)
            self.save()
        except:pass

    def get_improved_parameters(self,instrument):
        """Suggest improved parameters based on analysis"""
        try:
            instrument_analyses=[a for a in self.analyses if a.get('instrument')==instrument]
            if len(instrument_analyses)<5:return None

            sl_hits=[a for a in instrument_analyses if a['type']=='SL_HIT']
            improvements={}

            # Analyze common SL reasons
            all_reasons=[]
            for a in sl_hits:
                all_reasons.extend(a.get('reasons',[]))

            from collections import Counter
            reason_counts=Counter(all_reasons)

            # Suggest improvements
            suggestions={}
            if reason_counts.get('SL_TOO_TIGHT',0)>3:
                suggestions['atr_sl_mult']=1.8  # Increase SL
            if reason_counts.get('COUNTER_TREND_ENTRY',0)>3:
                suggestions['require_trend_align']=True
            if reason_counts.get('LOW_KAIROS_SCORE',0)>3:
                suggestions['min_kairos']=18  # Raise threshold
            if reason_counts.get('LOW_VOLUME_ENTRY',0)>3:
                suggestions['require_vol_surge']=True

            return suggestions
        except:return None

    def notify_analysis(self,analysis):
        """Send analysis to Telegram"""
        try:
            from v30_notify import send
            trade_type=analysis['type']
            instrument=analysis.get('instrument','')
            reasons=analysis.get('reasons',[])
            improvements=analysis.get('improvements',[])

            if trade_type=='SL_HIT':
                msg=f"""🔍 <b>TRADE ANALYSIS - SL HIT</b>
━━━━━━━━━━━━━━━
📊 {instrument}
💵 Entry: {analysis.get('entry',0):.0f}
🛑 Exit: {analysis.get('exit',0):.0f}
❌ Loss: ₹{abs(analysis.get('loss',0))*25:.0f}

<b>Why SL Hit:</b>
"""
                for r in reasons[:3]:
                    msg+=f'• {r}\n'
                msg+='\n<b>Better Entry Would Be:</b>\n'
                msg+=f'• {analysis.get("better_entry",0):.0f}\n'
                msg+='\n<b>Improvements:</b>\n'
                for imp in improvements[:2]:
                    msg+=f'• {imp}\n'
                send(msg)
        except Exception as e:
            log.error(f'[LEARN] Notify error: {e}')

    def weekly_summary(self):
        """Weekly learning summary"""
        try:
            from v30_notify import send
            recent=[a for a in self.analyses[-50:]]
            sl_hits=[a for a in recent if a['type']=='SL_HIT']
            target_miss=[a for a in recent if a['type']=='TARGET_MISS']

            all_reasons=[]
            for a in sl_hits:
                all_reasons.extend(a.get('reasons',[]))

            from collections import Counter
            top_reasons=Counter(all_reasons).most_common(3)

            msg=f"""📚 <b>WEEKLY LEARNING SUMMARY</b>
━━━━━━━━━━━━━━━
📊 Trades Analyzed: {len(recent)}
🛑 SL Hits: {len(sl_hits)}
🎯 Target Miss: {len(target_miss)}

<b>Top SL Reasons:</b>
"""
            for reason,count in top_reasons:
                msg+=f'• {reason}: {count}x\n'

            msg+=f'\n<b>AI Improvements Applied:</b>\n'
            for imp in self.lessons['improvements'][-3:]:
                msg+=f'• {imp}\n'

            send(msg)
        except Exception as e:
            log.error(f'[LEARN] Weekly summary error: {e}')

# Global instance
analyzer=PostTradeAnalyzer()
