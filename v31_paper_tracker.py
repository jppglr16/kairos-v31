"""
V31 Paper Trade Tracker - Final Clean Version
Bug fixes:
1. Test doesn't delete real data
2. PENDING trades auto-expire (30 min)
3. Capital persists correctly
4. Better dedup (same day)
5. Correct profit factor
"""
import json, os, time, logging
from datetime import datetime

log = logging.getLogger(__name__)
FILE = 'paper_trades.json'

LOT_SIZES = {
    'NIFTY':65,'BANKNIFTY':30,'SENSEX':20,
    'FINNIFTY':60,'MIDCPNIFTY':120,
    'CRUDEOIL':100,'GOLDM':10,'SILVERM':30,
    'NATURALGAS':1250,'LT':450,'NTPC':4500,
    'MARUTI':100,'BHARTIARTL':950,'SBIN':1500,
    'TATAMOTORS':1350,'RELIANCE':250,
    'HINDUNILVR':300,'TCS':150,'TATASTEEL':5500,
}

def _load():
    """Load with corruption protection"""
    for fname in [FILE, FILE+'.bak']:
        try:
            if os.path.exists(fname):
                d = json.load(open(fname))
                if isinstance(d,dict) and 'trades' in d:
                    return d
        except: pass
    return {
        'trades': [],
        'capital': 50000,
        'peak_capital': 50000,
        'start_capital': 50000
    }

def _save(data):
    """Atomic write - never corrupts"""
    try:
        # Backup existing
        if os.path.exists(FILE):
            import shutil
            shutil.copy2(FILE, FILE+'.bak')
        # Atomic write
        tmp = FILE + '.tmp'
        with open(tmp,'w') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, FILE)
    except Exception as e:
        log.error(f'[PAPER] Save error: {e}')

def _expire_pending(data):
    """Auto-expire PENDING trades older than 30 mins"""
    cutoff = time.time() - 1800  # 30 mins
    for t in data['trades']:
        if t['status']=='PENDING' and t['entry_ts']<cutoff:
            t['status'] = 'EXPIRED'
            t['exit_reason'] = 'NO_OPTION_FOUND'
            log.info(f'[PAPER] Expired: {t["id"]}')

def record_signal(instrument, action, score,
                  spot_price, path='?', strategy='?'):
    """
    Step 1: Called when Signal Manager says ALLOWED.
    Records immediately - no option data needed yet.
    Returns trade_id string.
    """
    data = _load()
    _expire_pending(data)

    today = datetime.now().strftime('%Y-%m-%d')
    now_str = datetime.now().strftime('%H:%M:%S')

    # Same-day dedup: same instrument+action today
    for t in data['trades']:
        if (t['instrument']==instrument and
            t['action']==action and
            t['date']==today and
            t['status'] in ['PENDING','OPEN']):
            log.info(f'[PAPER] Dedup: {instrument} {action} already open')
            return t['id']

    trade_id = f"{instrument}_{int(time.time()*1000)}"

    trade = {
        'id': trade_id,
        'date': today,
        'time': now_str,
        'entry_ts': time.time(),
        'instrument': instrument,
        'action': action,
        'score': score,
        'spot_price': spot_price,
        'path': path,
        'strategy': strategy,
        'lot_size': LOT_SIZES.get(instrument, 75),

        # Filled after option selected (Step 2)
        'option_symbol': None,
        'premium': None,
        'sl_pct': -35,
        'sl_price': None,
        't1_price': None,
        't2_price': None,
        'investment': None,

        # Exit data (Step 3)
        'status': 'PENDING',
        'exit_price': None,
        'exit_time': None,
        'exit_reason': None,
        'pnl': None,
        'pnl_pct': None,
        'result': None,
        'holding_mins': None,

        # ML dataset
        'features': {
            'score': score,
            'path': path,
            'strategy': strategy,
            'hour': datetime.now().hour,
            'minute': datetime.now().minute,
            'day_of_week': datetime.now().weekday(),
            'instrument': instrument,
            'action': action,
            'outcome': None,
            'pnl_pct': None,
        },
    }

    data['trades'].append(trade)
    _save(data)
    log.info(f'[PAPER] ✅ Step1 {trade_id}: {instrument} {action} score={score}')
    return trade_id

