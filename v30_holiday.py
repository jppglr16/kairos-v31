import requests
from datetime import date,datetime
from v30_cache import cache

NSE_HOLIDAY_WISHES = {
    date(2026,3,25): "🎨 Happy Holi!",
    date(2026,4,2):  "🙏 Happy Ram Navami!",
    date(2026,4,14): "🙏 Happy Dr. Ambedkar Jayanti!",
    date(2026,4,17): "✝️ Good Friday!",
    date(2026,5,1):  "👷 Happy Maharashtra Day!",
    date(2026,8,15): "🇮🇳 Happy Independence Day!",
    date(2026,10,2): "🙏 Happy Gandhi Jayanti!",
    date(2026,10,22):"🎊 Happy Dussehra!",
    date(2026,11,11):"🪔 Happy Diwali!",
    date(2026,11,12):"🪔 Happy Diwali Balipratipada!",
    date(2026,11,25):"🙏 Happy Guru Nanak Jayanti!",
    date(2026,12,25):"🎄 Merry Christmas!",
}

WEEKEND_WISHES = {
    5: "🌴 Happy Saturday! Enjoy your weekend!",
    6: "☀️ Happy Sunday! Rest well!",
}

def get_nse_holidays():
    cached=cache.get('nse_holidays')
    if cached:return cached
    try:
        headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.nseindia.com'}
        s=requests.Session()
        s.get('https://www.nseindia.com',headers=headers,timeout=10)
        r=s.get('https://www.nseindia.com/api/holiday-master?type=trading',headers=headers,timeout=10)
        data=r.json()
        holidays=[]
        for item in data.get('CM',[]):
            try:
                d=datetime.strptime(item['tradingDate'],'%d-%b-%Y').date()
                holidays.append(d)
            except:pass
        print(f'[HOLIDAY] Loaded {len(holidays)} NSE holidays')
        cache.set('nse_holidays',holidays,86400)
        return holidays
    except Exception as e:
        print(f'[HOLIDAY] Error: {e}')
        return list(NSE_HOLIDAY_WISHES.keys())

def get_holiday_name():
    today=date.today()
    try:
        headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.nseindia.com'}
        s=requests.Session()
        s.get('https://www.nseindia.com',headers=headers,timeout=10)
        r=s.get('https://www.nseindia.com/api/holiday-master?type=trading',headers=headers,timeout=10)
        data=r.json()
        for item in data.get('CM',[]):
            try:
                d=datetime.strptime(item['tradingDate'],'%d-%b-%Y').date()
                if d==today:
                    return item.get('description','Holiday')
            except:pass
    except:pass
    return None

def get_closed_message():
    today=date.today()
    weekday=today.weekday()
    # Weekend
    if weekday>=5:
        wish=WEEKEND_WISHES.get(weekday,"🌴 Enjoy your weekend!")
        day="Saturday" if weekday==5 else "Sunday"
        return f"""{wish}
━━━━━━━━━━━━━━━
📅 Today is {day}
🏦 NSE/BSE Markets Closed
⏰ V30 resumes Monday 9:15 AM
💪 See you Monday! 🚀"""
    # Holiday
    holiday_name=get_holiday_name()
    wish=NSE_HOLIDAY_WISHES.get(today,"🎉 Happy Holiday!")
    if not holiday_name:
        holiday_name="Market Holiday"
    return f"""{wish}
━━━━━━━━━━━━━━━
📅 Today: {holiday_name}
🏦 NSE/BSE Markets Closed
⏰ V30 resumes tomorrow 9:15 AM
🎊 Enjoy the holiday! 🚀"""

def is_market_open():
    today=date.today()
    if today.weekday()>=5:
        return False,f'WEEKEND_{today.strftime("%A")}'
    holidays=get_nse_holidays()
    if today in holidays:
        name=get_holiday_name() or 'HOLIDAY'
        return False,f'HOLIDAY_{name}'
    return True,'MARKET_OPEN'

def is_trading_time(instrument):
    now=datetime.now()
    h,m=now.hour,now.minute
    if instrument in ['NIFTY','BANKNIFTY','FINNIFTY','MIDCPNIFTY','SENSEX']:
        return (h==9 and m>=15) or (10<=h<=14) or (h==15 and m<=30)
    elif instrument in ['CRUDEOIL','GOLDM','SILVERM']:
        return (h==9) or (10<=h<=11) or (h==15 and m>=30) or h>=16
    return False
