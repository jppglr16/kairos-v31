"""
V31 Trade Decision Logger
Records every signal decision with reason
Helps debug and improve system
"""
import json,os,logging
from datetime import datetime
log=logging.getLogger(__name__)

LOG_FILE='trade_decisions.json'

def log_decision(instrument,signal,decision,reason,details={}):
    """
    Log every trade decision
    decision: TAKEN / BLOCKED / SKIPPED
    reason: why
    """
    try:
        records=[]
        if os.path.exists(LOG_FILE):
            records=json.load(open(LOG_FILE))

        records.append({
            'time':datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'instrument':instrument,
            'action':signal.get('action',''),
            'score':signal.get('score',0),
            'regime':signal.get('regime',''),
            'sl_type':signal.get('sl_type',''),
            'path':signal.get('path','A'),
            'decision':decision,
            'reason':reason,
            'ml_prob':signal.get('ml_prob',0),
            'real_prem':signal.get('real_prem',0),
            **details
        })

        # Keep last 500 records
        records=records[-500:]
        json.dump(records,open(LOG_FILE,'w'))
    except Exception as e:
        log.error(f'[LOGGER] Error: {e}')

def get_stats(days=1):
    """Get decision stats"""
    try:
        if not os.path.exists(LOG_FILE):return {}
        records=json.load(open(LOG_FILE))
        from datetime import timedelta
        cutoff=(datetime.now()-timedelta(days=days)).strftime('%Y-%m-%d')
        recent=[r for r in records if r['time'][:10]>=cutoff]

        taken=[r for r in recent if r['decision']=='TAKEN']
        blocked=[r for r in recent if r['decision']=='BLOCKED']

        # Group blocked reasons
        reasons={}
        for r in blocked:
            reason=r['reason']
            reasons[reason]=reasons.get(reason,0)+1

        return {
            'total':len(recent),
            'taken':len(taken),
            'blocked':len(blocked),
            'block_reasons':reasons,
            'instruments':list(set(r['instrument'] for r in taken))
        }
    except:
        return {}
