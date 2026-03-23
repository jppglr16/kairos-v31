"""
V31 Token Updater
Updates MCX futures tokens monthly
Run on 1st of every month or after expiry
"""
import requests,json,logging
log=logging.getLogger(__name__)

def update_mcx_tokens():
    """Download latest MCX futures tokens"""
    print('Downloading Angel One master file...')
    try:
        url='https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json'
        data=requests.get(url,timeout=30).json()

        # Find nearest futures for each MCX instrument
        MCX_INSTRUMENTS=['CRUDEOIL','GOLDM','SILVERM','NATURALGAS']
        tokens={}

        for inst in MCX_INSTRUMENTS:
            # Find futures (not options)
            futures=[d for d in data
                    if d.get('exch_seg')=='MCX'
                    and d.get('symbol','').startswith(inst)
                    and not d['symbol'].endswith(('CE','PE'))
                    and 'FUT' in d.get('symbol','')]

            if futures:
                # Get nearest expiry
                from datetime import datetime
                def get_date(s):
                    try:
                        import re
                        m=re.search(r'(\d{2})([A-Z]{3})(\d{2})FUT',s['symbol'])
                        if m:
                            return datetime.strptime(f"{m.group(1)}{m.group(2)}{m.group(3)}",'%d%b%y')
                    except:pass
                    return datetime.max

                futures.sort(key=get_date)
                nearest=futures[0]
                tokens[inst]={
                    'token':nearest['token'],
                    'symbol':nearest['symbol'],
                    'lotsize':nearest.get('lotsize',1),
                    'exchange':'MCX'
                }
                print(f'{inst}: {nearest["symbol"]} token={nearest["token"]}')
            else:
                print(f'{inst}: NOT FOUND!')

        # Update angel_feed.py
        content=open('angel_feed.py').read()
        for inst,info in tokens.items():
            import re
            old_pattern=f"'{inst}':\\s*\\{{.*?\\}}"
            new_val=f"'{inst}':  {{'token':'{info['token']}','exchange':'MCX'}}  # {info['symbol']}"
            content=re.sub(old_pattern,new_val,content)

        open('angel_feed.py','w').write(content)
        print('✅ angel_feed.py updated!')

        # Save tokens to file
        json.dump(tokens,open('mcx_tokens.json','w'),indent=2)
        print('✅ Saved to mcx_tokens.json!')
        return tokens

    except Exception as e:
        print(f'Error: {e}')
        return {}

if __name__=='__main__':
    tokens=update_mcx_tokens()
    print(f'\nUpdated {len(tokens)} tokens!')
