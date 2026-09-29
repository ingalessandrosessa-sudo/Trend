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
     variabili TELEGRAM_TOKEN e TELEGRAM_CHAT_ID.

Esecuzione locale:  python trend_knockout.py   (poi apri docs/index.html)
"""

import html
import json
import os
import time
import urllib.parse
import urllib.request
import warnings
from datetime import datetime
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


def regole(df, vix):
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


def segnali_oggi(dati, ris):
    out = []
    for nome, (df, R, classe) in dati.items():
        base = {"Strumento": nome, "Classe": classe, "Ultimo dato": df.index[-1].strftime("%d/%m/%Y"),
                "ATR14_%": float(df["ATR"].iloc[-1] / df["Close"].iloc[-1] * 100),
                "Prezzo": float(df["Close"].iloc[-1])}
        sub = ris[(ris["Strumento"] == nome) & (ris["Robusta"])] if not ris.empty else ris
        if sub.empty:
            out.append({**base, "Stato": "nessuna"})
            continue
        best = sub.iloc[0]
        s = R[best["Regola"]].iloc[-1]
        if best["Modo"] == "Solo long":
            s = max(s, 0)
        elif best["Modo"] == "Solo short":
            s = min(s, 0)
        dist = float(best["MAE90_%"]) * 1.2
        stato = {1: "rialzo", -1: "ribasso"}.get(int(s), "fuori")
        if stato != "fuori" and int(best["Conferme_classe"]) < MIN_CONFERME:
            stato += "-debole"      # direzione indicata ma regola non confermata nella classe
        out.append({**base, "Stato": stato,
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


def pagina(seg, ris, aggiornato):
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
{"".join(gruppi)}
<details><summary>Regole che superano la selezione</summary>{tab_rob}</details>
<details><summary>In osservazione, non ancora valide</summary>
<p class="vuoto">Vicine alla soglia ma non robuste in entrambi i periodi. Non usarle per operare.</p>{lista_oss}</details>
<details><summary>Come leggere questa pagina</summary>
<p class="vuoto">Ogni giorno vengono ripetute {n_test} prove su dati 2010-oggi. Una regola è valida solo se batte il semplice
mantenimento dello strumento sia nel 2010-2019 sia dal 2020 in poi. Un segnale diventa operativo solo se la stessa regola vale anche su almeno un altro strumento della stessa classe;
altrimenti è segnalato come da confermare. Il segnale vale per un ingresso all'apertura successiva
(alla chiusura per le valute) e per il numero di giorni indicato. La distanza della barriera copre il 90% delle oscillazioni
contrarie storiche più un margine del 20%. Costi di finanziamento dei Knock-Out non inclusi.</p>
<p class="vuoto"><a href="dati/segnali_oggi.csv">Segnali in CSV</a> · <a href="dati/risultati_completi.csv">Tutti i risultati in CSV</a></p>
</details>
<footer>Analisi statistica su dati storici Yahoo Finance. Non è una raccomandazione d'investimento.</footer>
</main></body></html>"""


# --------------------------------------------------------------------------
# TELEGRAM (facoltativo)
# --------------------------------------------------------------------------
def telegram(seg, aggiornato):
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return
    op = seg[seg["Stato"].isin(["rialzo", "ribasso"])]
    if op.empty:
        testo = f"Trend Knock-Out, {aggiornato}\nNessun segnale operativo oggi."
    else:
        righe = [f"{r['Strumento']}: {r['Stato'].upper()} per {int(r['Orizzonte_gg'])} gg, "
                 f"barriera >= {num(r['Distanza_min_barriera_%'])}%" for _, r in op.iterrows()]
        testo = f"Trend Knock-Out, {aggiornato}\n" + "\n".join(righe)
    url = os.environ.get("PAGINA_URL")
    if url:
        testo += f"\n{url}"
    try:
        dati = urllib.parse.urlencode({"chat_id": chat, "text": testo}).encode()
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

    dati = {}
    for nome, (tk, classe) in STRUMENTI.items():
        print(f"Scarico {nome} ({tk})...")
        df = scarica(tk)
        if df is None or len(df) < 800 or df.index[-1] <= SPLIT:
            print("   dati insufficienti, strumento saltato")
            continue
        df = indicatori(df)
        dati[nome] = (df, regole(df, vix), classe)

    if not dati:
        raise SystemExit("Nessun dato scaricato: Yahoo Finance non ha risposto.")

    print("Ricerca in corso...")
    ris = ricerca(dati)
    seg = segnali_oggi(dati, ris)
    aggiornato = datetime.now(FUSO).strftime("%d/%m/%Y alle %H:%M")

    os.makedirs(os.path.join(CARTELLA, "dati"), exist_ok=True)
    open(os.path.join(CARTELLA, ".nojekyll"), "w").close()
    opts = dict(sep=";", decimal=",", index=False, encoding="utf-8-sig")
    if not ris.empty:
        ris.round(3).to_csv(os.path.join(CARTELLA, "dati", "risultati_completi.csv"), **opts)
    seg.round(3).to_csv(os.path.join(CARTELLA, "dati", "segnali_oggi.csv"), **opts)
    with open(os.path.join(CARTELLA, "index.html"), "w", encoding="utf-8") as f:
        f.write(pagina(seg, ris, aggiornato))

    telegram(seg, aggiornato)
    n_rob = int(ris["Robusta"].sum()) if not ris.empty else 0
    print(f"\nFatto in {time.time() - t0:.0f} s: {len(ris)} combinazioni, {n_rob} robuste.")
    print(seg[["Strumento", "Stato"]].to_string(index=False))
    print(f"Pagina salvata in {CARTELLA}/index.html")


if __name__ == "__main__":
    main()
