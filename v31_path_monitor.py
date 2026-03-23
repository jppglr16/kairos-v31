"""
V31 Path Monitor v2
Complete analytics: paths + wins + time + efficiency
"""
import subprocess
from datetime import datetime

def safe_int(x):
    """Fix 1: Safe int conversion"""
    try:return int(str(x).strip())
    except:return 0

def run(cmd):
    try:
        r=subprocess.run(cmd,shell=True,capture_output=True,text=True)
        return r.stdout.strip()
    except:return '0'

def monitor():
    print('='*55)
    print(f'V31 Path Monitor - {datetime.now().strftime("%d %b %Y %H:%M")}')
    print('='*55)

    # 1. NaN skips
    nan=safe_int(run("grep 'NaN values skip' v31_log.txt | wc -l"))
    print(f'\n📊 NaN Skips: {nan}')
    print('⚠️ High NaN! Check data!' if nan>10 else '✅ Normal')

    # 2. Path activity + efficiency
    print('\n📊 Path Activity & Efficiency:')
    print(f'  {"Path":<15} {"Signals":>8} {"Wins":>6} {"Losses":>7} {"WR":>6}')
    print('  '+'-'*45)
    for path in ['A_SMART','B_VWAP','C_ORB','D_SUPERTREND']:
        today=datetime.now().strftime('%Y-%m-%d')
        total=safe_int(run(f"grep '{today}.*SIGNAL:.*{path}\|{today}.*path.*{path}' v31_log.txt | wc -l"))
        wins=safe_int(run(f"grep 'TARGET HIT' v31_log.txt | grep '{path}' | wc -l"))
        losses=safe_int(run(f"grep 'SL HIT' v31_log.txt | grep '{path}' | wc -l"))
        closed=wins+losses
        wr=f'{wins/closed*100:.0f}%' if closed>0 else 'N/A'
        bar='█'*min(total,15)
        print(f'  {path:<15} {total:>8} {wins:>6} {losses:>7} {wr:>6} {bar}')

    # 3. Time-based breakdown
    print('\n📊 Best Trading Hours:')
    print(f'  {"Hour":<8} {"Signals":>8} {"Wins":>6} {"WR":>6}')
    print('  '+'-'*30)
    for hour in ['09:','10:','11:','12:','13:','14:','15:']:
        sigs=safe_int(run(f"grep 'FINAL' v31_log.txt | grep '{hour}' | wc -l"))
        wins=safe_int(run(f"grep 'TARGET HIT' v31_log.txt | grep '{hour}' | wc -l"))
        wr=f'{wins/sigs*100:.0f}%' if sigs>0 else 'N/A'
        if sigs>0:
            bar='█'*min(sigs,10)
            print(f'  {hour+"xx":<8} {sigs:>8} {wins:>6} {wr:>6} {bar}')

    # 4. Conflict resolution
    conflicts=safe_int(run("grep 'CONFLICT' v31_log.txt | wc -l"))
    a_wins=safe_int(run("grep 'Path A preferred' v31_log.txt | wc -l"))
    orb_wins=safe_int(run("grep 'ORB overrides' v31_log.txt | wc -l"))
    print(f'\n📊 Conflicts: {conflicts} (Path A: {a_wins} | ORB: {orb_wins})')

    # 5. Filter activity
    print('\n📊 Filter Activity (Skips):')
    filters={
        'Weak flips':   "grep 'weak flip skip' v31_log.txt | wc -l",
        'Low volume':   "grep 'low volume skip' v31_log.txt | wc -l",
        'Wrong regime': "grep 'not suitable for VWAP' v31_log.txt | wc -l",
        'Narrow ORB':   "grep 'narrow range skip' v31_log.txt | wc -l",
        'VIX blocked':  "grep 'Trading blocked' v31_log.txt | wc -l",
        'News blocked': "grep -E 'NEWS.*blocked|blocked.*NEWS' v31_log.txt | wc -l",
        'Low quality':  "grep -E 'quality low|weak score' v31_log.txt | wc -l",
    }
    for name,cmd in filters.items():
        n=safe_int(run(cmd))
        if n>0:print(f'  {name:<15}: {n}')

    # 6. Win/Loss summary
    today=datetime.now().strftime('%Y-%m-%d')
    total_sigs=safe_int(run(f"grep '{today}.*SIGNAL:' v31_log.txt | wc -l"))
    total_wins=safe_int(run("grep 'TARGET HIT' v31_log.txt | wc -l"))
    total_loss=safe_int(run("grep 'SL HIT' v31_log.txt | wc -l"))
    approved=safe_int(run("grep 'APPROVED' v31_log.txt | wc -l"))
    executed=safe_int(run("grep -E 'ORDER PLACED|order.*placed|COMPLETE' v31_log.txt | wc -l"))
    failed=safe_int(run("grep -E 'ORDER FAILED|REJECTED.*order|order.*REJECTED' v31_log.txt | wc -l"))
    _closed=total_wins+total_loss
    overall_wr=f'{total_wins/_closed*100:.1f}%' if _closed>0 else 'N/A (no closed trades yet)'
    print(f'\n📊 Overall Summary:')
    print(f'  Signals generated: {total_sigs}')
    print(f'  Trades approved:   {approved}')
    print(f'  Orders executed:   {executed}')
    print(f'  Orders failed:     {failed}')
    if approved>0 and executed<approved:
        print(f'  ⚠️ Gap: {approved-executed} approved but not executed!')
    print(f'  Wins:              {total_wins}')
    print(f'  Losses:            {total_loss}')
    print(f'  Live Win Rate:     {overall_wr}')

    # 7. VIX regimes
    print('\n📊 VIX Regimes Today:')
    for regime in ['SWEET_SPOT','HIGH','LOW','SPIKE_UP','SPIKE_DOWN']:
        n=safe_int(run(f"grep '{regime}' v31_log.txt | wc -l"))
        if n>0:print(f'  {regime}: {n}')

    # 8. Best instrument
    print('\n📊 Top Instruments:')
    inst_data=run("grep 'FINAL' v31_log.txt | grep -oE '\\b[A-Z]{3,10}\\b' | grep -vE 'FINAL|BUY|SELL|VIA|PATH|SCORE|LOG|INFO' | sort | uniq -c | sort -rn | head -5")
    if inst_data:print(inst_data)

    print('\n'+'='*55)
    print('💡 Run daily after 3:30 PM!')
    print('💡 After 1 week: optimize thresholds!')

if __name__=='__main__':
    monitor()
