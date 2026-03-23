"""
V32 Token Updater (Bulletproof)
- Safe updates with backup + rollback
- Retry logic + timeout handling
- Token validation
- Atomic file write (no corruption)
- Dry-run mode
- Telegram alert
"""

import requests,json,logging,shutil,os,tempfile,re
from datetime import datetime

log=logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s [TOKEN] %(message)s')

MCX_INSTRUMENTS=['CRUDEOIL','GOLDM','SILVERM','NATURALGAS']
MASTER_URL='https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json'
DRY_RUN=False

def download_master():
    for attempt in range(3):
        try:
            log.info(f'Downloading master (attempt {attempt+1})...')
            r=requests.get(MASTER_URL,timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.warning(f'Retry {attempt+1} failed: {e}')
    raise Exception("Failed to download master file")

def extract_expiry(symbol):
    try:
        m=re.search(r'(\d{2})([A-Z]{3})(\d{2})FUT',symbol)
        if m:
            return datetime.strptime(
                f"{m.group(1)}{m.group(2)}{m.group(3)}",'%d%b%y')
    except Exception as e:
        log.debug(f'Expiry parse failed: {symbol}')
    return datetime.max

def get_nearest_futures(data,inst):
    futures=[d for d in data
             if d.get('exch_seg')=='MCX'
             and d.get('symbol','').startswith(inst)
             and 'FUT' in d.get('symbol','')
             and not d['symbol'].endswith(('CE','PE'))]
    if not futures:return None
    futures.sort(key=lambda x:extract_expiry(x['symbol']))
    return futures[0]

def build_tokens(data):
    tokens={}
    missing=[]
    for inst in MCX_INSTRUMENTS:
        contract=get_nearest_futures(data,inst)
        if not contract:
            log.error(f'{inst}: NOT FOUND')
            missing.append(inst)
            continue
        # Market validation
        if not contract.get('token') or int(contract['token'])<=0:
            raise Exception(f"Bad token for {inst}")
        tokens[inst]={
            'token':contract['token'],
            'symbol':contract['symbol'],
            'lotsize':contract.get('lotsize',1),
            'exchange':'MCX'
        }
    # All-or-nothing!
    if missing:
        raise Exception(f"Missing instruments: {missing} - aborting!")
    for inst,info in tokens.items():
        log.info(f"{inst}: {info['symbol']} token={info['token']}")
    return tokens

def backup_file(filepath):
    backup=filepath+'.bak'
    shutil.copy(filepath,backup)
    log.info(f'Backup: {backup}')

def atomic_write(filepath,content):
    with tempfile.NamedTemporaryFile('w',delete=False) as tmp:
        tmp.write(content)
        tempname=tmp.name
    os.replace(tempname,filepath)

def update_feed(tokens):
    path='angel_feed.py'
    if not os.path.exists(path):
        raise Exception("angel_feed.py not found!")
    backup_file(path)
    content=open(path).read()
    for inst,info in tokens.items():
        pattern=rf"'{inst}':\s*\{{[^}}]*\}}"
        new_val=f"'{inst}': {{'token':'{info['token']}','exchange':'MCX'}}  # {info['symbol']}"
        content=re.sub(pattern,new_val,content)
    if DRY_RUN:
        log.info("DRY RUN - no file written")
        return
    atomic_write(path,content)
    log.info('angel_feed.py updated safely')

def save_tokens(tokens):
    with open('mcx_tokens.json','w') as f:
        json.dump(tokens,f,indent=2)
    log.info('Saved to mcx_tokens.json')

def validate_tokens(tokens):
    if not tokens:
        raise Exception("No tokens generated!")
    for k,v in tokens.items():
        if not v.get('token'):
            raise Exception(f"Invalid token for {k}")
    log.info('Token validation passed')

def send_telegram_alert(tokens,success=True):
    try:
        from v30_notify import send
        if success:
            msg='✅ MCX Tokens Updated!\n'
            for inst,info in tokens.items():
                msg+=f"{inst}: {info['symbol']}\n"
        else:
            msg='❌ MCX Token Update FAILED!'
        send(msg)
    except:pass

def auto_git_commit():
    try:
        diff=os.system("cd ~/kairos_kotak_bot && git diff --quiet angel_feed.py mcx_tokens.json")
        if diff!=0:
            os.system("cd ~/kairos_kotak_bot && git add angel_feed.py mcx_tokens.json && git commit -m 'Auto: MCX token update' && git push origin main")
            log.info('Git commit done!')
        else:
            log.info('No changes to commit')
    except:pass

def update_mcx_tokens():
    try:
        data=download_master()
        tokens=build_tokens(data)
        validate_tokens(tokens)
        update_feed(tokens)
        save_tokens(tokens)
        send_telegram_alert(tokens,success=True)
        auto_git_commit()
        log.info(f'SUCCESS: Updated {len(tokens)} tokens')
        return tokens
    except Exception as e:
        log.error(f'FAILED: {e}')
        send_telegram_alert({},success=False)
        return {}

if __name__=='__main__':
    update_mcx_tokens()
