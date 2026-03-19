#!/bin/bash
cd ~
echo "Creating backup..."
tar -czf kairos_backup_$(date +%Y%m%d).tar.gz kairos_kotak_bot/
SIZE=$(du -sh kairos_backup_$(date +%Y%m%d).tar.gz | cut -f1)
echo "Backup size: $SIZE"
python3 -c "
import requests,os
BOT='8623010355:AAEnUfLlo5drxyd_sYVMCEv5CcANOz13c8M'
CHAT='8436318442'
import datetime
fname=f'kairos_backup_{datetime.datetime.now().strftime(\"%Y%m%d\")}.tar.gz'
size=os.path.getsize(fname)
if size<50000000:
    with open(fname,'rb') as f:
        r=requests.post(
            f'https://api.telegram.org/bot{BOT}/sendDocument',
            data={'chat_id':CHAT,'caption':f'Kairos V31 Backup {datetime.datetime.now().strftime(\"%d-%b-%Y\")}'},
            files={'document':f}
        )
    print('Backup sent to Telegram!' if r.ok else 'Send failed!')
else:
    print(f'File too large ({size/1024/1024:.0f}MB) - split needed')
"
