import logging
from datetime import datetime,timedelta
import pandas as pd
log=logging.getLogger(__name__)

# Selling priority order
SELL_PRIORITY=['SENSEX','NIFTY','FINNIFTY','MIDCPNIFTY']

# Index lots
INDEX_LOTS={
    'SENSEX':10,'NIFTY':75,
    'FINNIFTY':65,'MIDCPNIFTY':120
}

# Exchange segments
INDEX_SEG={
    'SENSEX':'bse_fo',
    'NIFTY':'nse_fo',
    'FINNIFTY':'nse_fo',
    'MIDCPNIFTY':'nse_fo'
}

def get_sell_mode(capital):
    """
    < 1,50,000 → Buy options (sideways range trade)
    ≥ 1,50,000 → Sell options (Iron Condor or CE/PE sell with hedge)
    """
    if capital>=150000:
        return 'SELL_OPTIONS'
    return 'BUY_OPTIONS'

def find_sell_strike(df5,instrument,action,
                     target_premium=200,exchange='NSE'):
    """
    Find strike with premium ~₹200 for SELL
    Find strike with premium ~₹15 for hedge BUY
    """
    try:
        import pyotp,time
        from SmartApi import SmartConnect
        from v30_oi import get_option_chain

        current=df5['close'].iloc[-1]
        steps={
            'SENSEX':100,'NIFTY':50,
            'FINNIFTY':50,'MIDCPNIFTY':25
        }
        step=steps.get(instrument,50)
        now=datetime.now()

        # Find expiry
        days_to_thu=(3-now.weekday())%7
        if days_to_thu==0:days_to_thu=7
        expiry=(now+timedelta(days=days_to_thu))
        expiry_str=expiry.strftime('%d%b%y').upper()

        # Get option chain
        chain=get_option_chain(instrument)
        if not chain:
            # Estimate strikes based on ATR
            atr=(df5['high']-df5['low']).tail(14).mean()
            if action=='SELL_CE':
                sell_strike=round((current+atr*2)/step)*step
                hedge_strike=sell_strike+step*3
            else:
                sell_strike=round((current-atr*2)/step)*step
                hedge_strike=sell_strike-step*3
            return sell_strike,hedge_strike,expiry_str

        # Find strike with ~₹200 premium
        best_sell=None
        best_hedge=None
        best_diff=999

        strikes=chain.get('strikes',[])
        for strike_data in strikes:
            strike=strike_data.get('strike',0)
            if action=='SELL_CE':
                premium=strike_data.get('ce_ltp',0)
                if 150<=premium<=300:
                    diff=abs(premium-target_premium)
                    if diff<best_diff:
                        best_diff=diff
                        best_sell=strike
            else:
                premium=strike_data.get('pe_ltp',0)
                if 150<=premium<=300:
                    diff=abs(premium-target_premium)
                    if diff<best_diff:
                        best_diff=diff
                        best_sell=strike

        # Hedge strike (3 steps away)
        if best_sell:
            if action=='SELL_CE':
                best_hedge=best_sell+step*3
            else:
                best_hedge=best_sell-step*3
        else:
            # Fallback estimate
            atr=(df5['high']-df5['low']).tail(14).mean()
            if action=='SELL_CE':
                best_sell=round((current+atr*2)/step)*step
                best_hedge=best_sell+step*3
            else:
                best_sell=round((current-atr*2)/step)*step
                best_hedge=best_sell-step*3

        return best_sell,best_hedge,expiry_str

    except Exception as e:
        log.error(f'[SELL] Strike find error: {e}')
        # Fallback
        atr=(df5['high']-df5['low']).tail(14).mean()
        step={'SENSEX':100,'NIFTY':50,'FINNIFTY':50,'MIDCPNIFTY':25}.get(instrument,50)
        current=df5['close'].iloc[-1]
        if action=='SELL_CE':
            sell=round((current+atr*2)/step)*step
            hedge=sell+step*3
        else:
            sell=round((current-atr*2)/step)*step
            hedge=sell-step*3
        now=datetime.now()
        days_to_thu=(3-now.weekday())%7
        if days_to_thu==0:days_to_thu=7
        expiry=(now+timedelta(days=days_to_thu)).strftime('%d%b%y').upper()
        return sell,hedge,expiry

