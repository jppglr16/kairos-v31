import logging,os,time,requests
from datetime import datetime
log=logging.getLogger(__name__)

def check_internet():
    """Check internet connectivity"""
    try:
        requests.get('https://google.com',timeout=5)
        return True
    except:
        return False

def rotate_logs():
    """Keep logs clean - max 50MB, 7 days"""
    import glob
    log_files=glob.glob('*.txt')+glob.glob('*.log')
    for fname in log_files:
        try:
            # Truncate if >50MB
            if os.path.exists(fname) and os.path.getsize(fname)>50*1024*1024:
                with open(fname,'r') as f:
                    lines=f.readlines()
                # Keep last 10000 lines
                with open(fname,'w') as f:
                    f.writelines(lines[-10000:])
                log.info(f'[HEALTH] Rotated {fname}')
        except:pass

def get_capital_angel():
    """Fetch capital from Angel One"""
    try:
        from SmartApi import SmartConnect
        import pyotp
        obj=SmartConnect(api_key='pEOas0vU')
        totp=pyotp.TOTP('R2T2F2BMP56U44O4OMOYJZTFJI').now()
        obj.generateSession('J234619','1605',totp)
        funds=obj.rmsLimit()
        if funds and funds.get('data'):
            cash=float(funds['data'].get('net',0) or
                      funds['data'].get('availablecash',0) or 0)
            return round(cash)
        return 0
    except:return 0
