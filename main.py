import asyncio,logging,json,os,pyotp
from datetime import datetime,time
from telethon import TelegramClient,events
from signal_parser import KairosSignalParser
from kotak_trader import KotakNeoTrader
from config import CONFIG
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s',handlers=[logging.FileHandler('trade_log.txt'),logging.StreamHandler()])
log=logging.getLogger(__name__)
def save(s,r):
    try:
        h=json.load(open('trade_history.json')) if os.path.exists('trade_history.json') else []
        h.append({'time':str(datetime.now()),'signal':s,'response':r})
        json.dump(h,open('trade_history.json','w'),indent=2)
    except Exception as e:log.error(e)
async def daily_relogin(trader):
    while True:
        now=datetime.now()
        # Calculate seconds until next 9:00 AM
        target=now.replace(hour=9,minute=0,second=0,microsecond=0)
        if now>=target:
            import datetime as dt
            target=target+dt.timedelta(days=1)
        secs=(target-now).total_seconds()
        log.info(f'Next Kotak re-login in {int(secs//3600)}h {int((secs%3600)//60)}m')
        await asyncio.sleep(secs)
        try:
            log.info('Auto re-login to Kotak Neo...')
            trader.login()
            trader.complete_login()
            log.info('Auto re-login done!')
        except Exception as e:
            log.error(f'Auto re-login failed: {e}')
async def main():
    k=CONFIG['kotak']
    trader=KotakNeoTrader(consumer_key=k['consumer_key'],mobile_number=k['mobile_number'],mpin=k['mpin'],ucc=k['ucc'],totp_secret=k['totp_secret'],environment=k.get('environment','prod'))
    log.info('Logging into Kotak Neo...')
    trader.login()
    trader.complete_login()
    log.info('Kotak login done!')
    parser=KairosSignalParser()
    client=TelegramClient('kairos_session',CONFIG['telegram']['api_id'],CONFIG['telegram']['api_hash'])
    await client.start(phone=CONFIG['telegram']['phone_number'])
    log.info('Telegram connected!')
    @client.on(events.NewMessage(chats=CONFIG['telegram']['kairos_source']))
    async def handle(event):
        signal=parser.parse(event.message.message)
        if not signal or not trader.risk_check(signal,CONFIG.get('risk',{})):return
        try:
            r=trader.place_order(signal)
            save(signal,r)
            if signal.get('stop_loss'):trader.place_sl_order(signal)
            for i,t in enumerate(signal.get('targets',[]),1):trader.place_target_order(signal,t,i)
        except Exception as e:log.error(e)
    log.info('Listening for Kairos X signals...')
    await asyncio.gather(
        client.run_until_disconnected(),
        daily_relogin(trader)
    )
asyncio.run(main())
