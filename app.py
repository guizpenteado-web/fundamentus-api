import os
import re
import time
from functools import wraps
from flask import Flask, jsonify, request
from flask_cors import CORS
import requests

app = Flask(__name__)
CORS(app)

URL_FUNDAMENTUS = "https://www.fundamentus.com.br/detalhes.php?papel="
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def parse(papel: str) -> dict:
    resp = requests.get(URL_FUNDAMENTUS + papel.upper(), headers=HEADERS, timeout=15)
    html = resp.text
    def pegar(rotulo: str) -> float | None:
        idx_rot = html.find(f'<span class="txt">{rotulo}</span>')
        if idx_rot < 0: return None
        chunk = html[idx_rot:]
        m = re.search(r'<td\s+class="data[^"]*">\s*<span\s+class="txt">\s*([\d.\-,%R$ ]+?)\s*</span>', chunk)
        if not m: return None
        val = m.group(1).strip().replace("R$","").replace("$","").replace("%","").replace("x","").replace(".","").replace(",",".").replace(" ","")
        if not val or val == "-": return None
        try: return float(val)
        except: return None
    def pegar_reais(rotulo: str) -> float | None:
        idx_rot = html.find(f'<span class="txt">{rotulo}</span>')
        if idx_rot < 0: return None
        chunk = html[idx_rot:]
        m = re.search(r'<td\s+class="data[^"]*">\s*<span\s+class="txt">\s*([\d.\-]+?)\s*</span>', chunk)
        if not m: return None
        val = m.group(1).strip().replace(".","")
        if not val or val == "-": return None
        try: return float(val)
        except: return None
    return {
        "preco": pegar("Cotação"), "P/L": pegar("P/L"), "P/VP": pegar("P/VP"),
        "PSR": pegar("PSR"), "Div. Yield": pegar("Div. Yield"),
        "EV/EBITDA": pegar("EV / EBITDA"), "EV/EBIT": pegar("EV / EBIT"),
        "Cresc. Rec. 5a": pegar("Cres. Rec (5a)"),
        "Marg. Bruta": pegar("Marg. Bruta"), "Marg. EBIT": pegar("Marg. EBIT"),
        "Marg. Líquida": pegar("Marg. Líquida"), "ROIC": pegar("ROIC"),
        "ROE": pegar("ROE"), "Dív.Líq./Patrim.": pegar("Dív Líq / Patrim"),
        "Market Cap": pegar_reais("Valor de mercado"),
    }

_cache = {}
CACHE_TTL = 3600

def cached(ttl=CACHE_TTL):
    def decorator(f):
        @wraps(f)
        def wrapper(ticker):
            now = time.time(); key = ticker.upper()
            if key in _cache and now - _cache[key]["ts"] < ttl: return _cache[key]["data"]
            data = f(key)
            if data is not None: _cache[key] = {"data": data, "ts": now}
            return data
        return wrapper
    return decorator

@cached()
def buscar_dados(ticker: str) -> dict | None:
    try: raw = parse(ticker)
    except: return None
    if not raw or raw.get("preco") is None: return None
    dl = raw.get("Dív. Líquida") or raw.get("Divida Líquida")
    eb = raw.get("EBIT"); pat = raw.get("Patrim. Líq")
    raw["Div Liq/EBIT"] = round(dl / eb, 2) if (dl and eb and eb != 0) else None
    raw["Div Liq/Patrim"] = round(dl / pat, 2) if (dl and pat and pat != 0) else None
    ordem = ["preco","P/L","P/VP","PSR","EV/EBITDA","EV/EBIT","Cresc. Rec. 5a",
             "Div. Yield","Marg. Bruta","Marg. EBIT","Marg. Líquida","ROIC","ROE",
             "Div Liq/Patrim","Div Liq/EBIT","Market Cap"]
    itens = [{"chave": k, "valor": raw.get(k)} for k in ordem]
    return {"ticker": ticker.upper(), "nome": ticker.upper(), "itens": itens}

@app.route("/api/<ticker>")
def api_ticker(ticker: str):
    dados = buscar_dados(ticker.upper())
    return (jsonify(dados) if dados else (jsonify({"erro": "Nao encontrado"}), 404))

@app.route("/api/pine-flat/<ticker>")
def api_pine_flat(ticker: str):
    dados = buscar_dados(ticker.upper())
    if not dados: return jsonify({"erro": "Nao encontrado"}), 404
    flat = {"ticker": dados["ticker"], "nome": dados["nome"]}
    for item in dados["itens"]: flat[item["chave"]] = item["valor"]
    return jsonify(flat)

