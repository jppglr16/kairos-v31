"""
Indian Market Holiday Calendar 2026
NSE/BSE + MCX holidays
"""
from datetime import datetime,date

# NSE/BSE Holidays 2026
NSE_HOLIDAYS_2026=[
    date(2026,1,26),   # Republic Day
    date(2026,3,25),   # Holi
    date(2026,4,2),    # Ram Navami
    date(2026,4,10),   # Good Friday
    date(2026,4,14),   # Dr Ambedkar Jayanti
    date(2026,5,1),    # Maharashtra Day
    date(2026,6,17),   # Bakri Id
    date(2026,8,15),   # Independence Day
    date(2026,8,27),   # Ganesh Chaturthi
    date(2026,10,2),   # Gandhi Jayanti
    date(2026,10,20),  # Diwali Laxmi Pujan
    date(2026,10,21),  # Diwali Balipratipada
    date(2026,11,5),   # Prakash Gurpurb
    date(2026,12,25),  # Christmas
]

# MCX has same holidays as NSE mostly
MCX_HOLIDAYS_2026=NSE_HOLIDAYS_2026.copy()

def is_nse_holiday(check_date=None):
    """Check if NSE is closed today"""
    if check_date is None:
        check_date=datetime.now().date()
    # Weekend check
    if check_date.weekday()>=5:
        return True,f'Weekend ({check_date.strftime("%A")})'
    # Holiday check
    if check_date in NSE_HOLIDAYS_2026:
        return True,'NSE Holiday'
    return False,''

def is_mcx_holiday(check_date=None):
    """Check if MCX is closed today"""
    if check_date is None:
        check_date=datetime.now().date()
    if check_date.weekday()>=5:
        return True,f'Weekend'
    if check_date in MCX_HOLIDAYS_2026:
        return True,'MCX Holiday'
    return False,''

def get_next_trading_day(from_date=None):
    """Get next NSE trading day"""
    from datetime import timedelta
    if from_date is None:
        from_date=datetime.now().date()
    next_day=from_date+timedelta(days=1)
    while True:
        is_holiday,_=is_nse_holiday(next_day)
        if not is_holiday:
            return next_day
        next_day+=timedelta(days=1)

def market_status():
    """Get current market status"""
    now=datetime.now()
    today=now.date()

    nse_closed,nse_reason=is_nse_holiday(today)
    mcx_closed,mcx_reason=is_mcx_holiday(today)

    nse_open=not nse_closed and (9<=now.hour<15 or (now.hour==15 and now.minute<=30))
    mcx_open=not mcx_closed and (15<=now.hour<23 or (now.hour==23 and now.minute<30))

    return {
        'nse_open':nse_open,
        'mcx_open':mcx_open,
        'nse_holiday':nse_closed,
        'mcx_holiday':mcx_closed,
        'nse_reason':nse_reason,
        'mcx_reason':mcx_reason,
        'next_trading':get_next_trading_day()
    }

if __name__=='__main__':
    s=market_status()
    print(f'NSE Open: {s["nse_open"]}')
    print(f'MCX Open: {s["mcx_open"]}')
    print(f'Next trading day: {s["next_trading"]}')
    today=datetime.now().date()
    h,r=is_nse_holiday(today)
    print(f'Today holiday: {h} {r}')
