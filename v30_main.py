import asyncio,logging,json,os,pyotp
from datetime import datetime,timedelta
from neo_api_client import NeoAPI
from config import CONFIG
from v30_risk import DailyRiskManager
from v30_strategy import generate_signal
from v30_adaptive import AdaptiveEngine
from v30_feed import MarketDataFeed
from angel_feed import get_angel_client,get_historical
from v30_holiday import is_market_open,get_closed_message
from v30_lot_config import get_lots
from v30_sell_logic import run_sell_strategy,manage_sell_positions,get_sell_mode
from v30_meta_learner import meta
from v30_self_learn import analyzer
from v30_adaptive_learner import brain
from v30_options_selling import options_seller
from v30_protection import get_protection
from v30_notify import notify_startup,notify_entry,notify_exit,notify_daily_summary
from v30_notify import notify_startup,notify_entry,notify_exit,notify_daily_summary,notify_stopped,notify_error
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s',handlers=[logging.FileHandler('v30_log.txt'),logging.StreamHandler()])
log=logging.getLogger(__name__)
INSTRUMENTS=['NIFTY','BANKNIFTY','FINNIFTY','MIDCPNIFTY','SENSEX','CRUDEOIL','GOLDM','SILVERM']
active_trades={}
active_positions={}
adaptive=AdaptiveEngine()
def get_capital(client):
    try:return float(client.limits().get('CashMargin',50000))
    except:return 50000
def get_option_symbol(instrument,option_type,current_price):
    step=50 if instrument=='NIFTY' else 100 if instrument=='BANKNIFTY' else 10
    atm=round(current_price/step)*step
    today=datetime.now()
    if instrument in ['NIFTY','BANKNIFTY']:
        d=(3-today.weekday())%7
        if d==0 and today.hour>=15:d=7
        expiry=(today+timedelta(days=d)).strftime('%d%b%y').upper()
    else:expiry=today.strftime('%b%y').upper()
    return f'{instrument}{expiry}{atm}{option_type}',atm
def save_trade(signal,order):
    try:
        h=json.load(open('v30_trades.json')) if os.path.exists('v30_trades.json') else []
        h.append({'time':str(datetime.now()),'signal':signal,'order':str(order)})
        json.dump(h,open('v30_trades.json','w'),indent=2)
    except Exception as e:log.error(e)
def exit_trade(client,instrument,trade,reason,risk_mgr,pnl=0):
    try:
        seg='nse_fo' if instrument!='CRUDEOIL' else 'mcx_fo'
        side='S' if trade['action']=='BUY' else 'B'
        client.place_order(exchange_segment=seg,product='NRML',price='0',order_type='MKT',quantity=str(trade['qty']),validity='DAY',trading_symbol=trade['symbol'],transaction_type=side,amo='NO',disclosed_quantity='0',market_protection='0',pf='N',trigger_price='0',tag='V30-EXIT')
        log.info(f"[V30] EXIT {instrument} | {reason} | PnL:{pnl:.0f}")
        notify_exit(instrument,reason,pnl,trade["entry"],0)
        risk_mgr.record_trade(pnl,instrument,trade['signal']['action'])
        adaptive.record_result(instrument,trade["signal"],pnl)
        from v30_rl import rl_record_result
        rl_record_result(instrument,trade["signal"].get("features",{}),trade["signal"]["action"],pnl,None)
        del active_trades[instrument]
    except Exception as e:log.error(f'Exit error:{e}')
