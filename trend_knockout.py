"""
TREND KNOCK-OUT - ricerca del vantaggio statistico e segnali giornalieri
========================================================================
Ad ogni esecuzione:
  1. scarica gli storici giornalieri (Yahoo Finance) di 15 strumenti + VIX;
  2. prova ~27 regole (trend, momentum, reversione, calendario, filtro VIX)
     su 7 orizzonti (1-60 giorni) e 3 modalita' (long+short, solo long, solo short);
  3. considera ROBUSTA una regola solo se batte il buy & hold (t >= 2) sia nel
     2010-2019 sia nel 2020-oggi ed e' in utile in entrambi i periodi;
  4. per ogni strumento sceglie la regola robusta migliore (preferendo quelle
     confermate su piu' strumenti della stessa classe) e ne calcola il segnale;
  5. scrive la pagina web docs/index.html e i CSV in docs/dati/;
  6. (facoltativo) invia un riepilogo su Telegram se sono impostate le
     variabili TELEGRAM_TOKEN e TELEGRAM_CHAT_ID (solo quando qualcosa cambia).

Componente geopolitica:
  - storico: Geopolitical Risk Index giornaliero (Caldara e Iacoviello,
    matteoiacoviello.com/gpr.htm). I picchi dell'indice diventano regole
    ("acquisto/vendita dopo un picco geopolitico") testate come tutte le altre;
  - tempo reale: radar dei titoli di Google News. Quando il radar e' "alto"
    viene trattato come un nuovo picco, cosi' le regole geopolitiche robuste
    possono dare il segnale la mattina stessa dell'evento.

Componente macro:
  - tassi e rendimenti giornalieri dal database FRED della Federal Reserve di St. Louis
    (rendimenti USA, tassi reali, inflazione attesa, curva, dollaro, tassi Fed e BCE):
    diventano regole "Macro" testate come le altre;
  - calendario degli appuntamenti (Fed, BCE, Bank of Japan, inflazione e occupazione USA)
    nel file calendario_macro.csv: avvisa nei giorni a rischio, non genera segnali.

Forza del segnale 0-100: 50 punti dalla significativita' statistica,
30 dalle conferme su altri strumenti della classe, 20 dalla percentuale
di operazioni positive dal 2020.

Esecuzione locale:  python trend_knockout.py   (poi apri docs/index.html)
"""

import html
import io
import json
import re
import xml.etree.ElementTree as ET
import os
import time
import urllib.parse
import urllib.request
import warnings
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# CONFIGURAZIONE
# --------------------------------------------------------------------------
STRUMENTI = {
    "S&P 500":       ("^GSPC",      "Indici"),
    "Nasdaq 100":    ("^NDX",       "Indici"),
    "DAX":           ("^GDAXI",     "Indici"),
    "FTSE MIB":      ("FTSEMIB.MI", "Indici"),
    "Euro Stoxx 50": ("^STOXX50E",  "Indici"),
    "Oro":           ("GC=F",       "Commodities"),
    "Argento":       ("SI=F",       "Commodities"),
    "Petrolio WTI":  ("CL=F",       "Commodities"),
    "Gas naturale":  ("NG=F",       "Commodities"),
    "EUR/USD":       ("EURUSD=X",   "Valute"),
    "GBP/USD":       ("GBPUSD=X",   "Valute"),
    "USD/JPY":       ("JPY=X",      "Valute"),
    "EUR/CHF":       ("EURCHF=X",   "Valute"),
    "Bitcoin":       ("BTC-USD",    "Cripto"),
    "Ethereum":      ("ETH-USD",    "Cripto"),
}
ORDINE_CLASSI = ["Indici", "Commodities", "Valute", "Cripto"]
COSTO = {"Indici": 0.0003, "Commodities": 0.0005, "Valute": 0.0002, "Cripto": 0.0015}
# Sulle valute l'apertura giornaliera di Yahoo non e' affidabile: ingresso alla chiusura
ENTRATA_APERTURA = {"Indici": True, "Commodities": True, "Valute": False, "Cripto": True}

INIZIO = "2010-01-01"
SPLIT = pd.Timestamp("2020-01-01")
ORIZZONTI = [1, 3, 5, 10, 20, 40, 60]
MODI = ["Long+Short", "Solo long", "Solo short"]
T_MIN = 2.0
MIN_TRADE = 20
MIN_CONFERME = 2        # segnale operativo solo se la regola vale su almeno 2 strumenti della classe
CARTELLA = "docs"
FUSO = ZoneInfo("Europe/Rome")

GPR_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls"
UA = {"User-Agent": "Mozilla/5.0 (trend-knockout personal research)"}

# Radar notizie: ricerche su Google News nelle ultime 24 ore
RADAR_QUERY = [
    "airstrike OR \"missile strike\" OR bombing",
    "invasion OR \"declares war\" OR \"troops cross\"",
    "Iran OR Israel OR Hormuz attack",
    "Russia Ukraine attack OR pipeline sabotage",
    "Taiwan OR \"North Korea\" military",
]
# Un titolo conta solo se contiene un'AZIONE militare e un ATTORE geopolitico rilevante per i mercati
RADAR_AZIONI = [r"\bair ?strikes?\b", r"\bmissiles?\b", r"\bbomb(s|ed|ing)?\b", r"\binvasion\b",
                r"\binvade[sd]?\b", r"\battack(s|ed)?\b", r"\bstrikes?\b", r"\btroops\b",
                r"\bdrones?\b", r"\bshelling\b", r"\bretaliat\w*", r"\bescalat\w*",
                r"\bwar\b", r"\bblockade\b", r"\bmobiliz\w*", r"\bthreaten(s|ed)?\b",
                r"\bclos(e|es|ed|ure|ing)\b.*\b(strait|hormuz|pipeline|airspace)",
                r"\bseiz(e|es|ed)\b.*\btanker", r"\bsabotage\b"]
RADAR_ESCLUSI = [r"review.?bomb", r"\bposter\b", r"\bmovie\b", r"\bfilm\b", r"\bgame\b",
                 r"\bnovel\b", r"\bbook\b", r"\bfootball\b", r"\bcricket\b", r"\bheart attack\b",
                 r"\bcyber", r"\bprice war\b", r"\btrade war\b", r"\bculture war\b"]
RADAR_GIORNI_CALIBRAZIONE = 10
AREE = {
    "Medio Oriente": (["iran", "israel", "hormuz", "saudi", "yemen", "houthi", "gulf", "iraq",
                       "lebanon", "gaza", "hezbollah", "syria"], "Petrolio, Oro"),
    "Russia/Ucraina": (["russia", "ukrain", "kremlin", "putin", "pipeline", "nord stream",
                        "moscow", "kyiv"], "Gas naturale, Petrolio, Oro"),
    "Asia": (["taiwan", "china", "north korea", "pyongyang", "beijing"], "Oro, Indici"),
}


