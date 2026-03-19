import logging
from datetime import datetime
log=logging.getLogger(__name__)

class ProtectionManager:
    def __init__(self,capital):
        self.capital=capital
        self.daily_loss=0
        self.daily_pnl=0
        self.max_daily_loss=capital*0.15
        self.trade_count=0
        self.stopped=False
        self.reason=None

    def update_capital(self,capital):
        self.capital=capital
        self.max_daily_loss=capital*0.15

    def can_trade(self):
        if self.stopped:
            log.warning(f'[PROTECT] Trading stopped: {self.reason}')
            return False
        if self.daily_loss>=self.max_daily_loss:
            self.stopped=True
            self.reason=f'MAX_DAILY_LOSS_{self.daily_loss:.0f}'
            log.warning(f'[PROTECT] Daily loss limit hit: {self.daily_loss:.0f}')
            return False
        return True

    def record_pnl(self,pnl):
        self.daily_pnl+=pnl
        if pnl<0:
            self.daily_loss+=abs(pnl)
        self.trade_count+=1
        log.info(f'[PROTECT] Daily PnL:{self.daily_pnl:.0f} Loss:{self.daily_loss:.0f} Max:{self.max_daily_loss:.0f}')

    def reset_daily(self):
        self.daily_loss=0
        self.daily_pnl=0
        self.trade_count=0
        self.stopped=False
        self.reason=None
        log.info('[PROTECT] Daily reset done!')

    def get_overnight_sl(self,sl_points):
        # Tighter SL for overnight - 30% tighter
        return sl_points*0.7

    def check_premium_sl(self,entry_premium,current_premium):
        # Exit if premium drops 40%
        if entry_premium<=0:return False
        drop_pct=(entry_premium-current_premium)/entry_premium
        if drop_pct>=0.4:
            log.warning(f'[PROTECT] Premium SL hit! Entry:{entry_premium} Current:{current_premium} Drop:{drop_pct*100:.0f}%')
            return True
        return False

    def check_profit_lock(self,entry_premium,current_premium,target_premium):
        # Lock 50% profit if reached 70% of target
        if entry_premium<=0 or target_premium<=0:return False
        progress=(current_premium-entry_premium)/(target_premium-entry_premium)
        if progress>=0.7:
            # Move SL to lock 50% profit
            lock_premium=entry_premium+(target_premium-entry_premium)*0.5
            if current_premium<=lock_premium:
                log.info(f'[PROTECT] Profit lock triggered! Locking 50% profit')
                return True
        return False

    def get_position_summary(self):
        return {
            'daily_pnl':self.daily_pnl,
            'daily_loss':self.daily_loss,
            'max_daily_loss':self.max_daily_loss,
            'trade_count':self.trade_count,
            'stopped':self.stopped,
            'reason':self.reason
        }

protection_mgr=None

def get_protection(capital):
    global protection_mgr
    if protection_mgr is None:
        protection_mgr=ProtectionManager(capital)
    return protection_mgr