@app.route("/api/pine-script-v7/<ticker>")
def api_pine_v7(ticker: str):
    base = request.host_url.rstrip("/")
    codigo = '''//@version=7
indicator("Fundamentus", overlay=true)
tickerInput = input.string("''' + ticker.upper() + '''", "Ticker", group="Fundamentus")
refreshInput = input.button("Atualizar", group="Fundamentus")
sizeInput = input.int(2, "Tamanho", minval=1, maxval=3, group="Aparencia")
ts = sizeInput == 1 ? size.tiny : sizeInput == 2 ? size.small : size.normal
url = "''' + base + '''/api/pine-flat/" + tickerInput
[body, statusCode, _] = http.get(url, timeout=10)
var jsonData = na
if statusCode == 200: jsonData := json.parse(body)
fmt(v, d) => na(v) ? "---" : str.tostring(math.round(v, d))
fmtPct(v, d) => na(v) ? "---" : str.tostring(math.round(v, d)) + "%"
fmtMult(v, d) => na(v) ? "---" : str.tostring(math.round(v, d)) + "x"
fmtBilhao(v) => na(v) ? "---" : str.tostring(math.round(v / 1e9, 2)) + "B"
var preco=na,pl=na,pvp=na,psr=na,evebitda=na
var evebit=na,cresc=na,dy=na,margBruta=na,margEbit=na
var margLiq=na,roic=na,roe=na,divLiqPat=na,divLiqEbit=na,mktCap=na
if not na(jsonData)
    preco:=jsonData.get("preco"); pl:=jsonData.get("P/L"); pvp:=jsonData.get("P/VP")
    psr:=jsonData.get("PSR"); evebitda:=jsonData.get("EV/EBITDA")
    evebit:=jsonData.get("EV/EBIT"); cresc:=jsonData.get("Cresc. Rec. 5a")
    dy:=jsonData.get("Div. Yield"); margBruta:=jsonData.get("Marg. Bruta")
    margEbit:=jsonData.get("Marg. EBIT"); margLiq:=jsonData.get("Marg. Líquida")
    roic:=jsonData.get("ROIC"); roe:=jsonData.get("ROE")
    divLiqPat:=jsonData.get("Div Liq/Patrim"); divLiqEbit:=jsonData.get("Div Liq/EBIT")
    mktCap:=jsonData.get("Market Cap")
cor(v)=>na(v)?color.gray:color.white
rw(t,l,lb,vl,rv,z,p)=>
    bg=l%2==0?z:p
    table.cell(t,0,l,lb,text_color=color.white,bgcolor=bg,text_size=ts)
    table.cell(t,1,l,vl,text_color=cor(rv),bgcolor=bg,text_size=ts)
var tbl=table.new(position.top_right,2,17,border_width=1,border_color=color.gray)
if barstate.islast
    table.cell(tbl,0,0,"Indicador",text_color=color.white,bgcolor=color.new(#1E88E5,30),text_size=ts)
    table.cell(tbl,1,0,"Valor",text_color=color.white,bgcolor=color.new(#1E88E5,30),text_size=ts)
    z=color.new(#1a1a2e,50);p=color.new(#16213e,50)
    rw(tbl,1,"Preco",fmt(preco,2),preco,z,p);rw(tbl,2,"P/L",fmt(pl,2),pl,p,z)
    rw(tbl,3,"P/VP",fmt(pvp,2),pvp,z,p);rw(tbl,4,"P/SR",fmt(psr,2),psr,p,z)
    rw(tbl,5,"EV/EBITDA",fmtMult(evebitda,2),evebitda,z,p);rw(tbl,6,"EV/EBIT",fmtMult(evebit,2),evebit,p,z)
    rw(tbl,7,"Cresc Rec 5a",fmtPct(cresc,2),cresc,z,p);rw(tbl,8,"Div Yield",fmtPct(dy,2),dy,p,z)
    rw(tbl,9,"Marg Bruta",fmtPct(margBruta,2),margBruta,z,p);rw(tbl,10,"Marg EBIT",fmtPct(margEbit,2),margEbit,p,z)
    rw(tbl,11,"Marg Liquida",fmtPct(margLiq,2),margLiq,z,p);rw(tbl,12,"ROIC",fmtPct(roic,2),roic,p,z)
    rw(tbl,13,"ROE",fmtPct(roe,2),roe,z,p);rw(tbl,14,"DL/Patrim",fmt(divLiqPat,2),divLiqPat,p,z)
    rw(tbl,15,"DL/EBIT",fmt(divLiqEbit,2),divLiqEbit,z,p);rw(tbl,16,"Market Cap",fmtBilhao(mktCap),mktCap,p,z)'''
    return codigo, 200, {"Content-Type": "text/plain; charset=utf-8"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False)
