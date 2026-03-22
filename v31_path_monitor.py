"""
V31 Path Monitor
Run after market hours to analyze path performance
"""
import subprocess,os
from datetime import datetime

def run(cmd):
    try:
        r=subprocess.run(cmd,shell=True,capture_output=True,text=True)
        return r.stdout.strip()
    except:return '0'

def monitor():
    print('='*50)
    print(f'V31 Path Monitor - {datetime.now().strftime("%d %b %Y %H:%M")}')
    print('='*50)

    # 1. NaN skips
    nan=run("grep 'NaN values skip' v31_log.txt | wc -l")
    print(f'\n📊 NaN Skips: {nan}')
    if int(nan)>10:print('⚠️ High NaN! Check data quality!')
    else:print('✅ NaN skips normal')

    # 2. Path activity
    print('\n📊 Path Activity:')
    for path in ['A_SMART','B_VWAP','C_ORB','D_SUPERTREND']:
        count=run(f"grep 'FINAL' v31_log.txt | grep '{path}' | wc -l")
        bar='█'*min(int(count),20)
        print(f'  {path:<15}: {count:>4} {bar}')

    # 3. Path distribution
    print('\n📊 Path Distribution:')
    dist=run("grep 'FINAL' v31_log.txt | grep -o 'via [A-Z_]*' | sort | uniq -c | sort -rn")
    if dist:print(dist)
    else:print('  No signals yet')

    # 4. Conflict resolution
    conflicts=run("grep 'CONFLICT' v31_log.txt | wc -l")
    print(f'\n📊 Conflicts resolved: {conflicts}')

    # 5. Weak skips
    print('\n📊 Filter Activity:')
    weak=run("grep 'weak flip skip' v31_log.txt | wc -l")
    lowvol=run("grep 'low volume skip' v31_log.txt | wc -l")
    regime=run("grep 'not suitable for VWAP' v31_log.txt | wc -l")
    nar=run("grep 'narrow range skip' v31_log.txt | wc -l")
    print(f'  Weak flips skipped:  {weak}')
    print(f'  Low volume skipped:  {lowvol}')
    print(f'  Wrong regime (VWAP): {regime}')
    print(f'  Narrow ORB skipped:  {nar}')

    # 6. Final signals
    total=run("grep 'FINAL' v31_log.txt | wc -l")
    approved=run("grep 'APPROVED' v31_log.txt | wc -l")
    rejected=run("grep 'REJECTED' v31_log.txt | wc -l")
    print(f'\n📊 Signal Summary:')
    print(f'  Total signals:  {total}')
    print(f'  Approved:       {approved}')
    print(f'  Rejected:       {rejected}')

    # 7. VIX regime
    print('\n📊 VIX Regimes:')
    for regime in ['SWEET_SPOT','HIGH','LOW','SPIKE']:
        count=run(f"grep 'VIX.*{regime}' v31_log.txt | wc -l")
        if int(count)>0:
            print(f'  {regime}: {count}')

    print('\n'+'='*50)
    print('Run after 3:30 PM daily! 📊')

if __name__=='__main__':
    monitor()
