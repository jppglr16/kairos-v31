from datetime import datetime
import logging
log=logging.getLogger(__name__)

class V31RiskManager:
    def __init__(self,capital):
        self.initial_capital=capital
        self.peak_capital=capital
        self.daily_pnl=0
        self.weekly_pnl=0
        self.consecutive_losses=0
        self.daily_trades=0
        self.daily_losses=0
        self.last_reset=datetime.now().date()

    def reset_daily(self):
        self.daily_pnl=0
        self.daily_trades=0
        self.daily_losses=0
        self.consecutive_losses=0
        self.last_reset=datetime.now().date()

    def can_trade(self,capital,signal_risk):
        if datetime.now().date()!=self.last_reset:
            self.reset_daily()
        if capital>self.peak_capital:
            self.peak_capital=capital
        if self.daily_trades>=4:
            return False,'MAX_DAILY_TRADES'
        if self.daily_losses>=3:
            return False,'MAX_DAILY_LOSSES'
        if self.daily_pnl<-(self.initial_capital*0.20):  # 20% daily limit
            return False,'DAILY_LOSS_20%'
        if self.weekly_pnl<-(self.initial_capital*0.30):  # 30% weekly limit
            return False,'WEEKLY_LOSS_30%'
        dd=(self.peak_capital-capital)/self.peak_capital*100
        if dd>30:  # 30% drawdown limit
            return False,f'DRAWDOWN_{dd:.1f}%'
        if signal_risk>capital*0.20:  # 20% per trade max
            return False,'SIGNAL_RISK_20%'
        if self.consecutive_losses>=2:
            return True,'REDUCE_SIZE'
        return True,'OK'

    def update_trade(self,pnl):
        self.daily_pnl+=pnl
        self.weekly_pnl+=pnl
        self.daily_trades+=1
        if pnl<0:
            self.daily_losses+=1
            self.consecutive_losses+=1
        else:
            self.consecutive_losses=0

    def get_adjusted_lots(self,base_lots):
        if self.consecutive_losses>=2:
            return max(1,base_lots//2)
        return base_lots

    def get_status(self):
        return {
            'daily_pnl':round(self.daily_pnl),
            'weekly_pnl':round(self.weekly_pnl),
            'daily_trades':self.daily_trades,
            'daily_losses':self.daily_losses,
            'consecutive_losses':self.consecutive_losses,
            'peak_capital':round(self.peak_capital),
        }