def update_option(trade_id, option_symbol, premium, sl_pct=-35):
    """
    Step 2: Called after option token found.
    Updates premium, SL, targets.
    """
    if not trade_id or not premium or premium <= 0:
        return False

    data = _load()
    for t in data['trades']:
        if t['id'] == trade_id and t['status'] == 'PENDING':
            lot = t['lot_size']

            # Both BUY CE and BUY PE are buying options
            # SL is always below entry premium
            sl_price = round(premium * (1 + sl_pct/100), 2)
            t1_price = round(premium * 1.5, 2)
            t2_price = round(premium * 2.0, 2)

            t['option_symbol'] = option_symbol
            t['premium'] = premium
            t['sl_pct'] = sl_pct
            t['sl_price'] = sl_price
            t['t1_price'] = t1_price
            t['t2_price'] = t2_price
            t['investment'] = round(premium * lot, 2)
            t['status'] = 'OPEN'

            _save(data)
            log.info(f'[PAPER] ✅ Step2 {trade_id}: '
                     f'{option_symbol} @ Rs.{premium} '
                     f'SL={sl_price} T1={t1_price} T2={t2_price}')
            return True
    return False

def record_exit(trade_id, exit_price, reason='MANUAL'):
    """
    Step 3: Called when trade exits.
    Calculates P&L and updates capital.
    """
    if not trade_id or not exit_price:
        return None

    data = _load()
    for t in data['trades']:
        if t['id']==trade_id and t['status']=='OPEN':
            lot = t['lot_size']
            prem = t['premium'] or 0

            if prem <= 0:
                log.warning(f'[PAPER] No premium for {trade_id}')
                return None

            BROKERAGE = 40  # Per trade realistic cost
            pnl = round((exit_price - prem) * lot - BROKERAGE, 2)
            pnl_pct = round((exit_price-prem)/prem*100, 1)
            hold = round((time.time()-t['entry_ts'])/60, 1)

            t['exit_price'] = exit_price
            t['exit_time'] = datetime.now().strftime('%H:%M:%S')
            t['exit_reason'] = reason
            t['pnl'] = pnl
            t['pnl_pct'] = pnl_pct
            t['result'] = 'WIN' if pnl > 0 else 'LOSS'
            t['status'] = 'CLOSED'
            t['holding_mins'] = hold

            # Update ML features
            if 'features' in t:
                t['features']['outcome'] = t['result']
                t['features']['pnl_pct'] = pnl_pct
                t['features']['holding_mins'] = hold

            # Update capital
            old_cap = data.get('capital', 50000)
            data['capital'] = round(old_cap + pnl, 2)
            if data['capital'] > data.get('peak_capital', 50000):
                data['peak_capital'] = data['capital']

            _save(data)
            log.info(
                f'[PAPER] ✅ Step3 {trade_id}: '
                f'{t["result"]} Rs.{pnl:+,.0f} ({pnl_pct:+.1f}%) '
                f'hold={hold}m capital=Rs.{data["capital"]:,.0f}')
            return t
    return None

def auto_exit_check(current_prices):
    """
    Called from main loop with current option prices.
    current_prices = {option_symbol: ltp}
    Auto-exits on SL/T1/T2.
    """
    data = _load()
    actions = []

    for t in data['trades']:
        if t['status'] != 'OPEN':
            continue
        sym = t.get('option_symbol','')
        ltp = current_prices.get(sym, 0)
        if not ltp or not t.get('sl_price'):
            continue

        if ltp <= t['sl_price']:
            record_exit(t['id'], ltp, 'SL_HIT')
            actions.append(f"🛑 SL {t['instrument']} @ Rs.{ltp}")
        elif ltp >= t['t2_price']:
            record_exit(t['id'], ltp, 'T2_HIT')
            actions.append(f"🎯 T2 {t['instrument']} @ Rs.{ltp}")
        elif ltp >= t['t1_price'] and not t.get('t1_hit'):
            t['t1_hit'] = True
            _save(data)
            actions.append(f"🎯 T1 {t['instrument']} @ Rs.{ltp}")

    return actions

def get_open_trades():
    """All open/pending trades"""
    data = _load()
    _expire_pending(data)
    return [t for t in data['trades']
            if t['status'] in ['OPEN','PENDING']]