# --------------------------------------------------------------------------
# DATI
# --------------------------------------------------------------------------
def scarica(ticker, tentativi=3):
    import yfinance as yf
    for k in range(tentativi):
        try:
            df = yf.download(ticker, start=INIZIO, auto_adjust=True, progress=False)
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df[["Open", "High", "Low", "Close"]].dropna()
                df.index = pd.to_datetime(df.index)
                if df.index.tz is not None:
                    df.index = df.index.tz_localize(None)
                df = df[(df["Low"] > 0) & (df["High"] >= df["Low"]) & (df["Close"] > 0)]
                return df[~df.index.duplicated()]
        except Exception as e:
            print(f"   tentativo {k + 1} fallito: {e}")
        time.sleep(5 * (k + 1))
    return None


# --------------------------------------------------------------------------
# GEOPOLITICA: indice GPR storico + radar notizie
# --------------------------------------------------------------------------
def scarica_gpr():
    """Serie giornaliera GPRD (indice di rischio geopolitico). None se non disponibile."""
    try:
        req = urllib.request.Request(GPR_URL, headers=UA)
        dati = urllib.request.urlopen(req, timeout=60).read()
        x = pd.read_excel(io.BytesIO(dati))
        col = {c.lower(): c for c in x.columns}
        if "date" in col:
            d = pd.to_datetime(x[col["date"]], errors="coerce")
        else:
            d = pd.to_datetime(x[col["day"]].astype(str), format="%Y%m%d", errors="coerce")
        serie = pd.Series(pd.to_numeric(x[col["gprd"]], errors="coerce").values, index=d)
        serie = serie[serie.index.notna()].dropna().sort_index()
        serie = serie[~serie.index.duplicated()]
        return serie if len(serie) > 1000 else None
    except Exception as ex:
        print(f"   GPR non disponibile: {ex}")
        return None


def leggi_rss(query):
    q = urllib.parse.quote(f"{query} when:1d")
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers=UA)
    radice = ET.fromstring(urllib.request.urlopen(req, timeout=30).read())
    out = []
    for it in radice.iter("item"):
        titolo = (it.findtext("title") or "").strip()
        try:
            quando = parsedate_to_datetime(it.findtext("pubDate"))
        except Exception:
            quando = None
        out.append({"titolo": titolo, "link": it.findtext("link") or "", "quando": quando})
    return out


def titolo_rilevante(titolo):
    t = titolo.lower()
    if any(re.search(x, t) for x in RADAR_ESCLUSI):
        return False
    if not any(re.search(x, t) for x in RADAR_AZIONI):
        return False
    return any(k in t for kw, _ in AREE.values() for k in kw)


def radar_notizie(storico):
    """Conta i titoli geopolitici delle ultime 24 ore e li confronta con i giorni precedenti."""
    limite = datetime.now(ZoneInfo("UTC")) - timedelta(hours=24)
    visti, titoli = set(), []
    try:
        for q in RADAR_QUERY:
            for t in leggi_rss(q):
                chiave = re.sub(r"\W+", " ", t["titolo"].lower()).strip()[:90]
                if chiave in visti or (t["quando"] and t["quando"] < limite):
                    continue
                if not titolo_rilevante(t["titolo"]):
                    continue
                visti.add(chiave)
                titoli.append(t)
    except Exception as ex:
        print(f"   Radar notizie non disponibile: {ex}")
        return {"livello": "non disponibile", "conteggio": 0, "titoli": [], "aree": []}

    n = len(titoli)
    giorni = len(storico) if storico is not None else 0
    if giorni >= RADAR_GIORNI_CALIBRAZIONE and storico["conteggio"].tail(60).median() > 0:
        rapporto = n / storico["conteggio"].tail(60).median()
        livello = "alto" if (rapporto >= 2.5 and n >= 15) else ("elevato" if rapporto >= 1.5 else "normale")
    else:
        # nei primi giorni il radar raccoglie solo la media di riferimento: nessun allarme
        rapporto = None
        livello = "calibrazione"

    testo = " ".join(t["titolo"].lower() for t in titoli)
    aree = sorted(((a, sum(testo.count(k) for k in kw), asset) for a, (kw, asset) in AREE.items()),
                  key=lambda x: -x[1])
    aree = [(a, c, asset) for a, c, asset in aree if c >= 3]
    titoli.sort(key=lambda t: t["quando"] or limite, reverse=True)
    return {"livello": livello, "conteggio": n, "rapporto": rapporto,
            "titoli": titoli[:6], "aree": aree}


def carica_storico_radar():
    p = os.path.join(CARTELLA, "dati", "radar_storico_v2.csv")
    if os.path.exists(p):
        try:
            return pd.read_csv(p, parse_dates=["data"])
        except Exception:
            pass
    return pd.DataFrame(columns=["data", "conteggio", "livello"])


def salva_storico_radar(storico, radar):
    if radar["livello"] == "non disponibile":
        return storico
    oggi = pd.Timestamp(datetime.now(FUSO).date())
    ordine = {"calibrazione": 0, "normale": 0, "elevato": 1, "alto": 2}
    conteggio, livello = radar["conteggio"], radar["livello"]
    prima = storico[storico["data"] == oggi] if len(storico) else storico
    if len(prima):     # nella stessa giornata si conserva il valore piu' alto
        r0 = prima.iloc[-1]
        conteggio = max(conteggio, int(r0["conteggio"]))
        if ordine.get(r0["livello"], 0) > ordine.get(livello, 0):
            livello = r0["livello"]
    riga = pd.DataFrame([{"data": oggi, "conteggio": conteggio, "livello": livello}])
    storico = storico[storico["data"] != oggi] if len(storico) else storico
    storico = pd.concat([storico, riga], ignore_index=True).sort_values("data").tail(400)
    storico.to_csv(os.path.join(CARTELLA, "dati", "radar_storico_v2.csv"), index=False)
    return storico


def date_picchi_geo(gpr, storico_radar):
    """Date di inizio dei picchi geopolitici: dal GPR storico + dai giorni di radar 'alto' successivi."""
    if gpr is None:
        return [], None
    soglia = gpr.rolling(365, min_periods=180).quantile(0.95)
    picco = (gpr > soglia).astype(int)
    inizio = (picco == 1) & (picco.shift(1).rolling(10, min_periods=1).max() == 0)
    date = list(gpr.index[inizio])
    ultimo_gpr = gpr.index[-1]
    if storico_radar is not None and len(storico_radar):
        alti = storico_radar[(storico_radar["livello"] == "alto") & (storico_radar["data"] > ultimo_gpr)]
        for d in sorted(alti["data"]):
            if not date or (d - date[-1]).days > 14:
                date.append(d)
    # regime di rischio elevato (media 7 giorni nel 20% piu' alto dell'ultimo anno)
    m7 = gpr.rolling(7).mean()
    regime = m7 > m7.rolling(365, min_periods=180).quantile(0.8)
    return date, regime


