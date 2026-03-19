
# Kairos V30 - Adaptive Learning Engine
import json, os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

HISTORY_FILE = 'v30_trades.json'
PARAMS_FILE = 'v30_params.json'

DEFAULT_PARAMS = {
    'NIFTY': {
        'rsi_bull_min': 52, 'rsi_bear_max': 48,
        'rsi_strong_bull': 60, 'rsi_strong_bear': 40,
        'atr_sl_mult': 1.5, 'atr_target_mult': 2.0,
        'vol_surge_mult': 1.5, 'min_confidence': 60,
        'best_hours': [9,10,11,14], 'avoid_hours': [12,13],
        'sideways_target_rr': 1.5, 'trending_target_rr': 2.5,
    },
    'BANKNIFTY': {
        'rsi_bull_min': 52, 'rsi_bear_max': 48,
        'rsi_strong_bull': 60, 'rsi_strong_bear': 40,
        'atr_sl_mult': 1.5, 'atr_target_mult': 2.0,
        'vol_surge_mult': 1.5, 'min_confidence': 60,
        'best_hours': [9,10,11,14], 'avoid_hours': [12,13],
        'sideways_target_rr': 1.5, 'trending_target_rr': 2.5,
    },
    'CRUDEOIL': {
        'rsi_bull_min': 52, 'rsi_bear_max': 48,
        'rsi_strong_bull': 58, 'rsi_strong_bear': 42,
        'atr_sl_mult': 1.2, 'atr_target_mult': 2.0,
        'vol_surge_mult': 1.3, 'min_confidence': 55,
        'best_hours': [15,16,17,9,10], 'avoid_hours': [11],
        'sideways_target_rr': 1.5, 'trending_target_rr': 2.0,
    }
}

def load_params():
    if os.path.exists(PARAMS_FILE):
        return json.load(open(PARAMS_FILE))
    return DEFAULT_PARAMS.copy()

def save_params(params):
    json.dump(params, open(PARAMS_FILE,'w'), indent=2)

def load_history():
    if os.path.exists(HISTORY_FILE):
        return json.load(open(HISTORY_FILE))
    return []

