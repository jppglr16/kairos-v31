import json,os,pickle
import numpy as np
from datetime import datetime,timedelta
import logging
log=logging.getLogger(__name__)

class WarmStartSystem:
    """
    Accelerates learning by:
    1. Pre-loading brain with mined data
    2. Setting RL epsilon based on history
    3. Auto-tuning thresholds
    4. Weekly retraining schedule
    """

    def __init__(self):
        self.config_file='warm_start_config.json'
        self.config=self.load()

    def load(self):
        if os.path.exists(self.config_file):
            return json.load(open(self.config_file))
        return {
            'initialized':False,
            'last_retrain':None,
            'performance_by_week':{},
            'threshold_history':[],
            'rl_epsilon_schedule':[],
        }

    def save(self):
        json.dump(self.config,open(self.config_file,'w'),indent=2)

    def initialize_brain_from_mining(self):
        """Pre-load brain with mined failure corrections"""
        try:
            from v30_adaptive_learner import brain

            # Load failure corrections
            if not os.path.exists('failure_corrections.json'):
                print('[WARM] No failure corrections yet')
                return

            corrections=json.load(open('failure_corrections.json'))
            suggestions=corrections.get('parameter_suggestions',{})

            if not suggestions:
                print('[WARM] No suggestions yet')
                return

            print('[WARM] Initializing brain from mining...')

            for instrument,sugg in suggestions.items():
                brain.init_instrument(instrument)
                inst=brain.brain['instruments'][instrument]

                # Apply mined SL
                inst['sl_multiplier']=sugg.get('sl_multiplier',1.5)

                # Set initial win rate estimate
                correction_rate=sugg.get('correction_rate',0)/100
                inst['win_rate']=0.35+correction_rate*0.3

                print(f'[WARM] {instrument}: SL={inst["sl_multiplier"]}x WR_est={inst["win_rate"]*100:.1f}%')

            brain.save()
            print('[WARM] Brain initialized from 3 year mining!')

        except Exception as e:
            log.error(f'[WARM] Brain init error: {e}')

    def set_rl_epsilon(self,instrument,trades_done):
        """Set RL epsilon based on mining knowledge"""
        try:
            # If we have mining data, start with lower epsilon
            if os.path.exists('failure_corrections.json'):
                corrections=json.load(open('failure_corrections.json'))
                if corrections.get('parameter_suggestions',{}).get(instrument):
                    # Start at 0.3 instead of 1.0
                    # Because we already know 34% of failure patterns
                    epsilon=max(0.1,0.3-(trades_done*0.01))
                    return epsilon

            # Default decay
            return max(0.1,1.0-(trades_done*0.02))

        except:return 0.5

    def auto_tune_thresholds(self):
        """Auto-tune KAIROS and confirmation thresholds"""
        try:
            if not os.path.exists('failure_corrections.json'):return {}

            corrections=json.load(open('failure_corrections.json'))
            suggestions=corrections.get('parameter_suggestions',{})
            tuned={}

            for instrument,sugg in suggestions.items():
                rate=sugg.get('correction_rate',0)

                # High correction rate = lower threshold
                # (Many failures fixable = signals are good)
                if rate>40:
                    kairos_threshold=12  # Lower = more trades
                elif rate>30:
                    kairos_threshold=15  # Normal
                else:
                    kairos_threshold=18  # Higher = stricter

                tuned[instrument]={
                    'min_kairos':kairos_threshold,
                    'sl_multiplier':sugg.get('sl_multiplier',1.5),
                    'best_entry':sugg.get('best_entry_type','FVG')
                }

            return tuned

        except:return {}

    def get_week_number(self):
        return datetime.now().isocalendar()[1]

    def should_retrain(self):
        """Check if it's time for weekly retraining"""
        try:
            if not self.config.get('last_retrain'):
                return True
            last=datetime.fromisoformat(self.config['last_retrain'])
            days_since=( datetime.now()-last).days
            return days_since>=7
        except:return True

    def run_weekly_retrain(self):
        """Run every Sunday - retrain with latest data"""
        try:
            from v30_notify import send
            send('🔄 <b>Weekly Retraining Started!</b>\nAnalyzing last week performance...')

            print('[WARM] Starting weekly retrain...')

            # 1. Run failure mining on latest data
            from v30_failure_miner import miner
            print('[WARM] Mining failures...')
            miner.run_full_mining()

            # 2. Retrain all models
            print('[WARM] Retraining models...')
            from v30_train_kairos import train_all
            train_all()

            # 3. Update brain parameters
            self.initialize_brain_from_mining()

            # 4. Auto-tune thresholds
            thresholds=self.auto_tune_thresholds()
            if thresholds:
                json.dump(thresholds,open('auto_thresholds.json','w'),indent=2)
                print(f'[WARM] Updated thresholds for {len(thresholds)} instruments')

            self.config['last_retrain']=str(datetime.now())
            self.save()

            # 5. Send summary
            self.send_weekly_report()
            print('[WARM] Weekly retrain complete!')

        except Exception as e:
            log.error(f'[WARM] Weekly retrain error: {e}')

    def send_weekly_report(self):
        try:
            from v30_notify import send
            from v30_adaptive_learner import brain

            total=brain.brain['total_trades']
            wins=brain.brain['total_wins']
            wr=wins/total*100 if total>0 else 0

            msg=f"""📊 <b>WEEKLY PERFORMANCE REPORT</b>
━━━━━━━━━━━━━━━
📅 Week: {self.get_week_number()}
📈 Total Trades: {total}
✅ Win Rate: {wr:.1f}%

<b>Per Instrument:</b>
"""
            for inst,data in brain.brain['instruments'].items():
                t=data['trades']
                w=data['wins']
                if t>0:
                    iwr=w/t*100
                    msg+=f'• {inst}: {t} trades WR:{iwr:.0f}%\n'

            msg+=f'\n🔄 Models retrained with latest data!\n'
            msg+=f'📈 Next week should be better!\n'
            send(msg)
        except:pass

warm_start=WarmStartSystem()
