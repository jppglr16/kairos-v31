import logging
log=logging.getLogger(__name__)

class PartialExitManager:
    def __init__(self):
        self.trade_status={}

    def init_trade(self,instrument,entry,sl,t1,t2,qty,action):
        self.trade_status[instrument]={
            'entry':entry,
            'sl':sl,
            't1':t1,
            't2':t2,
            'original_qty':qty,
            'remaining_qty':qty,
            'action':action,
            't1_done':False,
            't2_done':False,
            'sl_moved':False,
            'locked_profit':0
        }

    def check_exit(self,instrument,current_price,client,trade):
        if instrument not in self.trade_status:return None
        status=self.trade_status[instrument]
        entry=status['entry']
        action=status['action']
        qty=status['remaining_qty']
        sl=status['sl']
        t1=status['t1']
        t2=status['t2']
        result=[]

        if action=='BUY':
            profit_pts=current_price-entry

            # T1 hit → Exit 30%, move SL to breakeven
            if not status['t1_done'] and profit_pts>=t1:
                exit_qty=max(1,int(status['original_qty']*0.30))
                pnl=t1*exit_qty
                status['t1_done']=True
                status['remaining_qty']-=exit_qty
                status['sl_moved']=True
                status['sl']=0  # Move SL to breakeven
                status['locked_profit']+=pnl
                log.info(f'[PARTIAL] {instrument} T1 hit! Exit {exit_qty} qty PnL:₹{pnl:.0f}')
                result.append({'action':'PARTIAL_T1','qty':exit_qty,'pnl':pnl})

            # T2 hit → Exit another 30%
            elif status['t1_done'] and not status['t2_done'] and profit_pts>=t2:
                exit_qty=max(1,int(status['original_qty']*0.30))
                pnl=t2*exit_qty
                status['t2_done']=True
                status['remaining_qty']-=exit_qty
                status['locked_profit']+=pnl
                log.info(f'[PARTIAL] {instrument} T2 hit! Exit {exit_qty} qty PnL:₹{pnl:.0f}')
                result.append({'action':'PARTIAL_T2','qty':exit_qty,'pnl':pnl})

            # T3 → Trail remaining 40%
            elif status['t2_done']:
                # Trail SL at 50% of current profit
                trail_sl=entry+(profit_pts*0.5)
                if current_price<=trail_sl:
                    exit_qty=status['remaining_qty']
                    pnl=profit_pts*0.5*exit_qty
                    status['locked_profit']+=pnl
                    log.info(f'[PARTIAL] {instrument} T3 Trail exit! PnL:₹{pnl:.0f}')
                    result.append({'action':'TRAIL_EXIT','qty':exit_qty,'pnl':pnl})
                    del self.trade_status[instrument]

            # SL hit
            if current_price<=entry-sl and not status['sl_moved']:
                exit_qty=status['remaining_qty']
                pnl=-sl*exit_qty
                log.info(f'[PARTIAL] {instrument} SL hit! Loss:₹{pnl:.0f}')
                result.append({'action':'SL_HIT','qty':exit_qty,'pnl':pnl})
                del self.trade_status[instrument]

        else:  # SELL
            profit_pts=entry-current_price

            if not status['t1_done'] and profit_pts>=t1:
                exit_qty=max(1,int(status['original_qty']*0.30))
                pnl=t1*exit_qty
                status['t1_done']=True
                status['remaining_qty']-=exit_qty
                status['sl']=0
                status['locked_profit']+=pnl
                result.append({'action':'PARTIAL_T1','qty':exit_qty,'pnl':pnl})

            elif status['t1_done'] and not status['t2_done'] and profit_pts>=t2:
                exit_qty=max(1,int(status['original_qty']*0.30))
                pnl=t2*exit_qty
                status['t2_done']=True
                status['remaining_qty']-=exit_qty
                status['locked_profit']+=pnl
                result.append({'action':'PARTIAL_T2','qty':exit_qty,'pnl':pnl})

            elif status['t2_done']:
                trail_sl=entry-(profit_pts*0.5)
                if current_price>=trail_sl:
                    exit_qty=status['remaining_qty']
                    pnl=profit_pts*0.5*exit_qty
                    result.append({'action':'TRAIL_EXIT','qty':exit_qty,'pnl':pnl})
                    del self.trade_status[instrument]

        return result if result else None

    def get_remaining_qty(self,instrument):
        if instrument in self.trade_status:
            return self.trade_status[instrument]['remaining_qty']
        return 0

    def clear(self,instrument):
        if instrument in self.trade_status:
            del self.trade_status[instrument]

partial_exit_mgr=PartialExitManager()
