import os
import time
from functools import wraps
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from fetch.fundamentus import parse
from config import TICKERS_CONHECIDOS
import requests

app = Flask(__name__)
CORS(app)

# === Cache em memória ===
_cache = {}
CACHE_TTL = 3600

def cached(ttl=CACHE_TTL):
    def decorator(f):
        @wraps(f)
        def wrapper(ticker):
            now = time.time()
            key = ticker.upper()
            if key in _cache and now - _cache[key]["ts"] < ttl:
                return _cache[key]["data"]
            data = f(key)
            if data is not None:
                _cache[key] = {"data": data, "ts": now}
            return data
        return wrapper
    return decorator

def calc_extra(dados: dict) -> dict:
    dl = dados.get("Divida Líquida")
    eb = dados.get("EBIT")
    pat = dados.get("Patrim. Líq")
    dl_ebit = round(dl / eb, 2) if (dl is not None and eb is not None and eb != 0) else None
    dl_pl = round(dl / pat, 2) if (dl is not None and pat is not None and pat != 0) else None
    return {"Div Liq/EBIT": dl_ebit, "Div Liq/Patrim": dl_pl}

def fmt_valor(chave: str, val: float | None) -> str:
    if val is None:
        return "N/A"
    if chave == "preco":
        return f"R$ {val:.2f}"
    if chave in ("Market Cap", "EV"):
        if val >= 1e12:
            return f"R$ {val/1e12:.2f}T"
        return f"R$ {val/1e9:.2f}B"
    if chave in ("Ativo", "Patrim. Líq", "Divida Bruta", "Divida Líquida",
                 "Disponibilidades", "Receita Líquida", "EBIT", "Lucro Líquido"):
        if val >= 1e12:
            return f"R$ {val/1e12:.2f}T"
        return f"R$ {val/1e9:.2f}B"
    if chave in ("Cresc. Rec. 5a", "Div. Yield", "Marg. Bruta",
                 "Marg. EBIT", "Marg. Líquida", "ROIC", "ROE"):
        return f"{val:.2f}%"
    if chave in ("EV/EBITDA", "EV/EBIT"):
        return f"{val:.2f}x"
    if chave == "Nro Ações":
        return f"{val:_.0f}".replace("_", ".")
    return f"{val:.2f}"

@cached()
def buscar_dados(ticker: str) -> dict | None:
    try:
        raw = parse(ticker)
    except requests.exceptions.RequestException:
        return None
    if not raw or raw.get("preco") is None:
        return None
    extra = calc_extra(raw)
    raw.update(extra)
    ordem = [
        "preco", "P/L", "P/VP", "PSR",
        "EV/EBITDA", "EV/EBIT",
        "Cresc. Rec. 5a", "Div. Yield",
        "Marg. Bruta", "Marg. EBIT", "Marg. Líquida",
        "ROIC", "ROE",
        "Div Liq/Patrim", "Div Liq/EBIT",
        "Market Cap",
    ]
    nome = TICKERS_CONHECIDOS.get(ticker.upper(), {}).get("nome", ticker.upper())
    itens = []
    for chave in ordem:
        val = raw.get(chave)
        itens.append({
            "chave": chave,
            "valor": val,
            "formatado": fmt_valor(chave, val),
        })
    return {"ticker": ticker.upper(), "nome": nome, "itens": itens}

@app.route("/")
def index():
    return render_template("dashboard.html", ticker=None, dados=None)

@app.route("/ticker/<ticker>")
def ticker_page(ticker: str):
    dados = buscar_dados(ticker.upper())
    return render_template("dashboard.html", ticker=ticker.upper(), dados=dados)

@app.route("/api/<ticker>")
def api_ticker(ticker: str):
    dados = buscar_dados(ticker.upper())
    if dados is None:
        return jsonify({"erro": f"Ticker {ticker.upper()} nao encontrado"}), 404
    return jsonify(dados)

@app.route("/api/pine-flat/<ticker>")
def api_pine_flat(ticker: str):
    dados = buscar_dados(ticker.upper())
    if dados is None:
        return jsonify({"erro": f"Ticker {ticker.upper()} nao encontrado"}), 404
    flat = {"ticker": dados["ticker"], "nome": dados["nome"]}
    for item in dados["itens"]:
        flat[item["chave"]] = item["valor"]
    return jsonify(flat)

@app.route("/api/pine/<ticker>")
def api_pine_code(ticker: str):
    codigo = gerar_pine_script(ticker.upper())
    return codigo, 200, {"Content-Type": "text/plain; charset=utf-8"}