def place_trade(client,signal,risk_mgr,feed):
    if not risk_mgr.can_trade():return
    if not check_min_capital(capital,signal["instrument"]):return
    from v30_protection import get_protection
    prot=get_protection(50000)
    if not prot.can_trade():return
    instrument=signal['instrument']
    if instrument in active_trades:return
    price=feed.get_price(instrument)
    if price<=0:return
    symbol,strike=get_option_symbol(instrument,signal['option_type'],price)
    qty={'NIFTY':75,'BANKNIFTY':30,'CRUDEOIL':100}[instrument]
    seg='nse_fo' if instrument!='CRUDEOIL' else 'mcx_fo'
    log.info(f'[V30] TRADE: {instrument} {signal["option_type"]} Conf:{signal.get("confidence",0)}/100')
    try:
        order=client.place_order(exchange_segment=seg,product='NRML',price='0',order_type='MKT',quantity=str(qty),validity='DAY',trading_symbol=symbol,transaction_type='B' if signal['action']=='BUY' else 'S',amo='NO',disclosed_quantity='0',market_protection='0',pf='N',trigger_price='0',tag='KairosV30')
        log.info(f'[V30] Order:{order}')
        active_trades[instrument]={'symbol':symbol,'action':signal['action'],'qty':qty,'entry':price,'sl_points':signal['sl_points'],'target1':signal['target1'],'target2':signal['target2'],'use_trailing':signal['use_trailing'],'hold_overnight':signal['hold_overnight'],'highest':price,'lowest':price,'signal':signal}
        save_trade(signal,order)
    except Exception as e:log.error(f'Order error:{e}')
def manage_trades(client,feed,risk_mgr):
    run_sell_strategy(client,feed,capital,active_trades,active_positions)
    manage_sell_positions(client,feed,active_positions,capital)
    now=datetime.now()
    force_exit=now.hour==15 and now.minute>=10
    LOT={'NIFTY':75,'BANKNIFTY':30,'CRUDEOIL':100}
    for instrument in list(active_trades.keys()):
        trade=active_trades[instrument]
        current=feed.get_price(instrument)
        if current<=0:continue
        entry=trade['entry']
        sl=trade['sl_points']
        if force_exit and not trade['hold_overnight']:
            pnl=(current-entry if trade['action']=='BUY' else entry-current)*LOT[instrument]
            exit_trade(client,instrument,trade,'EOD',risk_mgr,pnl);continue
        if trade['action']=='BUY':
            sl_price=entry-sl
            if trade['use_trailing']:
                if current>trade['highest']:active_trades[instrument]['highest']=current
                sl_price=max(sl_price,trade['highest']-sl)
            if current<=sl_price:exit_trade(client,instrument,trade,'SL',risk_mgr,(sl_price-entry)*LOT[instrument])
            elif current>=entry+trade['target2']:exit_trade(client,instrument,trade,'T2',risk_mgr,trade['target2']*LOT[instrument])
            elif current>=entry+trade['target1']:active_trades[instrument]['use_trailing']=True
        else:
            sl_price=entry+sl
            if trade['use_trailing']:
                if current<trade['lowest']:active_trades[instrument]['lowest']=current
                sl_price=min(sl_price,trade['lowest']+sl)
            if current>=sl_price:exit_trade(client,instrument,trade,'SL',risk_mgr,-sl*LOT[instrument])
            elif current<=entry-trade['target2']:exit_trade(client,instrument,trade,'T2',risk_mgr,trade['target2']*LOT[instrument])
def load_candles_from_angel(feed,angel):
    log.info('[V30] Loading historical candles from Angel One...')
    for inst in INSTRUMENTS:
        for tf in [5,15]:
            candles=get_historical(angel,inst,tf)
            for c in candles:
                feed.builders[inst][str(tf)].candles.append(c)
    log.info('[V30] Historical candles loaded!')
def load_candles_from_angel(feed,angel):
    from angel_feed import get_historical
    for inst in INSTRUMENTS:
        for tf in [5,15]:
            candles=get_historical(angel,inst,tf)
            for c in candles:
                feed.builders[inst][str(tf)].candles.append(c)

