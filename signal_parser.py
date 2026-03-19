import re,logging
log=logging.getLogger(__name__)
class KairosSignalParser:
    def parse(self,text):
        if not text:return None
        tl=text.lower()
        if not any(k in tl for k in ['buy','sell','entry','target','signal','long','short']):return None
        s={}
        tu=text.upper()
        if re.search(r'\bBUY\b|\bLONG\b',tu):s['action']='BUY'
        elif re.search(r'\bSELL\b|\bSHORT\b',tu):s['action']='SELL'
        else:return None
        m=re.search(r'(?:BUY|SELL|LONG|SHORT)\s*[|:\-]?\s*([A-Z]{2,20})',tu)
        if not m:return None
        sym=m.group(1).strip()
        if sym in {'NSE','BSE','MCX','NFO','EQ','CE','PE','FUT'}:return None
        s['symbol']=sym
        s['exchange']='MCX' if 'MCX' in tu else 'NFO' if 'NFO' in tu or 'F&O' in tu else 'NSE'
        s['segment']='CE' if re.search(r'\bCE\b',tu) else 'PE' if re.search(r'\bPE\b',tu) else 'FUT' if re.search(r'\bFUT\b',tu) else 'EQ'
        m=re.search(r'[Ee]ntry\s*[:\-]?\s*([\d.]+)\s*[-to]+\s*([\d.]+)',text)
        if m:s['entry_price']=float(m.group(1))
        else:
            m=re.search(r'[Ee]ntry\s*[:\-]?\s*([\d.]+)',text)
            s['entry_price']=float(m.group(1)) if m else None
        m=re.search(r'(?:[Ss]top\s*[Ll]oss|SL)\s*[:\-]?\s*([\d.]+)',text)
        s['stop_loss']=float(m.group(1)) if m else None
        s['targets']=[float(x) for x in re.findall(r'[Tt]arget\s*\d?\s*[:\-]?\s*([\d.]+)',text)]
        m=re.search(r'(?:[Qq]ty|[Ll]ots?)\s*[:/]?\s*(\d+)',text)
        s['quantity']=int(m.group(1)) if m else 1
        s['order_type']='L' if s.get('entry_price') else 'MKT'
        return s
