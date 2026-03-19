from SmartApi import SmartConnect
import pyotp,time,re

obj=SmartConnect(api_key='pEOas0vU')
totp=pyotp.TOTP('R2T2F2BMP56U44O4OMOYJZTFJI').now()
obj.generateSession('J234619','1605',totp)
time.sleep(3)

instruments=[
    ('NIFTY','NFO'),
    ('BANKNIFTY','NFO'),
    ('FINNIFTY','NFO'),
    ('MIDCPNIFTY','NFO'),
    ('SENSEX','BFO'),
    ('CRUDEOIL','MCX'),
    ('GOLDM','MCX'),
    ('LT','NFO'),
    ('RELIANCE','NFO'),
]

print('Expiry dates from Angel One:')
print('-'*40)
for inst,exch in instruments:
    time.sleep(2)
    resp=obj.searchScrip(exchange=exch,searchscrip=inst)
    if resp and resp.get('data'):
        expiries=set()
        for s in resp['data']:
            sym=s.get('tradingsymbol','')
            m=re.search(rf'{inst}(\d{{2}}[A-Z]{{3}}\d{{2}})',sym)
            if m:
                expiries.add(m.group(1))
        # Sort and show nearest 2
        sorted_exp=sorted(expiries)[:2]
        print(f'{inst:<15}: {sorted_exp}')
    else:
        print(f'{inst:<15}: Not found')
