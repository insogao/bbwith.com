import re,json,sys
def iaps(html):
    m=re.search(r'In-App Purchases","summary":"[^"]*","items":(\[.*?\])\s*[,}]\s*"', html)
    out=[]
    for a,b in re.findall(r'"leadingText":"((?:[^"\\]|\\.)*)","trailingText":"((?:[^"\\]|\\.)*)"', html[html.find('In-App Purchases","summary'):][:20000]):
        out.append((json.loads('"'+a+'"'),json.loads('"'+b+'"')))
    return out
if __name__=="__main__":
    print(iaps(open(sys.argv[1],encoding='utf8').read()))
