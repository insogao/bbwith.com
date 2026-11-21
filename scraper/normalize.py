import json,re
DOLLAR={"au":"AUD","ca":"CAD","cl":"CLP","co":"COP","mx":"MXN","nz":"NZD","us":"USD"}
SYM={"USD":"USD","US$":"USD","€":"EUR","AED":"AED","R$":"BRL","CHF":"CHF","Kč":"CZK","EGP":"EGP","£":"GBP","HUF":"HUF","₹":"INR","₪":"ILS","₸":"KZT","￦":"KRW","RM":"MYR","₦":"NGN","Rs":"PKR","S/":"PEN","₱":"PHP","zł":"PLN","QAR":"QAR","lei":"RON","SAR":"SAR","S$":"SGD","฿":"THB","₺":"TRY","NT$":"TWD","TZS":"TZS","đ":"VND","R":"ZAR","HK$":"HKD","RUB":"RUB","Rp":"IDR","Rpribu":"IDR","Rpjuta":"IDR"}
KR={"dk":"DKK","no":"NOK","se":"SEK"}; YEN={"jp":"JPY","cn":"CNY"}
def num(s):
    s=re.sub(r'[^\d.,]','',s)
    if "," in s and "." in s:
        dec = "," if s.rfind(",")>s.rfind(".") else "."
        s=s.replace("." if dec=="," else ",","").replace(",",".")
    elif "," in s or "." in s:
        sep="," if "," in s else "."
        parts=s.split(sep)
        if len(parts[-1])==3 and len(parts)>=2: s=s.replace(sep,"")
        else: s="".join(parts[:-1])+"."+parts[-1]
    return float(s)
def parse(cc,p):
    sym=re.sub(r'[\d.,\s\xa0 ]','',p)
    if sym=="$": cur=DOLLAR.get(cc,"USD")
    elif sym=="kr": cur=KR[cc]
    elif sym=="¥": cur=YEN[cc]
    else: cur=SYM[sym]
    v=num(p)
    if sym=="Rpribu": v*=1000
    if sym=="Rpjuta":
        v=float(re.sub(r'[^\d.,]','',p).replace(",","."))*1e6
    return cur,v
