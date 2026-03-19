import numpy as np
import logging,os,pickle,json
from datetime import datetime
log=logging.getLogger(__name__)

class UncertaintyEstimator:
    """
    Uncertainty Estimation:
    Monte Carlo Dropout approach
    
    Instead of ONE prediction:
    Run model 100 times with noise
    = Distribution of predictions!
    
    Low uncertainty = Confident = TRADE ✅
    High uncertainty = Unsure = SKIP ❌
    """

    def __init__(self,symbol,n_samples=100):
        self.symbol=symbol
        self.n_samples=n_samples
        self.uncertainty_threshold=0.15  # Max allowed uncertainty

    def monte_carlo_predict(self,model,features,n_samples=100):
        """
        Simulate Monte Carlo Dropout:
        Add random noise to features
        Run multiple predictions
        Measure variance = uncertainty!
        """
        try:
            X=np.array(features[:30]).reshape(1,-1)
            predictions=[]

            for _ in range(n_samples):
                # Add small random noise (simulates dropout)
                noise=np.random.normal(0,0.05,X.shape)
                X_noisy=X+noise

                # Predict with noisy input
                if hasattr(model,'predict_proba'):
                    prob=float(model.predict_proba(X_noisy)[0][1])
                else:
                    prob=0.5
                predictions.append(prob)

            predictions=np.array(predictions)

            # Key statistics
            mean_pred=float(np.mean(predictions))
            std_pred=float(np.std(predictions))
            uncertainty=std_pred  # Higher std = more uncertain
            confidence=1-uncertainty  # Higher = more confident

            # Prediction interval
            lower=float(np.percentile(predictions,5))
            upper=float(np.percentile(predictions,95))
            interval_width=upper-lower

            return {
                'mean':round(mean_pred,3),
                'uncertainty':round(uncertainty,3),
                'confidence':round(confidence,3),
                'lower':round(lower,3),
                'upper':round(upper,3),
                'interval':round(interval_width,3),
                'samples':n_samples
            }
        except Exception as e:
            log.error(f'[UNC] MC error: {e}')
            return {'mean':0.5,'uncertainty':0.5,'confidence':0.5}

    def bayesian_estimate(self,features,all_model_probs):
        """
        Bayesian uncertainty from model disagreement:
        If models disagree = High uncertainty!
        If models agree = Low uncertainty!
        """
        try:
            probs=list(all_model_probs.values())
            if not probs:return 0.5,0.5

            mean_prob=np.mean(probs)
            # Epistemic uncertainty = model disagreement
            epistemic=np.std(probs)
            # Aleatoric uncertainty = inherent randomness
            aleatoric=np.mean([p*(1-p) for p in probs])
            # Total uncertainty
            total_uncertainty=epistemic+aleatoric*0.5

            confidence=1-min(total_uncertainty,1)
            return round(float(mean_prob),3),round(float(total_uncertainty),3)
        except Exception as e:
            log.error(f'[UNC] Bayesian error: {e}')
            return 0.5,0.5

    def get_uncertainty(self,symbol,features,all_model_probs,model=None):
        """
        Complete uncertainty estimation:
        1. Monte Carlo from primary model
        2. Bayesian from model ensemble
        3. Combined uncertainty score
        """
        try:
            results={}

            # Method 1: Bayesian from ensemble disagreement
            mean_prob,bayesian_unc=self.bayesian_estimate(features,all_model_probs)
            results['bayesian']={
                'mean':mean_prob,
                'uncertainty':bayesian_unc
            }

            # Method 2: Monte Carlo if model available
            mc_results={'mean':mean_prob,'uncertainty':0.3,'confidence':0.7}
            if model is not None:
                mc_results=self.monte_carlo_predict(model,features,n_samples=50)
            results['monte_carlo']=mc_results

            # Combined uncertainty
            combined_unc=(bayesian_unc*0.6+mc_results['uncertainty']*0.4)
            combined_conf=1-min(combined_unc,1)
            combined_mean=(mean_prob+mc_results['mean'])/2

            results['combined']={
                'mean':round(combined_mean,3),
                'uncertainty':round(combined_unc,3),
                'confidence':round(combined_conf,3)
            }

            log.info(f'[UNC] {symbol}: conf={combined_conf:.2f} unc={combined_unc:.2f}')
            return results
        except Exception as e:
            log.error(f'[UNC] Error: {e}')
            return {'combined':{'mean':0.5,'uncertainty':0.5,'confidence':0.5}}

    def should_trade(self,uncertainty_results,signal):
        """
        Decision: Take trade or skip?
        Based on uncertainty threshold
        """
        try:
            combined=uncertainty_results.get('combined',{})
            uncertainty=combined.get('uncertainty',0.5)
            confidence=combined.get('confidence',0.5)
            mean_prob=combined.get('mean',0.5)

            # Dynamic threshold
            import os
            regime=signal.get('regime','')
            trained=[f for f in os.listdir('ml_models') if '_v31_ml.pkl' in f]
            if len(trained)<10:
                max_unc=0.40
            elif 'TRENDING' in regime:
                max_unc=0.20
            elif regime=='VOLATILE':
                max_unc=0.10
            else:
                max_unc=0.15

            if uncertainty>max_unc:
                return False,f'HIGH_UNCERTAINTY_{uncertainty:.2f}>{max_unc}'
            if confidence<0.55:
                return False,f'LOW_CONFIDENCE_{confidence:.2f}'
            if mean_prob<0.40:
                return False,f'LOW_MEAN_PROB_{mean_prob:.2f}'

            return True,'UNCERTAINTY_OK'
        except Exception as e:
            log.error(f'[UNC] Decision error: {e}')
            return True,'ERROR'

    def format_telegram(self,uncertainty_results,instrument):
        """Format uncertainty for Telegram"""
        try:
            c=uncertainty_results.get('combined',{})
            conf=c.get('confidence',0.5)*100
            unc=c.get('uncertainty',0.5)*100
            mean=c.get('mean',0.5)*100

            # Confidence emoji
            if conf>=80:emoji='🟢'
            elif conf>=65:emoji='🟡'
            else:emoji='🔴'

            return f'{emoji} Confidence: {conf:.0f}% | Uncertainty: {unc:.0f}%'
        except:
            return '⚪ Confidence: N/A'


# Global instances
_unc_estimators={}

def get_estimator(symbol):
    if symbol not in _unc_estimators:
        _unc_estimators[symbol]=UncertaintyEstimator(symbol)
    return _unc_estimators[symbol]

def check_uncertainty(symbol,features,all_model_probs,signal,model=None):
    """Main function"""
    est=get_estimator(symbol)
    results=est.get_uncertainty(symbol,features,all_model_probs,model)
    should_trade,reason=est.should_trade(results,signal)
    conf_str=est.format_telegram(results,symbol)
    return should_trade,reason,results,conf_str
