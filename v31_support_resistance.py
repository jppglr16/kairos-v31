"""
V31 Support & Resistance Engine
Identifies key price levels for better entries
"""
import logging,numpy as np
import pandas as pd
from datetime import datetime
log=logging.getLogger(__name__)

class SREngine:

    def calculate_pivots(self,df):
        """Daily pivot points from yesterday's OHLC"""
        try:
            if len(df)<2:return {}
            yesterday=df.iloc[-2]
            h=float(yesterday['high'])
            l=float(yesterday['low'])
            c=float(yesterday['close'])

            pp=(h+l+c)/3
            r1=2*pp-l
            r2=pp+(h-l)
            r3=h+2*(pp-l)
            s1=2*pp-h
            s2=pp-(h-l)
            s3=l-2*(h-pp)

            return {
                'PP':round(pp,2),
                'R1':round(r1,2),'R2':round(r2,2),'R3':round(r3,2),
                'S1':round(s1,2),'S2':round(s2,2),'S3':round(s3,2),
            }
        except:return {}

    def calculate_round_levels(self,price,step=None):
        """Find nearby round number levels"""
        try:
            if step is None:
                # Auto step based on price
                if price>50000:step=500
                elif price>20000:step=200
                elif price>10000:step=100
                elif price>1000:step=50
                elif price>100:step=10
                else:step=5

            lower=round(price/step)*step
            upper=lower+step

            return {
                'round_support':lower,
                'round_resistance':upper,
                'step':step
            }
        except:return {}

    def find_swing_levels(self,df,lookback=20):
        """Find recent swing highs and lows"""
        try:
            if len(df)<lookback:return {}
            recent=df.tail(lookback)

            # Swing highs = local maxima
            highs=[]
            for i in range(1,len(recent)-1):
                if (float(recent['high'].iloc[i]) > float(recent['high'].iloc[i-1]) and
                    float(recent['high'].iloc[i]) > float(recent['high'].iloc[i+1])):
                    highs.append(float(recent['high'].iloc[i]))

            # Swing lows = local minima
            lows=[]
            for i in range(1,len(recent)-1):
                if (float(recent['low'].iloc[i]) < float(recent['low'].iloc[i-1]) and
                    float(recent['low'].iloc[i]) < float(recent['low'].iloc[i+1])):
                    lows.append(float(recent['low'].iloc[i]))

            return {
                'swing_highs':sorted(highs,reverse=True)[:3],
                'swing_lows':sorted(lows)[:3],
            }
        except:return {}

    def find_prev_day_levels(self,df):
        """Previous day high/low/close"""
        try:
            # Fix 5: Use copy to prevent mutation
            df_temp=df.copy()
            df_temp['date']=pd.to_datetime(df_temp['time']).dt.date
            days=df_temp.groupby('date').agg(
                high=('high','max'),
                low=('low','min'),
                close=('close','last')
            ).reset_index()

            if len(days)<2:return {}
            prev=days.iloc[-2]

            return {
                'PDH':round(float(prev['high']),2),
                'PDL':round(float(prev['low']),2),
                'PDC':round(float(prev['close']),2),
            }
        except:return {}

    def get_all_levels(self,df,price):
        """Get all S/R levels"""
        levels={}
        levels.update(self.calculate_pivots(df))
        levels.update(self.calculate_round_levels(price))
        levels.update(self.find_swing_levels(df))
        levels.update(self.find_prev_day_levels(df))
        return levels

    def detect_retest(self,df,level,atr,lookback=None):
        """
        Detect if price recently broke level and is retesting it
        Pattern: Break → Pullback → Retest = HUGE signal!
        """
        try:
            # Fix 4: Adaptive lookback based on ATR
            if lookback is None:
                if atr>200:lookback=6    # High volatility = shorter
                elif atr>50:lookback=10  # Normal
                else:lookback=15         # Low vol = longer
            if len(df)<lookback+5:return False
            recent=df.tail(lookback)
            closes=[float(c) for c in recent['close']]

            # Check if price broke level in last lookback candles
            broke_above=any(c>level+(atr*0.2) for c in closes[:-3])
            broke_below=any(c<level-(atr*0.2) for c in closes[:-3])

            current=closes[-1]
            near_level=abs(current-level)<atr*0.5

            if broke_above and near_level and current>level:
                return 'RETEST_SUPPORT'  # Break up, now retesting as support
            if broke_below and near_level and current<level:
                return 'RETEST_RESISTANCE'  # Break down, retesting as resistance

            return False
        except:return False

    def check_signal_quality(self,signal,df,price):
        """
        Check if signal aligns with S/R levels
        Returns: (quality_score, nearest_level, comment)
        """
        try:
            levels=self.get_all_levels(df,price)
            action=signal.get('action','BUY')
            atr=signal.get('atr',price*0.01)
            score_boost=0
            comments=[]

            # Check BUY signals
            # Retest detection (with all fixes!)
            try:
                base_score=signal.get('score',20)
                vol_ratio=signal.get('volume_ratio',1.0)
                retest_found=False  # Fix 3: only 1 retest boost!

                for level_name in ['PDH','PDL','R1','S1','PP']:
                    if retest_found:break  # Fix 3: stop after first!
                    level_val=levels.get(level_name,0)
                    if not level_val:continue

                    retest=self.detect_retest(df,level_val,atr)

                    # Fix 2: Volume confirmation required!
                    if not retest or vol_ratio<1.2:continue

                    # Fix 1: Context-aware boost
                    if base_score>20:
                        retest_boost=3  # Strong signal = full boost
                    else:
                        retest_boost=2  # Weak signal = smaller boost

                    if retest=='RETEST_SUPPORT' and action=='BUY':
                        score_boost+=retest_boost
                        comments.append(f'RETEST {level_name}(+{retest_boost})')
                        retest_found=True
                    elif retest=='RETEST_RESISTANCE' and action in ('SELL','PE'):
                        score_boost+=retest_boost
                        comments.append(f'RETEST {level_name}(+{retest_boost})')
                        retest_found=True
            except:pass

            # Fix 1: Variable thresholds (strong levels = tighter range)
            LEVEL_THRESHOLDS={
                'PDH':atr*0.8,'PDL':atr*0.8,   # Strong = tight
                'R1':atr,'R2':atr,               # Normal
                'S1':atr,'S2':atr,
                'PP':atr,
                'round_resistance':atr*1.2,      # Weak = loose
                'round_support':atr*1.2,
            }

            # Fix 2: Weighted levels (stronger levels = more weight)
            SUPPORT_WEIGHTS={'PDL':3,'S1':2,'S2':2,'PP':2,'round_support':1}
            RESIST_WEIGHTS={'PDH':3,'R1':2,'R2':2,'PP':2,'round_resistance':1}
            SWING_WEIGHT=2

            if action=='BUY':
                # Near support = good BUY!
                for level_name,weight in SUPPORT_WEIGHTS.items():
                    level_val=levels.get(level_name,0)
                    thresh=LEVEL_THRESHOLDS.get(level_name,atr)
                    if level_val and abs(price-level_val)<thresh:
                        score_boost+=weight
                        comments.append(f'{level_name}={level_val:.0f}(+{weight})')

                # Near resistance = bad BUY (unless breakout!)
                for level_name,weight in RESIST_WEIGHTS.items():
                    level_val=levels.get(level_name,0)
                    thresh=LEVEL_THRESHOLDS.get(level_name,atr)
                    if level_val and abs(price-level_val)<thresh:
                        # Breakout detection with buffer!
                        vol_ratio=signal.get('volume_ratio',1.0)
                        vol_thresh=signal.get('vol_threshold',1.5)
                        # Fix 1: Real breakout = price > level + 20% ATR buffer
                        is_breakout=price>level_val+(atr*0.2)
                        has_volume=vol_ratio>vol_thresh
                        if is_breakout and has_volume:
                            # STRONG breakout with volume!
                            score_boost+=weight+2
                            comments.append(f'BREAKOUT {level_name}={level_val:.0f}(+{weight+2})')
                        elif is_breakout:
                            # Breakout without volume (weak)
                            score_boost+=weight
                            comments.append(f'weak_break {level_name}(+{weight})')
                        else:
                            score_boost-=weight
                            comments.append(f'resist {level_name}(-{weight})')

                # Swing lows
                for sl in levels.get('swing_lows',[]):
                    if abs(price-sl)<atr*1.5:
                        score_boost+=SWING_WEIGHT
                        comments.append(f'swing_low={sl:.0f}')

            else:
                # Near resistance = good SELL!
                for level_name,weight in RESIST_WEIGHTS.items():
                    level_val=levels.get(level_name,0)
                    thresh=LEVEL_THRESHOLDS.get(level_name,atr)
                    if level_val and abs(price-level_val)<thresh:
                        # Rejection detection!
                        if price<=level_val:
                            # Price REJECTED at resistance!
                            score_boost+=weight+1
                            comments.append(f'REJECTION {level_name}={level_val:.0f}(+{weight+1})')
                        else:
                            score_boost+=weight
                            comments.append(f'{level_name}={level_val:.0f}(+{weight})')

                # Near support = bad SELL!
                for level_name,weight in SUPPORT_WEIGHTS.items():
                    level_val=levels.get(level_name,0)
                    thresh=LEVEL_THRESHOLDS.get(level_name,atr)
                    if level_val and abs(price-level_val)<thresh:
                        score_boost-=weight
                        comments.append(f'support {level_name}(-{weight})')

                # Swing highs
                for sh in levels.get('swing_highs',[]):
                    if abs(price-sh)<atr*1.5:
                        score_boost+=SWING_WEIGHT
                        comments.append(f'swing_high={sh:.0f}')

            # Fix 1: Cap boost to prevent distortion
            score_boost=max(min(score_boost,5),-5)

            # Fix 3: Trend context filter
            trend=signal.get('regime','')
            if 'DOWN' in trend and action=='BUY':
                score_boost-=2
                comments.append('downtrend penalty')
            elif 'UP' in trend and action in ('SELL','PE'):
                score_boost-=2
                comments.append('uptrend penalty')

            # Re-cap after trend adjustment
            score_boost=max(min(score_boost,5),-5)

            comment=', '.join(comments) if comments else 'No S/R nearby'
            log.info(f'[SR] {signal.get("instrument","")} '
                    f'{action} price={price:.0f} '
                    f'boost={score_boost:+d} {comment}')
            return score_boost,levels,comment

        except Exception as e:
            log.debug(f'[SR] Error: {e}')
            return 0,{},'Error'

# Global instance
sr_engine=SREngine()
