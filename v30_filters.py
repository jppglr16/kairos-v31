import requests,json
from datetime import datetime,date
from bs4 import BeautifulSoup

HEADERS = {'User-Agent':'Mozilla/5.0','Accept':'application/json','Referer':'https://www.nseindia.com'}

def get_nse_session():
    s=requests.Session()
    s.get('https://www.nseindia.com',headers=HEADERS,timeout=10)
    return s

def get_india_vix():
    try:
        s=get_nse_session()
        r=s.get('https://www.nseindia.com/api/allIndices',headers=HEADERS,timeout=10)
        data=r.json()
        for idx in data.get('data',[]):
            if idx.get('index')=='INDIA VIX':
                vix=float(idx.get('last',0))
                print(f'[VIX] India VIX: {vix}')
                return vix
        return 15.0
    except Exception as e:
        print(f'[VIX] Error: {e}')
        return 15.0

def get_vix_filter():
    vix=get_india_vix()
    if vix>20:
        return False,'HIGH_VIX'
    elif vix<10:
        return False,'LOW_VIX'
    return True,f'VIX_OK_{vix}'

def get_expiry_dates():
    now=datetime.now()
    # Weekly expiry - Thursday for NIFTY/BANKNIFTY
    days_to_thu=(3-now.weekday())%7
    if days_to_thu==0 and now.hour>=15:days_to_thu=7
    weekly=date(now.year,now.month,now.day)
    from datetime import timedelta
    weekly=now.date()+timedelta(days=days_to_thu)
    return weekly

def is_expiry_day(instrument):
    today=date.today()
    expiry=get_expiry_dates()
    return today==expiry

def get_expiry_filter(instrument,action):
    today=date.today()
    expiry=get_expiry_dates()
    days_to_expiry=(expiry-today).days
    now=datetime.now()

    # On expiry day
    if days_to_expiry==0:
        # After 1PM on expiry - very risky to buy options
        if now.hour>=13:
            return False,'EXPIRY_AFTERNOON'
        # Morning expiry - only high confidence trades
        return True,'EXPIRY_MORNING'

    # Day before expiry - theta decay high
    if days_to_expiry==1 and now.hour>=14:
        return False,'PRE_EXPIRY_EOD'

    return True,f'DAYS_TO_EXPIRY_{days_to_expiry}'

def get_prev_day_levels():
    try:
        s=get_nse_session()
        r=s.get('https://www.nseindia.com/api/allIndices',headers=HEADERS,timeout=10)
        data=r.json()
        levels={}
        for idx in data.get('data',[]):
            name=idx.get('index','')
            if name in ['NIFTY 50','NIFTY BANK']:
                key='NIFTY' if name=='NIFTY 50' else 'BANKNIFTY'
                levels[key]={
                    'prev_high':float(idx.get('previousClose',0))*1.003,
                    'prev_low':float(idx.get('previousClose',0))*0.997,
                    'prev_close':float(idx.get('previousClose',0)),
                    'current':float(idx.get('last',0))
                }
        return levels
    except Exception as e:
        print(f'[LEVELS] Error: {e}')
        return {}

def get_fii_dii_bias():
    try:
        s=get_nse_session()
        r=s.get('https://www.nseindia.com/api/fiidiiTradeReact',headers=HEADERS,timeout=10)
        data=r.json()
        fii_net=0;dii_net=0
        for item in data[:2]:
            if 'FII' in str(item.get('category','')):
                fii_net=float(item.get('netDii',0))
            elif 'DII' in str(item.get('category','')):
                dii_net=float(item.get('netDii',0))
        bias='BULLISH' if fii_net>0 else 'BEARISH' if fii_net<-500 else 'NEUTRAL'
        print(f'[FII] FII:{fii_net:.0f} DII:{dii_net:.0f} Bias:{bias}')
        return {'fii_net':fii_net,'dii_net':dii_net,'bias':bias}
    except Exception as e:
        print(f'[FII] Error: {e}')
        return {'fii_net':0,'dii_net':0,'bias':'NEUTRAL'}

def get_sgx_nifty():
    try:
        s=requests.Session()
        r=s.get('https://query1.finance.yahoo.com/v8/finance/chart/^NSEI?interval=1m&range=1d',timeout=10)
        data=r.json()
        price=data['chart']['result'][0]['meta']['regularMarketPrice']
        prev=data['chart']['result'][0]['meta']['previousClose']
        change=((price-prev)/prev)*100
        print(f'[SGX] Nifty:{price} Change:{change:.2f}%')
        return {'price':price,'change':change,'bias':'BULLISH' if change>0.3 else 'BEARISH' if change<-0.3 else 'NEUTRAL'}
    except Exception as e:
        print(f'[SGX] Error: {e}')
        return {'price':0,'change':0,'bias':'NEUTRAL'}

def check_economic_calendar():
    now=datetime.now()
    # High impact dates to avoid
    # RBI policy - typically Feb,Apr,Jun,Aug,Oct,Dec first week
    rbi_months=[2,4,6,8,10,12]
    if now.month in rbi_months and 1<=now.day<=8:
        return False,'RBI_POLICY_WEEK'
    return True,'CLEAR'

def apply_all_filters(instrument,action,current_price):
    results={}

    # VIX filter
    vix_ok,vix_reason=get_vix_filter()
    results['vix_ok']=vix_ok
    results['vix_reason']=vix_reason
    if not vix_ok:
        return False,results

    # Expiry filter
    if instrument in ['NIFTY','BANKNIFTY','FINNIFTY','MIDCPNIFTY']:
        exp_ok,exp_reason=get_expiry_filter(instrument,action)
        results['expiry_ok']=exp_ok
        results['expiry_reason']=exp_reason
        if not exp_ok:
            return False,results

    # Economic calendar
    cal_ok,cal_reason=check_economic_calendar()
    results['calendar_ok']=cal_ok
    results['calendar_reason']=cal_reason
    if not cal_ok:
        return False,results

    # FII bias
    fii=get_fii_dii_bias()
    results['fii']=fii
    # Don't block trade but reduce confidence if against FII
    if fii['bias']=='BEARISH' and action=='BUY':
        results['fii_warning']='AGAINST_FII'
    elif fii['bias']=='BULLISH' and action=='SELL':
        results['fii_warning']='AGAINST_FII'

    # Prev day levels
    levels=get_prev_day_levels()
    if instrument in levels:
        l=levels[instrument]
        results['prev_close']=l['prev_close']
        results['at_resistance']=current_price>=l['prev_high']
        results['at_support']=current_price<=l['prev_low']

    return True,results