# Geração do Pine Script (código embutido, sem http.get)
PINE_TEMPLATE = '''//@version=6
indicator("Fundamentus - {TICKER}", overlay=true)

// Gerado em {DATA} pelo Fundamentus Scraper
// Dados exatos de fundamentus.com.br

tamanho = input.int(2, "Tamanho (1=P, 2=M, 3=G)", minval=1, maxval=3)
ts = tamanho == 1 ? size.tiny : tamanho == 2 ? size.small : size.normal

// === Dados do Fundamentus ===
{VARIAVEIS}

// === Formatacao ===
f(v, d) => na(v) ? "N/A" : str.tostring(math.round(v, d))
fp(v, d) => na(v) ? "N/A" : str.tostring(math.round(v, d)) + "%"
fm(v, d) => na(v) ? "N/A" : str.tostring(math.round(v, d)) + "x"
fb(v) => na(v) ? "N/A" : str.tostring(math.round(v / 1e9, 2)) + "B"
cor(v) => na(v) ? color.gray : color.white

rw(t, l, lb, v, nv, b1, b2) =>
    bg = l % 2 == 0 ? b1 : b2
    table.cell(t, 0, l, lb, text_color=color.white, bgcolor=bg, text_size=ts)
    table.cell(t, 1, l, v, text_color=cor(nv), bgcolor=bg, text_size=ts)

var scr = table.new(position.top_right, 2, {NLINHAS}, border_width=1, border_color=color.gray)

if barstate.islast
    table.cell(scr, 0, 0, "Indicador", text_color=color.white, bgcolor=color.new(#1E88E5, 30), text_size=ts)
    table.cell(scr, 1, 0, "Valor", text_color=color.white, bgcolor=color.new(#1E88E5, 30), text_size=ts)

{LINHAS}
'''

def gerar_pine_script(ticker: str) -> str:
    dados = buscar_dados(ticker.upper())
    if not dados:
        return f"// Erro ao buscar {ticker} no Fundamentus"

    import datetime
    hoje = datetime.date.today().strftime("%d/%m/%Y")

    def fmt(chave):
        if chave in ("Cresc. Rec. 5a", "Div. Yield", "Marg. Bruta", "Marg. EBIT", "Marg. Líquida", "ROIC", "ROE"):
            return "fp"
        if chave in ("EV/EBITDA", "EV/EBIT"):
            return "fm"
        if chave in ("Market Cap",):
            return "fb"
        return "f"

    linhas = []
    vars_code = []
    for i, item in enumerate(dados["itens"]):
        nm = f"v{i+1}"
        v = item["valor"]
        if v is not None:
            vars_code.append(f"float {nm} = {v}")
        else:
            vars_code.append(f"float {nm} = na")
        k = item["chave"]
        fname = fmt(k)
        fn = f"{fname}({nm}, 2)" if fname != "fb" else f"fb({nm})"
        alt1 = 'color.new(#1a1a2e, 50)' if i % 2 == 0 else 'color.new(#16213e, 50)'
        alt2 = 'color.new(#16213e, 50)' if i % 2 == 0 else 'color.new(#1a1a2e, 50)'
        linhas.append(f'    rw(scr, {i+1}, "{k}", {fn}, {nm}, {alt1}, {alt2})')

    n = len(dados["itens"])
    return PINE_TEMPLATE.format(
        TICKER=ticker.upper(),
        DATA=hoje,
        VARIAVEIS="\n".join(vars_code),
        NLINHAS=str(n + 1),
        LINHAS="\n".join(linhas),
    )

@app.route("/api/pine-script-v7/<ticker>")
def api_pine_v7(ticker: str):
    base = request.host_url.rstrip("/")
    codigo = PINE_V7_TEMPLATE.format(TICKER=ticker.upper(), BASE_URL=base)
    return codigo, 200, {"Content-Type": "text/plain; charset=utf-8"}

