def get_brokerage(qty, price, instrument):
    # Flat fee per order (like Zerodha)
    flat_fee = 20  # ₹20 per order

    # STT (Securities Transaction Tax)
    turnover = price * qty
    if instrument in ['NIFTY','BANKNIFTY','SENSEX','FINNIFTY','MIDCPNIFTY']:
        stt = turnover * 0.000625  # Options STT
    elif instrument in ['CRUDEOIL','GOLDM','SILVERM']:
        stt = turnover * 0.0001
    else:
        stt = turnover * 0.000625

    # Exchange fees
    exchange = turnover * 0.0000335

    # GST on brokerage
    gst = flat_fee * 0.18

    # SEBI charges
    sebi = turnover * 0.000001

    # Stamp duty
    stamp = turnover * 0.00003

    total = flat_fee + stt + exchange + gst + sebi + stamp
    return round(total, 2)

def get_brokerage_simple(lots):
    # Simple calculation
    # 1 lot: ~₹25
    # 2 lots: ~₹45
    # 3 lots: ~₹65
    if lots==1: return 25
    elif lots==2: return 45
    elif lots==3: return 65
    else: return lots * 20