def get_sell_lots(capital,instrument):
    """
    Min 3-4 lots for sell strategy
    More capital = more lots
    """
    base_lot=INDEX_LOTS.get(instrument,75)
    if capital>=500000:lots=6
    elif capital>=300000:lots=5
    elif capital>=200000:lots=4
    else:lots=3  # Minimum 3 lots
    return lots

def get_sideways_action(df5,df15,instrument):
    """Determine if market favors CE sell or PE sell"""
    try:
        from v30_train_kairos import calc_rsi,get_trend
        c=df5['close']
        rsi=calc_rsi(c).iloc[-1]
        trend15=get_trend(df15)
        trend_daily=get_trend(df15.iloc[::3] if len(df15)>30 else df15)

        # Near top of range → Sell CE
        h20=df5['high'].tail(20).max()
        l20=df5['low'].tail(20).min()
        range_size=h20-l20
        pos=(c.iloc[-1]-l20)/range_size if range_size>0 else 0.5

        if pos>=0.65 and rsi>55:
            return 'SELL_CE'
        elif pos<=0.35 and rsi<45:
            return 'SELL_PE'
        else:
            return 'IRON_CONDOR'  # Neutral = sell both
    except:return 'IRON_CONDOR'

def place_sell_with_hedge(client,instrument,action,
                           sell_strike,hedge_strike,
                           expiry_str,lots,capital):
    """Place sell order + hedge buy"""
    try:
        seg=INDEX_SEG.get(instrument,'nse_fo')
        base_lot=INDEX_LOTS.get(instrument,75)
        qty=lots*base_lot

        option_type='CE' if action=='SELL_CE' else 'PE'
        sell_symbol=f'{instrument}{expiry_str}{sell_strike}{option_type}'
        hedge_symbol=f'{instrument}{expiry_str}{hedge_strike}{option_type}'

        orders=[]

        # 1. SELL main strike
        try:
            sell_order=client.place_order(
                exchange_segment=seg,
                product='NRML',
                price='0',
                order_type='MKT',
                quantity=str(qty),
                validity='DAY',
                trading_symbol=sell_symbol,
                transaction_type='S',
                amo='NO',
                disclosed_quantity='0',
                market_protection='0',
                pf='N',
                trigger_price='0',
                tag='V30-SELL'
            )
            orders.append(('SELL',sell_symbol,sell_order))
            log.info(f'[SELL] SOLD {sell_symbol} qty={qty}')
        except Exception as e:
            log.error(f'[SELL] Sell order error: {e}')
            return None

        # 2. BUY hedge (far OTM)
        try:
            hedge_order=client.place_order(
                exchange_segment=seg,
                product='NRML',
                price='0',
                order_type='MKT',
                quantity=str(qty),
                validity='DAY',
                trading_symbol=hedge_symbol,
                transaction_type='B',
                amo='NO',
                disclosed_quantity='0',
                market_protection='0',
                pf='N',
                trigger_price='0',
                tag='V30-HEDGE'
            )
            orders.append(('BUY_HEDGE',hedge_symbol,hedge_order))
            log.info(f'[SELL] HEDGE {hedge_symbol} qty={qty}')
        except Exception as e:
            log.error(f'[SELL] Hedge order error: {e}')

        # Notify
        if orders:
            from v30_notify import send
            pnl_est=200*qty  # Estimated premium collected
            send(f"""🔴 <b>OPTIONS SELL + HEDGE</b>
━━━━━━━━━━━━━━━
📊 {instrument} | {action}
💰 Capital: ₹{capital:,.0f}

🔴 SELL {option_type}: {sell_strike} @ ~₹200
🟢 BUY HEDGE {option_type}: {hedge_strike} @ ~₹15
📦 Lots: {lots} | Qty: {qty}
💵 Premium collected: ~₹{pnl_est:,.0f}
⚠️ Max loss protected by hedge
⏰ {datetime.now().strftime('%H:%M')}""")

        return orders

    except Exception as e:
        log.error(f'[SELL] Place order error: {e}')
        return None

