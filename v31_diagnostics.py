"""
V31 Diagnostics Tool
Check win rates and train best instruments
"""
import logging
from v31_ml_trainer_new import load_data,to_df,label_outcome,train_instrument
from v31_instrument_manager import INSTRUMENTS

logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')
log=logging.getLogger(__name__)

def check_win_rates():
    """Check labeling win rates for all instruments"""
    results=[]
    log.info('Checking win rates...')

    for sym in INSTRUMENTS:
        try:
            d=load_data(sym)
            if not d:
                results.append({'symbol':sym,'win_rate':0,'atr':0,'status':'NO DATA'})
                continue
            df=to_df(d)
            if len(df)>30000:df=df.tail(30000).reset_index(drop=True)
            atr=float((df['high']-df['low']).tail(14).mean())
            sample=range(50,min(len(df)-120,5000),10)
            wins=sum(label_outcome(df,i,'BUY',atr) for i in sample)
            total=len(sample)
            wr=wins/total if total>0 else 0
            status='✅ Good' if wr>=0.30 else '⚠️ OK' if wr>=0.20 else '❌ Poor'
            results.append({'symbol':sym,'win_rate':wr,'atr':atr,'status':status})
            log.info(f'{sym}: WR={wr:.1%} ATR={atr:.2f} {status}')
        except Exception as e:
            log.warning(f'{sym}: Error {e}')
            results.append({'symbol':sym,'win_rate':0,'atr':0,'status':'ERROR'})

    # Sort by WR
    results.sort(key=lambda x:-x['win_rate'])

    print()
    print('=== Win Rate Diagnostic Report ===')
    print(f'{"Rank":<5}{"Symbol":<15}{"WinRate":<10}{"ATR":<10}Status')
    print('-'*50)
    for i,r in enumerate(results,1):
        print(f'{i:<5}{r["symbol"]:<15}{r["win_rate"]:.1%}     {r["atr"]:<10.1f}{r["status"]}')

    good=sum(1 for r in results if r['win_rate']>=0.30)
    ok=sum(1 for r in results if 0.20<=r['win_rate']<0.30)
    poor=sum(1 for r in results if r['win_rate']<0.20)

    print()
    print(f'✅ Good (>=30%): {good}/{len(results)}')
    print(f'⚠️ OK   (>=20%): {ok}/{len(results)}')
    print(f'❌ Poor (<20%):  {poor}/{len(results)}')
    print()

    # Top 5
    print('Top 5 performers:')
    for r in results[:5]:
        print(f'  {r["symbol"]}: WR={r["win_rate"]:.1%}')

    # Bottom 5
    print('Bottom 5 (need attention):')
    for r in results[-5:]:
        print(f'  {r["symbol"]}: WR={r["win_rate"]:.1%}')

    return results

def retrain_poor(threshold=0.20):
    """Retrain instruments with poor win rates"""
    results=check_win_rates()
    poor=[r['symbol'] for r in results if r['win_rate']<threshold]
    log.info(f'Retraining {len(poor)} poor instruments: {poor}')
    for sym in poor:
        ok=train_instrument(sym)
        log.info(f'{sym}: retrained={ok}')

def retrain_all():
    """Retrain all instruments"""
    success=0
    for sym in INSTRUMENTS:
        ok=train_instrument(sym)
        if ok:success+=1
        log.info(f'{sym}: {"✅" if ok else "❌"}')
    log.info(f'Done: {success}/{len(INSTRUMENTS)}')

if __name__=='__main__':
    import sys
    cmd=sys.argv[1] if len(sys.argv)>1 else 'check'
    if cmd=='check':
        check_win_rates()
    elif cmd=='retrain_poor':
        retrain_poor()
    elif cmd=='retrain_all':
        retrain_all()
    else:
        print('Usage: python3 v31_diagnostics.py [check|retrain_poor|retrain_all]')
