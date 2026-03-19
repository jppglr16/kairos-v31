import numpy as np
import logging,os,pickle,json
from datetime import datetime
from collections import deque
log=logging.getLogger(__name__)

class OnlineLearningEngine:
    """
    Continuous Adaptation Engine:
    - Updates model after EVERY trade
    - No weekly retraining needed!
    - Market evolves → Model evolves!
    
    Methods:
    1. SGD (Stochastic Gradient Descent)
    2. Passive-Aggressive Learning
    3. Hoeffding Tree (streaming)
    4. Adaptive windowing (ADWIN)
    """

    def __init__(self,symbol,window_size=200):
        self.symbol=symbol
        self.window_size=window_size
        self.buffer=deque(maxlen=window_size)
        self.model=None
        self.update_count=0
        self.drift_detector=ADWINDriftDetector()
        self.performance_window=deque(maxlen=50)
        self._load_model()

    def _load_model(self):
        """Load existing model or create new"""
        try:
            fname=f'ml_models/{self.symbol}_v31_online.pkl'
            if os.path.exists(fname):
                self.model=pickle.load(open(fname,'rb'))
                log.info(f'[OL] {self.symbol} model loaded!')
            else:
                self._create_model()
        except:
            self._create_model()

    def _create_model(self):
        """Create incremental learning model"""
        try:
            from sklearn.linear_model import SGDClassifier,PassiveAggressiveClassifier
            from sklearn.preprocessing import StandardScaler
            from sklearn.pipeline import Pipeline

            # SGD with log loss = online logistic regression
            self.model=Pipeline([
                ('scaler',StandardScaler()),
                ('clf',SGDClassifier(
                    loss='log_loss',
                    learning_rate='adaptive',
                    eta0=0.01,
                    max_iter=1,
                    warm_start=True,
                    random_state=42
                ))
            ])
            log.info(f'[OL] {self.symbol} new model created!')
        except Exception as e:
            log.error(f'[OL] Create error: {e}')

    def partial_fit(self,features,outcome):
        """
        Update model with single trade
        This is the core online learning!
        """
        try:
            if features is None or len(features)<10:return

            X=np.array(features[:30]).reshape(1,-1)
            y=np.array([outcome])

            # Add to buffer
            self.buffer.append((features[:30],outcome))
            self.update_count+=1

            # Check for concept drift
            drift=self.drift_detector.update(outcome)
            if drift:
                log.warning(f'[OL] {self.symbol} CONCEPT DRIFT detected!')
                self._handle_drift()

            # Partial fit
            if not hasattr(self.model,'named_steps'):
                self._create_model()

            # Need at least 2 classes seen
            if len(set([b[1] for b in self.buffer]))<2:
                return

            # Update with recent window
            window_X=np.array([b[0] for b in self.buffer])
            window_y=np.array([b[1] for b in self.buffer])

            # Fit scaler on window
            self.model.named_steps['scaler'].fit(window_X)
            # Partial fit classifier
            self.model.named_steps['clf'].partial_fit(
                self.model.named_steps['scaler'].transform(X),
                y,classes=[0,1]
            )

            self.performance_window.append(outcome)

            # Save every 10 updates
            if self.update_count%10==0:
                self._save_model()
                self._log_performance()

        except Exception as e:
            log.error(f'[OL] Fit error: {e}')

    def _handle_drift(self):
        """Handle concept drift - reset or adapt"""
        try:
            log.warning(f'[OL] {self.symbol} adapting to drift...')
            # Keep recent data only
            recent=list(self.buffer)[-50:]
            self.buffer.clear()
            for item in recent:
                self.buffer.append(item)
            # Reset learning rate
            if hasattr(self.model,'named_steps'):
                self.model.named_steps['clf'].eta0=0.05  # Higher LR after drift
            # Notify
            try:
                from v30_notify import send
                send(f'🔄 {self.symbol}: Market regime changed!\nOnline model adapting...')
            except:pass
        except Exception as e:
            log.error(f'[OL] Drift handle error: {e}')

    def predict(self,features):
        """Get online model prediction"""
        try:
            if self.model is None:return 0.5
            if len(self.buffer)<20:return 0.5

            X=np.array(features[:30]).reshape(1,-1)

            if hasattr(self.model,'named_steps'):
                X_scaled=self.model.named_steps['scaler'].transform(X)
                prob=float(self.model.named_steps['clf'].predict_proba(X_scaled)[0][1])
            else:
                prob=float(self.model.predict_proba(X)[0][1])

            return prob
        except:return 0.5

    def _save_model(self):
        try:
            fname=f'ml_models/{self.symbol}_v31_online.pkl'
            pickle.dump(self.model,open(fname,'wb'))
        except:pass

    def _log_performance(self):
        try:
            recent=list(self.performance_window)
            if recent:
                wr=sum(recent)/len(recent)
                log.info(f'[OL] {self.symbol} online WR: {wr:.1%} ({self.update_count} updates)')
        except:pass