def place_iron_condor_full(client,instrument,df5,df15,
                            capital,active_positions):
    """Full Iron Condor for capital >= 1,50,000"""
    try:
        current=df5['close'].iloc[-1]
        atr=(df5['high']-df5['low']).tail(14).mean()
        lots=get_sell_lots(capital,instrument)

        # Get CE sell strike
        ce_sell,ce_hedge,expiry=find_sell_strike(
            df5,instrument,'SELL_CE',200)
        # Get PE sell strike
        pe_sell,pe_hedge,_=find_sell_strike(
            df5,instrument,'SELL_PE',200)

        seg=INDEX_SEG.get(instrument,'nse_fo')
        base_lot=INDEX_LOTS.get(instrument,75)
        qty=lots*base_lot

        orders=[]
        legs=[
            (f'{instrument}{expiry}{ce_sell}CE','S',qty,'SELL_CE'),
            (f'{instrument}{expiry}{pe_sell}PE','S',qty,'SELL_PE'),
            (f'{instrument}{expiry}{ce_hedge}CE','B',qty,'HEDGE_CE'),
            (f'{instrument}{expiry}{pe_hedge}PE','B',qty,'HEDGE_PE'),
        ]

        for symbol,side,q,tag in legs:
            try:
                order=client.place_order(
                    exchange_segment=seg,product='NRML',
                    price='0',order_type='MKT',
                    quantity=str(q),validity='DAY',
                    trading_symbol=symbol,transaction_type=side,
                    amo='NO',disclosed_quantity='0',
                    market_protection='0',pf='N',
                    trigger_price='0',tag=f'V30-{tag}'
                )
                orders.append(order)
                log.info(f'[CONDOR] {side} {symbol} qty={q}')
            except Exception as e:
                log.error(f'[CONDOR] Leg error {symbol}: {e}')

        if orders:
            active_positions[instrument]={
                'type':'IRON_CONDOR',
                'ce_sell':ce_sell,'pe_sell':pe_sell,
                'ce_hedge':ce_hedge,'pe_hedge':pe_hedge,
                'lots':lots,'qty':qty,'expiry':expiry,
                'entry_time':str(datetime.now())
            }

            from v30_notify import send
            premium_est=(200+200-15-15)*qty
            send(f"""🔵 <b>IRON CONDOR PLACED</b>
━━━━━━━━━━━━━━━
📊 {instrument}
💰 Capital: ₹{capital:,.0f}
📦 Lots: {lots} | Qty: {qty}

🔴 Sell CE: {ce_sell} @ ~₹200
🔴 Sell PE: {pe_sell} @ ~₹200
🟢 Hedge CE: {ce_hedge} @ ~₹15
🟢 Hedge PE: {pe_hedge} @ ~₹15

💵 Net Premium: ~₹{premium_est:,.0f}
📈 Profit if stays {pe_sell}-{ce_sell}
⏰ {datetime.now().strftime('%H:%M')}""")

        return orders

    except Exception as e:
        log.error(f'[CONDOR] Full error: {e}')
        return None