PINE_V7_TEMPLATE = '''//@version=7
indicator("Fundamentus - {TICKER}", overlay=true)

//
//  INDICADOR DINAMICO — Fundamentus
//  =================================
//  Este script busca dados REAIS do Fundamentus.com.br
//  via API HTTP. Nao precisa copiar e colar dados nunca mais.
//
//  Como usar:
//    1. Troque o ticker no input abaixo
//    2. Clique em "Atualizar" para buscar dados frescos
//    3. A tabela aparece no canto superior direito do grafico
//
//  API: {BASE_URL}
//

// === Inputs ===
tickerInput = input.string("{TICKER}", "Ticker",
  group="Fundamentus", tooltip="Digite o ticker desejado (ex: WEGE3, PETR4, VALE3)")
refreshInput = input.button("🔄 Atualizar Agora", group="Fundamentus")

// === Tamanho da tabela ===
sizeInput = input.int(2, "Tamanho", minval=1, maxval=3,
  group="Aparencia", tooltip="1=Pequeno, 2=Medio, 3=Grande")
ts = sizeInput == 1 ? size.tiny : sizeInput == 2 ? size.small : size.normal

// === HTTP Request ===
url = "{BASE_URL}/api/pine-flat/" + tickerInput
[body, statusCode, _] = http.get(url, timeout=10)

// === Parse do JSON ===
var jsonData = na
if statusCode == 200
    jsonData := json.parse(body)

// === Helper functions ===
fmt(v, d) => na(v) ? "---" : str.tostring(math.round(v, d))
fmtPct(v, d) => na(v) ? "---" : str.tostring(math.round(v, d)) + "%"
fmtMult(v, d) => na(v) ? "---" : str.tostring(math.round(v, d)) + "x"
fmtBilhao(v) =>
    if na(v)
        "---"
    else
        b = v / 1e9
        if b >= 1000
            str.tostring(math.round(b / 1000, 2)) + "T"
        else
            str.tostring(math.round(b, 2)) + "B"

colorFor(val) => na(val) ? color.gray : color.white

// === Guarda os valores em variaveis ===
var preco = na
var pl = na
var pvp = na
var psr = na
var evebitda = na
var evebit = na
var cresc = na
var dy = na
var margBruta = na
var margEbit = na
var margLiq = na
var roic = na
var roe = na
var divLiqPat = na
var divLiqEbit = na
var mktCap = na

if not na(jsonData)
    preco := jsonData.get("preco")
    pl := jsonData.get("P/L")
    pvp := jsonData.get("P/VP")
    psr := jsonData.get("PSR")
    evebitda := jsonData.get("EV/EBITDA")
    evebit := jsonData.get("EV/EBIT")
    cresc := jsonData.get("Cresc. Rec. 5a")
    dy := jsonData.get("Div. Yield")
    margBruta := jsonData.get("Marg. Bruta")
    margEbit := jsonData.get("Marg. EBIT")
    margLiq := jsonData.get("Marg. Líquida")
    roic := jsonData.get("ROIC")
    roe := jsonData.get("ROE")
    divLiqPat := jsonData.get("Div Liq/Patrim")
    divLiqEbit := jsonData.get("Div Liq/EBIT")
    mktCap := jsonData.get("Market Cap")

// === Monta a tabela ===
row(t, line, label, value, rawVal, color1, color2) =>
    bg = line % 2 == 0 ? color1 : color2
    table.cell(t, 0, line, label, text_color=color.white, bgcolor=bg, text_size=ts)
    table.cell(t, 1, line, value, text_color=colorFor(rawVal), bgcolor=bg, text_size=ts)

var tableName = table.new(position.top_right, 2, 17, border_width=1, border_color=color.gray)

if barstate.islast
    // Header
    table.cell(tableName, 0, 0, "Indicador", text_color=color.white,
      bgcolor=color.new(#1E88E5, 30), text_size=ts)
    table.cell(tableName, 1, 0, "Valor", text_color=color.white,
      bgcolor=color.new(#1E88E5, 30), text_size=ts)

    // Linhas
    row(tableName, 1, "Preco", fmt(preco, 2), preco,
      color.new(#1a1a2e, 50), color.new(#16213e, 50))
    row(tableName, 2, "P/L", fmt(pl, 2), pl,
      color.new(#16213e, 50), color.new(#1a1a2e, 50))
    row(tableName, 3, "P/VP", fmt(pvp, 2), pvp,
      color.new(#1a1a2e, 50), color.new(#16213e, 50))
    row(tableName, 4, "P/SR", fmt(psr, 2), psr,
      color.new(#16213e, 50), color.new(#1a1a2e, 50))
    row(tableName, 5, "EV/EBITDA", fmtMult(evebitda, 2), evebitda,
      color.new(#1a1a2e, 50), color.new(#16213e, 50))
    row(tableName, 6, "EV/EBIT", fmtMult(evebit, 2), evebit,
      color.new(#16213e, 50), color.new(#1a1a2e, 50))
    row(tableName, 7, "Cresc. Rec. 5a", fmtPct(cresc, 2), cresc,
      color.new(#1a1a2e, 50), color.new(#16213e, 50))
    row(tableName, 8, "Div. Yield", fmtPct(dy, 2), dy,
      color.new(#16213e, 50), color.new(#1a1a2e, 50))
    row(tableName, 9, "Marg. Bruta", fmtPct(margBruta, 2), margBruta,
      color.new(#1a1a2e, 50), color.new(#16213e, 50))
    row(tableName, 10, "Marg. EBIT", fmtPct(margEbit, 2), margEbit,
      color.new(#16213e, 50), color.new(#1a1a2e, 50))
    row(tableName, 11, "Marg. Liquida", fmtPct(margLiq, 2), margLiq,
      color.new(#1a1a2e, 50), color.new(#16213e, 50))
    row(tableName, 12, "ROIC", fmtPct(roic, 2), roic,
      color.new(#16213e, 50), color.new(#1a1a2e, 50))
    row(tableName, 13, "ROE", fmtPct(roe, 2), roe,
      color.new(#1a1a2e, 50), color.new(#16213e, 50))
    row(tableName, 14, "DL/Patrim.", fmt(divLiqPat, 2), divLiqPat,
      color.new(#16213e, 50), color.new(#1a1a2e, 50))
    row(tableName, 15, "DL/EBIT", fmt(divLiqEbit, 2), divLiqEbit,
      color.new(#1a1a2e, 50), color.new(#16213e, 50))
    row(tableName, 16, "Market Cap", fmtBilhao(mktCap), mktCap,
      color.new(#16213e, 50), color.new(#1a1a2e, 50))
'''

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False)
