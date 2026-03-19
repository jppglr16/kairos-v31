def get_lots_kelly(instrument, capital, ml_prob=0.5, rr=2.0, premium=50, sl_pct=0.40):
    """Kelly criterion based lot sizing"""
    LOT_SIZE={'NIFTY':65,'BANKNIFTY':30,'SENSEX':20,'FINNIFTY':60,
              'MIDCPNIFTY':120,'CRUDEOIL':100,'GOLDM':10,'SILVERM':30,
              'NATURALGAS':1250,'LT':450,'NTPC':4500,'MARUTI':100,
              'BHARTIARTL':950,'SBIN':1500,'TATAMOTORS':1350,
              'RELIANCE':250,'HINDUNILVR':300,'TCS':150,'TATASTEEL':5500}

    lot_size=LOT_SIZE.get(instrument,75)

    # Kelly fraction
    p=max(0.35,min(0.75,ml_prob))
    q=1-p
    kelly=(p*rr-q)/rr
    kelly=max(0.05,min(0.25,kelly))  # Cap 5-25%

    # Max risk capital
    max_risk=capital*kelly
    # Risk per lot = SL amount
    sl_per_lot=premium*sl_pct*lot_size
    if sl_per_lot<=0:return 1

    # Kelly lots
    kelly_lots=int(max_risk/sl_per_lot)

    # Hard cap: max 50% capital in one trade
    max_cost_lots=int(capital*0.40/(premium*lot_size)) if premium*lot_size>0 else 1

    lots=min(kelly_lots,max_cost_lots)
    return max(1,lots)


def get_lots(instrument, capital):
    INDEX = ['NIFTY','BANKNIFTY','FINNIFTY','MIDCPNIFTY','SENSEX']
    COMMODITY = ['CRUDEOIL','GOLDM','SILVERM']

    if instrument in INDEX or instrument in COMMODITY:
        if capital < 3000:
            return 1
        elif capital <= 50000:
            return 2
        else:
            # Every 25k above 50k = +1 lot
            # 50001-75000 = 3 lots
            # 75001-100000 = 4 lots
            # 100001-125000 = 5 lots
            # 125001-150000 = 6 lots
            # 225001-250000 = 9 lots
            # No upper limit!
            extra = int((capital - 50001) / 25000) + 1
            return 2 + extra
    else:
        # Stocks always 1 lot
        return 1
