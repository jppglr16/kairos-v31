"""
V31 Token Updater - Production Grade
Updates MCX futures tokens monthly
Run on 1st of every month or after expiry
"""
import requests,json,logging,shutil,re,os
from datetime import datetime
log=logging.getLogger(__name__)

DRY_RUN=False  # Set True to test without writing

def get_date(s):
    """Safe expiry date parser"""
    try:
        m=re.search(r'(\d{2})([A-Z]{3})(\d{2})FUT',s['symbol'])
        if m:
            return datetime.strptime(
                f"{m.group(1)}{m.group(2)}{m.group(3)}",'%d%b%y')
    except Exception as e:
        log.debug(f"Date parse failed: {s['symbol']}: {e}")
    return datetime.max

def download_master(retries=3):
    """Download Angel One master with retry"""
    url='https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json'
    for attempt in range(retries):
        try:
            log.info(f'Downloading master (attempt {attempt+1})...')
            data=requests.get(url,timeout=30).json()
            log.info(f'Downloaded {len(data)} instruments')
            return data
        except Exception as e:
            log.warning(f'Attempt {attempt+1} failed: {e}')
            if attempt<retries-1:
                import time;time.sleep(3)
    return None

def update_mcx_tokens(dry_run=DRY_RUN):
    """Update MCX futures tokens safely"""

    # Step 1: Download master
    data=download_master()
    if not data:
        log.error('Failed to download master!')
        return {}

    # Step 2: Find nearest futures
    MCX_INSTRUMENTS=['CRUDEOIL','GOLDM','SILVERM','NATURALGAS']
    tokens={}

    for inst in MCX_INSTRUMENTS:
        futures=[d for d in data
                if d.get('exch_seg')=='MCX'
                and d.get('symbol','').startswith(inst)
                and not d['symbol'].endswith(('CE','PE'))
                and 'FUT' in d.get('symbol','')]

        if not futures:
            log.warning(f'{inst}: No futures found!')
            continue

        # Sort by nearest expiry
        futures.sort(key=get_date)
        nearest=futures[0]
        tokens[inst]={
            'token':nearest['token'],
            'symbol':nearest['symbol'],
            'lotsize':nearest.get('lotsize',1),
            'exchange':'MCX'
        }
        log.info(f'{inst}: {nearest["symbol"]} token={nearest["token"]}')

    # Step 3: Validate
    if not tokens:
        log.error('No tokens found - aborting!')
        return {}

    # Step 4: Backup before modify!
    if not dry_run:
        shutil.copy('angel_feed.py','angel_feed_backup.py')
        log.info('Backup created: angel_feed_backup.py')

    # Step 5: Update angel_feed.py safely
    content=open('angel_feed.py').read()
    for inst,info in tokens.items():
        # Safe precise regex
        old_pattern=rf"'{inst}':\s*\{{[^}}]*\}}"
        new_val=f"'{inst}':  {{'token':'{info['token']}','exchange':'MCX'}}  # {info['symbol']}"
        new_content=re.sub(old_pattern,new_val,content)
        if new_content==content:
            log.warning(f'{inst}: Pattern not found in angel_feed.py!')
        else:
            content=new_content
            log.info(f'{inst}: Updated in angel_feed.py')

    if dry_run:
        log.info('DRY RUN - not writing files')
        print('DRY RUN complete!')
    else:
        open('angel_feed.py','w').write(content)
        json.dump(tokens,open('mcx_tokens.json','w'),indent=2)
        log.info('✅ angel_feed.py + mcx_tokens.json updated!')

    # Step 6: Verify
    print('\n=== Token Update Summary ===')
    for inst,info in tokens.items():
        print(f'{inst:<12}: {info["symbol"]} token={info["token"]}')
    print(f'\nTotal: {len(tokens)}/4 updated')

    return tokens

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,
                       format='%(asctime)s %(levelname)s %(message)s')
    tokens=update_mcx_tokens()
    if tokens:
        print('\n✅ Token update successful!')
    else:
        print('\n❌ Token update failed!')
