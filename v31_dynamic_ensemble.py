import numpy as np
import logging,os,pickle,json
from datetime import datetime
from collections import defaultdict
log=logging.getLogger(__name__)

class DynamicEnsemble:
    """
    Dynamic Weighted Ensemble:
    - Weights based on recent performance
    - Context-aware (regime specific)
    - Auto-adjusts every 20 trades
    
    Models:
    1. ML (GradientBoosting) - general
    2. RL Agent - sequential decisions
    3. Transformer - pattern recognition
    4. Meta-labeling - signal quality
    5. MMT - multi-modal
    6. CRL - risk-aware
    """

    def __init__(self,symbol):
        self.symbol=symbol

        # Default weights per model
        self.base_weights={
            'ml':0.25,
            'rl':0.15,
            'transformer':0.20,
            'meta':0.15,
            'mmt':0.15,
            'crl':0.10
        }

        # Context weights per regime
        self.regime_weights={
            'TRENDING_UP':{
                'ml':0.20,
                'rl':0.25,      # RL good at trends
                'transformer':0.25,  # Transformer sees patterns
                'meta':0.15,
                'mmt':0.10,
                'crl':0.05
            },
            'TRENDING_UP_HV':{
                'ml':0.15,
                'rl':0.30,      # RL excels in strong trends
                'transformer':0.25,
                'meta':0.15,
                'mmt':0.10,
                'crl':0.05
            },
            'TRENDING_DOWN':{
                'ml':0.20,
                'rl':0.25,
                'transformer':0.25,
                'meta':0.15,
                'mmt':0.10,
                'crl':0.05
            },
            'RANGING':{
                'ml':0.30,      # ML good at ranging
                'rl':0.10,      # RL bad at ranging
                'transformer':0.15,
                'meta':0.20,    # Meta important in ranging
                'mmt':0.15,
                'crl':0.10
            },
            'VOLATILE':{
                'ml':0.15,
                'rl':0.10,
                'transformer':0.20,
                'meta':0.20,
                'mmt':0.15,
                'crl':0.20     # CRL most important in volatile!
            }
        }

        # Performance tracking per model per regime
        self.performance=defaultdict(lambda:defaultdict(list))
        self.dynamic_weights={}
        self._load_weights()

    def _load_weights(self):
        """Load saved dynamic weights"""
        try:
            fname=f'ml_models/{self.symbol}_ensemble_weights.json'
            if os.path.exists(fname):
                self.dynamic_weights=json.load(open(fname))
                log.info(f'[ENS] {self.symbol} weights loaded!')
        except:pass

    def _save_weights(self):
        """Save dynamic weights"""
        try:
            fname=f'ml_models/{self.symbol}_ensemble_weights.json'
            json.dump(self.dynamic_weights,open(fname,'w'),indent=2)
        except:pass

    def get_weights(self,regime):
        """Get current weights for regime"""
        try:
            # Check dynamic weights first
            key=f'{regime}_weights'
            if key in self.dynamic_weights:
                return self.dynamic_weights[key]
            # Use regime-specific defaults
            if regime in self.regime_weights:
                return self.regime_weights[regime]
            return self.base_weights
        except:
            return self.base_weights

    def update_weights(self,regime,model,outcome):
        """Update model weight based on outcome"""
        try:
            self.performance[regime][model].append(outcome)

            # Recalculate after 20 samples
            if len(self.performance[regime][model])%20==0:
                self._recalculate_weights(regime)
        except Exception as e:
            log.error(f'[ENS] Update error: {e}')

    def _recalculate_weights(self,regime):
        """Recalculate weights based on performance"""
        try:
            models=list(self.base_weights.keys())
            performance_scores={}

            for model in models:
                outcomes=self.performance[regime][model]
                if len(outcomes)<10:
                    # Use default
                    default=self.regime_weights.get(regime,self.base_weights)
                    performance_scores[model]=default.get(model,0.15)
                    continue

                # Calculate win rate
                wr=sum(outcomes)/len(outcomes)
                # Recent performance (last 20)
                recent=outcomes[-20:]
                recent_wr=sum(recent)/len(recent)
                # Combined score
                score=wr*0.4+recent_wr*0.6
                performance_scores[model]=score

            # Normalize weights
            total=sum(performance_scores.values())
            if total>0:
                normalized={m:round(s/total,3) for m,s in performance_scores.items()}
            else:
                normalized=self.base_weights.copy()

            key=f'{regime}_weights'
            self.dynamic_weights[key]=normalized
            self._save_weights()

            log.info(f'[ENS] {self.symbol} {regime} weights updated:')
            for m,w in sorted(normalized.items(),key=lambda x:x[1],reverse=True):
                log.info(f'  {m}: {w:.3f}')

        except Exception as e:
            log.error(f'[ENS] Recalculate error: {e}')

    def combine_predictions(self,predictions,regime,signal):
        """
        Combine model predictions with dynamic weights
        predictions = dict of {model_name: probability}
        """
        try:
            weights=self.get_weights(regime)
            total_weight=0
            weighted_sum=0

            model_details={}
            for model,prob in predictions.items():
                if model in weights:
                    w=weights[model]
                    weighted_sum+=prob*w
                    total_weight+=w
                    model_details[model]={'prob':round(prob,3),'weight':round(w,3)}

            if total_weight==0:
                return 0.5,{}

            final_prob=weighted_sum/total_weight

            # Confidence boost for agreement
            probs=list(predictions.values())
            agreement=sum(1 for p in probs if p>0.5)/len(probs) if probs else 0.5
            if agreement>0.8:  # 80%+ models agree
                final_prob=min(final_prob*1.1,0.95)
                log.info(f'[ENS] {self.symbol} HIGH AGREEMENT! {agreement:.0%}')
            elif agreement<0.3:  # Models disagree strongly
                final_prob*=0.8
                log.info(f'[ENS] {self.symbol} LOW AGREEMENT! {agreement:.0%}')

            log.info(f'[ENS] {self.symbol} final={final_prob:.3f} regime={regime}')
            return round(final_prob,3),model_details

        except Exception as e:
            log.error(f'[ENS] Combine error: {e}')
            return 0.5,{}

    def get_ensemble_prob(self,symbol,signal,features,
                         ml_prob,meta_prob,mmt_prob,crl_ok):
        """
        Main function: Get ensemble probability
        """
        try:
            regime=signal.get('regime','RANGING')

            # Collect all model predictions
            predictions={
                'ml':ml_prob,
                'meta':meta_prob,
                'mmt':mmt_prob,
                'crl':0.7 if crl_ok else 0.3,
            }

            # Try to get RL prediction
            try:
                rl_fname=f'ml_models/{symbol}_v31_rl.pkl'
                if os.path.exists(rl_fname):
                    rl_agent=pickle.load(open(rl_fname,'rb'))
                    if hasattr(rl_agent,'predict'):
                        rl_prob=float(rl_agent.predict(np.array(features[:30]).reshape(1,-1))[0])
                        predictions['rl']=rl_prob
                    else:
                        predictions['rl']=0.5
                else:
                    predictions['rl']=0.5
            except:
                predictions['rl']=0.5

            # Try transformer prediction
            try:
                tf_fname=f'ml_models/{symbol}_v31_transformer.pkl'
                if os.path.exists(tf_fname):
                    tf_model=pickle.load(open(tf_fname,'rb'))
                    if hasattr(tf_model,'predict_proba'):
                        tf_prob=float(tf_model.predict_proba(
                            np.array(features[:30]).reshape(1,-1))[0][1])
                        predictions['transformer']=tf_prob
                    else:
                        predictions['transformer']=0.5
                else:
                    predictions['transformer']=0.5
            except:
                predictions['transformer']=0.5

            # Combine with dynamic weights
            final_prob,details=self.combine_predictions(predictions,regime,signal)
            return final_prob,details

        except Exception as e:
            log.error(f'[ENS] Error: {e}')
            return ml_prob,{}  # Fallback to ML prob

    def record_outcome(self,regime,predictions,outcome):
        """Record outcome for weight updates"""
        try:
            for model,prob in predictions.items():
                model_correct=1 if (prob>=0.5)==(outcome==1) else 0
                self.update_weights(regime,model,model_correct)
        except Exception as e:
            log.error(f'[ENS] Record error: {e}')


# Global instances
_ensemble_engines={}

def get_ensemble(symbol):
    if symbol not in _ensemble_engines:
        _ensemble_engines[symbol]=DynamicEnsemble(symbol)
    return _ensemble_engines[symbol]

def get_dynamic_ensemble_prob(symbol,signal,features,
                              ml_prob,meta_prob,mmt_prob,crl_ok):
    """Main function"""
    eng=get_ensemble(symbol)
    return eng.get_ensemble_prob(symbol,signal,features,
                                 ml_prob,meta_prob,mmt_prob,crl_ok)