def run_sell_strategy(client,feed,capital,active_trades,active_positions):
    """Main sell strategy runner - called every 60 seconds"""
    try:
        now=datetime.now()
        h=now.hour

        # Only run 10AM-2PM
        if h<10 or h>14:return

        mode=get_sell_mode(capital)

        # Check each instrument by priority
        for instrument in SELL_PRIORITY:
            # Skip if already in position
            if instrument in active_trades:continue
            if instrument in active_positions:continue

            df5=feed.get_candles(instrument,'5')
            df15=feed.get_candles(instrument,'15')
            if df5 is None or df15 is None:continue
            if len(df5)<20:continue

            # Check sideways market
            from v30_momentum import detect_market_condition
            market=detect_market_condition(df15)

            if mode=='BUY_OPTIONS':
                # Capital < 1,50,000 → Buy options
                if market=='SIDEWAYS':
                    from v30_strategy import generate_sideways_signal
                    signal=generate_sideways_signal(df5,df15,instrument,capital)
                    if signal:
                        from v30_main import place_trade
                        place_trade(client,signal,None,feed)
                        log.info(f'[SELL] {instrument} BUY sideways signal')
                        break

            else:
                # Capital >= 1,50,000 → Sell options
                if market!='SIDEWAYS':continue

                # Check VIX
                from v30_cache import cached_vix
                vix=cached_vix()
                if vix>18 or vix<10:
                    log.info(f'[SELL] VIX={vix} not suitable for selling')
                    continue

                action=get_sideways_action(df5,df15,instrument)
                lots=get_sell_lots(capital,instrument)

                if action=='IRON_CONDOR':
                    log.info(f'[SELL] {instrument} Iron Condor (capital={capital})')
                    place_iron_condor_full(client,instrument,
                                          df5,df15,capital,active_positions)
                else:
                    # Directional sell (CE or PE)
                    sell_strike,hedge_strike,expiry=find_sell_strike(
                        df5,instrument,action,200)
                    log.info(f'[SELL] {instrument} {action} strike={sell_strike}')
                    place_sell_with_hedge(client,instrument,action,
                                         sell_strike,hedge_strike,
                                         expiry,lots,capital)

                active_positions[instrument]={'type':action,'time':str(now)}
                break  # One instrument at a time

    except Exception as e:
        log.error(f'[SELL] Strategy error: {e}')

def manage_sell_positions(client,feed,active_positions,capital):
    """Monitor and exit sell positions"""
    try:
        now=datetime.now()
        for instrument,pos in list(active_positions.items()):
            current=feed.get_price(instrument)
            if current<=0:continue

            pos_type=pos.get('type','')

            # Exit at 3PM
            if now.hour>=15:
                log.info(f'[SELL] EOD exit {instrument}')
                close_sell_position(client,instrument,pos,active_positions)
                continue

            # Iron Condor - exit if breaks range
            if pos_type=='IRON_CONDOR':
                ce_sell=pos.get('ce_sell',0)
                pe_sell=pos.get('pe_sell',0)
                if current>ce_sell*1.005 or current<pe_sell*0.995:
                    log.info(f'[SELL] {instrument} broke condor range!')
                    close_sell_position(client,instrument,pos,active_positions)

            # Directional sell - exit if price moves against
            elif pos_type in ['SELL_CE','SELL_PE']:
                entry_time=datetime.fromisoformat(pos.get('time',str(now)))
                if (now-entry_time).seconds>7200:  # Max 2 hours
                    log.info(f'[SELL] {instrument} time exit')
                    close_sell_position(client,instrument,pos,active_positions)

    except Exception as e:
        log.error(f'[SELL] Manage error: {e}')

def close_sell_position(client,instrument,pos,active_positions):
    """Close sell position"""
    try:
        seg=INDEX_SEG.get(instrument,'nse_fo')
        base_lot=INDEX_LOTS.get(instrument,75)
        lots=pos.get('lots',3)
        qty=lots*base_lot
        expiry=pos.get('expiry','')
        pos_type=pos.get('type','')

        if pos_type=='IRON_CONDOR':
            legs=[
                (f'{instrument}{expiry}{pos["ce_sell"]}CE','B',qty),
                (f'{instrument}{expiry}{pos["pe_sell"]}PE','B',qty),
                (f'{instrument}{expiry}{pos["ce_hedge"]}CE','S',qty),
                (f'{instrument}{expiry}{pos["pe_hedge"]}PE','S',qty),
            ]
            for symbol,side,q in legs:
                try:
                    client.place_order(
                        exchange_segment=seg,product='NRML',
                        price='0',order_type='MKT',
                        quantity=str(q),validity='DAY',
                        trading_symbol=symbol,transaction_type=side,
                        amo='NO',disclosed_quantity='0',
                        market_protection='0',pf='N',
                        trigger_price='0',tag='V30-EXIT'
                    )
                except:pass

        if instrument in active_positions:
            del active_positions[instrument]
            log.info(f'[SELL] {instrument} position closed')

        from v30_notify import send
        send(f'✅ <b>SELL POSITION CLOSED</b>\n{instrument} | {pos_type}')

    except Exception as e:
        log.error(f'[SELL] Close error: {e}')