class AdaptiveEngine:
    def __init__(self):
        self.params = load_params()
        self.history = load_history()
        self.stats = {}
        self.analyze_history()

    def analyze_history(self):
        if len(self.history) < 5:
            return
        for instrument in ['NIFTY','BANKNIFTY','CRUDEOIL']:
            trades = [t for t in self.history if t.get('signal',{}).get('instrument')==instrument]
            if len(trades) < 3:
                continue
            wins = [t for t in trades if t.get('pnl',0) > 0]
            losses = [t for t in trades if t.get('pnl',0) < 0]
            total = len(trades)
            win_rate = len(wins)/total if total > 0 else 0
            avg_win = np.mean([t['pnl'] for t in wins]) if wins else 0
            avg_loss = abs(np.mean([t['pnl'] for t in losses])) if losses else 1
            profit_factor = (avg_win * len(wins)) / (avg_loss * len(losses)) if losses else 999
            # Hour analysis
            hour_stats = {}
            for t in trades:
                try:
                    h = int(t['signal']['timestamp'][11:13])
                    if h not in hour_stats:
                        hour_stats[h] = {'wins':0,'losses':0}
                    if t.get('pnl',0) > 0:
                        hour_stats[h]['wins'] += 1
                    else:
                        hour_stats[h]['losses'] += 1
                except:
                    pass
            best_hours = [h for h,s in hour_stats.items() if s['wins']/(s['wins']+s['losses']+0.01) > 0.6]
            avoid_hours = [h for h,s in hour_stats.items() if s['losses']/(s['wins']+s['losses']+0.01) > 0.6]
            # Market condition analysis
            cond_stats = {}
            for t in trades:
                cond = t.get('signal',{}).get('market_condition','UNKNOWN')
                if cond not in cond_stats:
                    cond_stats[cond] = {'wins':0,'losses':0,'pnl':0}
                if t.get('pnl',0) > 0:
                    cond_stats[cond]['wins'] += 1
                else:
                    cond_stats[cond]['losses'] += 1
                cond_stats[cond]['pnl'] += t.get('pnl',0)
            self.stats[instrument] = {
                'win_rate': win_rate,
                'profit_factor': profit_factor,
                'avg_win': avg_win,
                'avg_loss': avg_loss,
                'total_trades': total,
                'hour_stats': hour_stats,
                'best_hours': best_hours,
                'avoid_hours': avoid_hours,
                'cond_stats': cond_stats
            }
            print(f'[ADAPTIVE] {instrument}: WR={win_rate:.0%} PF={profit_factor:.2f} Trades={total}')
            self._tune_params(instrument)

    def _tune_params(self, instrument):
        if instrument not in self.stats:
            return
        s = self.stats[instrument]
        p = self.params.get(instrument, DEFAULT_PARAMS[instrument].copy())
        win_rate = s['win_rate']
        profit_factor = s['profit_factor']
        # Tighten confidence if win rate is low
        if win_rate < 0.45:
            p['min_confidence'] = min(75, p['min_confidence'] + 5)
            p['atr_sl_mult'] = max(1.0, p['atr_sl_mult'] - 0.1)
            print(f'[ADAPTIVE] {instrument}: Tightening filters (low WR={win_rate:.0%})')
        elif win_rate > 0.65:
            p['min_confidence'] = max(50, p['min_confidence'] - 3)
            print(f'[ADAPTIVE] {instrument}: Relaxing filters (high WR={win_rate:.0%})')
        # Adjust targets based on profit factor
        if profit_factor > 2.0:
            p['atr_target_mult'] = min(3.5, p['atr_target_mult'] + 0.2)
            print(f'[ADAPTIVE] {instrument}: Increasing targets (PF={profit_factor:.2f})')
        elif profit_factor < 1.2:
            p['atr_target_mult'] = max(1.5, p['atr_target_mult'] - 0.2)
            print(f'[ADAPTIVE] {instrument}: Reducing targets (PF={profit_factor:.2f})')
        # Update best/avoid hours from history
        if s['best_hours']:
            p['best_hours'] = s['best_hours']
        if s['avoid_hours']:
            p['avoid_hours'] = s['avoid_hours']
        self.params[instrument] = p
        save_params(self.params)

    def get_confidence_score(self, signal, instrument):
        score = 0
        p = self.params.get(instrument, DEFAULT_PARAMS[instrument])
        # SMC strength (0-30 points)
        score += signal.get('smc_strength', 0) * 10
        # Momentum alignment (0-25 points)
        score += signal.get('momentum_strength', 0) * 8
        # RSI quality (0-20 points)
        rsi = signal.get('rsi', 50)
        action = signal.get('action')
        if action == 'BUY':
            if rsi > p['rsi_strong_bull']:
                score += 20
            elif rsi > p['rsi_bull_min']:
                score += 10
        elif action == 'SELL':
            if rsi < p['rsi_strong_bear']:
                score += 20
            elif rsi < p['rsi_bear_max']:
                score += 10
        # Hour quality (0-15 points)
        now_hour = datetime.now().hour
        if now_hour in p.get('best_hours',[]):
            score += 15
        elif now_hour in p.get('avoid_hours',[]):
            score -= 20
        # Historical win rate boost (0-10 points)
        if instrument in self.stats:
            wr = self.stats[instrument]['win_rate']
            score += int(wr * 10)
        # Market condition boost
        cond = signal.get('market_condition','')
        if instrument in self.stats:
            cond_stats = self.stats[instrument].get('cond_stats',{})
            if cond in cond_stats:
                cs = cond_stats[cond]
                cond_wr = cs['wins']/(cs['wins']+cs['losses']+0.01)
                if cond_wr > 0.6:
                    score += 10
                elif cond_wr < 0.4:
                    score -= 10
        return min(100, max(0, score))

    def should_trade(self, signal, instrument):
        p = self.params.get(instrument, DEFAULT_PARAMS[instrument])
        score = self.get_confidence_score(signal, instrument)
        signal['confidence'] = score
        min_conf = p['min_confidence']
        if score >= min_conf:
            print(f'[ADAPTIVE] ✅ TRADE APPROVED: {instrument} score={score}/100')
            return True
        else:
            print(f'[ADAPTIVE] ❌ TRADE SKIPPED: {instrument} score={score}/100 (min={min_conf})')
            return False

    def record_result(self, instrument, signal, pnl):
        entry = {
            'time': str(datetime.now()),
            'pnl': pnl,
            'signal': signal
        }
        self.history.append(entry)
        json.dump(self.history, open(HISTORY_FILE,'w'), indent=2)
        # Re-analyze after every 5 trades
        if len(self.history) % 5 == 0:
            print('[ADAPTIVE] Re-analyzing trade history...')
            self.analyze_history()

    def get_dynamic_targets(self, instrument, signal):
        p = self.params.get(instrument, DEFAULT_PARAMS[instrument])
        sl = signal.get('sl_points', 50)
        cond = signal.get('market_condition','SIDEWAYS')
        if cond == 'SIDEWAYS':
            rr = p['sideways_target_rr']
        else:
            rr = p['trending_target_rr']
        # Check if instrument is performing well — extend targets
        if instrument in self.stats:
            if self.stats[instrument]['profit_factor'] > 2.0:
                rr = min(rr * 1.3, 4.0)
        target1 = sl * rr
        target2 = sl * (rr * 1.5)
        use_trailing = cond != 'SIDEWAYS' and signal.get('momentum_strength',0) >= 2
        return {
            'target1': target1,
            'target2': target2,
            'use_trailing': use_trailing,
            'rr_ratio': rr
        }

    def print_summary(self):
        print('\n===== KAIROS V30 PERFORMANCE SUMMARY =====')
        for inst, s in self.stats.items():
            print(f'{inst}: WR={s["win_rate"]:.0%} | PF={s["profit_factor"]:.2f} | Trades={s["total_trades"]} | AvgWin={s["avg_win"]:.0f} | AvgLoss={s["avg_loss"]:.0f}')
        print('==========================================\n')

def record_winning_pattern(self,instrument,signal,features):
    """Save features from winning trades for future training"""
    try:
        fname=f'ml_models/{instrument}_winners.json'
        patterns=json.load(open(fname)) if os.path.exists(fname) else []
        patterns.append({
            'features':features,
            'signal':str(signal),
            'timestamp':str(datetime.now())
        })
        # Keep last 1000 winners
        if len(patterns)>1000:
            patterns=patterns[-1000:]
        json.dump(patterns,open(fname,'w'))
        # Retrain every 50 new wins
        if len(patterns)%50==0:
            print(f'[ADAPTIVE] {instrument}: {len(patterns)} wins saved - scheduling retrain')
    except Exception as e:
        print(f'[ADAPTIVE] Error saving winner: {e}')
