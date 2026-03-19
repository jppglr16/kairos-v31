from v31_gamma import get_nse_session

s=get_nse_session()
if not s:
    print('Session failed!')
    exit()

url="https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
r=s.get(url,timeout=10)
data=r.json()
rec=data.get("records",{})

print("Status:",r.status_code)
print("Records:",len(rec.get("data",[])))
print("Expiry:",rec.get("expiryDates",[])[:3])

# Test BANKNIFTY too
url2="https://www.nseindia.com/api/option-chain-indices?symbol=BANKNIFTY"
r2=s.get(url2,timeout=10)
data2=r2.json()
rec2=data2.get("records",{})
print("BANKNIFTY Records:",len(rec2.get("data",[])))
