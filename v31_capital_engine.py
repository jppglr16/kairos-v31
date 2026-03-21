"""
V31 Capital Allocation Engine
Allocates capital based on instrument performance
Best performers get more lots!
"""
import json,os,logging,pickle,glob
from datetime import datetime,timedelta
log=logging.getLogger(__name__)

PERF_FILE='instrument_performance.json'

class CapitalEngine:
    def __init__(self):
        self.perf={}  # {instrument: {wins,losses,pnl,trades}}
        self.load()

    def load(self):
        try:
            if os.path.exists(PERF_FILE):
                self.perf=json.load(open(PERF_FILE))
        except:self.perf={}

    def save(self):
        try:
            json.dump(self.perf,open(PERF_FILE,'w'),indent=2)
        except:pass

    def update(self,instrument,pnl,won):
        """Update instrument performance after trade"""
        if instrument not in self.perf:
            self.perf[instrument]={
                'wins':0,'losses':0,
                'total_pnl':0,'trades':0,
                'last_updated':''
            }
        p=self.perf[instrument]
        p['trades']+=1
        p['total_pnl']+=pnl
        if won:p['wins']+=1
        else:p['losses']+=1
        p['last_updated']=datetime.now().isoformat()
        self.save()
        log.info(f'[CAP] {instrument} updated: WR={self.win_rate(instrument):.0%} PnL=Rs.{p["total_pnl"]:,.0f}')

    def win_rate(self,instrument):
        """Get win rate for instrument"""
        p=self.perf.get(instrument,{})
        total=p.get('wins',0)+p.get('losses',0)
        if total<5:return 0.5  # Default if not enough data
        return p['wins']/total

    def risk_score(self,instrument):
        """
        Risk-adjusted score:
        score = 0.4*win_rate + 0.3*profit_factor + 0.3*consistency
        """
        p=self.perf.get(instrument,{})
        trades=p.get('trades',0)
        if trades<5:return 0.5  # Default

        wr=self.win_rate(instrument)
        wins=p.get('wins',0)
        losses=p.get('losses',1)

        # Profit factor = total wins / total losses
        pf=min(wins/max(losses,1),3.0)/3.0  # Normalize 0-1

        # Consistency = trades with good score
        consistency=min(trades/20,1.0)  # More trades = more consistent

        score=(0.4*wr)+(0.3*pf)+(0.3*consistency)
        return score

    def get_lots(self,instrument,base_lots=1,score=20,capital=50000):
        """
        Smart lot allocation - 5 factor system:
        1. Win rate
        2. PnL profitability
        3. Drawdown protection
        4. Sample size scaling
        5. Time decay
        """
        p=self.perf.get(instrument,{})
        trades=p.get('trades',0)
        total_pnl=p.get('total_pnl',0)

        # Fix 3: Scale by sample size
        if trades<10:
            scale=trades/10 if trades>0 else 0
            scaled=max(1,int(base_lots*scale)) if trades>=5 else base_lots
            log.debug(f'[CAP] {instrument}: {trades} trades, scale={scale:.1f}, lots={scaled}')
            return scaled

        wr=self.win_rate(instrument)
        avg_pnl=total_pnl/max(trades,1)

        # Fix 2: Drawdown protection
        if total_pnl<-2000:
            log.info(f'[CAP] {instrument} DRAWDOWN PROTECTION! PnL=Rs.{total_pnl:,.0f} → SKIP!')
            return 0

        # Fix 5: Time decay
        try:
            last=p.get('last_updated','')
            if last:
                from datetime import datetime
                age=(datetime.now()-datetime.fromisoformat(last)).days
                if age>7:
                    log.info(f'[CAP] {instrument} stale data ({age}d) → reduce confidence')
                    wr=wr*0.8  # Reduce effective WR by 20%
        except:pass

        # Fix 1: Combine WR + PnL
        if wr>=0.65 and avg_pnl>0:
            lots=min(base_lots*2,2)
            log.info(f'[CAP] {instrument} HIGH: WR={wr:.0%} avg=Rs.{avg_pnl:.0f} → {lots} lots')
        elif wr>=0.55 and avg_pnl>0:
            lots=base_lots
            log.info(f'[CAP] {instrument} GOOD: WR={wr:.0%} avg=Rs.{avg_pnl:.0f} → {lots} lots')
        elif wr>=0.45:
            lots=max(base_lots-1,1)
            log.info(f'[CAP] {instrument} AVG: WR={wr:.0%} → {lots} lots')
        else:
            lots=0
            log.info(f'[CAP] {instrument} POOR: WR={wr:.0%} → SKIP!')

        return lots

    def get_ranking(self):
        """Get instrument ranking by performance"""
        ranked=[]
        for inst,p in self.perf.items():
            if p.get('trades',0)>=5:
                ranked.append({
                    'instrument':inst,
                    'win_rate':self.win_rate(inst),
                    'risk_score':self.risk_score(inst),
                    'total_pnl':p.get('total_pnl',0),
                    'trades':p.get('trades',0),
                })
        ranked.sort(key=lambda x:-x['risk_score'])
        return ranked

    def send_weekly_ranking(self):
        """Send instrument ranking to Telegram"""
        try:
            from v31_notify import send
            ranking=self.get_ranking()
            if not ranking:
                send('📊 No instrument ranking yet\nNeed 5+ trades per instrument')
                return
            msg='📊 Instrument Rankings\n━━━━━━━━━━━━━━━\n'
            for i,r in enumerate(ranking[:10],1):
                e='🏆' if i<=3 else '📈' if r['win_rate']>=0.55 else '📉'
                msg+=f'{e} {i}. {r["instrument"]}: WR={r["win_rate"]:.0%} PnL=Rs.{r["total_pnl"]:,.0f}\n'
            send(msg)
        except Exception as e:
            log.error(f'[CAP] Ranking error: {e}')

# Global instance
capital_engine=CapitalEngine()