class ADWINDriftDetector:
    """
    ADWIN - Adaptive Windowing
    Detects when market regime changes!
    """
    def __init__(self,delta=0.002):
        self.delta=delta
        self.window=deque(maxlen=100)
        self.drift_count=0

    def update(self,outcome):
        """Returns True if drift detected"""
        try:
            self.window.append(outcome)
            if len(self.window)<30:return False

            # Split window and compare means
            w=list(self.window)
            n=len(w)
            mid=n//2

            mean1=sum(w[:mid])/mid
            mean2=sum(w[mid:])/max(len(w[mid:]),1)

            # ADWIN test
            diff=abs(mean1-mean2)
            epsilon=np.sqrt(
                (1/(2*mid)+1/(2*(n-mid)))*np.log(4*n/self.delta)
            )

            if diff>epsilon:
                self.drift_count+=1
                log.warning(f'[ADWIN] Drift! mean1={mean1:.2f} mean2={mean2:.2f}')
                self.window.clear()
                return True
            return False
        except:return False


class AdaptiveEnsemble:
    """
    Combines online model with existing models
    Weights adapt based on recent performance
    """
    def __init__(self,symbol):
        self.symbol=symbol
        self.online_engine=OnlineLearningEngine(symbol)
        self.model_performance={}
        self._load_performance()

    def _load_performance(self):
        try:
            fname=f'ml_models/{self.symbol}_adaptive_perf.json'
            if os.path.exists(fname):
                self.model_performance=json.load(open(fname))
        except:pass

    def update(self,features,outcome,ml_prob,online_prob):
        """Update online model and track performance"""
        try:
            # Update online model
            self.online_engine.partial_fit(features,outcome)

            # Track which model was right
            for name,prob in [('ml',ml_prob),('online',online_prob)]:
                correct=1 if (prob>=0.5)==(outcome==1) else 0
                if name not in self.model_performance:
                    self.model_performance[name]=deque(maxlen=50)
                self.model_performance[name].append(correct)

            # Save
            fname=f'ml_models/{self.symbol}_adaptive_perf.json'
            save_data={k:list(v) for k,v in self.model_performance.items()}
            json.dump(save_data,open(fname,'w'))
        except Exception as e:
            log.error(f'[ADAPTIVE] Update error: {e}')

    def get_adaptive_prob(self,features,ml_prob):
        """
        Get probability combining online + offline models
        Online model gets more weight when performing better!
        """
        try:
            online_prob=self.online_engine.predict(features)

            # Calculate dynamic weights
            ml_wr=0.5
            online_wr=0.5

            if 'ml' in self.model_performance:
                ml_data=list(self.model_performance['ml'])
                if ml_data:ml_wr=sum(ml_data)/len(ml_data)

            if 'online' in self.model_performance:
                online_data=list(self.model_performance['online'])
                if online_data:online_wr=sum(online_data)/len(online_data)

            total=ml_wr+online_wr
            ml_w=ml_wr/total if total>0 else 0.5
            online_w=online_wr/total if total>0 else 0.5

            # Combine
            adaptive_prob=ml_prob*ml_w+online_prob*online_w

            log.info(f'[ADAPTIVE] {self.symbol}: ml={ml_prob:.2f}({ml_w:.2f}) '
                    f'online={online_prob:.2f}({online_w:.2f}) '
                    f'final={adaptive_prob:.2f}')

            return adaptive_prob,online_prob
        except Exception as e:
            log.error(f'[ADAPTIVE] Prob error: {e}')
            return ml_prob,0.5


# Global instances
_adaptive_engines={}

def get_adaptive_engine(symbol):
    if symbol not in _adaptive_engines:
        _adaptive_engines[symbol]=AdaptiveEnsemble(symbol)
    return _adaptive_engines[symbol]

def get_online_prob(symbol,features,ml_prob):
    """Main function"""
    engine=get_adaptive_engine(symbol)
    return engine.get_adaptive_prob(features,ml_prob)

def update_online_model(symbol,features,outcome,ml_prob,online_prob):
    """Update after trade outcome"""
    engine=get_adaptive_engine(symbol)
    engine.update(features,outcome,ml_prob,online_prob)
    log.info(f'[OL] {symbol} model updated! outcome={outcome}')
