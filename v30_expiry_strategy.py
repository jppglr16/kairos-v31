import logging
from datetime import datetime,date,timedelta
log=logging.getLogger(__name__)

def get_expiry_info(instrument):
    today=datetime.now()
    weekday=today.weekday()
    
    if instrument in ['NIFTY','BANKNIFTY','FINNIFTY','MIDCPNIFTY','SENSEX']:
        # Weekly expiry Thursday
        days_to_thu=(3-weekday)%7
        if days_to_thu==0:days_to_thu=7
        expiry=today+timedelta(days=days_to_thu)
        days_left=days_to_thu
        return {'type':'WEEKLY','expiry':expiry,'days_left':days_left}
    else:
        # Monthly expiry last Thursday
        import calendar
        m=today.month;y=today.year
        last_day=calendar.monthrange(y,m)[1]
        last_thu=max(d for d in range(1,last_day+1)
                    if datetime(y,m,d).weekday()==3)
        expiry=datetime(y,m,last_thu)
        if today.date()>=expiry.date():
            if m==12:m=1;y+=1
            else:m+=1
            last_day=calendar.monthrange(y,m)[1]
            last_thu=max(d for d in range(1,last_day+1)
                        if datetime(y,m,d).weekday()==3)
            expiry=datetime(y,m,last_thu)
        days_left=(expiry.date()-today.date()).days
        return {'type':'MONTHLY','expiry':expiry,'days_left':days_left}

def is_expiry_day(instrument):
    info=get_expiry_info(instrument)
    return info['days_left']==0 or (
        info['days_left']==7 and 
        datetime.now().weekday()==3
    )

def get_expiry_action(instrument,df5,current_price,capital):
    try:
        now=datetime.now()
        info=get_expiry_info(instrument)
        days_left=info['days_left']
        hour=now.hour;minute=now.minute

        # Only for index options
        if instrument not in ['NIFTY','BANKNIFTY','FINNIFTY','MIDCPNIFTY','SENSEX']:
            return None

        # Expiry day selling strategy
        if days_left<=1:
            # After 1 PM on expiry → Sell OTM options
            if hour>=13:
                atr=(df5['high']-df5['low']).tail(14).mean()
                
                # Sell OTM CE (above current price)
                ce_strike=round((current_price+atr*2)/50)*50
                # Sell OTM PE (below current price)
                pe_strike=round((current_price-atr*2)/50)*50
                
                log.info(f'[EXPIRY] {instrument} Expiry sell opportunity!')
                log.info(f'[EXPIRY] Sell CE: {ce_strike} | Sell PE: {pe_strike}')
                
                return {
                    'strategy':'EXPIRY_SELL',
                    'instrument':instrument,
                    'ce_strike':ce_strike,
                    'pe_strike':pe_strike,
                    'current_price':current_price,
                    'days_left':days_left,
                    'action':'SELL_STRANGLE',
                    'reason':'Expiry day OTM sell'
                }

        # 2 days before expiry → Sell spreads
        elif days_left==2 and hour>=14:
            atr=(df5['high']-df5['low']).tail(14).mean()
            ce_strike=round((current_price+atr*1.5)/50)*50
            return {
                'strategy':'PRE_EXPIRY_SELL',
                'instrument':instrument,
                'ce_strike':ce_strike,
                'current_price':current_price,
                'days_left':days_left,
                'action':'SELL_CE',
                'reason':'Pre-expiry sell'
            }

        return None
    except Exception as e:
        log.error(f'[EXPIRY] Error: {e}')
        return None

def place_expiry_trade(client,instrument,action,strike,option_type,qty):
    try:
        seg='nse_fo' if instrument!='CRUDEOIL' else 'mcx_fo'
        symbol=f'{instrument}{strike}{option_type}'
        order=client.place_order(
            exchange_segment=seg,
            product='NRML',
            price='0',
            order_type='MKT',
            quantity=str(qty),
            validity='DAY',
            trading_symbol=symbol,
            transaction_type='S',  # SELL
            amo='NO',
            disclosed_quantity='0',
            market_protection='0',
            pf='N',
            trigger_price='0',
            tag='V30-EXPIRY'
        )
        log.info(f'[EXPIRY] Order placed: {symbol} SELL {qty}')
        return order
    except Exception as e:
        log.error(f'[EXPIRY] Order error: {e}')
        return None
