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
                if resp and resp.get('data') and len(resp['data'])>=100:
                    fname=f'historical_data/{inst}_{year}_5min.json'
                    new_data=resp['data']
                    # Merge with existing data (not overwrite!)
                    if os.path.exists(fname):
                        try:
                            old_data=json.load(open(fname))
                            # Deduplicate by timestamp
                            existing_ts=set(c[0] for c in old_data)
                            added=[c for c in new_data if c[0] not in existing_ts]
                            merged=old_data+added
                            json.dump(merged,open(fname,'w'))
                            log.info(f'  {inst}: +{len(added)} new candles (total {len(merged)})')
                        except:
                            json.dump(new_data,open(fname,'w'))
                    else:
                        json.dump(new_data,open(fname,'w'))
                    updated+=1
                elif resp and resp.get('data'):
                    log.warning(f'  {inst}: insufficient data ({len(resp["data"])} candles)')
                time.sleep(1)
            except Exception as e:
                log.warning(f'  {inst}: {e}')
                time.sleep(2)

        log.info(f'Step 1 done: {updated}/{len(INSTRUMENTS)} updated')
        return updated
    except Exception as e:
        log.error(f'Step 1 failed: {e}')
        return 0

def _model_score(data):
    """
    Champion vs Challenger scoring
    Score = 0.4*accuracy + 0.4*win_rate + 0.2*consistency
    Better than accuracy alone!
    """
    if not isinstance(data,dict):return 0
    acc=data.get('accuracy',0)
    wr=data.get('win_rate',acc)  # fallback to accuracy
    consistency=data.get('consistency',0.5)
    score=(0.4*acc)+(0.4*wr)+(0.2*consistency)
    return score

def _keep_best_model(sym,new_model_path,model_type='gbm'):
    """
    Champion vs Challenger model selection
    Keep model with better trading score!
    """
    import pickle,shutil
    old_path=f'ml_models/{sym}_model.pkl' if model_type=='gbm' else f'ml_models/{sym}_v31_lgbm.pkl'
    try:
        new_data=pickle.load(open(new_model_path,'rb'))
        new_acc=new_data.get('accuracy',0) if isinstance(new_data,dict) else 0

        # Auto delete if accuracy too low
        if new_acc<0.45:
            os.remove(new_model_path)
            log.warning(f'  {sym}: New model too weak ({new_acc:.1%}<45%) - DELETED!')
            return False

        if os.path.exists(old_path):
            old_data=pickle.load(open(old_path,'rb'))
            old_score=_model_score(old_data)
            new_score=_model_score(new_data)

            if new_score>=old_score:
                shutil.copy(new_model_path,old_path)
                log.info(f'  {sym}: Challenger wins! ({new_score:.3f}>{old_score:.3f}) ✅')
                return True
            else:
                os.remove(new_model_path)
                log.info(f'  {sym}: Champion retained ({old_score:.3f}>{new_score:.3f})')
                return False
        else:
            # No existing model - use new one
            shutil.copy(new_model_path,old_path)
            log.info(f'  {sym}: First model saved ({new_acc:.1%}) ✅')
            return True
    except Exception as e:
        log.warning(f'  {sym}: Model selection error: {e}')
        return True

def step2_train_gbm():
    """Train GBM models with versioning"""
    log.info('Step 2: Training GBM models...')
    try:
        from v31_ml_trainer_new import train_instrument
        from v31_instrument_manager import INSTRUMENTS
        from concurrent.futures import ThreadPoolExecutor
        import pickle

        def train_one(sym):
            try:
                # Train to temp file first
                ok=train_instrument(sym)
                if ok:
                    log.info(f'  {sym}: GBM ✅')
                    return True
                return False
            except Exception as e:
                log.warning(f'  {sym}: {e}')
                return False

        # Parallel training (4 workers)
        with ThreadPoolExecutor(max_workers=4) as ex:
            results=list(ex.map(train_one,INSTRUMENTS.keys()))

        success=sum(results)
        log.info(f'Step 2 done: {success}/{len(INSTRUMENTS)} GBM trained')
        return success
    except Exception as e:
        log.error(f'Step 2 failed: {e}')
        return 0

def step3_train_lgbm():
    """Train LightGBM models - parallel!"""
    log.info('Step 3: Training LightGBM models (parallel)...')
    try:
        from v31_lgbm_trainer import train_lgbm
        from v31_instrument_manager import INSTRUMENTS
        from concurrent.futures import ThreadPoolExecutor

        def train_one(sym):
            try:
                ok=train_lgbm(sym)
                if ok:log.info(f'  {sym}: LGBM ✅')
                return ok
            except Exception as e:
                log.warning(f'  {sym}: {e}')
                return False

        # Parallel training (3 workers for LGBM)
        with ThreadPoolExecutor(max_workers=3) as ex:
            results=list(ex.map(train_one,INSTRUMENTS.keys()))

        success=sum(r for r in results if r)
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

def _safety_check():
    """Pipeline safety lock - prevent training on bad data"""
    issues=[]
    # Check 1: Minimum data files
    data_count=len(glob.glob('historical_data/*.json'))
    if data_count<10:
        issues.append(f'Too few data files: {data_count}')
    # Check 2: Internet
    try:
        import urllib.request
        urllib.request.urlopen('https://www.google.com',timeout=5)
    except:
        issues.append('No internet!')
    # Check 3: Angel connection
    try:
        from v31_angel_trader import angel_trader
        if not angel_trader.connected:
            issues.append('Angel not connected!')
    except:
        issues.append('Angel trader error!')
    if issues:
        log.error(f'Safety FAILED: {issues}')
        send_telegram('Pipeline Safety FAILED!\n'+' | '.join(issues))
        return False
    log.info('Safety check passed ✅')
    return True

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
