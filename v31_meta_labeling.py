import logging,os,pickle
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.calibration import CalibratedClassifierCV

log=logging.getLogger(__name__)

class MetaLabelingEngine:
    """
    Two-model approach:
    Model 1 (Primary): Predicts direction (BUY/SELL)
    Model 2 (Meta):    Predicts if we should TAKE this signal
    
    Meta model features:
    - Primary model confidence
    - Signal score
    - Regime
    - Time of day
    - Recent win/loss streak
    - ATR level
    - Volume confirmation
    """
    
    def __init__(self,symbol):
        self.symbol=symbol
        self.primary_model=None
        self.meta_model=None
        self.trade_history=[]  # Recent trades
        
    def get_streak_features(self):
        """Get recent performance features"""
        if len(self.trade_history)<3:
            return 0,0,0.5
        recent=self.trade_history[-10:]
        wins=sum(1 for t in recent if t==1)
        losses=len(recent)-wins
        streak=0
        for t in reversed(recent):
            if t==recent[-1]:streak+=1
            else:break
        win_rate=wins/len(recent)
        return wins-losses,streak,win_rate
    
    def extract_meta_features(self,signal,primary_prob,features):
        """Extract meta features for Model 2"""
        try:
            score=signal.get('score',0)/52.0
            regime=signal.get('regime','RANGING')
            atr=signal.get('atr',50)
            price=signal.get('price',100)
            gamma=signal.get('gamma_boost',0)/10.0
            rr=min(signal.get('rr_ratio',2),10)/10.0
            
            regime_enc={
                'TRENDING_UP':1.0,
                'TRENDING_UP_HV':0.9,
                'TRENDING_DOWN':-1.0,
                'TRENDING_DOWN_HV':-0.9,
                'RANGING':0.0,
                'VOLATILE':0.5
            }.get(regime,0.0)
            
            # Time features
            from datetime import datetime
            now=datetime.now()
            hour=now.hour/24.0
            day=now.weekday()/4.0
            
            # Streak features
            net_streak,streak_len,recent_wr=self.get_streak_features()
            
            meta_features=[
                primary_prob,           # Primary model confidence
                score,                  # Signal score normalized
                regime_enc,             # Market regime
                atr/price if price>0 else 0,  # ATR%
                gamma,                  # Gamma boost
                rr,                     # Risk reward
                hour,                   # Time of day
                day,                    # Day of week
                net_streak/10.0,        # Recent performance
                streak_len/10.0,        # Streak length
                recent_wr,              # Recent win rate
                1 if signal.get('liq_type','')!='NONE' else 0,  # Liq sweep
                1 if signal.get('imbalance_type','') else 0,     # FVG/OB
            ]
            return meta_features
        except Exception as e:
            log.error(f'[META] Feature error: {e}')
            return None
    
    def get_meta_probability(self,signal,primary_prob,features):
        """
        Model 2: Should we take this signal?
        Returns probability of success
        """
        try:
            fname=f'ml_models/{self.symbol}_v31_meta.pkl'
            if not os.path.exists(fname):
                # No meta model yet - use primary prob
                return primary_prob
            
            meta_features=self.extract_meta_features(signal,primary_prob,features)
            if not meta_features:return primary_prob
            
            if self.meta_model is None:
                self.meta_model=pickle.load(open(fname,'rb'))
            
            X=np.array(meta_features).reshape(1,-1)
            meta_prob=float(self.meta_model.predict_proba(X)[0][1])
            
            # Combined probability
            combined=(primary_prob*0.4)+(meta_prob*0.6)
            log.info(f'[META] {self.symbol}: primary={primary_prob:.2f} meta={meta_prob:.2f} combined={combined:.2f}')
            return combined
        except Exception as e:
            log.error(f'[META] Error: {e}')
            return primary_prob
    
    def train_meta_model(self,signals_with_meta):
        """Train Model 2 on signal outcomes"""
        try:
            X=[]
            y=[]
            for s in signals_with_meta:
                if s.get('meta_features') and s.get('outcome') is not None:
                    X.append(s['meta_features'])
                    y.append(s['outcome'])
            
            if len(X)<100:
                log.info(f'[META] {self.symbol}: Need more data ({len(X)}/100)')
                return False
            
            model=GradientBoostingClassifier(
                n_estimators=200,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.8
            )
            # Calibrate probabilities
            calibrated=CalibratedClassifierCV(model,cv=3)
            calibrated.fit(np.array(X),np.array(y))
            
            fname=f'ml_models/{self.symbol}_v31_meta.pkl'
            pickle.dump(calibrated,open(fname,'wb'))
            
            wins=sum(y)
            log.info(f'[META] {self.symbol} trained: {len(X)} samples WR:{wins/len(X)*100:.1f}%')
            return True
        except Exception as e:
            log.error(f'[META] Training error: {e}')
            return False
    
    def update_history(self,outcome):
        """Update trade history for streak calculation"""
        self.trade_history.append(outcome)
        if len(self.trade_history)>50:
            self.trade_history=self.trade_history[-50:]

# Global instances per symbol
_meta_engines={}

def get_meta_engine(symbol):
    if symbol not in _meta_engines:
        _meta_engines[symbol]=MetaLabelingEngine(symbol)
    return _meta_engines[symbol]

def get_meta_prob(symbol,signal,primary_prob,features):
    """Main function to get meta probability"""
    engine=get_meta_engine(symbol)
    return engine.get_meta_probability(signal,primary_prob,features)
