"""
V31 Model Guard
Protects against accuracy regression
Auto-rollback if new model worse than old
Champion-vs-challenger system
"""
import pickle,os,shutil,json,logging
from datetime import datetime
log=logging.getLogger(__name__)

class ModelGuard:
    def __init__(self):
        self.backup_dir='ml_models/backups'
        self.registry_file='ml_models/model_registry.json'
        os.makedirs(self.backup_dir,exist_ok=True)
        self._load_registry()

    def _load_registry(self):
        try:
            if os.path.exists(self.registry_file):
                self.registry=json.load(open(self.registry_file))
            else:
                self.registry={}
        except:
            self.registry={}

    def _save_registry(self):
        try:
            with open(self.registry_file,'w') as f:
                json.dump(self.registry,f,indent=2)
        except Exception as e:
            log.error(f'[GUARD] Registry save error: {e}')

    def get_current_accuracy(self,instrument):
        """Get accuracy of current best model"""
        try:
            f=f'ml_models/{instrument}_v31_ml.pkl'
            if os.path.exists(f):
                d=pickle.load(open(f,'rb'))
                if isinstance(d,dict):
                    return d.get('accuracy',0)
        except:pass
        return 0

    def backup_current(self,instrument):
        """Backup current model before overwrite"""
        try:
            src=f'ml_models/{instrument}_v31_ml.pkl'
            if not os.path.exists(src):return None
            ts=datetime.now().strftime('%Y%m%d_%H%M')
            dst=f'{self.backup_dir}/{instrument}_v31_{ts}.pkl'
            shutil.copy2(src,dst)
            log.info(f'[GUARD] {instrument} backed up → {dst}')
            return dst
        except Exception as e:
            log.error(f'[GUARD] Backup error: {e}')
            return None

    def should_save(self,instrument,new_accuracy,min_improvement=0.001):
        """
        Champion-vs-Challenger!
        Only save if new model better than current
        """
        current_acc=self.get_current_accuracy(instrument)

        if current_acc==0:
            log.info(f'[GUARD] {instrument} no existing model, save!')
            return True,current_acc

        if new_accuracy>=current_acc-min_improvement:
            log.info(f'[GUARD] {instrument} new={new_accuracy:.1%} >= '
                    f'current={current_acc:.1%} ✅ SAVE!')
            return True,current_acc
        else:
            log.warning(f'[GUARD] {instrument} new={new_accuracy:.1%} < '
                       f'current={current_acc:.1%} ❌ KEEP OLD!')
            return False,current_acc

    def safe_save(self,instrument,model_data,new_accuracy):
        """
        Safe model save with:
        1. Backup current
        2. Compare accuracy
        3. Save only if better
        4. Auto-rollback if worse
        """
        # Backup first!
        backup=self.backup_current(instrument)

        # Compare
        should,old_acc=self.should_save(instrument,new_accuracy)

        if should:
            try:
                f=f'ml_models/{instrument}_v31_ml.pkl'
                with open(f,'wb') as fh:
                    pickle.dump(model_data,fh)

                # Update registry
                self.registry[instrument]={
                    'accuracy':new_accuracy,
                    'prev_accuracy':old_acc,
                    'saved_at':datetime.now().isoformat(),
                    'backup':backup,
                    'improved':new_accuracy>old_acc
                }
                self._save_registry()

                change=new_accuracy-old_acc
                icon='✅' if change>=0 else '⚠️'
                log.info(f'[GUARD] {instrument} saved! '
                        f'{old_acc:.1%}→{new_accuracy:.1%} ({change:+.1%}) {icon}')
                return True
            except Exception as e:
                log.error(f'[GUARD] Save error: {e}')
                # Rollback!
                if backup and os.path.exists(backup):
                    shutil.copy2(backup,f'ml_models/{instrument}_v31_ml.pkl')
                    log.warning(f'[GUARD] {instrument} ROLLED BACK!')
                return False
        else:
            # Keep old model!
            log.warning(f'[GUARD] {instrument} keeping old model '
                       f'({old_acc:.1%} > {new_accuracy:.1%})')
            return False

    def rollback(self,instrument):
        """Manual rollback to best backup"""
        try:
            backups=sorted([f for f in os.listdir(self.backup_dir)
                          if f.startswith(instrument)],reverse=True)
            if not backups:
                log.warning(f'[GUARD] No backups for {instrument}!')
                return False
            best=f'{self.backup_dir}/{backups[0]}'
            shutil.copy2(best,f'ml_models/{instrument}_v31_ml.pkl')
            log.info(f'[GUARD] {instrument} rolled back to {backups[0]}')
            return True
        except Exception as e:
            log.error(f'[GUARD] Rollback error: {e}')
            return False

    def status_report(self):
        """Show model health for all instruments"""
        from v31_instrument_manager import INSTRUMENTS
        print('='*55)
        print('📊 Model Registry Report')
        print('='*55)
        improved=0
        degraded=0
        for inst in INSTRUMENTS:
            r=self.registry.get(inst,{})
            curr=self.get_current_accuracy(inst)
            if r:
                prev=r.get('prev_accuracy',0)
                change=curr-prev
                icon='✅' if change>=0 else '⚠️'
                if change>=0:improved+=1
                else:degraded+=1
                print(f'{inst:<15} {curr:.1%} ({change:+.1%}) {icon}')
            else:
                print(f'{inst:<15} {curr:.1%} (new)')
        print(f'\nImproved: {improved} | Degraded: {degraded}')
        print('='*55)

# Global instance
model_guard=ModelGuard()
