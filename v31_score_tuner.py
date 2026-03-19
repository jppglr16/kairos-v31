import json,os,logging
from datetime import datetime
log=logging.getLogger(__name__)

# Default thresholds
DEFAULT_THRESHOLDS={
    # NSE Indices
    'NIFTY':15,'BANKNIFTY':15,'SENSEX':15,
    'FINNIFTY':15,'MIDCPNIFTY':15,
    # MCX Commodities
    'CRUDEOIL':13,'GOLDM':13,'SILVERM':13,'NATURALGAS':13,
    # Stocks
    'LT':15,'NTPC':16,'MARUTI':15,'BHARTIARTL':15,
    'SBIN':16,'TATAMOTORS':16,'RELIANCE':15,
    'HINDUNILVR':15,'TCS':15,'TATASTEEL':16
}

# Score weights per instrument type
SCORE_WEIGHTS={
    'NIFTY':{
        'liq_sweep':5,'bos_choch':4,'fvg':4,
        'trend':4,'vwap':2,'gamma':6,'session':4,
        'trap':9,'volume':2
    },
    'CRUDEOIL':{
        'liq_sweep':5,'bos_choch':4,'fvg':4,
        'trend':4,'vwap':2,'gamma':0,  # No gamma for MCX!
        'session':4,'volume':3,'atr_pct':3  # ATR% bonus for MCX
    },
    'NATURALGAS':{
        'liq_sweep':5,'bos_choch':3,'fvg':3,
        'trend':3,'vwap':2,'gamma':0,
        'session':4,'volume':4,'atr_pct':2
    }
}

def get_threshold(instrument):
    """Get current score threshold for instrument"""
    try:
        fname=f'ml_models/{instrument}_score_config.json'
        if os.path.exists(fname):
            config=json.load(open(fname))
            return config.get('min_score',DEFAULT_THRESHOLDS.get(instrument,15))
        return DEFAULT_THRESHOLDS.get(instrument,15)
    except:
        return DEFAULT_THRESHOLDS.get(instrument,15)

def update_threshold(instrument,signals):
    """
    Auto-tune score threshold per instrument
    Finds optimal score that maximizes WR
    """
    try:
        completed=[s for s in signals if s.get('outcome') is not None]
        if len(completed)<30:
            return get_threshold(instrument)

        # Test different thresholds
        scores=[s.get('score',0) for s in completed]
        min_s=max(10,int(min(scores)))
        max_s=min(35,int(max(scores)))

        best_thresh=DEFAULT_THRESHOLDS.get(instrument,15)
        best_score=0

        for thresh in range(min_s,max_s,1):
            filtered=[s for s in completed if s.get('score',0)>=thresh]
            if len(filtered)<10:continue

            wins=sum(1 for s in filtered if s.get('outcome')==1)
            wr=wins/len(filtered)
            # Balance WR vs trade count
            trade_ratio=len(filtered)/len(completed)
            combined=wr*0.7+trade_ratio*0.3

            if combined>best_score:
                best_score=combined
                best_thresh=thresh

        # Save config
        fname=f'ml_models/{instrument}_score_config.json'
        config={
            'min_score':best_thresh,
            'optimized_at':str(datetime.now()),
            'sample_size':len(completed),
            'expected_wr':round(best_score*100,1)
        }
        json.dump(config,open(fname,'w'),indent=2)
        log.info(f'[SCORE] {instrument}: optimal threshold={best_thresh} (WR:{best_score:.2f})')
        return best_thresh
    except Exception as e:
        log.error(f'[SCORE] Tuning error: {e}')
        return get_threshold(instrument)

def get_instrument_weights(instrument):
    """Get scoring weights for instrument"""
    if instrument in SCORE_WEIGHTS:
        return SCORE_WEIGHTS[instrument]
    elif instrument in ['GOLDM','SILVERM','NATURALGAS']:
        return SCORE_WEIGHTS['NATURALGAS']
    elif instrument in ['BANKNIFTY','SENSEX','FINNIFTY','MIDCPNIFTY']:
        return SCORE_WEIGHTS['NIFTY']
    else:
        # Stocks - similar to NIFTY but no gamma
        weights=SCORE_WEIGHTS['NIFTY'].copy()
        weights['gamma']=0
        return weights

def get_score_summary():
    """Show current thresholds for all instruments"""
    summary={}
    for inst in DEFAULT_THRESHOLDS:
        summary[inst]=get_threshold(inst)
    return summary
