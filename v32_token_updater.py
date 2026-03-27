"""
V32 Token Updater (Final Bulletproof Version)
- All-or-nothing updates
- Safe token validation
- Atomic writes
- Retry logic
- Fallback to previous tokens
- Telegram alerts
- Safe git commit
"""
import requests,json,logging,shutil,os,tempfile,re,time
from datetime import datetime

log=logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s [TOKEN] %(message)s')

MCX_INSTRUMENTS=['CRUDEOIL','GOLDM','SILVERM','NATURALGAS']
MASTER_URL='https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json'
DRY_RUN=False

def download_master():
    """Download with retry"""
    for attempt in range(3):
        try:
            log.info(f'Downloading master (attempt {attempt+1})...')
            r=requests.get(MASTER_URL,timeout=30)
            r.raise_for_status()
            data=r.json()
            log.info(f'Downloaded {len(data)} instruments')
            return data
        except Exception as e:
            log.warning(f'Attempt {attempt+1} failed: {e}')
            if attempt<2:time.sleep(3)
    raise Exception("Failed to download master after 3 attempts")

def extract_expiry(symbol):
    """Safe expiry extraction"""
    try:
        m=re.search(r'(\d{2})([A-Z]{3})(\d{2})FUT',symbol)
        if m:
            return datetime.strptime(
                f"{m.group(1)}{m.group(2)}{m.group(3)}",'%d%b%y')
    except Exception as e:
        log.debug(f'Expiry parse failed: {symbol}: {e}')
    return datetime.max

def get_nearest_futures(data,inst):
    """Find nearest active futures contract"""
    from datetime import datetime
    today = datetime.now().replace(hour=0,minute=0,second=0)
    
    futures=[d for d in data
             if d.get('exch_seg')=='MCX'
             and d.get('symbol','').startswith(inst)
             and 'FUT' in d.get('symbol','')
             and not d['symbol'].endswith(('CE','PE'))]
    if not futures:return None
    
    # Sort by expiry
    futures.sort(key=lambda x:extract_expiry(x['symbol']))
    
    # Skip expired contracts!
    for f in futures:
        expiry = extract_expiry(f['symbol'])
        if expiry >= today:
            return f
    
    # All expired? Return last one
    return futures[-1]

def validate_contract(inst,contract):
    """Validate contract data"""
    # Safe int parsing
    try:
        token_val=int(contract.get('token',0))
        if token_val<=0:raise Exception()
    except:
        raise Exception(f"Bad token for {inst}: {contract.get('token')}")
    # Symbol validation
    if not contract.get('symbol'):
        raise Exception(f"Missing symbol for {inst}")
    return True

def build_tokens_once(data):
    """Build tokens - raises if any missing"""
    tokens={}
    missing=[]
    for inst in MCX_INSTRUMENTS:
        contract=get_nearest_futures(data,inst)
        if not contract:
            log.error(f'{inst}: NOT FOUND')
            missing.append(inst)
            continue
        # Validate
        validate_contract(inst,contract)
        # Safe lotsize
        try:
            lotsize=int(contract.get('lotsize',1) or 1)
            if lotsize<=0:raise Exception()
        except:
            raise Exception(f"Bad lotsize for {inst}")
        tokens[inst]={
            'token':contract['token'],
            'symbol':contract['symbol'],
            'lotsize':lotsize,
            'exchange':'MCX'
        }
    # All-or-nothing!
    if missing:
        raise Exception(f"Missing: {missing}")
    for inst,info in tokens.items():
        log.info(f"{inst}: {info['symbol']} token={info['token']}")
    return tokens

def build_tokens(data):
    """Build tokens with retry + fallback"""
    for attempt in range(3):
        try:
            return build_tokens_once(data)
        except Exception as e:
            log.warning(f'Token build attempt {attempt+1} failed: {e}')
            if attempt<2:time.sleep(2)
    # Fallback to previous tokens
    if os.path.exists('mcx_tokens.json'):
        log.warning('Using previous tokens as fallback!')
        try:
            with open('mcx_tokens.json') as f:
                return json.load(f)
        except Exception as e:
            raise Exception(f"Fallback tokens invalid: {e}")
    raise Exception("Token build failed - no fallback available!")

