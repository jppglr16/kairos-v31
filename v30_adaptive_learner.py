import json,os,pickle
import numpy as np
import pandas as pd
from datetime import datetime,timedelta
from collections import defaultdict
import logging
log=logging.getLogger(__name__)

class AdaptiveLearner:
    def __init__(self):
        self.file='adaptive_brain.json'
        self.brain=self.load()

    def load(self):
        if os.path.exists(self.file):
            return json.load(open(self.file))
        return {
            # Per instrument learning
            'instruments':{},
            # Global patterns
            'sl_patterns':{},
            'win_patterns':{},
            # Parameter adjustments
            'adjustments':{},
            # Market condition performance
            'market_performance':{},
            # Hour performance
            'hour_performance':{},
            # Stats
            'total_trades':0,
            'total_wins':0,
            'total_losses':0,
            'last_updated':str(datetime.now())
        }

    def save(self):
        self.brain['last_updated']=str(datetime.now())
        json.dump(self.brain,open(self.file,'w'),indent=2)

    def init_instrument(self,instrument):
        if instrument not in self.brain['instruments']:
            self.brain['instruments'][instrument]={
                'trades':0,'wins':0,'losses':0,
                'win_rate':0,
                # Dynamic parameters
                'sl_multiplier':1.5,
                'min_kairos':15,
                'min_confirmation':4,
                'best_hours':[9,10,13,14],
                'avoid_hours':[],
                'best_market':'TRENDING',
                # Pattern memory
                'sl_hit_count':0,
                'consecutive_losses':0,
                'recovery_mode':False,
                # SL adjustment history
                'sl_adjustments':[],
                'entry_adjustments':[],
            }

    def record_win(self,instrument,signal,entry,exit_price,pnl,df5,df15):
        self.init_instrument(instrument)
        inst=self.brain['instruments'][instrument]
        inst['trades']+=1
        inst['wins']+=1
        inst['win_rate']=inst['wins']/inst['trades']
        inst['consecutive_losses']=0
        inst['recovery_mode']=False

        # Extract winning pattern
        pattern=self.extract_pattern(signal,df5,df15,'WIN')
        if pattern:
            key=pattern['key']
            if key not in self.brain['win_patterns']:
                self.brain['win_patterns'][key]={'count':0,'pnl':0}
            self.brain['win_patterns'][key]['count']+=1
            self.brain['win_patterns'][key]['pnl']+=pnl

        # Track hour performance
        hour=str(datetime.now().hour)
        if hour not in self.brain['hour_performance']:
            self.brain['hour_performance'][hour]={'wins':0,'losses':0}
        self.brain['hour_performance'][hour]['wins']+=1

        # Track market condition
        market=signal.get('market_condition','UNKNOWN')
        if market not in self.brain['market_performance']:
            self.brain['market_performance'][market]={'wins':0,'losses':0}
        self.brain['market_performance'][market]['wins']+=1

        self.brain['total_wins']+=1
        self.brain['total_trades']+=1
        log.info(f'[BRAIN] {instrument} WIN recorded WR:{inst["win_rate"]*100:.1f}%')
        self.save()
        self.auto_adjust(instrument,'WIN',signal,pnl)

    def record_loss(self,instrument,signal,entry,sl_price,exit_price,pnl,df5,df15):
        self.init_instrument(instrument)
        inst=self.brain['instruments'][instrument]
        inst['trades']+=1
        inst['losses']+=1
        inst['win_rate']=inst['wins']/inst['trades']
        inst['sl_hit_count']+=1
        inst['consecutive_losses']+=1

        # Check if SL was too tight
        if df5 is not None and len(df5)>14:
            atr=(df5['high']-df5['low']).tail(14).mean()
            sl_pts=abs(entry-sl_price)
            sl_atr_ratio=sl_pts/atr if atr>0 else 1.5

            # If SL was too tight (< 1.2 ATR)
            if sl_atr_ratio<1.2:
                new_mult=min(2.5,inst['sl_multiplier']+0.1)
                inst['sl_multiplier']=round(new_mult,2)
                inst['sl_adjustments'].append({
                    'time':str(datetime.now()),
                    'old_mult':inst['sl_multiplier']-0.1,
                    'new_mult':inst['sl_multiplier'],
                    'reason':'SL_TOO_TIGHT',
                    'sl_atr_ratio':sl_atr_ratio
                })
                log.info(f'[BRAIN] {instrument} SL too tight! Widening to {inst["sl_multiplier"]}x ATR')

        # Extract losing pattern
        pattern=self.extract_pattern(signal,df5,df15,'LOSS')
        if pattern:
            key=pattern['key']
            if key not in self.brain['sl_patterns']:
                self.brain['sl_patterns'][key]={'count':0,'pnl':0}
            self.brain['sl_patterns'][key]['count']+=1
            self.brain['sl_patterns'][key]['pnl']+=pnl

        # Track hour performance
        hour=str(datetime.now().hour)
        if hour not in self.brain['hour_performance']:
            self.brain['hour_performance'][hour]={'wins':0,'losses':0}
        self.brain['hour_performance'][hour]['losses']+=1

        # Track market
        market=signal.get('market_condition','UNKNOWN')
        if market not in self.brain['market_performance']:
            self.brain['market_performance'][market]={'wins':0,'losses':0}
        self.brain['market_performance'][market]['losses']+=1

        # Recovery mode after 3 consecutive losses
        if inst['consecutive_losses']>=3:
            inst['recovery_mode']=True
            inst['min_kairos']=min(25,inst['min_kairos']+2)
            log.info(f'[BRAIN] {instrument} RECOVERY MODE! Raising KAIROS to {inst["min_kairos"]}')

        self.brain['total_losses']+=1
        self.brain['total_trades']+=1
        self.save()
        self.auto_adjust(instrument,'LOSS',signal,pnl)

    def extract_pattern(self,signal,df5,df15,outcome):
        try:
            action=signal.get('action','')
            market=signal.get('market_condition','')
            kairos=signal.get('kairos_score',0)
            hour=datetime.now().hour
            rsi=signal.get('rsi',50)

            # Create pattern key
            rsi_zone='LOW' if rsi<40 else 'HIGH' if rsi>60 else 'MID'
            kairos_grade='HIGH' if kairos>=20 else 'MED' if kairos>=15 else 'LOW'
            hour_zone='MORNING' if hour<12 else 'AFTERNOON'

            key=f'{action}_{market}_{rsi_zone}_{kairos_grade}_{hour_zone}'
            return {'key':key,'outcome':outcome}
        except:return None

    def auto_adjust(self,instrument,outcome,signal,pnl):
        """Automatically adjust parameters based on performance"""
        try:
            inst=self.brain['instruments'][instrument]
            adjustments={}

            # Win rate based adjustments
            wr=inst['win_rate']
            trades=inst['trades']

            if trades>=10:
                # Good win rate → be more aggressive
                if wr>0.65:
                    new_kairos=max(10,inst['min_kairos']-1)
                    if new_kairos!=inst['min_kairos']:
                        adjustments['min_kairos']=new_kairos
                        inst['min_kairos']=new_kairos
                        log.info(f'[BRAIN] {instrument} WR good! Lowering KAIROS to {new_kairos}')

                # Poor win rate → be more selective
                elif wr<0.40:
                    new_kairos=min(25,inst['min_kairos']+1)
                    if new_kairos!=inst['min_kairos']:
                        adjustments['min_kairos']=new_kairos
                        inst['min_kairos']=new_kairos
                        log.info(f'[BRAIN] {instrument} WR poor! Raising KAIROS to {new_kairos}')

            # Update best hours
            if trades>=20:
                hour_stats=self.brain['hour_performance']
                best_hours=[]
                avoid_hours=[]
                for h,stats in hour_stats.items():
                    total=stats['wins']+stats['losses']
                    if total>=3:
                        wr_h=stats['wins']/total
                        if wr_h>=0.6:best_hours.append(int(h))
                        elif wr_h<=0.3:avoid_hours.append(int(h))
                if best_hours:inst['best_hours']=best_hours
                if avoid_hours:inst['avoid_hours']=avoid_hours

            if adjustments:
                if instrument not in self.brain['adjustments']:
                    self.brain['adjustments'][instrument]=[]
                self.brain['adjustments'][instrument].append({
                    'time':str(datetime.now()),
                    'adjustments':adjustments,
                    'trigger':outcome,
                    'win_rate':wr
                })
            self.save()
        except Exception as e:
            log.error(f'[BRAIN] Auto adjust error: {e}')

    def get_parameters(self,instrument):
        """Get current optimized parameters for instrument"""
        self.init_instrument(instrument)
        inst=self.brain['instruments'][instrument]
        return {
            'sl_multiplier':inst.get('sl_multiplier',1.5),
            'min_kairos':inst.get('min_kairos',15),
            'min_confirmation':inst.get('min_confirmation',4),
            'best_hours':inst.get('best_hours',[9,10,13,14]),
            'avoid_hours':inst.get('avoid_hours',[]),
            'recovery_mode':inst.get('recovery_mode',False),
            'win_rate':inst.get('win_rate',0),
            'trades':inst.get('trades',0)
        }

    def should_trade(self,instrument,signal,current_hour):
        """Check if we should trade based on learned patterns"""
        params=self.get_parameters(instrument)

        # Avoid bad hours
        if current_hour in params['avoid_hours']:
            log.info(f'[BRAIN] {instrument} Avoiding hour {current_hour}')
            return False,f'BAD_HOUR_{current_hour}'

        # Recovery mode - stricter
        if params['recovery_mode']:
            kairos=signal.get('kairos_score',0)
            if kairos<params['min_kairos']:
                return False,f'RECOVERY_MODE_LOW_KAIROS_{kairos}'

        # Check if this is a known losing pattern
        pattern=self.extract_pattern(signal,None,None,'CHECK')
        if pattern:
            key=pattern['key']
            if key in self.brain['sl_patterns']:
                sl_count=self.brain['sl_patterns'][key]['count']
                win_count=self.brain['win_patterns'].get(key,{}).get('count',0)
                if sl_count>win_count*2:
                    log.info(f'[BRAIN] {instrument} Known losing pattern: {key}')
                    return False,f'LOSING_PATTERN_{key}'

        return True,'OK'

    def retrain_from_experience(self,instrument):
        """Retrain ML model using accumulated trade experience"""
        try:
            winners_file=f'ml_models/{instrument}_winners.json'
            if not os.path.exists(winners_file):return

            winners=json.load(open(winners_file))
            if len(winners)<20:
                log.info(f'[BRAIN] {instrument}: Need 20+ wins to retrain (have {len(winners)})')
                return

            log.info(f'[BRAIN] Retraining {instrument} from {len(winners)} live wins...')

            # Load existing model
            model_file=f'ml_models/{instrument}_model.pkl'
            if not os.path.exists(model_file):return
            data=pickle.load(open(model_file,'rb'))

            # Get live winning features
            live_features=[w['features'] for w in winners if 'features' in w]
            if not live_features:return

            # These are all wins - label 1
            live_labels=[1]*len(live_features)

            log.info(f'[BRAIN] {instrument}: Adding {len(live_features)} live wins to training')

            # Update model with new wins
            from sklearn.utils import resample
            X_new=np.array(live_features)
            y_new=np.array(live_labels)

            # Get existing model features
            model=data['model']
            scaler=data['scaler']

            # Transform new data
            n_features=model.n_features_in_
            X_padded=[]
            for f in live_features:
                if len(f)>=n_features:
                    X_padded.append(f[:n_features])
                else:
                    X_padded.append(f+[0]*(n_features-len(f)))

            X_new_sc=scaler.transform(X_padded)

            # Partial fit (incremental learning)
            if hasattr(model,'partial_fit'):
                model.partial_fit(X_new_sc,y_new,classes=[0,1])
                data['model']=model
                pickle.dump(data,open(model_file,'wb'))
                log.info(f'[BRAIN] {instrument}: Model updated with live wins!')

        except Exception as e:
            log.error(f'[BRAIN] Retrain error: {e}')

    def get_optimized_sl(self,instrument,atr):
        """Get optimized SL based on past performance"""
        params=self.get_parameters(instrument)
        mult=params['sl_multiplier']
        return atr*mult

    def print_brain_summary(self):
        """Print complete brain summary"""
        print('\n'+'='*50)
        print('  KAIROS BRAIN SUMMARY')
        print('='*50)
        total=self.brain['total_trades']
        wins=self.brain['total_wins']
        print(f'Total Trades: {total}')
        print(f'Win Rate: {wins/total*100:.1f}%' if total>0 else 'No trades yet')

        print('\nPer Instrument:')
        for inst,data in self.brain['instruments'].items():
            t=data['trades']
            w=data['wins']
            wr=w/t*100 if t>0 else 0
            mode='🔴RECOVERY' if data['recovery_mode'] else '🟢NORMAL'
            print(f'  {inst}: {t} trades WR:{wr:.1f}% SL:{data["sl_multiplier"]}x KAIROS:{data["min_kairos"]} {mode}')

        print('\nBest Hours:')
        hour_stats=self.brain['hour_performance']
        for h in sorted(hour_stats.keys()):
            stats=hour_stats[h]
            t=stats['wins']+stats['losses']
            if t>0:
                wr=stats['wins']/t*100
                print(f'  {h}:00 → WR:{wr:.0f}% ({t} trades)')

        print('\nKnown Losing Patterns:')
        for k,v in list(self.brain['sl_patterns'].items())[:5]:
            print(f'  {k}: {v["count"]} losses')
        print('='*50)

# Global instance
brain=AdaptiveLearner()
