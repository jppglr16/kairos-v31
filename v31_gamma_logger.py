"""V31 Gamma Blast ML Logger"""
import json, os, logging, threading
from datetime import datetime
log = logging.getLogger(__name__)
GAMMA_LOG_FILE = 'gamma_training_data.json'

def log_gamma_entry(signal, premium, lots):
    try:
        data = _load_data()
        entry = {
            'id': f"gamma_{int(datetime.now().timestamp())}",
            'date': datetime.now().strftime('%Y-%m-%d'),
            'time': datetime.now().strftime('%H:%M'),
            'instrument': signal.get('instrument'),
            'action': signal.get('action'),
            'score': signal.get('score'),
            'premium': premium, 'lots': lots,
            'status': 'OPEN',
            'features': {
                'dte': signal.get('days_to_expiry',0),
                'gex_bias': signal.get('gex_bias','UNKNOWN'),
                'gex_strength': signal.get('gex_strength',0),
                'gamma_regime': signal.get('gamma_regime','UNKNOWN'),
                'squeeze': signal.get('squeeze',False),
                'squeeze_ratio': signal.get('squeeze_ratio',0),
                'iv_ratio': signal.get('iv_ratio',1.0),
                'oi_flow': signal.get('oi_flow','UNKNOWN'),
                'pcr': signal.get('pcr',1.0),
                'vanna_active': signal.get('vanna_active',False),
                'institutional': signal.get('institutional',False),
                'delta_flow': signal.get('delta_flow',False),
                'mkt_regime': signal.get('mkt_regime','NORMAL'),
                'hour': datetime.now().hour,
                'weekday': datetime.now().weekday(),
            },
            'exit_premium': None, 'exit_time': None,
            'exit_reason': None, 'pnl': None,
            'pnl_pct': None, 'outcome': None,
        }
        data['trades'].append(entry)
        _save_data(data)
        log.info(f'[GAMMA_ML] Entry: {entry["id"]}')
        return entry['id']
    except Exception as e:
        log.error(f'[GAMMA_ML] Error: {e}')
        return None

def log_gamma_exit(trade_id, exit_premium, exit_reason):
    try:
        data = _load_data()
        for t in data['trades']:
            if t['id'] == trade_id:
                pnl_pct = ((exit_premium-t['premium'])/t['premium']*100) if t['premium'] else 0
                t.update({
                    'exit_premium': exit_premium,
                    'exit_time': datetime.now().strftime('%H:%M'),
                    'exit_reason': exit_reason,
                    'pnl': round(exit_premium - t['premium'], 2),
                'pnl_pct': round(pnl_pct,2),
                    'status': 'CLOSED',
                    'outcome': 'WIN' if pnl_pct>0 else 'LOSS'
                })
                break
        _save_data(data)
    except Exception as e:
        log.error(f'[GAMMA_ML] Exit error: {e}')

def get_gamma_stats():
    try:
        data = _load_data()
        closed = [t for t in data['trades'] if t['status']=='CLOSED']
        if not closed:
            return {'trades':0,'ready_for_ml':False,'message':'Need 20 trades!'}
        wins = [t for t in closed if t['outcome']=='WIN']
        return {
            'trades': len(closed),
            'win_rate': round(len(wins)/len(closed)*100,1),
            'ready_for_ml': len(closed)>=20,
            'message': '✅ Ready!' if len(closed)>=20 else f'Need {20-len(closed)} more!'
        }
    except:
        return {'trades':0,'ready_for_ml':False}

def _load_data():
    if os.path.exists(GAMMA_LOG_FILE):
        try: return json.load(open(GAMMA_LOG_FILE))
        except: pass
    return {'trades':[],'version':'V31_GAMMA_ML'}

_lock = threading.Lock()

def _save_data(data):
    with _lock:
        tmp = GAMMA_LOG_FILE + '.tmp'
        with open(tmp,'w') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, GAMMA_LOG_FILE)

if __name__ == '__main__':
    print(get_gamma_stats())