# --------------------------------------------------------------------------
# MACRO: tassi di mercato (FRED) e calendario degli appuntamenti
# --------------------------------------------------------------------------
FRED = {
    "DGS2": "Rendimento Treasury USA 2 anni",
    "DGS10": "Rendimento Treasury USA 10 anni",
    "DFII10": "Tasso reale USA 10 anni",
    "T10YIE": "Inflazione attesa USA 10 anni",
    "T10Y2Y": "Curva USA (10 anni meno 2 anni)",
    "DTWEXBGS": "Dollaro ponderato",
    "DFEDTARU": "Tasso Fed (limite superiore)",
    "ECBDFR": "Tasso BCE sui depositi",
}
AREE_MACRO = {
    "USA": ["S&P 500", "Nasdaq 100", "Oro", "Argento", "EUR/USD", "GBP/USD", "USD/JPY", "Bitcoin", "Ethereum"],
    "EUROPA": ["DAX", "FTSE MIB", "Euro Stoxx 50", "EUR/USD", "EUR/CHF"],
    "GIAPPONE": ["USD/JPY"],
}


def scarica_fred(codice):
    try:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={codice}"
        req = urllib.request.Request(url, headers=UA)
        x = pd.read_csv(io.BytesIO(urllib.request.urlopen(req, timeout=60).read()))
        d = pd.to_datetime(x.iloc[:, 0], errors="coerce")
        v = pd.to_numeric(x.iloc[:, 1], errors="coerce")
        serie = pd.Series(v.values, index=d).dropna()
        return serie[serie.index.notna()].sort_index() if len(serie) > 500 else None
    except Exception as ex:
        print(f"   FRED {codice} non disponibile: {ex}")
        return None


def scarica_macro():
    out = {}
    for c in FRED:
        s = scarica_fred(c)
        if s is not None:
            out[c] = s
    print(f"   serie macro scaricate: {len(out)} di {len(FRED)}")
    return out


def regole_macro(df, macro):
    """Regole basate sulla direzione dei tassi. Ogni regola ha anche la versione inversa."""
    base = {}

    def al(serie):
        return serie.reindex(df.index, method="ffill", limit=7)

    def segno(x):
        return np.sign(x)

    if "DFII10" in macro:
        for n in (20, 60):
            base[f"tassi reali USA in calo ({n}g)"] = al(-segno(macro["DFII10"].diff(n)))
    if "DGS2" in macro:
        for n in (20, 60):
            base[f"rendimento USA 2 anni in salita ({n}g)"] = al(segno(macro["DGS2"].diff(n)))
    if "T10YIE" in macro:
        base["inflazione attesa in salita (20g)"] = al(segno(macro["T10YIE"].diff(20)))
    if "DTWEXBGS" in macro:
        base["dollaro in salita (20g)"] = al(segno(macro["DTWEXBGS"].pct_change(20)))
    if "T10Y2Y" in macro:
        base["curva USA positiva"] = al(segno(macro["T10Y2Y"]))
        base["curva USA in irripidimento (60g)"] = al(segno(macro["T10Y2Y"].diff(60)))
    if "DFEDTARU" in macro:
        base["Fed in fase di taglio (6 mesi)"] = al(-segno(macro["DFEDTARU"].diff(126)))
    if "ECBDFR" in macro:
        base["BCE in fase di taglio (6 mesi)"] = al(-segno(macro["ECBDFR"].diff(126)))
    R = {}
    for nome, sig in base.items():
        R[f"Macro: {nome}"] = sig
        R[f"Macro: {nome}, inverso"] = -sig
    return R


def leggi_calendario():
    """Calendario dal file calendario_macro.csv, integrato con il calendario ufficiale BLS se raggiungibile."""
    righe = []
    try:
        c = pd.read_csv("calendario_macro.csv", sep=";")
        for _, r in c.iterrows():
            righe.append((pd.Timestamp(r["data"]), str(r["evento"]), str(r["strumenti"]).strip().upper()))
    except Exception as ex:
        print(f"   calendario_macro.csv non leggibile: {ex}")
    try:
        req = urllib.request.Request("https://www.bls.gov/schedule/news_release/bls.ics", headers=UA)
        testo = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
        noti = {(d.date(), "CPI" in e) for d, e, _ in righe if "USA" in e}
        for ev in testo.split("BEGIN:VEVENT")[1:]:
            m_s = re.search(r"SUMMARY:(.*)", ev)
            m_d = re.search(r"DTSTART[^:]*:(\d{8})", ev)
            if not m_s or not m_d:
                continue
            titolo = m_s.group(1).strip()
            d = pd.Timestamp(datetime.strptime(m_d.group(1), "%Y%m%d"))
            if titolo.startswith("Consumer Price Index") and (d.date(), True) not in noti:
                righe.append((d, "Inflazione USA (CPI)", "USA"))
            elif titolo.startswith("Employment Situation") and (d.date(), False) not in noti:
                righe.append((d, "Occupazione USA (Employment Situation)", "USA"))
    except Exception as ex:
        print(f"   calendario BLS non raggiungibile, uso solo il file: {ex}")
    righe = sorted(set(righe))
    return righe


def agenda(calendario, giorni=7):
    oggi = pd.Timestamp(datetime.now(FUSO).date())
    fine = oggi + pd.Timedelta(days=giorni)
    return [(d, e, a) for d, e, a in calendario if oggi <= d <= fine]


def rischio_evento(nome, calendario):
    """Eventi di oggi o domani che riguardano lo strumento."""
    oggi = pd.Timestamp(datetime.now(FUSO).date())
    out = []
    for d, e, area in calendario:
        if nome in AREE_MACRO.get(area, []) and 0 <= (d - oggi).days <= 1:
            out.append(("oggi" if d == oggi else "domani", e))
    return out


# --------------------------------------------------------------------------
# INDICATORI E REGOLE
# --------------------------------------------------------------------------
def wilder(s, n):
    return s.ewm(alpha=1 / n, adjust=False).mean()


