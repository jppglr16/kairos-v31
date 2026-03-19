# Realistic margin requirements
SELL_MARGIN={
    'SENSEX':   144375,
    'NIFTY':    162422,
    'BANKNIFTY':138600,
    'FINNIFTY': 140766,
    'MIDCPNIFTY':138600,
}

def can_sell(capital,instrument):
    """Check if capital enough for selling"""
    margin=SELL_MARGIN.get(instrument,150000)
    return capital>=margin

def get_sell_instruments(capital):
    """Get list of instruments we can sell"""
    return [inst for inst,margin in SELL_MARGIN.items()
            if capital>=margin]

def get_lots(capital):
    """Buying lots based on capital"""
    if capital>=100000:return 3
    elif capital>=75000:return 2
    else:return 1

def get_strategy(capital):
    """
    Capital-based strategy:
    < Rs.1,50,000 = Buy only
    >= Rs.1,50,000 = Buy + Sell
    """
    if capital<150000:
        return 'BUY_ONLY',[]
    else:
        return 'BUY_AND_SELL',get_sell_instruments(capital)

if __name__=='__main__':
    print('Strategy by capital:')
    for cap in [50000,75000,100000,150000,200000,300000]:
        strategy,insts=get_strategy(cap)
        print(f'  Rs.{cap:>8,.0f}: {strategy} {insts}')