async def daily_reset(risk_mgr,client,feed):
    while True:
        from v30_holiday import is_market_open
        ok,reason=is_market_open()
        if not ok:
            log.info(f"[V30] {reason} - no trading")
            await asyncio.sleep(3600)
            continue
        from v30_holiday import is_market_open
        now=datetime.now()
        next9=now.replace(hour=9,minute=0,second=0,microsecond=0)
        if now>=next9:next9+=timedelta(days=1)
        await asyncio.sleep((next9-now).total_seconds())
        try:
            k=CONFIG['kotak']
            totp=pyotp.TOTP(k['totp_secret']).now()
            client.totp_login(mobile_number=k['mobile_number'],ucc=k['ucc'],totp=totp)
            client.totp_validate(mpin=k['mpin'])
            log.info('[V30] Kotak re-login done!')
        except Exception as e:log.error(f'Relogin:{e}')
        risk_mgr.reset_daily()
        angel=get_angel_client()
        if angel:load_candles_from_angel(feed,angel)
async def main():
    k=CONFIG['kotak']
    client=NeoAPI(environment=k.get('environment','prod'),access_token=None,neo_fin_key=None,consumer_key=k['consumer_key'])
    totp=pyotp.TOTP(k['totp_secret']).now()
    client.totp_login(mobile_number=k['mobile_number'],ucc=k['ucc'],totp=totp)
    client.totp_validate(mpin=k['mpin'])
    log.info('[V30] Kotak connected!')
    capital=get_capital(client)
    log.info(f'[V30] Capital: Rs.{capital:.0f}')
    risk_mgr=DailyRiskManager(capital=capital,max_losses=3)
    protection=get_protection(capital)
    feed=MarketDataFeed(client)
    from v30_feed import patch_feed
    patch_feed(feed)
    from v30_feed import patch_feed
    patch_feed(feed)
    angel=get_angel_client()
    if angel:load_candles_from_angel(feed,angel)
    from v30_cache import preload_cache
    preload_cache()
    from v30_cache import preload_cache
    preload_cache()
    feed.start()
    log.info('[V30] Kairos V30 LIVE!')
    notify_startup(capital)
    from v30_holiday import is_market_open
    ok,reason=is_market_open()
    if not ok:
        from v30_notify import send
        from v30_holiday import get_closed_message
        send(f"🏖 <b>Market Closed</b>\n{get_closed_message()}")
    pass #daily_summary_task
    asyncio.create_task(daily_reset(risk_mgr,client,feed))
    while True:
        from v30_holiday import is_market_open
        ok,reason=is_market_open()
        if not ok:
            log.info(f"[V30] {reason} - no trading")
            await asyncio.sleep(3600)
            continue
        for instrument in INSTRUMENTS:
            df5=feed.get_candles(instrument,'5')
            df15=feed.get_candles(instrument,'15')
            if df5 is None or df15 is None:continue
            signal=generate_signal(df5,df15,instrument,capital)
            if signal:place_trade(client,signal,risk_mgr,feed)
        manage_trades(client,feed,risk_mgr)
        run_sell_strategy(client,feed,capital,active_trades,active_positions)
        manage_sell_positions(client,feed,active_positions,capital)
        await asyncio.sleep(60)
asyncio.run(main())

def check_min_capital(capital, instrument):
    min_margins = {
        'NIFTY':8000,'BANKNIFTY':7000,
        'FINNIFTY':4000,'MIDCPNIFTY':3000,
        'SENSEX':7000,'CRUDEOIL':5000,
        'GOLDM':4000,'SILVERM':4000
    }
    required = min_margins.get(instrument, 5000)
    if capital < required:
        log.warning(f'[CAPITAL] {instrument} needs ₹{required}, have ₹{capital:.0f} - SKIP')
        return False
    return True

async def daily_summary_task(risk_mgr,capital):
    while True:
        from v30_holiday import is_market_open
        ok,reason=is_market_open()
        if not ok:
            log.info(f"[V30] {reason} - no trading")
            await asyncio.sleep(3600)
            continue
        now=datetime.now()
        target=now.replace(hour=15,minute=30,second=0,microsecond=0)
        if now>=target:target+=timedelta(days=1)
        await asyncio.sleep((target-now).total_seconds())
        from v30_notify import notify_daily_summary
        s=risk_mgr
        notify_daily_summary(s.wins+s.losses,s.wins,s.losses,s.pnl,capital)
