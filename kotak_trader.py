import logging,pyotp
from neo_api_client import NeoAPI
log=logging.getLogger(__name__)
class KotakNeoTrader:
    TX={'BUY':'B','SELL':'S'}
    PROD={'EQ':'CNC','CE':'NRML','PE':'NRML','FUT':'NRML'}
    SEG={'NSE-EQ':'nse_cm','NSE-CE':'nse_fo','NSE-PE':'nse_fo','NSE-FUT':'nse_fo','BSE-EQ':'bse_cm','MCX-FUT':'mcx_fo'}
    def __init__(self,consumer_key,mobile_number,mpin,ucc,totp_secret,environment='prod'):
        self.consumer_key=consumer_key
        self.mobile_number=mobile_number
        self.mpin=mpin
        self.ucc=ucc
        self.totp_secret=totp_secret
        self.environment=environment
        self.client=None
    def login(self):
        totp=pyotp.TOTP(self.totp_secret).now()
        self.client=NeoAPI(environment=self.environment,access_token=None,neo_fin_key=None,consumer_key=self.consumer_key)
        resp=self.client.totp_login(mobile_number=self.mobile_number,ucc=self.ucc,totp=totp)
        log.info(f'Login:{resp}')
    def complete_login(self,otp=None):
        resp=self.client.totp_validate(mpin=self.mpin)
        log.info(f'Validate:{resp}')
    def risk_check(self,signal,cfg):
        if signal.get('segment') not in cfg.get('allowed_segments',['EQ','CE','PE','FUT']):return False
        if signal.get('quantity',1)>cfg.get('max_quantity',500):return False
        if cfg.get('require_sl',True) and not signal.get('stop_loss'):return False
        return True
    def _symbol(self,s):
        seg=s.get('segment','EQ')
        return s['symbol']+('-EQ' if seg=='EQ' else seg)
    def _seg(self,s):
        return self.SEG.get(s.get('exchange','NSE')+'-'+s.get('segment','EQ'),'nse_cm')
    def _order(self,signal,action,price,otype,trigger,tag,qty=None):
        q=qty or signal.get('quantity',1)
        return self.client.place_order(exchange_segment=self._seg(signal),product=self.PROD.get(signal.get('segment','EQ'),'CNC'),price=str(price) if price else '0',order_type=otype,quantity=str(q),validity='DAY',trading_symbol=self._symbol(signal),transaction_type=self.TX[action],amo='NO',disclosed_quantity='0',market_protection='0',pf='N',trigger_price=str(trigger) if trigger else '0',tag=tag)
    def place_order(self,s):
        return self._order(s,s['action'],s.get('entry_price'),'L' if s.get('entry_price') else 'MKT',None,'KairosX')
    def place_sl_order(self,s):
        a='SELL' if s['action']=='BUY' else 'BUY'
        return self._order(s,a,None,'SL-M',s['stop_loss'],'KairosX-SL')
    def place_target_order(self,s,target,n=1):
        a='SELL' if s['action']=='BUY' else 'BUY'
        q=max(1,s.get('quantity',1)//len(s.get('targets',[target])))
        return self._order(s,a,target,'L',None,f'KairosX-T{n}',q)
