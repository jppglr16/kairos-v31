"""
V31 Affordability Engine
Centralized capital + lot size management
Production-grade trade cost validation
"""
import logging
log=logging.getLogger(__name__)

# Per trade capital limit
MAX_TRADE_CAPITAL=20000  # Rs.20,000 max per trade

# Safety buffer for volatility
BUFFER=1.10  # 10% buffer

def get_lot_size(instrument):
    """Get F&O lot size from instrument manager"""
    try:
        from v31_instrument_manager import INSTRUMENTS
        return int(INSTRUMENTS.get(instrument,{}).get('lot',0))
    except:
        return 0

def calculate_trade_cost(instrument,premium,buffer=True):
    """Calculate total cost for 1 lot"""
    lot=get_lot_size(instrument)
    if lot==0:
        log.warning(f'[AFF] {instrument}: lot size missing!')
        return 0
    cost=lot*premium
    if buffer:cost*=BUFFER
    return round(cost)

def is_affordable(instrument,premium,capital=50000):
    """
    Check if trade is affordable
    Returns: (allowed, cost, reason)
    """
    lot=get_lot_size(instrument)
    if lot==0:
        return False,0,f'Lot size unknown for {instrument}'

    if premium<=0:
        return False,0,'Invalid premium'

    cost=calculate_trade_cost(instrument,premium)
    max_allowed=min(MAX_TRADE_CAPITAL,capital*0.40)

    if cost>max_allowed:
        return False,cost,f'Cost Rs.{cost:,} > limit Rs.{max_allowed:,.0f}'

    return True,cost,f'Affordable Rs.{cost:,}'

def rank_signals(signals,capital=50000):
    """
    Rank signals by capital efficiency
    Returns sorted list: most efficient first
    """
    ranked=[]
    for s in signals:
        inst=s.get('instrument','')
        prem=s.get('real_prem',s.get('premium',20))
        score=s.get('score',0)

        allowed,cost,reason=is_affordable(inst,prem,capital)
        if not allowed:
            log.info(f'[AFF] {inst} FILTERED: {reason}')
            continue

        # Efficiency = score per rupee invested
        efficiency=score/(cost+1)*1000
        ranked.append((efficiency,s,cost))
        log.info(f'[AFF] {inst} score={score} cost=Rs.{cost:,} eff={efficiency:.2f}')

    ranked.sort(reverse=True,key=lambda x:x[0])
    return [(s,cost) for _,s,cost in ranked]

def get_affordable_instruments(capital=50000):
    """Get list of affordable instruments at current capital"""
    try:
        from v31_instrument_manager import INSTRUMENTS
        affordable=[]
        # Real typical premiums per instrument
        TYPICAL_PREMIUMS={
            'NIFTY':100,'BANKNIFTY':200,'SENSEX':150,
            'FINNIFTY':450,'MIDCPNIFTY':50,  # FINNIFTY premium ~Rs.450!
            'CRUDEOIL':150,'NATURALGAS':20,'GOLDM':200,'SILVERM':100,
            'SBIN':20,'TATASTEEL':5,'NTPC':3,'TATAMOTORS':8,
            'BHARTIARTL':25,'RELIANCE':15,'LT':25,'HINDUNILVR':30,
            'TCS':60,'MARUTI':200,'HDFCBANK':15,'ICICIBANK':20,
            'BAJFINANCE':100,'ICICIBANK':20,'RELIANCE':15,
        }
        for inst,cfg in INSTRUMENTS.items():
            lot=int(cfg.get('lot',0))
            typ_prem=TYPICAL_PREMIUMS.get(inst,50)
            cost=lot*typ_prem*BUFFER
            if cost<=capital*0.40:
                affordable.append(inst)
        return affordable
    except:
        return []

def print_affordability_report(capital=50000):
    """Print affordability report for all instruments"""
    try:
        from v31_instrument_manager import INSTRUMENTS
        print(f'\n=== Affordability Report (Capital: Rs.{capital:,}) ===')
        print(f'Max per trade: Rs.{min(MAX_TRADE_CAPITAL,capital*0.40):,.0f}')
        print()

        affordable=[]
        expensive=[]

        TYPICAL_PREMIUMS={
            'NIFTY':100,'BANKNIFTY':200,'SENSEX':150,
            'FINNIFTY':450,'MIDCPNIFTY':50,  # FINNIFTY premium ~Rs.450!
            'CRUDEOIL':150,'NATURALGAS':20,'GOLDM':200,'SILVERM':100,
            'SBIN':20,'TATASTEEL':5,'NTPC':3,'TATAMOTORS':8,
            'BHARTIARTL':25,'RELIANCE':15,'LT':25,'HINDUNILVR':30,
            'TCS':60,'MARUTI':200,'HDFCBANK':15,'ICICIBANK':20,
            'BAJFINANCE':100,'BAJFINANCE':20,'NATURALGAS':20,
        }
        for inst,cfg in sorted(INSTRUMENTS.items()):
            lot=int(cfg.get('lot',0))
            typ_prem=TYPICAL_PREMIUMS.get(inst,30)
            cost=lot*typ_prem
            allowed=cost<=min(MAX_TRADE_CAPITAL,capital*0.40)
            if allowed:
                affordable.append((inst,lot,cost))
            else:
                expensive.append((inst,lot,cost))

        print(f'✅ Affordable ({len(affordable)}):')
        for inst,lot,cost in affordable:
            print(f'   {inst:<15} lot={lot:<6} est=Rs.{cost:,}')

        print(f'\n❌ Too Expensive ({len(expensive)}):')
        for inst,lot,cost in expensive:
            print(f'   {inst:<15} lot={lot:<6} est=Rs.{cost:,}')

    except Exception as e:
        print(f'Error: {e}')

if __name__=='__main__':
    print_affordability_report(50000)