def indicatori(df):
    df = df.copy()
    c, h, l = df["Close"], df["High"], df["Low"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    df["ATR"] = wilder(tr, 14)
    up, dn = h.diff(), -l.diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    pdi = 100 * wilder(pdm, 14) / df["ATR"]
    mdi = 100 * wilder(mdm, 14) / df["ATR"]
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    df["ADX"], df["PDI"], df["MDI"] = wilder(dx, 14), pdi, mdi
    delta = c.diff()
    g, p = wilder(delta.clip(lower=0), 2), wilder(-delta.clip(upper=0), 2)
    df["RSI2"] = (100 - 100 / (1 + g / p.replace(0, np.nan))).where(p > 0, 100)
    return df


def regole(df, vix, picchi=None, regime_geo=None, macro=None):
    c = df["Close"]
    R = {}
    for n in (20, 50, 100, 200):
        R[f"Prezzo vs SMA{n}"] = np.sign(c - c.rolling(n).mean())
    for f, s in ((10, 30), (20, 50), (50, 200)):
        R[f"EMA {f}/{s}"] = np.sign(c.ewm(span=f, adjust=False).mean()
                                    - c.ewm(span=s, adjust=False).mean())
    for L in (5, 10, 20, 60, 120):
        R[f"Momentum {L}g"] = np.sign(c / c.shift(L) - 1)
    for n in (20, 55):
        hh = df["High"].rolling(n).max().shift(1)
        ll = df["Low"].rolling(n).min().shift(1)
        s = pd.Series(np.nan, index=df.index)
        s[c > hh] = 1
        s[c < ll] = -1
        R[f"Breakout Donchian {n}"] = s.ffill()
    for thr in (20, 25):
        R[f"ADX>{thr} + direzione DI"] = pd.Series(
            np.where(df["ADX"] > thr, np.where(df["PDI"] > df["MDI"], 1, -1), 0), index=df.index)
    m200 = c.rolling(200).mean()
    t1, t2 = np.sign(c - m200), np.sign(c / c.shift(20) - 1)
    R["SMA200 + Momentum20 concordi"] = pd.Series(np.where(t1 == t2, t1, 0), index=df.index)
    rsi = df["RSI2"]
    R["Reversione RSI2"] = pd.Series(np.where(rsi < 10, 1, np.where(rsi > 90, -1, 0)), index=df.index)
    R["Reversione RSI2 nel trend SMA200"] = pd.Series(
        np.where((rsi < 10) & (c > m200), 1, np.where((rsi > 90) & (c < m200), -1, 0)), index=df.index)

    # Calendario: segnale il penultimo giorno di borsa del mese, ingresso l'ultimo
    mese = df.index.to_period("M")
    dal_fondo = pd.Series(1, index=df.index).groupby(mese).cumcount(ascending=False)
    R["Fine/inizio mese"] = pd.Series(np.where(dal_fondo.values == 1, 1, 0), index=df.index)

    # Filtro VIX: si opera solo quando la volatilita' non e' nel 20% piu' alto dell'ultimo anno
    if vix is not None:
        v = vix.reindex(df.index).ffill()
        soglia_alta = v.rolling(252, min_periods=120).quantile(0.8)
        vix_ok = v <= soglia_alta
        for base in ("Prezzo vs SMA200", "Momentum 60g", "Momentum 120g",
                     "EMA 50/200", "Breakout Donchian 55"):
            R[f"{base} + filtro VIX"] = R[base].where(vix_ok, 0)
        panico = v >= v.rolling(252, min_periods=120).quantile(0.9)
        R["Acquisto su picco VIX"] = pd.Series(np.where(panico, 1, 0), index=df.index)

    # Geopolitica: segnale il primo giorno di borsa successivo all'inizio di un picco
    if picchi:
        n = len(df)
        subito, dopo3 = np.zeros(n), np.zeros(n)
        for d in picchi:
            i = df.index.searchsorted(pd.Timestamp(d))
            if i >= n:          # evento di oggi, barra non ancora disponibile: ingresso alla prossima apertura
                i = n - 1
            subito[i] = 1
            if i + 3 < n:
                dopo3[i + 3] = 1
        R["Geo: acquisto dopo picco"] = pd.Series(subito, index=df.index)
        R["Geo: vendita dopo picco"] = pd.Series(-subito, index=df.index)
        R["Geo: acquisto 3 giorni dopo picco"] = pd.Series(dopo3, index=df.index)
        R["Geo: vendita 3 giorni dopo picco"] = pd.Series(-dopo3, index=df.index)
    if macro:
        R.update(regole_macro(df, macro))
    if regime_geo is not None:
        g = regime_geo.reindex(df.index, method="ffill").fillna(False).astype(bool)
        R["Geo: rischio elevato, acquisto"] = pd.Series(np.where(g, 1, 0), index=df.index)
        R["Geo: rischio elevato, vendita"] = pd.Series(np.where(g, -1, 0), index=df.index)

    for k in R:
        R[k] = pd.Series(R[k], index=df.index).fillna(0).astype(float)
        R[k].iloc[:200] = 0
    return R


# --------------------------------------------------------------------------
# BACKTEST
# --------------------------------------------------------------------------
def rendimenti(df, h, apertura):
    entrata = df["Open"].shift(-1) if apertura else df["Close"]
    fwd = df["Close"].shift(-h) / entrata - 1
    minlo = df["Low"].rolling(h).min().shift(-h)
    maxhi = df["High"].rolling(h).max().shift(-h)
    return entrata, fwd, minlo, maxhi


def valuta(df, sig, h, costo, apertura):
    entrata, fwd, minlo, maxhi = [x.values for x in rendimenti(df, h, apertura)]
    atr, s, date = df["ATR"].values, sig.values, df.index
    idx = np.flatnonzero((s != 0) & ~np.isnan(fwd) & ~np.isnan(atr) & ~np.isnan(entrata))
    righe, libero = [], -1
    for i in idx:
        if i < libero:
            continue
        d, e = s[i], entrata[i]
        mae = (e - minlo[i]) / e if d > 0 else (maxhi[i] - e) / e
        righe.append((date[i], d, d * fwd[i] - costo, max(mae, 0.0), atr[i] / e))
        libero = i + h
    return pd.DataFrame(righe, columns=["data", "dir", "ret", "mae", "atr_pct"])


def tstat(x):
    sd = x.std(ddof=1)
    return float(x.mean() / sd * np.sqrt(len(x))) if sd > 0 else 0.0


def statistiche(t):
    if len(t) < MIN_TRADE:
        return None
    r = t["ret"]
    gain, loss = r[r > 0].sum(), -r[r < 0].sum()
    return {"n": len(t), "hit": float((r > 0).mean()), "ret": float(r.mean()),
            "t_exc": tstat(t["excess"]), "pf": float(gain / loss) if loss > 0 else np.nan}


def ricerca(dati):
    righe = []
    for nome, (df, R, classe) in dati.items():
        costo, ap = COSTO[classe], ENTRATA_APERTURA[classe]
        anni_oos = max((df.index[-1] - SPLIT).days / 365.25, 0.1)
        for h in ORIZZONTI:
            _, fwd, _, _ = rendimenti(df, h, ap)
            mu_is, mu_oos = fwd[fwd.index < SPLIT].mean(), fwd[fwd.index >= SPLIT].mean()
            for regola, sig in R.items():
                for modo in MODI:
                    s = sig if modo == "Long+Short" else (
                        sig.clip(lower=0) if modo == "Solo long" else sig.clip(upper=0))
                    t = valuta(df, s, h, costo, ap)
                    if len(t) < 2 * MIN_TRADE:
                        continue
                    is_ = (t["data"] < SPLIT).values
                    t["excess"] = t["ret"] - t["dir"] * np.where(is_, mu_is, mu_oos)
                    a, b = statistiche(t[is_]), statistiche(t[~is_])
                    if a is None or b is None:
                        continue
                    righe.append({
                        "Strumento": nome, "Classe": classe, "Regola": regola, "Modo": modo,
                        "Orizzonte_gg": h,
                        "Trade_IS": a["n"], "Hit_IS_%": a["hit"] * 100,
                        "RetMedio_IS_%": a["ret"] * 100, "t_vs_BH_IS": a["t_exc"],
                        "Trade_OOS": b["n"], "Hit_OOS_%": b["hit"] * 100,
                        "RetMedio_OOS_%": b["ret"] * 100, "t_vs_BH_OOS": b["t_exc"],
                        "ProfitFactor_OOS": b["pf"],
                        "RendAnnuo_OOS_%_senza_leva": b["ret"] * b["n"] / anni_oos * 100,
                        "Robustezza": min(a["t_exc"], b["t_exc"]),
                        "Robusta": bool(a["t_exc"] >= T_MIN and b["t_exc"] >= T_MIN
                                        and a["ret"] > 0 and b["ret"] > 0),
                        "MAE90_%": t["mae"].quantile(0.9) * 100,
                    })
    ris = pd.DataFrame(righe)
    if ris.empty:
        return ris
    chiave = ["Classe", "Regola", "Modo", "Orizzonte_gg"]
    conf = ris.groupby(chiave)["Robusta"].sum().rename("Conferme_classe").reset_index()
    ris = ris.merge(conf, on=chiave, how="left")
    return ris.sort_values(["Robusta", "Conferme_classe", "Robustezza"], ascending=False)


def forza(riga):
    """Punteggio 0-100 della forza statistica di una regola."""
    if riga is None:
        return 0
    t = min(max(float(riga["Robustezza"]), 0), 5) * 10                      # max 50
    c = int(riga["Conferme_classe"])
    conf = 0 if c <= 1 else (15 if c == 2 else (25 if c == 3 else 30))       # max 30
    hit = min(max((float(riga["Hit_OOS_%"]) - 50) * 2, 0), 20)              # max 20
    return int(round(t + conf + hit))


def fascia(p):
    return "forte" if p >= 75 else ("moderato" if p >= 50 else ("debole" if p >= 25 else "assente"))


def segnale_attuale(R, riga):
    s = R[riga["Regola"]].iloc[-1]
    if riga["Modo"] == "Solo long":
        s = max(s, 0)
    elif riga["Modo"] == "Solo short":
        s = min(s, 0)
    return int(s)


def segnali_oggi(dati, ris):
    out = []
    for nome, (df, R, classe) in dati.items():
        base = {"Strumento": nome, "Classe": classe, "Ultimo dato": df.index[-1].strftime("%d/%m/%Y"),
                "ATR14_%": float(df["ATR"].iloc[-1] / df["Close"].iloc[-1] * 100),
                "Prezzo": float(df["Close"].iloc[-1])}
        tutte = ris[ris["Strumento"] == nome] if not ris.empty else ris
        sub = tutte[tutte["Robusta"]] if not tutte.empty else tutte
        if sub.empty:
            cand = tutte[(tutte["RetMedio_IS_%"] > 0) & (tutte["RetMedio_OOS_%"] > 0)] if not tutte.empty else tutte
            best_c = cand.sort_values("Robustezza", ascending=False).iloc[0] if not cand.empty else None
            p = min(forza(best_c), 24)          # senza regola robusta non c'e' vantaggio misurabile
            out.append({**base, "Stato": "nessuna", "Forza": p, "Fascia": fascia(p)})
            continue
        best = sub.iloc[0]
        # un segnale geopolitico robusto che scatta oggi ha la precedenza
        geo = sub[sub["Regola"].str.startswith("Geo:")]
        for _, g in geo.sort_values("Robustezza", ascending=False).iterrows():
            if segnale_attuale(R, g) != 0:
                best = g
                break
        s = segnale_attuale(R, best)
        dist = float(best["MAE90_%"]) * 1.2
        stato = {1: "rialzo", -1: "ribasso"}.get(int(s), "fuori")
        if stato != "fuori" and int(best["Conferme_classe"]) < MIN_CONFERME:
            stato += "-debole"      # direzione indicata ma regola non confermata nella classe
        p = forza(best)
        # la fascia rispecchia lo stato: robusta ma non confermata = debole; confermata = almeno moderato
        p = min(max(p, 25), 49) if int(best["Conferme_classe"]) < MIN_CONFERME else max(p, 50)
        out.append({**base, "Stato": stato, "Forza": p, "Fascia": fascia(p),
                    "Regola": best["Regola"], "Modo": best["Modo"],
                    "Orizzonte_gg": int(best["Orizzonte_gg"]),
                    "Conferme_classe": int(best["Conferme_classe"]),
                    "Hit_OOS_%": float(best["Hit_OOS_%"]),
                    "Distanza_min_barriera_%": dist,
                    "Leva_max_indicativa": 100 / dist if dist > 0 else None})
    return pd.DataFrame(out)


# --------------------------------------------------------------------------
# PAGINA WEB
# --------------------------------------------------------------------------
def num(x, d=1):
    return f"{x:.{d}f}".replace(".", ",")


def modo_testo(m):
    return {"Long+Short": "rialzo e ribasso", "Solo long": "solo rialzo",
            "Solo short": "solo ribasso"}[m]


ETICHETTE = {"rialzo": "Rialzo", "ribasso": "Ribasso", "fuori": "Stare fuori",
             "rialzo-debole": "Rialzo da confermare", "ribasso-debole": "Ribasso da confermare",
             "nessuna": "Nessuna regola valida"}


def blocco_radar(radar, gpr):
    e = html.escape
    liv = radar["livello"]
    testo_liv = {"alto": "Alto", "elevato": "Elevato", "normale": "Normale",
                 "calibrazione": "In calibrazione", "non disponibile": "Non disponibile"}[liv]
    righe = [f'<div class="testa"><span class="nome">Radar geopolitico</span>'
             f'<span class="stato">{testo_liv}</span></div>']
    if liv != "non disponibile":
        conf = f", {num(radar['rapporto'])} volte la media recente" if radar.get("rapporto") else ""
        righe.append(f'<p class="det">{radar["conteggio"]} titoli su conflitti e attacchi nelle ultime 24 ore{conf}.</p>')
        if liv == "calibrazione":
            giorni = len(carica_storico_radar())
            righe.append(f'<p class="det">Il radar sta imparando il volume normale di notizie '
                         f'({giorni} di {RADAR_GIORNI_CALIBRAZIONE} giorni). Fino ad allora non genera allarmi.</p>')
        if radar["aree"]:
            righe.append('<p class="det">Aree più citate: ' + "; ".join(
                f"{e(a)} (mercati sensibili: {e(asset)})" for a, _, asset in radar["aree"]) + ".</p>")
        if liv == "alto":
            righe.append('<p class="det"><strong>Trattato come nuovo picco geopolitico:</strong> le regole '
                         '"Geo" robuste possono dare segnale oggi.</p>')
        if radar["titoli"]:
            righe.append('<ul class="titoli">' + "".join(
                f'<li><a href="{e(t["link"])}" rel="noopener" target="_blank">{e(t["titolo"])}</a></li>'
                for t in radar["titoli"]) + "</ul>")
    righe.append('<p class="det">Il radar è un indicatore di attenzione, non testato sul passato. '
                 + (f"Indice GPR storico aggiornato al {gpr.index[-1].strftime('%d/%m/%Y')}." if gpr is not None
                    else "Indice GPR storico non disponibile oggi.") + "</p>")
    return f'<section><h2>Geopolitica</h2><div class="riga radar r-{liv.replace(" ", "-")}">{"".join(righe)}</div></section>'


def blocco_macro(macro, calendario):
    e = html.escape
    ag = agenda(calendario)
    if ag:
        gg = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
        voci = "".join(f"<li><strong>{gg[d.weekday()]} {d.strftime('%d/%m')}</strong> {e(ev)}</li>" for d, ev, _ in ag)
        agenda_html = f'<ul class="titoli">{voci}</ul>'
    else:
        agenda_html = '<p class="det">Nessun appuntamento importante nei prossimi 7 giorni.</p>'
    ultimo = max((d for d, _, _ in calendario), default=None)
    avviso = ""
    if ultimo is None or (ultimo - pd.Timestamp(datetime.now(FUSO).date())).days < 45:
        avviso = ('<p class="det"><strong>Il calendario sta per esaurirsi:</strong> aggiungi le nuove date '
                  'nel file calendario_macro.csv.</p>')
    letture = []
    for c in ("DGS2", "DFII10", "T10YIE", "T10Y2Y", "DFEDTARU", "ECBDFR"):
        if c in macro:
            s = macro[c]
            var = s.iloc[-1] - s.iloc[-21] if len(s) > 21 else 0
            freccia = "in salita" if var > 0.02 else ("in calo" if var < -0.02 else "stabile")
            letture.append(f"<tr><td>{e(FRED[c])}</td><td>{num(s.iloc[-1], 2)}%</td><td>{freccia} nell'ultimo mese</td></tr>")
    tab = ("<div class='scorri'><table class='compatta'><tbody>" + "".join(letture) + "</tbody></table></div>") if letture else \
          "<p class='det'>Dati sui tassi non disponibili oggi.</p>"
    return (f'<section><h2>Macro</h2><div class="riga"><div class="testa"><span class="nome">Prossimi 7 giorni</span></div>'
            f'{agenda_html}{avviso}<details class="interno"><summary>Tassi di mercato</summary>{tab}'
            f'<p class="det">Fonte FRED, Federal Reserve Bank of St. Louis. I tassi riflettono già le sorprese dei dati macro; '
            f'le regole "Macro" li usano come segnali, testate come tutte le altre.</p></details></div></section>')


def barra_forza(p, fa):
    return (f'<div class="forza" role="img" aria-label="Forza del vantaggio {p} su 100, {fa}">'
            f'<div class="traccia"><div class="pieno f-{fa}" style="width:{p}%"></div></div>'
            f'<span class="punti">{p}<small>/100</small> {fa}</span></div>')


def pagina(seg, ris, aggiornato, radar, gpr, macro=None, calendario=None):
    macro = macro or {}
    calendario = calendario or []
    e = html.escape
    operativi = seg[seg["Stato"].isin(["rialzo", "ribasso"])]
    n_op, n_tot = len(operativi), len(seg)
    deboli = seg[seg["Stato"].str.endswith("-debole")]
    if n_op == 0:
        verdetto = "Nessun segnale operativo oggi"
        sotto = (f"Su {n_tot} strumenti nessuna regola confermata indica una direzione. "
                 "Non ci sono basi statistiche per aprire posizioni.")
        if not deboli.empty:
            sotto += (f" {len(deboli)} {'segnale da confermare' if len(deboli) == 1 else 'segnali da confermare'}"
                      ", probabilmente casuali.")
    else:
        verdetto = f"{n_op} {'segnale operativo' if n_op == 1 else 'segnali operativi'} oggi"
        sotto = ", ".join(f"{r['Strumento']} in {r['Stato']}" for _, r in operativi.iterrows())

    gruppi = []
    for classe in ORDINE_CLASSI:
        g = seg[seg["Classe"] == classe]
        if g.empty:
            continue
        righe = []
        for _, r in g.iterrows():
            det = [f"Ultimo dato {e(r['Ultimo dato'])}, volatilità giornaliera media {num(r['ATR14_%'])}%"]
            for quando, ev in rischio_evento(r["Strumento"], calendario):
                det.insert(0, f"<strong>Attenzione, {quando}: {e(ev)}.</strong> Possibili movimenti bruschi: barriere vicine sconsigliate.")
            if r["Stato"] != "nessuna":
                gg = int(r["Orizzonte_gg"])
                det.insert(0, f"{e(r['Regola'])}, {modo_testo(r['Modo'])}, "
                              f"mantenimento {gg} {'giorno' if gg == 1 else 'giorni'}")
                if r["Stato"] in ("rialzo", "ribasso"):
                    det.insert(1, f"Barriera ad almeno {num(r['Distanza_min_barriera_%'])}% dal prezzo, "
                                  f"leva massima circa {num(r['Leva_max_indicativa'], 0)}")
                if r["Stato"].endswith("-debole"):
                    det.insert(1, "Regola valida su un solo strumento: può essere un risultato casuale. Non usarla per operare.")
                conf = int(r["Conferme_classe"])
                det.append(f"Esito positivo nel {num(r['Hit_OOS_%'], 0)}% dei casi dal 2020; "
                           f"valida su {conf} {'strumento' if conf == 1 else 'strumenti'} della classe")
            righe.append(
                f'<li class="riga s-{r["Stato"]}"><div class="testa"><span class="nome">{e(r["Strumento"])}</span>'
                f'<span class="stato">{ETICHETTE[r["Stato"]]}</span></div>'
                + barra_forza(int(r["Forza"]), r["Fascia"])
                + "".join(f'<p class="det">{d}</p>' for d in det) + "</li>")
        gruppi.append(f'<section><h2>{classe}</h2><ul>{"".join(righe)}</ul></section>')

    rob = ris[ris["Robusta"]].head(15) if not ris.empty else ris
    if rob.empty:
        tab_rob = "<p class='vuoto'>Nessuna combinazione supera oggi la selezione.</p>"
    else:
        tab_rob = "<div class='scorri'><table><thead><tr><th>Strumento</th><th>Regola</th><th>Modo</th>" \
                  "<th>Giorni</th><th>t dal 2020</th><th>Esito +</th><th>Conferme</th></tr></thead><tbody>" + "".join(
            f"<tr><td>{e(r['Strumento'])}</td><td>{e(r['Regola'])}</td><td>{modo_testo(r['Modo'])}</td>"
            f"<td>{int(r['Orizzonte_gg'])}</td><td>{num(r['t_vs_BH_OOS'])}</td><td>{num(r['Hit_OOS_%'], 0)}%</td>"
            f"<td>{int(r['Conferme_classe'])}</td></tr>" for _, r in rob.iterrows()) + "</tbody></table></div>"

    oss = ris[(~ris["Robusta"]) & (ris["Robustezza"] >= 1.5)].sort_values(
        "Robustezza", ascending=False).head(8) if not ris.empty else ris
    lista_oss = "<p class='vuoto'>Nessuna.</p>" if oss.empty else "<ul class='oss'>" + "".join(
        f"<li>{e(r['Strumento'])}: {e(r['Regola'])}, {modo_testo(r['Modo'])}, {int(r['Orizzonte_gg'])} giorni "
        f"(t minimo {num(r['Robustezza'])})</li>" for _, r in oss.iterrows()) + "</ul>"

    n_test = len(ris)
    return f"""<!doctype html>
<html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow">
<meta name="theme-color" content="#E9EEF2">
<title>Trend Knock-Out</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🚦</text></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;600;800&display=swap" rel="stylesheet">
<style>
:root{{--carta:#E9EEF2;--foglio:#F7F9FA;--inchiostro:#17212B;--tenue:#5B6875;--filo:#CBD3DA;
--su:#1D7348;--su-f:#DCEFE3;--attesa:#8A5A00;--attesa-f:#F4E7C8;--giu:#A8321F;--giu-f:#F6E0DA;--neutro:#6C7885;--neutro-f:#E3E7EB;
box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}}
@media (prefers-color-scheme:dark){{:root{{--carta:#10161C;--foglio:#18212A;--inchiostro:#E4EAF0;--tenue:#94A1AE;
--filo:#2B3642;--su:#5CC98E;--su-f:#173726;--attesa:#E0B45C;--attesa-f:#3A2C10;--giu:#F08A74;--giu-f:#3E1E17;--neutro:#9AA6B2;--neutro-f:#232D37}}}}
*{{box-sizing:border-box}}
html{{scroll-padding-top:env(safe-area-inset-top,0px)}}
body{{margin:0;background:var(--carta);color:var(--inchiostro);
font-family:"Public Sans",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;line-height:1.5;
font-variant-numeric:tabular-nums}}
main{{max-width:40rem;margin:0 auto;padding:1.25rem 1rem 3rem}}
header p{{margin:0;color:var(--tenue);font-size:.875rem}}
.verdetto{{margin:.5rem 0 .25rem;font-size:clamp(1.9rem,8vw,2.6rem);line-height:1.1;font-weight:800;letter-spacing:-.02em}}
.sotto{{margin:0 0 1.75rem;color:var(--tenue);max-width:34rem}}
h2{{font-size:1rem;font-weight:600;margin:1.75rem 0 .5rem;color:var(--tenue)}}
ul{{list-style:none;margin:0;padding:0}}
.riga{{background:var(--foglio);border-left:5px solid var(--neutro);padding:.75rem .9rem;margin-bottom:.4rem;border-radius:0 6px 6px 0}}
.testa{{display:flex;justify-content:space-between;align-items:baseline;gap:.75rem}}
.nome{{font-weight:600;font-size:1.05rem}}
.stato{{font-weight:600;font-size:.85rem;padding:.1rem .55rem;border-radius:4px;background:var(--neutro-f);color:var(--neutro);white-space:nowrap}}
.s-rialzo{{border-left-color:var(--su)}} .s-rialzo .stato{{background:var(--su-f);color:var(--su)}}
.s-ribasso{{border-left-color:var(--giu)}} .s-ribasso .stato{{background:var(--giu-f);color:var(--giu)}}
.s-rialzo-debole,.s-ribasso-debole{{border-left-color:var(--attesa)}}
.s-rialzo-debole .stato,.s-ribasso-debole .stato{{background:var(--attesa-f);color:var(--attesa)}}
.s-nessuna{{border-left-color:var(--filo)}} .s-nessuna .nome{{color:var(--tenue)}}
.det{{margin:.2rem 0 0;font-size:.85rem;color:var(--tenue)}}
.forza{{display:flex;align-items:center;gap:.6rem;margin:.45rem 0 .2rem}}
.traccia{{flex:1;height:6px;background:var(--neutro-f);border-radius:3px;overflow:hidden}}
.pieno{{height:100%;background:var(--neutro)}}
.f-debole{{background:var(--attesa)}} .f-moderato{{background:var(--inchiostro)}} .f-forte{{background:var(--su)}}
.punti{{font-size:.8rem;font-weight:600;white-space:nowrap;min-width:6.5rem;text-align:right}}
.punti small{{font-weight:400;color:var(--tenue)}}
.radar{{border-left-color:var(--neutro)}}
.r-elevato{{border-left-color:var(--attesa)}} .r-elevato .stato{{background:var(--attesa-f);color:var(--attesa)}}
.r-alto{{border-left-color:var(--giu)}} .r-alto .stato{{background:var(--giu-f);color:var(--giu)}}
.titoli{{margin:.5rem 0 .2rem;padding:0}}
.titoli li{{font-size:.82rem;margin:.35rem 0;line-height:1.35}}
.titoli a{{text-decoration:none;border-bottom:1px solid var(--filo)}}
details.interno{{margin-top:.6rem;border-top:0;padding-top:0}}
details.interno summary{{font-size:.85rem}}
table.compatta{{min-width:0;width:100%}}
details{{margin-top:2rem;border-top:1px solid var(--filo);padding-top:1rem}}
summary{{cursor:pointer;font-weight:600}}
.scorri{{overflow-x:auto;margin-top:.75rem}}
table{{border-collapse:collapse;font-size:.8rem;min-width:36rem}}
th,td{{text-align:left;padding:.35rem .5rem;border-bottom:1px solid var(--filo)}}
th{{color:var(--tenue);font-weight:600}}
.oss li,.vuoto{{font-size:.85rem;color:var(--tenue);margin:.5rem 0}}
footer{{margin-top:2.5rem;font-size:.78rem;color:var(--tenue)}}
a{{color:inherit}}
:focus-visible{{outline:2px solid var(--inchiostro);outline-offset:2px}}
</style></head><body><main>
<header><p>Aggiornato {e(aggiornato)}</p></header>
<h1 class="verdetto">{e(verdetto)}</h1>
<p class="sotto">{e(sotto)}</p>
{blocco_radar(radar, gpr)}
{blocco_macro(macro, calendario)}
{"".join(gruppi)}
<details><summary>Regole che superano la selezione</summary>{tab_rob}</details>
<details><summary>In osservazione, non ancora valide</summary>
<p class="vuoto">Vicine alla soglia ma non robuste in entrambi i periodi. Non usarle per operare.</p>{lista_oss}</details>
<details><summary>Come leggere questa pagina</summary>
<p class="vuoto">Ogni giorno vengono ripetute {n_test} prove su dati 2010-oggi. Una regola è valida solo se batte il semplice
mantenimento dello strumento sia nel 2010-2019 sia dal 2020 in poi. Un segnale diventa operativo solo se la stessa regola vale anche su almeno un altro strumento della stessa classe;
altrimenti è segnalato come da confermare.
La forza da 0 a 100 somma: significatività statistica in entrambi i periodi (fino a 50 punti), conferme su altri strumenti
della classe (fino a 30) e percentuale di operazioni positive dal 2020 (fino a 20). Sotto 25 non c'è vantaggio misurabile,
25-49 debole, 50-74 moderato, da 75 forte. Le regole "Geo" usano i picchi dell'indice di rischio geopolitico di Caldara e
Iacoviello (Federal Reserve) e, per i giorni più recenti, il radar delle notizie. Le regole "Macro" usano la direzione
dei tassi di mercato (FRED); ognuna è provata anche in versione inversa. Gli avvisi del calendario macro non generano segnali:
segnalano i giorni in cui un Knock-Out con barriera vicina rischia di più. Il segnale vale per un ingresso all'apertura successiva
(alla chiusura per le valute) e per il numero di giorni indicato. La distanza della barriera copre il 90% delle oscillazioni
contrarie storiche più un margine del 20%. Costi di finanziamento dei Knock-Out non inclusi.</p>
<p class="vuoto"><a href="dati/segnali_oggi.csv">Segnali in CSV</a> · <a href="dati/risultati_completi.csv">Tutti i risultati in CSV</a></p>
</details>
<footer>Analisi statistica su dati storici Yahoo Finance. Non è una raccomandazione d'investimento.</footer>
</main></body></html>"""


# --------------------------------------------------------------------------
# TELEGRAM (facoltativo)
# --------------------------------------------------------------------------
def telegram(seg, aggiornato, radar):
    """Invia un messaggio solo quando segnali operativi o livello del radar cambiano."""
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    op = seg[seg["Stato"].isin(["rialzo", "ribasso"])]
    stato = {"segnali": sorted(f"{r['Strumento']}|{r['Stato']}" for _, r in op.iterrows()),
             "radar": radar["livello"]}
    percorso = os.path.join(CARTELLA, "dati", "ultimo_stato.json")
    try:
        precedente = json.load(open(percorso, encoding="utf-8"))
    except Exception:
        precedente = None
    json.dump(stato, open(percorso, "w", encoding="utf-8"))
    if not token or not chat or stato == precedente:
        return
    righe = [f"Trend Knock-Out, {aggiornato}"]
    if radar["livello"] in ("alto", "elevato"):
        aree = ", ".join(a for a, _, _ in radar["aree"]) or "varie"
        righe.append(f"Radar geopolitico {radar['livello'].upper()} ({radar['conteggio']} titoli, aree: {aree})")
    if op.empty:
        righe.append("Nessun segnale operativo.")
    for _, r in op.iterrows():
        righe.append(f"{r['Strumento']}: {r['Stato'].upper()} per {int(r['Orizzonte_gg'])} gg, "
                     f"forza {int(r['Forza'])}/100, barriera >= {num(r['Distanza_min_barriera_%'])}%")
    url = os.environ.get("PAGINA_URL")
    if url:
        righe.append(url)
    try:
        dati = urllib.parse.urlencode({"chat_id": chat, "text": "\n".join(righe)}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", dati, timeout=20)
        print("Messaggio Telegram inviato.")
    except Exception as ex:
        print(f"Invio Telegram non riuscito: {ex}")


# --------------------------------------------------------------------------
# PROGRAMMA PRINCIPALE
# --------------------------------------------------------------------------
def main():
    t0 = time.time()
    print("Scarico VIX...")
    vdf = scarica("^VIX")
    vix = vdf["Close"] if vdf is not None else None

    os.makedirs(os.path.join(CARTELLA, "dati"), exist_ok=True)
    print("Scarico indice di rischio geopolitico (GPR)...")
    gpr = scarica_gpr()
    print("Leggo il radar delle notizie...")
    storico = carica_storico_radar()
    radar = radar_notizie(storico)
    storico = salva_storico_radar(storico, radar)
    print(f"   radar: {radar['livello']} ({radar['conteggio']} titoli)")
    picchi, regime_geo = date_picchi_geo(gpr, storico)
    print("Scarico tassi e dati macro (FRED)...")
    macro = scarica_macro()
    calendario = leggi_calendario()

    dati = {}
    for nome, (tk, classe) in STRUMENTI.items():
        print(f"Scarico {nome} ({tk})...")
        df = scarica(tk)
        if df is None or len(df) < 800 or df.index[-1] <= SPLIT:
            print("   dati insufficienti, strumento saltato")
            continue
        df = indicatori(df)
        dati[nome] = (df, regole(df, vix, picchi, regime_geo, macro), classe)

    if not dati:
        raise SystemExit("Nessun dato scaricato: Yahoo Finance non ha risposto.")

    print("Ricerca in corso...")
    ris = ricerca(dati)
    seg = segnali_oggi(dati, ris)
    aggiornato = datetime.now(FUSO).strftime("%d/%m/%Y alle %H:%M")

    open(os.path.join(CARTELLA, ".nojekyll"), "w").close()
    opts = dict(sep=";", decimal=",", index=False, encoding="utf-8-sig")
    if not ris.empty:
        ris.round(3).to_csv(os.path.join(CARTELLA, "dati", "risultati_completi.csv"), **opts)
    seg.round(3).to_csv(os.path.join(CARTELLA, "dati", "segnali_oggi.csv"), **opts)
    with open(os.path.join(CARTELLA, "index.html"), "w", encoding="utf-8") as f:
        f.write(pagina(seg, ris, aggiornato, radar, gpr, macro, calendario))

    telegram(seg, aggiornato, radar)
    n_rob = int(ris["Robusta"].sum()) if not ris.empty else 0
    print(f"\nFatto in {time.time() - t0:.0f} s: {len(ris)} combinazioni, {n_rob} robuste.")
    print(seg[["Strumento", "Stato", "Forza", "Fascia"]].to_string(index=False))
    print(f"Pagina salvata in {CARTELLA}/index.html")


if __name__ == "__main__":
    main()
