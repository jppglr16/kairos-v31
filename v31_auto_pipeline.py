"""
V31 Auto Training Pipeline
Runs every Sunday - keeps models fresh!
"""
import os,logging,glob
from datetime import datetime
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')
log=logging.getLogger(__name__)

def send_telegram(msg):
    try:
        from v31_notify import send
        send(msg)
    except:pass

def step1_download_candles():
    """Download latest candles for all instruments"""
    log.info('Step 1: Downloading latest candles...')
    try:
        from v31_angel_trader import angel_trader
        from v31_instrument_manager import INSTRUMENTS
        import time,json
        angel_trader.connect()
        time.sleep(2)

        updated=0
        for inst,cfg in INSTRUMENTS.items():
            try:
                token=cfg.get('token','')
                exchange='MCX' if cfg.get('type')=='COMMODITY' else 'NSE'
                if inst=='SENSEX':exchange='BSE'

                today=datetime.now().strftime('%Y-%m-%d')
                year=datetime.now().year

                resp=angel_trader.obj.getCandleData({
                    'exchange':exchange,
                    'symboltoken':token,
                    'interval':'FIVE_MINUTE',
                    'fromdate':f'{year}-01-01 09:15',
                    'todate':f'{today} 15:30'
                })
                if resp and resp.get('data'):
                    fname=f'historical_data/{inst}_{year}_5min.json'
                    json.dump(resp['data'],open(fname,'w'))
                    updated+=1
                    log.info(f'  {inst}: {len(resp["data"])} candles updated')
                time.sleep(1)
            except Exception as e:
                log.warning(f'  {inst}: {e}')
                time.sleep(2)

        log.info(f'Step 1 done: {updated}/{len(INSTRUMENTS)} updated')
        return updated
    except Exception as e:
        log.error(f'Step 1 failed: {e}')
        return 0

def step2_train_gbm():
    """Train GBM models"""
    log.info('Step 2: Training GBM models...')
    try:
        from v31_ml_trainer_new import train_instrument
        from v31_instrument_manager import INSTRUMENTS
        success=0
        for sym in INSTRUMENTS:
            try:
                ok=train_instrument(sym)
                if ok:
                    success+=1
                    log.info(f'  {sym}: GBM ✅')
            except Exception as e:
                log.warning(f'  {sym}: {e}')
        log.info(f'Step 2 done: {success}/{len(INSTRUMENTS)} GBM trained')
        return success
    except Exception as e:
        log.error(f'Step 2 failed: {e}')
        return 0

def step3_train_lgbm():
    """Train LightGBM models"""
    log.info('Step 3: Training LightGBM models...')
    try:
        from v31_lgbm_trainer import train_lgbm
        from v31_instrument_manager import INSTRUMENTS
        success=0
        for sym in INSTRUMENTS:
            try:
                ok=train_lgbm(sym)
                if ok:
                    success+=1
                    log.info(f'  {sym}: LGBM ✅')
            except Exception as e:
                log.warning(f'  {sym}: {e}')
        log.info(f'Step 3 done: {success}/{len(INSTRUMENTS)} LGBM trained')
        return success
    except Exception as e:
        log.error(f'Step 3 failed: {e}')
        return 0

def step4_update_ensemble():
    """Update ensemble weights based on recent performance"""
    log.info('Step 4: Updating ensemble...')
    try:
        from v31_dynamic_ensemble import dynamic_ensemble
        dynamic_ensemble.update_weights()
        log.info('Step 4 done: Ensemble updated ✅')
        return True
    except Exception as e:
        log.warning(f'Step 4: {e}')
        return False

def step5_accuracy_report():
    """Generate accuracy report"""
    log.info('Step 5: Generating report...')
    try:
        import pickle
        gbm_models=glob.glob('ml_models/*_model.pkl')
        lgbm_models=glob.glob('ml_models/*_v31_lgbm.pkl')

        gbm_accs=[]
        for m in gbm_models:
            try:
                d=pickle.load(open(m,'rb'))
                if isinstance(d,dict):
                    gbm_accs.append(d.get('accuracy',0))
            except:pass

        lgbm_accs=[]
        for m in lgbm_models:
            try:
                d=pickle.load(open(m,'rb'))
                lgbm_accs.append(d.get('accuracy',0))
            except:pass

        gbm_avg=sum(gbm_accs)/len(gbm_accs) if gbm_accs else 0
        lgbm_avg=sum(lgbm_accs)/len(lgbm_accs) if lgbm_accs else 0

        return {
            'gbm_count':len(gbm_accs),
            'gbm_avg':gbm_avg,
            'lgbm_count':len(lgbm_accs),
            'lgbm_avg':lgbm_avg,
        }
    except Exception as e:
        log.error(f'Step 5 failed: {e}')
        return {}

def run_pipeline():
    """Run full training pipeline"""
    start=datetime.now()
    log.info('='*50)
    log.info('V31 AUTO TRAINING PIPELINE STARTED')
    log.info('='*50)

    send_telegram('🤖 V31 Auto Training Started!\nThis will take 2-3 hours...')

    # Run all steps
    candles=step1_download_candles()
    gbm=step2_train_gbm()
    lgbm=step3_train_lgbm()
    ensemble=step4_update_ensemble()
    report=step5_accuracy_report()

    # Send report
    elapsed=(datetime.now()-start).seconds//60
    msg=(f'✅ V31 Training Complete!\n'
         f'━━━━━━━━━━━━━━━\n'
         f'⏱️ Time: {elapsed} mins\n'
         f'📊 Candles updated: {candles}\n'
         f'🤖 GBM: {report.get("gbm_count",0)} models ({report.get("gbm_avg",0):.1%})\n'
         f'⚡ LGBM: {report.get("lgbm_count",0)} models ({report.get("lgbm_avg",0):.1%})\n'
         f'🔄 Ensemble: {"✅" if ensemble else "⚠️"}\n'
         f'🚀 V31 ready for Monday!')
    send_telegram(msg)
    log.info('Pipeline complete!')

if __name__=='__main__':
    run_pipeline()
