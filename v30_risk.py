def get_lot_size(instrument):
    return {'NIFTY':25,'BANKNIFTY':15,'CRUDEOIL':100}.get(instrument,25)
def get_risk_amount(capital):
    if capital<15000:return capital*0.05
    if capital<50000:return 2500
    elif capital<200000:return capital*0.05
    else:return capital*0.03
def get_lots_to_trade(capital,instrument,sl_points):
    risk=get_risk_amount(capital)
    lot=get_lot_size(instrument)
    if sl_points<=0:return 1
    return max(1,int(risk/(sl_points*lot)))
class DailyRiskManager:
    def __init__(self,capital,max_losses=3):
        self.capital=capital
        self.max_losses=max_losses
        self.losses=0
        self.wins=0
        self.pnl=0
        self.stopped=False
    def can_trade(self):return not self.stopped
    def record_trade(self,pnl,instrument='',signal=''):
        self.pnl+=pnl
        if pnl<0:
            self.losses+=1
            if self.losses>=self.max_losses:
                self.stopped=True
                print(f'[RISK] 3 losses hit. Stopped for today.')
        else:self.wins+=1
        print(f'[RISK] PnL:{self.pnl:.0f} W:{self.wins} L:{self.losses}')
    def reset_daily(self):
        self.losses=0;self.wins=0;self.pnl=0;self.stopped=False
        print('[RISK] Daily reset done.')
