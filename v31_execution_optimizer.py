import numpy as np
import logging,os,pickle,json
from datetime import datetime
log=logging.getLogger(__name__)

class ExecutionOptimizer:
    """
    Smart Execution Layer:
    1. Smart Order Routing (best exchange/price)
    2. Limit vs Market decision
    3. Slippage prediction
    4. Optimal entry timing
    5. Order size optimization
    """

    def __init__(self,symbol,capital=50000):
        self.symbol=symbol
        self.capital=capital
        self.execution_history=[]
        self.slippage_model=None
        self._load_history()

    def _load_history(self):
        try:
            fname=f'ml_models/{self.symbol}_execution.json'
            if os.path.exists(fname):
                self.execution_history=json.load(open(fname))
        except:pass

    def _save_history(self):
        try:
            fname=f'ml_models/{self.symbol}_execution.json'
            json.dump(self.execution_history[-200:],open(fname,'w'))
        except:pass

    # ============================================================
    # 1. LIMIT VS MARKET DECISION
    # ============================================================
    def should_use_limit(self,df5,signal,atr):
        """
        Decide: Limit order or Market order?

        Market order:
        + Guaranteed fill
        - Pays spread + slippage
        
        Limit order:
        + Better price
        - Might not fill!
        
        Use MARKET when:
        → Strong breakout (fast move)
        → High momentum
        → Expiry day
        
        Use LIMIT when:
        → Ranging market
        → Near support/resistance
        → Low urgency signal
        """
        try:
            c=df5['close'].values
            v=df5['volume'].values
            regime=signal.get('regime','')
            score=signal.get('score',0)
            action=signal.get('action','BUY')

            # Calculate momentum
            momentum=abs(c[-1]-c[-5])/atr if atr>0 else 0

            # Volume spike
            avg_vol=np.mean(v[-20:]) if len(v)>=20 else np.mean(v)
            vol_ratio=v[-1]/avg_vol if avg_vol>0 else 1

            # Expiry check
            now=datetime.now()
            is_expiry=(3-now.weekday())%7==0

            # Decision logic
            use_market=False
            reason=''

            if momentum>1.5:
                use_market=True
                reason='HIGH_MOMENTUM'
            elif vol_ratio>2.0:
                use_market=True
                reason='VOLUME_SPIKE'
            elif is_expiry:
                use_market=True
                reason='EXPIRY_DAY'
            elif regime in ['TRENDING_UP_HV','TRENDING_DOWN_HV']:
                use_market=True
                reason='STRONG_TREND'
            elif score>=25:
                use_market=True
                reason='VERY_HIGH_SCORE'
            else:
                reason='USE_LIMIT_BETTER_PRICE'

            log.info(f'[EXEC] {self.symbol} order type: {"MARKET" if use_market else "LIMIT"} ({reason})')
            return use_market,reason
        except Exception as e:
            log.error(f'[EXEC] Limit/Market error: {e}')
            return True,'ERROR_USE_MARKET'

    # ============================================================
    # 2. SLIPPAGE PREDICTION
    # ============================================================
    def predict_slippage(self,df5,instrument,qty,atr):
        """
        Predict expected slippage before order
        Based on: volume, ATR, qty, time of day
        """
        try:
            v=df5['volume'].values
            c=df5['close'].values
            cur=float(c[-1])

            avg_vol=np.mean(v[-20:]) if len(v)>=20 else np.mean(v)
            vol_ratio=v[-1]/avg_vol if avg_vol>0 else 1

            now=datetime.now()
            hour=now.hour

            # Base slippage (0.1%)
            base_slip=cur*0.001

            # Adjust for volume
            if vol_ratio<0.5:base_slip*=3    # Low volume = more slippage
            elif vol_ratio>2.0:base_slip*=0.5  # High volume = less

            # Adjust for time of day
            if hour==9:base_slip*=2.0   # Opening = high slippage
            elif 10<=hour<=12:base_slip*=0.8  # Best time
            elif 12<=hour<=13:base_slip*=1.5  # Lunch = more slippage
            elif hour==14:base_slip*=1.2

            # Adjust for order size
            market_impact=qty*atr/(avg_vol+1)*0.1
            total_slip=base_slip+market_impact

            # Check against history
            if self.execution_history:
                hist_slip=[e.get('actual_slippage',0) for e in self.execution_history[-20:]]
                if hist_slip:
                    avg_hist=np.mean(hist_slip)
                    total_slip=(total_slip+avg_hist)/2

            log.info(f'[EXEC] {instrument} predicted slippage: Rs.{total_slip:.2f}')
            return round(total_slip,2)
        except Exception as e:
            log.error(f'[EXEC] Slippage error: {e}')
            return 1.0

    # ============================================================
    # 3. OPTIMAL ENTRY TIMING
    # ============================================================
    def get_optimal_entry(self,df5,signal,atr):
        """
        Find best entry price:
        Don't just enter at market!
        Wait for slight pullback if possible
        """
        try:
            c=df5['close'].values
            h=df5['high'].values
            l=df5['low'].values
            cur=float(c[-1])
            action=signal.get('action','BUY')
            regime=signal.get('regime','')

            # For market orders - just use current
            use_market,_=self.should_use_limit(df5,signal,atr)
            if use_market:
                return cur,'MARKET',0

            # Calculate limit price
            if action=='BUY':
                # Place limit slightly below current
                # Better fill, small risk of missing
                if regime in ['RANGING']:
                    offset=atr*0.2   # Bigger pullback in ranging
                else:
                    offset=atr*0.1   # Small pullback in trending

                limit_price=round(cur-offset,1)
                saving=cur-limit_price
            else:  # SELL
                if regime in ['RANGING']:
                    offset=atr*0.2
                else:
                    offset=atr*0.1
                limit_price=round(cur+offset,1)
                saving=limit_price-cur

            log.info(f'[EXEC] {self.symbol} limit entry: Rs.{limit_price} (save Rs.{saving:.1f})')
            return limit_price,'LIMIT',saving
        except Exception as e:
            log.error(f'[EXEC] Entry error: {e}')
            return 0,'MARKET',0

    # ============================================================
    # 4. ORDER SIZE OPTIMIZATION
    # ============================================================
    def get_optimal_size(self,signal,capital,base_qty,uncertainty):
        """
        Kelly Criterion + uncertainty adjustment:
        High confidence = normal size
        Low confidence = smaller size
        After losses = smaller size
        """
        try:
            ml_prob=signal.get('ml_prob',0.5)
            regime=signal.get('regime','')
            score=signal.get('score',0)

            # Base Kelly fraction
            win_prob=ml_prob
            loss_prob=1-ml_prob
            rr=signal.get('rr_ratio',2)

            # Kelly fraction
            kelly=(win_prob*rr-loss_prob)/rr
            kelly=max(0,min(kelly,0.25))  # Cap at 25%

            # Uncertainty adjustment
            unc=uncertainty.get('combined',{}).get('uncertainty',0.5)
            unc_multiplier=1-unc  # High uncertainty = smaller

            # Score adjustment
            if score>=25:score_mult=1.2
            elif score>=20:score_mult=1.0
            else:score_mult=0.8

            # Regime adjustment
            if regime in ['TRENDING_UP_HV','TRENDING_DOWN_HV']:
                regime_mult=1.2  # Bigger in strong trends
            elif regime=='VOLATILE':
                regime_mult=0.7  # Smaller in volatile
            else:
                regime_mult=1.0

            # Recent performance adjustment
            recent_perf=self._get_recent_performance()
            if recent_perf<0.4:  # Bad run
                perf_mult=0.7
            elif recent_perf>0.7:  # Good run
                perf_mult=1.1
            else:
                perf_mult=1.0

            # Capital-based max lots (max 10% risk)
            sl_pts=signal.get('sl_points',50)
            LOT_SIZE={'NIFTY':65,'BANKNIFTY':30,'SENSEX':20,'FINNIFTY':60,'MIDCPNIFTY':120,'CRUDEOIL':100,'GOLDM':10,'SILVERM':30,'NATURALGAS':1250,'LT':450,'NTPC':4500,'MARUTI':100,'BHARTIARTL':950,'SBIN':1500,'TATAMOTORS':1350,'RELIANCE':250,'HINDUNILVR':300,'TCS':150,'TATASTEEL':5500}
            inst=signal.get('instrument','NIFTY')
            qty_per_lot=LOT_SIZE.get(inst,75)
            risk_per_lot=sl_pts*qty_per_lot
            max_lots=max(1,int(self.capital*0.10/risk_per_lot)) if risk_per_lot>0 else 1
            # Final size
            optimal_lots=base_qty*kelly*unc_multiplier*score_mult*regime_mult*perf_mult
            optimal_lots=min(max(1,round(optimal_lots)),max_lots)

            log.info(f'[EXEC] {self.symbol} optimal size: {optimal_lots} '
                    f'(kelly={kelly:.2f} unc={unc_multiplier:.2f})')
            return optimal_lots
        except Exception as e:
            log.error(f'[EXEC] Size error: {e}')
            return base_qty

    def _get_recent_performance(self):
        try:
            recent=self.execution_history[-20:]
            if not recent:return 0.5
            wins=sum(1 for e in recent if e.get('outcome')==1)
            return wins/len(recent)
        except:return 0.5

    # ============================================================
    # 5. SMART ORDER ROUTING
    # ============================================================
    def get_smart_route(self,instrument,action):
        """
        Choose best route:
        NSE vs BSE for indices
        MCX for commodities
        NFO for options
        """
        try:
            MCX_INST=['CRUDEOIL','GOLDM','SILVERM','NATURALGAS']
            BSE_INST=['SENSEX']

            if instrument in MCX_INST:
                exchange='MCX'
                product='INTRADAY'
            elif instrument in BSE_INST:
                exchange='BFO'
                product='INTRADAY'
            else:
                exchange='NFO'
                product='INTRADAY'

            # Time-based routing
            now=datetime.now()
            if now.hour>=15 and instrument not in MCX_INST:
                product='CARRYFORWARD'  # After hours

            route={
                'exchange':exchange,
                'product':product,
                'order_type':'MARKET',
                'duration':'DAY'
            }
            log.info(f'[EXEC] {instrument} route: {route}')
            return route
        except Exception as e:
            log.error(f'[EXEC] Route error: {e}')
            return {'exchange':'NFO','product':'INTRADAY',
                   'order_type':'MARKET','duration':'DAY'}

    # ============================================================
    # MAIN FUNCTION
    # ============================================================
    def optimize(self,df5,signal,atr,base_qty,uncertainty={}):
        """
        Complete execution optimization
        Returns optimized order params
        """
        try:
            instrument=signal.get('instrument','')
            action=signal.get('action','BUY')
            cur=float(df5['close'].iloc[-1])

            # 1. Order type decision
            use_market,order_reason=self.should_use_limit(df5,signal,atr)

            # 2. Slippage prediction
            predicted_slip=self.predict_slippage(df5,instrument,base_qty,atr)

            # 3. Optimal entry
            entry_price,order_type,saving=self.get_optimal_entry(df5,signal,atr)
            if use_market:
                order_type='MARKET'
                entry_price=cur

            # 4. Order size
            opt_qty=self.get_optimal_size(signal,self.capital,base_qty,uncertainty)

            # 5. Smart routing
            route=self.get_smart_route(instrument,action)
            route['order_type']=order_type

            result={
                'order_type':order_type,
                'entry_price':round(entry_price,2),
                'optimal_qty':opt_qty,
                'predicted_slippage':predicted_slip,
                'saving':round(saving,2),
                'route':route,
                'reason':order_reason
            }

            log.info(f'[EXEC] {instrument} optimized: {result}')
            return result
        except Exception as e:
            log.error(f'[EXEC] Optimize error: {e}')
            return {
                'order_type':'MARKET',
                'entry_price':0,
                'optimal_qty':base_qty,
                'predicted_slippage':1.0,
                'saving':0,
                'route':{'exchange':'NFO','product':'INTRADAY',
                        'order_type':'MARKET','duration':'DAY'},
                'reason':'ERROR'
            }

    def record_execution(self,signal,planned_price,actual_price,qty,outcome):
        """Record execution for learning"""
        try:
            actual_slip=abs(actual_price-planned_price)
            entry={
                'instrument':signal.get('instrument',''),
                'planned':planned_price,
                'actual':actual_price,
                'actual_slippage':actual_slip,
                'qty':qty,
                'outcome':outcome,
                'time':str(datetime.now())
            }
            self.execution_history.append(entry)
            self._save_history()
        except:pass


# Global instances
_exec_optimizers={}

def get_exec_optimizer(symbol,capital=50000):
    if symbol not in _exec_optimizers:
        _exec_optimizers[symbol]=ExecutionOptimizer(symbol,capital)
    return _exec_optimizers[symbol]

def optimize_execution(symbol,df5,signal,atr,base_qty,uncertainty={},capital=50000):
    """Main function"""
    opt=get_exec_optimizer(symbol,capital)
    return opt.optimize(df5,signal,atr,base_qty,uncertainty)