def get_today_summary():
    """Today's complete summary"""
    data = _load()
    _expire_pending(data)
    _save(data)  # Persist expired trades!
    today = datetime.now().strftime('%Y-%m-%d')
    today_t = [t for t in data['trades'] if t['date']==today]

    closed = [t for t in today_t if t['status']=='CLOSED']
    open_t = [t for t in today_t if t['status']=='OPEN']
    pending = [t for t in today_t if t['status']=='PENDING']
    expired = [t for t in today_t if t['status']=='EXPIRED']
    wins = [t for t in closed if t['result']=='WIN']
    losses = [t for t in closed if t['result']=='LOSS']
    pnl = sum(t['pnl'] or 0 for t in closed)
    wr = round(len(wins)/len(closed)*100,1) if closed else 0
    start = data.get('start_capital', 50000)
    cap = data.get('capital', 50000)

    return {
        'date': today,
        'total': len(today_t),
        'open': len(open_t),
        'pending': len(pending),
        'expired': len(expired),
        'closed': len(closed),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': wr,
        'pnl': round(pnl, 2),
        'capital': cap,
        'capital_return': round((cap-start)/start*100, 2),
        'trades': today_t,
    }

def get_lifetime_stats():
    """All-time statistics"""
    data = _load()
    closed = [t for t in data['trades'] if t['status']=='CLOSED']
    if not closed:
        return None

    wins = [t for t in closed if t['result']=='WIN']
    losses = [t for t in closed if t['result']=='LOSS']
    pnl = sum(t['pnl'] or 0 for t in closed)
    win_sum = sum(t['pnl'] for t in wins) if wins else 0
    loss_sum = abs(sum(t['pnl'] for t in losses)) if losses else 0

    # Correct profit factor
    if loss_sum > 0:
        pf = round(win_sum/loss_sum, 2)
    elif win_sum > 0:
        pf = 'INF'  # No losses!
    else:
        pf = 0

    return {
        'total': len(closed),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': round(len(wins)/len(closed)*100, 1),
        'pnl': round(pnl, 2),
        'profit_factor': pf,
        'avg_win': round(win_sum/len(wins), 2) if wins else 0,
        'avg_loss': round(-loss_sum/len(losses), 2) if losses else 0,
        'capital': data.get('capital', 50000),
        'peak_capital': data.get('peak_capital', 50000),
        'ml_ready': len(closed) >= 20,
    }

def telegram_report():
    """Telegram EOD report"""
    s = get_today_summary()
    st = get_lifetime_stats()
    emoji = ('🔥' if s['win_rate']>=60 else
             '✅' if s['win_rate']>=50 else '⚠️')

    msg = f"""📊 <b>V31 Paper Trade Report</b>
━━━━━━━━━━━━━━━
📅 {s['date']}

{emoji} <b>Today:</b>
📡 Total: {s['total']} (⏳{s['pending']} ❌{s['expired']})
🟢 Open: {s['open']} | 🔒 Closed: {s['closed']}
✅ Wins: {s['wins']} | ❌ Losses: {s['losses']}
🎯 Win Rate: {s['win_rate']}%
💰 Paper P&L: Rs.{s['pnl']:+,.0f}
💼 Capital: Rs.{s['capital']:,.0f} ({s['capital_return']:+.2f}%)"""

    if s['trades']:
        msg += '\n\n<b>Trades:</b>'
        for t in s['trades'][-8:]:
            ic = ('✅' if t['result']=='WIN' else
                  '❌' if t['result']=='LOSS' else '🟡')
            detail = (f"Rs.{t['pnl']:+,.0f}"
                     if t['pnl'] is not None else t['status'])
            opt = t.get('option_symbol','') or 'pending'
            msg += f'\n{ic} {t["instrument"]} | {opt} | {detail}'

    if st and st['total'] >= 5:
        msg += f"""

📊 <b>All Time ({st['total']} trades):</b>
🎯 Win Rate: {st['win_rate']}%
💰 Total P&L: Rs.{st['pnl']:+,.0f}
📈 Profit Factor: {st['profit_factor']}
🤖 ML Ready: {'YES ✅' if st['ml_ready'] else f'No ({st["total"]}/20)'}"""

    msg += '\n━━━━━━━━━━━━━━━\n📱 Paper Trade Mode'
    return msg