def backup_file(filepath):
    """Backup file before modify"""
    backup=filepath+'.bak'
    shutil.copy(filepath,backup)
    log.info(f'Backup: {backup}')

def atomic_write(filepath,content):
    """Write atomically - no corruption risk"""
    with tempfile.NamedTemporaryFile('w',
            delete=False,suffix='.tmp') as tmp:
        tmp.write(content)
        tempname=tmp.name
    os.replace(tempname,filepath)
    log.info(f'Atomic write: {filepath}')

def update_feed(tokens):
    """Update angel_feed.py safely"""
    path='angel_feed.py'
    if not os.path.exists(path):
        raise Exception("angel_feed.py not found!")
    backup_file(path)
    content=open(path).read()
    for inst,info in tokens.items():
        pattern=rf"'{inst}':\s*\{{[^}}]*\}}"
        new_val=(f"'{inst}': {{'token':'{info['token']}',"
                f"'exchange':'MCX'}}  # {info['symbol']}")
        count=len(re.findall(pattern,content))
        if count!=1:
            raise Exception(f"{inst}: Expected 1 match, found {count}")
        new_content=re.sub(pattern,new_val,content)
        content=new_content
        log.info(f'{inst}: Updated')
    if DRY_RUN:
        log.info("DRY RUN - not writing")
        return
    atomic_write(path,content)

def save_tokens(tokens):
    """Save tokens atomically"""
    with tempfile.NamedTemporaryFile('w',
            delete=False,suffix='.tmp') as tmp:
        json.dump(tokens,tmp,indent=2)
        tempname=tmp.name
    os.replace(tempname,'mcx_tokens.json')
    log.info('Saved mcx_tokens.json')

def validate_tokens(tokens):
    """Final validation"""
    if not tokens:
        raise Exception("No tokens generated!")
    for k,v in tokens.items():
        validate_contract(k,{'token':v['token'],
                             'symbol':v['symbol']})
    log.info(f'Validated {len(tokens)} tokens')

def send_telegram_alert(tokens,success=True):
    """Telegram notification"""
    try:
        from v30_notify import send
        if success:
            msg='✅ MCX Tokens Updated!\n━━━━━━━━━\n'
            for inst,info in tokens.items():
                msg+=f"📌 {inst}: {info['symbol']}\n"
            msg+=f"🕐 {datetime.now().strftime('%d-%b %H:%M')}"
        else:
            msg=('❌ MCX Token Update FAILED!\n'
                f'🕐 {datetime.now().strftime("%d-%b %H:%M")}')
        send(msg)
    except Exception as e:
        log.error(f'Telegram alert failed: {e}')

def auto_git_commit():
    """Commit only if changed"""
    try:
        diff=os.system(
            "cd ~/kairos_kotak_bot && "
            "git diff --quiet angel_feed.py mcx_tokens.json")
        if diff!=0:
            r1=os.system("cd ~/kairos_kotak_bot && git add angel_feed.py mcx_tokens.json")
            r2=os.system("cd ~/kairos_kotak_bot && git commit -m 'Auto: MCX token update'")
            r3=os.system("cd ~/kairos_kotak_bot && git push origin main")
            if r3!=0:
                raise Exception(f"Git push failed! code={r3}")
            log.info('Git commit done!')
        else:
            log.info('No changes to commit')
    except Exception as e:
        log.error(f'Git commit failed: {e}')

def update_mcx_tokens():
    """Main update function"""
    log.info('='*40)
    log.info('V32 MCX Token Updater Starting...')
    log.info('='*40)
    try:
        data=download_master()
        tokens=build_tokens(data)
        validate_tokens(tokens)
        update_feed(tokens)
        save_tokens(tokens)
        auto_git_commit()
        send_telegram_alert(tokens,success=True)
        log.info(f'SUCCESS: {len(tokens)}/4 tokens updated!')
        return tokens
    except Exception as e:
        log.error(f'FAILED: {e}')
        send_telegram_alert({},success=False)
        return {}

if __name__=='__main__':
    update_mcx_tokens()
