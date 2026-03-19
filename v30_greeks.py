import requests
import numpy as np
from datetime import datetime

HEADERS={'User-Agent':'Mozilla/5.0','Accept':'application/json','Referer':'https://www.nseindia.com'}

def get_nse_session():
    s=requests.Session()
    s.get('https://www.nseindia.com',headers=HEADERS,timeout=10)
    return s

def get_option_greeks(symbol,strike,option_type,expiry=None):
    try:
        s=get_nse_session()
        url=f'https://www.nseindia.com/api/option-chain-indices?symbol={symbol}'
        r=s.get(url,headers=HEADERS,timeout=10)
        data=r.json()
        for rec in data['records']['data']:
            if rec.get('strikePrice')==strike:
                opt=rec.get(option_type,{})
                if opt:
                    return {
                        'delta':opt.get('delta',0),
                        'gamma':opt.get('gamma',0),
                        'theta':opt.get('theta',0),
                        'vega':opt.get('vega',0),
                        'iv':opt.get('impliedVolatility',0),
                        'oi':opt.get('openInterest',0),
                        'oi_change':opt.get('changeinOpenInterest',0),
                        'premium':opt.get('lastPrice',0)
                    }
        return None
    except Exception as e:
        print(f'[GREEKS] Error: {e}')
        return None

def get_iv_rank(symbol,current_iv):
    try:
        # IV rank - if current IV is low compared to 52 week range, options are cheap
        # Approximate using VIX as proxy
        s=get_nse_session()
        r=s.get('https://www.nseindia.com/api/allIndices',headers=HEADERS,timeout=10)
        data=r.json()
        for idx in data.get('data',[]):
            if idx.get('index')=='INDIA VIX':
                vix=float(idx.get('last',15))
                year_high=float(idx.get('yearHigh',25))
                year_low=float(idx.get('yearLow',10))
                iv_rank=((vix-year_low)/(year_high-year_low))*100 if year_high!=year_low else 50
                return round(iv_rank,1)
        return 50
    except:
        return 50

def check_greeks_filter(symbol,strike,option_type,current_price):
    try:
        greeks=get_option_greeks(symbol,strike,option_type)
        if not greeks:
            # If can't get greeks, use basic premium filter
            return True,{'reason':'NO_GREEKS_DATA'}

        delta=abs(greeks.get('delta',0.5))
        theta=abs(greeks.get('theta',0))
        iv=greeks.get('iv',20)
        premium=greeks.get('premium',0)
        iv_rank=get_iv_rank(symbol,iv)

        results={
            'delta':delta,
            'theta':theta,
            'iv':iv,
            'iv_rank':iv_rank,
            'premium':premium
        }

        # Delta filter - not too far OTM
        if delta < 0.25:
            return False,{**results,'reason':'LOW_DELTA_DEEP_OTM'}

        # IV rank filter - avoid expensive options
        if iv_rank > 80:
            return False,{**results,'reason':'HIGH_IV_EXPENSIVE'}

        # Premium filter 80-200 range
        if premium > 0 and (premium < 80 or premium > 200):
            return False,{**results,'reason':f'PREMIUM_OUT_OF_RANGE_{premium}'}

        # Theta filter - avoid high decay
        if theta > premium * 0.05:
            return False,{**results,'reason':'HIGH_THETA_DECAY'}

        return True,{**results,'reason':'GREEKS_OK'}

    except Exception as e:
        print(f'[GREEKS] Filter error: {e}')
        return True,{'reason':'GREEKS_ERROR_SKIP'}

def get_best_strike_by_delta(symbol,option_type,target_delta=0.4):
    try:
        s=get_nse_session()
        url=f'https://www.nseindia.com/api/option-chain-indices?symbol={symbol}'
        r=s.get(url,headers=HEADERS,timeout=10)
        data=r.json()
        best_strike=None
        best_diff=999
        best_premium=0
        for rec in data['records']['data']:
            opt=rec.get(option_type,{})
            if not opt:continue
            delta=abs(opt.get('delta',0))
            premium=opt.get('lastPrice',0)
            if 80<=premium<=200:
                diff=abs(delta-target_delta)
                if diff<best_diff:
                    best_diff=diff
                    best_strike=rec['strikePrice']
                    best_premium=premium
        print(f'[GREEKS] Best {option_type} strike:{best_strike} premium:{best_premium} delta_diff:{best_diff:.2f}')
        return best_strike,best_premium
    except Exception as e:
        print(f'[GREEKS] Best strike error: {e}')
        return None,0
