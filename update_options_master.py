"""
Smart Options Master Update:
✅ Download fresh from Angel One
✅ Add new contracts
✅ Remove expired contracts
✅ Keep valid future contracts
✅ Notify changes via Telegram
"""
import requests,json,os,re
from datetime import datetime
from v30_notify import send

MASTER_FILE='angel_options_lookup.json'
today=datetime.now()

# Lock file - prevent duplicate runs
LOCK_FILE=os.path.expanduser('~/kairos_kotak_bot/options_update.lock')
import sys
if os.path.exists(LOCK_FILE):
    # Check if process still running
    try:
        pid=int(open(LOCK_FILE).read().strip())
        os.kill(pid,0)  # Check if PID alive
        print(f'Already running (PID:{pid})! Skipping.')
        sys.exit(0)
    except (ProcessLookupError,ValueError):
        os.remove(LOCK_FILE)  # Stale lock - remove

# Create lock
open(LOCK_FILE,'w').write(str(os.getpid()))

import atexit
def cleanup():
    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)
atexit.register(cleanup)

print(f'[{today.strftime("%H:%M")}] Updating options master...')

# Step 1: Download fresh master
url='https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json'
r=requests.get(url,timeout=60)
fresh_data=r.json()

# Step 2: Filter options only
fresh_options=[d for d in fresh_data
               if d.get('exch_seg') in ['NFO','BFO','MCX']
               and ('CE' in d.get('symbol','') or 'PE' in d.get('symbol',''))]

# Step 3: Build new lookup
new_lookup={}
for d in fresh_options:
    sym=d.get('symbol','')
    new_lookup[sym]={
        'token':d.get('token',''),
        'exch':d.get('exch_seg',''),
        'lotsize':d.get('lotsize',0)
    }

# Step 4: Load old lookup
old_count=0
old_lookup={}
if os.path.exists(MASTER_FILE):
    old_lookup=json.load(open(MASTER_FILE))
    old_count=len(old_lookup)

# Step 5: Find changes
added=set(new_lookup.keys())-set(old_lookup.keys())
removed=set(old_lookup.keys())-set(new_lookup.keys())

# Step 6: Filter removed - only remove EXPIRED contracts
def is_expired(symbol):
    """Check if contract has expired"""
    m=re.search(r'(\d{2}[A-Z]{3}\d{2})',symbol)
    if not m:return False
    try:
        exp=datetime.strptime(m.group(1),'%d%b%y')
        return exp.date()<today.date()
    except:return False

expired_removed=[s for s in removed if is_expired(s)]
valid_removed=[s for s in removed if not is_expired(s)]

# Step 7: Save new lookup
json.dump(new_lookup,open(MASTER_FILE,'w'))

# Step 8: Report
print(f'Old: {old_count} | New: {len(new_lookup)}')
print(f'Added: {len(added)} | Expired removed: {len(expired_removed)}')
print(f'Valid but removed: {len(valid_removed)}')

# Step 9: Telegram notification
msg=f"""📊 Options Master Updated!
━━━━━━━━━━━━━━━
📅 {today.strftime('%d %b %Y %H:%M')}
✅ Total options: {len(new_lookup):,}
🆕 New contracts: {len(added):,}
🗑 Expired removed: {len(expired_removed):,}
📌 Valid contracts kept: {len(new_lookup):,}"""

# Show sample new contracts
if added:
    sample=list(added)[:3]
    msg+=f'\n\nNew examples:\n'
    msg+='\n'.join(f'• {s}' for s in sample)

send(msg)
print('Done! Options master updated!')
