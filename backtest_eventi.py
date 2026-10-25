"""
BACKTEST "APPUNTAMENTI FISSI" - regole fissate prima di vedere i risultati
==========================================================================
Domanda: nei giorni di un appuntamento noto in anticipo (decisione Fed, inflazione USA,
occupazione USA, decisione BCE, scorte settimanali EIA di gas e petrolio) esiste un
comportamento ripetibile da sfruttare con un Knock-Out tenuto 1 o 2 giorni?

Tre famiglie di regole, nessun parametro ottimizzato:
  A. REAZIONE: se il giorno dell'evento lo strumento si muove piu' di 1 volta la sua
     oscillazione normale (deviazione standard dei 60 giorni precedenti):
       - "Continua reazione" -> si entra nella stessa direzione
       - "Inverte reazione"  -> si entra in direzione opposta
     ingresso come nel sistema principale (apertura successiva; chiusura per le valute),
     uscita dopo 1 o 2 giorni.
  B. ATTRAVERSO L'EVENTO: acquisto (o vendita) alla chiusura del giorno prima,
     uscita alla chiusura del giorno dell'evento.
  C. SORPRESA EIA (solo gas e petrolio): variazione delle scorte confrontata con la media
     della stessa settimana negli anni precedenti. Sorpresa oltre 1 deviazione standard:
       - "Segue la sorpresa"  -> scorte piu' alte del normale = vendita, piu' basse = acquisto
       - "Contro la sorpresa" -> il contrario
     ingresso all'apertura del giorno dopo l'uscita del dato, uscita dopo 1 o 2 giorni.

Esame (identico al sistema principale): costi inclusi, almeno 20 operazioni per periodo,
t >= 2 contro il semplice mantenimento sia nel 2010-2019 sia dal 2020, in utile in entrambi.
Per diventare un segnale deve valere su almeno 2 strumenti della stessa classe
(le regole EIA riguardano un solo strumento e bastano da sole).

Fonti delle date: siti ufficiali Fed, BLS, BCE, EIA (raggiungibili da GitHub).
Risultati: docs/dati/backtest_eventi.csv, backtest_eventi_date.csv, backtest_eventi_riepilogo.md
Prova senza internet:  SIMULA=1 python backtest_eventi.py
"""

import io
import os
import re
import urllib.request

import numpy as np
import pandas as pd

import trend_knockout as tk

SIMULA = os.environ.get("SIMULA") == "1"
GIORNI = (1, 2)
SOGLIA_Z = 1.0
OGGI = pd.Timestamp.today().normalize()
ANNI = range(2010, OGGI.year + 1)
BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "Accept-Language": "en-US,en;q=0.9"}

TUTTI = list(tk.STRUMENTI)
EUROPA = ["DAX", "FTSE MIB", "Euro Stoxx 50", "EUR/USD", "EUR/CHF"]
# ora italiana dell'annuncio e strumenti interessati
EVENTI = {
    "Decisione Fed":       (20.0, TUTTI),
    "Inflazione USA":      (14.5, TUTTI),
    "Occupazione USA":     (14.5, TUTTI),
    "Decisione BCE":       (14.25, EUROPA),
    "Scorte gas EIA":      (16.5, ["Gas naturale"]),
    "Scorte petrolio EIA": (16.5, ["Petrolio WTI"]),
}
EVENTI_EIA = {"Scorte gas EIA": "Gas naturale", "Scorte petrolio EIA": "Petrolio WTI"}
# ora italiana della chiusura giornaliera dei dati Yahoo
CHIUSURA = {"S&P 500": 22.0, "Nasdaq 100": 22.0, "DAX": 17.5, "FTSE MIB": 17.5, "Euro Stoxx 50": 17.5}
EIA_URL = {
    "Scorte gas EIA": "https://www.eia.gov/dnav/ng/hist_xls/NW2_EPG0_SWO_R48_BCFw.xls",
    "Scorte petrolio EIA": "https://www.eia.gov/dnav/pet/hist_xls/WCESTUS1w.xls",
}
# giorni tra la fine della settimana di riferimento (venerdi') e l'uscita del dato
EIA_RITARDO = {"Scorte gas EIA": (6, 5, 7), "Scorte petrolio EIA": (5, 6)}


# --------------------------------------------------------------------------
# DATE DEGLI APPUNTAMENTI
# --------------------------------------------------------------------------
def leggi(url, limite=30):
    req = urllib.request.Request(url, headers=BROWSER)
    return urllib.request.urlopen(req, timeout=limite).read()


def raccogli(pagine, schema, formato):
    trovate, errori = set(), 0
    for url in pagine:
        try:
            testo = leggi(url).decode("utf-8", "ignore")
            for m in re.findall(schema, testo):
                try:
                    trovate.add(pd.Timestamp(pd.to_datetime(m, format=formato)))
                except Exception:
                    pass
        except Exception as ex:
            errori += 1
            print(f"   {url} non raggiungibile: {ex}")
    return trovate, errori


def date_fed():
    pagine = ["https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"] + \
             [f"https://www.federalreserve.gov/monetarypolicy/fomchistorical{a}.htm" for a in range(2010, 2021)]
    d, err = raccogli(pagine, r"monetary/?(\d{8})a\.htm", "%Y%m%d")
    return d, f"federalreserve.gov ({len(pagine) - err}/{len(pagine)} pagine lette)"


def date_bls(sigla):
    d, err = raccogli([f"https://www.bls.gov/bls/news-release/{sigla}.htm"], sigla + r"_(\d{8})\.htm", "%m%d%Y")
    return d, f"bls.gov archivio ({'letto' if not err else 'non raggiungibile'})"


def date_bce():
    pagine = [f"https://www.ecb.europa.eu/press/govcdec/mopo/{a}/html/index_include.en.html" for a in ANNI]
    d, err = raccogli(pagine, r"(?:ecb\.mp|/pr)(\d{6})[^\"]*\.en\.html", "%y%m%d")
    return d, f"ecb.europa.eu ({len(pagine) - err}/{len(pagine)} anni letti)"


def primo_venerdi():
    out = set()
    for a in ANNI:
        for m in range(1, 13):
            g = pd.Timestamp(a, m, 1)
            out.add(g + pd.Timedelta(days=(4 - g.weekday()) % 7))
    return out


def tutte_le_date():
    """{evento: (insieme di date, descrizione della fonte)} per gli eventi a data fissa."""
    if SIMULA:
        rng = np.random.default_rng(1)
        giorni = pd.bdate_range("2010-01-01", OGGI)
        return {e: ({pd.Timestamp(x) for x in rng.choice(giorni, n, replace=False)}, "simulate")
                for e, n in (("Decisione Fed", 135), ("Inflazione USA", 200), ("Occupazione USA", 200),
                             ("Decisione BCE", 140))}
    fed, f_fed = date_fed()
    cpi, f_cpi = date_bls("cpi")
    nfp, f_nfp = date_bls("empsit")
    bce, f_bce = date_bce()
    calendario = tk.leggi_calendario()           # file calendario_macro.csv + calendario BLS dell'anno
    for d, ev, _ in calendario:
        if d > OGGI:
            continue
        if ev.startswith("Decisione Fed"):
            fed.add(d)
        elif ev.startswith("Inflazione USA"):
            cpi.add(d)
        elif ev.startswith("Occupazione USA"):
            nfp.add(d)
        elif ev.startswith("Decisione BCE"):
            bce.add(d)
    try:                                         # date ufficiali raccolte a mano da bls.gov ed ecb.europa.eu
        fisse = pd.read_csv("date_eventi.csv", sep=";")
        mappa = {"Inflazione USA": (cpi, "cpi"), "Occupazione USA": (nfp, "nfp"), "Decisione BCE": (bce, "bce")}
        for ev, gruppo in fisse.groupby("evento"):
            if ev in mappa:
                mappa[ev][0].update(pd.to_datetime(gruppo["data"]))
        n = fisse["evento"].value_counts()
        f_cpi += f" + file date_eventi.csv ({n.get('Inflazione USA', 0)} date)"
        f_nfp += f" + file date_eventi.csv ({n.get('Occupazione USA', 0)} date)"
        f_bce += f" + file date_eventi.csv ({n.get('Decisione BCE', 0)} date)"
    except Exception as ex:
        print(f"   date_eventi.csv non leggibile: {ex}")
    if len(nfp) < 100:
        nfp |= primo_venerdi()
        f_nfp += "; integrato con la regola del primo venerdi' del mese (date approssimate)"
    sicuri = lambda s: {d for d in s if pd.Timestamp("2009-12-01") <= d <= OGGI and d.weekday() < 5}
    return {"Decisione Fed": (sicuri(fed), f_fed), "Inflazione USA": (sicuri(cpi), f_cpi),
            "Occupazione USA": (sicuri(nfp), f_nfp), "Decisione BCE": (sicuri(bce), f_bce)}


# --------------------------------------------------------------------------
# SCORTE EIA E SORPRESA
# --------------------------------------------------------------------------
def serie_eia(evento):
    if SIMULA:
        rng = np.random.default_rng(7 if "gas" in evento else 8)
        idx = pd.date_range("2010-01-08", OGGI, freq="W-FRI")
        stag = 80 * np.sin(2 * np.pi * (idx.dayofyear - 100) / 365.25)
        return pd.Series(3000 + np.cumsum(stag + rng.normal(0, 15, len(idx))), index=idx), "simulata"
    try:
        x = pd.read_excel(io.BytesIO(leggi(EIA_URL[evento], 60)), sheet_name="Data 1", header=None)
        d = pd.to_datetime(x.iloc[:, 0], errors="coerce")
        v = pd.to_numeric(x.iloc[:, 1], errors="coerce")
        s = pd.Series(v.values, index=d)
        s = s[s.index.notna()].dropna().sort_index()
        if len(s) > 300:
            return s[~s.index.duplicated()], "eia.gov"
    except Exception as ex:
        print(f"   EIA {evento} non raggiungibile: {ex}")
    if evento == "Scorte petrolio EIA":
        s = tk.scarica_fred("WCESTUS1")
        if s is not None:
            return s, "FRED (serie EIA WCESTUS1)"
    return None, "non disponibile"


def sorprese(s):
    """Variazione settimanale meno la media della stessa settimana negli anni precedenti (fino a 5, almeno 3)."""
    s = s.resample("W-FRI").last().interpolate(limit=2)
    ch = s.diff()
    passati = pd.concat([ch.shift(52 * k) for k in range(1, 6)], axis=1)
    attesa = passati.mean(axis=1).where(passati.notna().sum(axis=1) >= 3)
    sor = ch - attesa
    z = sor / sor.rolling(104, min_periods=52).std().shift(1)
    return pd.DataFrame({"variazione": ch, "attesa": attesa, "sorpresa": sor, "z": z}).dropna()


# --------------------------------------------------------------------------
# CALCOLO
# --------------------------------------------------------------------------
def posizione(indice, giorno, dopo=False):
    """Posizione del primo giorno di borsa >= giorno (o > giorno se dopo=True)."""
    i = indice.searchsorted(giorno, side="right" if dopo else "left")
    return int(i) if i < len(indice) and (indice[i] - giorno).days <= 4 else None


def giorno_reazione(df, nome, d, ora):
    return posizione(df.index, d, dopo=ora >= CHIUSURA.get(nome, 23.0))


def giorno_rilascio(df, fine_settimana, ritardi):
    for r in ritardi:
        g = fine_settimana + pd.Timedelta(days=r)
        if g in df.index:
            return int(df.index.get_loc(g))
    return None


def prova(df, classe, segnali, h, apertura):
    """segnali: lista di (posizione, direzione). Restituisce le operazioni con eccesso sul mantenimento."""
    _, fwd, _, _ = tk.rendimenti(df, h, apertura)
    costo = tk.COSTO[classe]
    mu_is, mu_oos = fwd[fwd.index < tk.SPLIT].mean(), fwd[fwd.index >= tk.SPLIT].mean()
    righe, libero = [], -1
    for i, d in sorted(segnali):
        if i < libero or np.isnan(fwd.iloc[i]):
            continue
        data = df.index[i]
        ret = d * fwd.iloc[i] - costo
        righe.append((data, d, ret, ret - d * (mu_is if data < tk.SPLIT else mu_oos)))
        libero = i + h
    return pd.DataFrame(righe, columns=["data", "dir", "ret", "excess"])


def esame(t, base):
    riga = dict(base, Trade_IS=0, Trade_OOS=0)
    if len(t):
        is_ = (t["data"] < tk.SPLIT).values
        for p, m in (("IS", is_), ("OOS", ~is_)):
            x = t[m]
            riga[f"Trade_{p}"] = len(x)
            if len(x) >= 2:
                riga[f"Hit_{p}_%"] = float((x["ret"] > 0).mean() * 100)
                riga[f"RetMedio_{p}_%"] = float(x["ret"].mean() * 100)
                riga[f"t_{p}"] = tk.tstat(x["excess"])
        u = t[t["data"] >= OGGI - pd.DateOffset(months=12)]
        riga["Trade_ultimo_anno"] = len(u)
        riga["Hit_ultimo_anno_%"] = float((u["ret"] > 0).mean() * 100) if len(u) else np.nan
        riga["RetMedio_ultimo_anno_%"] = float(u["ret"].mean() * 100) if len(u) else np.nan
    riga["Robusta"] = bool(riga["Trade_IS"] >= tk.MIN_TRADE and riga["Trade_OOS"] >= tk.MIN_TRADE
                           and riga.get("t_IS", 0) >= tk.T_MIN and riga.get("t_OOS", 0) >= tk.T_MIN
                           and riga.get("RetMedio_IS_%", 0) > 0 and riga.get("RetMedio_OOS_%", 0) > 0)
    return riga


def scarica_prezzi(nome, ticker):
    if not SIMULA:
        return tk.scarica(ticker)
    rng = np.random.default_rng(abs(hash(nome)) % 1000)
    idx = pd.bdate_range("2010-01-04", OGGI) if "Bitcoin" not in nome and "Ethereum" not in nome \
        else pd.date_range("2014-09-17", OGGI)
    c = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.012, len(idx))))
    o = c * np.exp(rng.normal(0, 0.003, len(idx)))
    return pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.004, "Low": np.minimum(o, c) * 0.996,
                         "Close": c}, index=idx)


def f(x, d=2):
    return "-" if x is None or pd.isna(x) else f"{x:.{d}f}".replace(".", ",")


def main():
    print("Raccolgo le date degli appuntamenti...", flush=True)
    date_ev = tutte_le_date()
    eia = {}
    for ev in EVENTI_EIA:
        s, fonte = serie_eia(ev)
        eia[ev] = (sorprese(s) if s is not None else None, fonte)

    copertura = []
    for ev, (dd, fonte) in date_ev.items():
        dd = sorted(dd)
        copertura.append({"Evento": ev, "Date": len(dd), "Prima": dd[0].strftime("%d/%m/%Y") if dd else "-",
                          "Ultima": dd[-1].strftime("%d/%m/%Y") if dd else "-",
                          "2010-19": sum(d < tk.SPLIT for d in dd), "Dal 2020": sum(d >= tk.SPLIT for d in dd),
                          "Fonte": fonte})
    for ev, (sz, fonte) in eia.items():
        n = 0 if sz is None else len(sz)
        copertura.append({"Evento": ev, "Date": n,
                          "Prima": sz.index[0].strftime("%d/%m/%Y") if n else "-",
                          "Ultima": sz.index[-1].strftime("%d/%m/%Y") if n else "-",
                          "2010-19": int((sz.index < tk.SPLIT).sum()) if n else 0,
                          "Dal 2020": int((sz.index >= tk.SPLIT).sum()) if n else 0, "Fonte": fonte})
    copertura = pd.DataFrame(copertura)
    print(copertura.to_string(index=False))

    righe, diagnosi, ultime_eia, elenco_date = [], {}, {}, []
    for nome, (ticker, classe) in tk.STRUMENTI.items():
        print(f"Scarico {nome} ({ticker})...", flush=True)
        df = scarica_prezzi(nome, ticker)
        if df is None or len(df) < 800 or df.index[-1] <= tk.SPLIT:
            print("   dati insufficienti, strumento saltato")
            continue
        ap = tk.ENTRATA_APERTURA[classe]
        r = df["Close"].pct_change()
        z = r / r.rolling(60).std().shift(1)

        for ev, (ora, strumenti) in EVENTI.items():
            if nome not in strumenti:
                continue
            # giorni di reazione all'evento
            if ev in EVENTI_EIA:
                sz = eia[ev][0]
                if sz is None:
                    continue
                pos = {}
                for fine, rr in sz.iterrows():
                    i = giorno_rilascio(df, fine, EIA_RITARDO[ev])
                    if i is not None:
                        pos[i] = rr
            else:
                pos = {}
                for d in date_ev[ev][0]:
                    i = giorno_reazione(df, nome, d, ora)
                    if i is not None and i >= 61:
                        pos[i] = d
            if not pos:
                continue
            for i in pos:
                elenco_date.append({"Evento": ev, "Strumento": nome, "Giorno_reazione": df.index[i].date()})
            base = {"Strumento": nome, "Classe": classe, "Evento": ev}

            # A. reazione forte del giorno dell'evento
            forti = [(i, float(np.sign(r.iloc[i]))) for i in pos
                     if not np.isnan(z.iloc[i]) and abs(z.iloc[i]) >= SOGLIA_Z]
            for h in GIORNI:
                for variante, segno in (("Continua reazione", 1), ("Inverte reazione", -1)):
                    t = prova(df, classe, [(i, segno * d) for i, d in forti], h, ap)
                    righe.append(esame(t, dict(base, Famiglia="A", Variante=variante, Giorni=h)))

            # B. attraverso l'evento (chiusura del giorno prima -> chiusura del giorno dell'evento)
            for variante, d in (("Long attraverso l'evento", 1), ("Short attraverso l'evento", -1)):
                t = prova(df, classe, [(i - 1, d) for i in pos if i >= 1], 1, False)
                righe.append(esame(t, dict(base, Famiglia="B", Variante=variante, Giorni=1)))

            # C. sorpresa EIA
            if ev in EVENTI_EIA:
                zs = pd.Series({i: rr["z"] for i, rr in pos.items()}).sort_index()
                reaz = r.iloc[zs.index.values].values
                ok = ~np.isnan(reaz)
                date_i = df.index[zs.index.values]
                corr = {p: float(np.corrcoef(zs.values[ok & m], reaz[ok & m])[0, 1]) if (ok & m).sum() > 20 else np.nan
                        for p, m in (("IS", date_i < tk.SPLIT), ("OOS", date_i >= tk.SPLIT))}
                grandi = ok & (np.abs(zs.values) >= SOGLIA_Z)
                coerenti = float((np.sign(reaz[grandi]) == -np.sign(zs.values[grandi])).mean() * 100) \
                    if grandi.any() else np.nan
                diagnosi[ev] = {"corr_IS": corr["IS"], "corr_OOS": corr["OOS"], "coerenti_%": coerenti,
                                "n_grandi": int(grandi.sum())}
                sig = [(int(i), -float(np.sign(v))) for i, v in zs.items() if abs(v) >= SOGLIA_Z]
                for h in GIORNI:
                    for variante, segno in (("Segue la sorpresa", 1), ("Contro la sorpresa", -1)):
                        t = prova(df, classe, [(i, segno * d) for i, d in sig], h, ap)
                        righe.append(esame(t, dict(base, Famiglia="C", Variante=variante, Giorni=h)))
                ult = []
                for i in list(zs.index)[-8:]:
                    rr = pos[i]
                    dopo = [(df["Close"].iloc[i + k] / df["Close"].iloc[i] - 1) * 100 if i + k < len(df) else np.nan
                            for k in (1, 2)]
                    ult.append((df.index[i], rr["variazione"], rr["attesa"], rr["z"], r.iloc[i] * 100, *dopo))
                ultime_eia[ev] = ult

    ris = pd.DataFrame(righe)
    if ris.empty:
        raise SystemExit("Nessun dato scaricato.")
    chiavi = ["Classe", "Evento", "Variante", "Giorni"]
    conf = ris.groupby(chiavi)["Robusta"].sum().rename("Conferme_classe").reset_index()
    ris = ris.merge(conf, on=chiavi, how="left")
    ris["Segnale_valido"] = ris["Robusta"] & ((ris["Conferme_classe"] >= tk.MIN_CONFERME)
                                              | ris["Evento"].isin(list(EVENTI_EIA)))
    ris["min_t"] = ris[["t_IS", "t_OOS"]].min(axis=1)
    cartella = os.path.join(tk.CARTELLA, "dati")
    os.makedirs(cartella, exist_ok=True)
    ris.round(3).to_csv(os.path.join(cartella, "backtest_eventi.csv"),
                        sep=";", decimal=",", index=False, encoding="utf-8-sig")
    pd.DataFrame(elenco_date).drop_duplicates().to_csv(os.path.join(cartella, "backtest_eventi_date.csv"),
                                                       sep=";", index=False, encoding="utf-8-sig")

    # ---------------- riepilogo ----------------
    validi = ris[ris["Segnale_valido"]]
    out = ["# Backtest 'appuntamenti fissi' (Knock-Out tenuto 1-2 giorni)", "",
           f"Combinazioni provate: {len(ris)}. Esame: costi inclusi, almeno {tk.MIN_TRADE} operazioni per periodo, "
           f"t >= {tk.T_MIN:g} contro il semplice mantenimento sia nel 2010-2019 sia dal 2020, in utile in entrambi, "
           "valida su almeno 2 strumenti della stessa classe (le regole EIA bastano da sole).", ""]
    if validi.empty:
        out.append("## Esito: **NON SUPERATO** — nessuna regola diventa un segnale.")
    else:
        out.append(f"## Esito: **SUPERATO** da {len(validi)} combinazioni")
        for _, x in validi.sort_values("min_t", ascending=False).iterrows():
            out.append(f"- **{x['Evento']} → {x['Strumento']}**: {x['Variante'].lower()}, {x['Giorni']} gg "
                       f"(t {f(x['t_IS'])} / {f(x['t_OOS'])}; rend. medio {f(x['RetMedio_IS_%'])}% / "
                       f"{f(x['RetMedio_OOS_%'])}%; in utile {f(x.get('Hit_OOS_%'), 0)}% delle volte dal 2020)")
    singole = ris[ris["Robusta"] & ~ris["Segnale_valido"]]
    if len(singole):
        out += ["", "Valide su un solo strumento della classe (non bastano): " + "; ".join(
            f"{x['Evento']} {x['Strumento']} {x['Variante'].lower()} {x['Giorni']} gg" for _, x in singole.iterrows())]

    out += ["", "## Date trovate per ogni appuntamento (controllo delle fonti)", "",
            "| Evento | Date | Prima | Ultima | 2010-19 | Dal 2020 | Fonte |", "|---|---|---|---|---|---|---|"]
    for _, c in copertura.iterrows():
        out.append(f"| {c['Evento']} | {c['Date']} | {c['Prima']} | {c['Ultima']} | {c['2010-19']} | "
                   f"{c['Dal 2020']} | {c['Fonte']} |")

    if diagnosi:
        out += ["", "## La misura della sorpresa EIA funziona?", "",
                "Se la misura è buona, nel giorno di uscita del dato scorte più alte del normale devono coincidere "
                "con prezzi in calo (correlazione negativa).", "",
                "| Evento | Correlazione 2010-19 | Correlazione dal 2020 | Sorprese forti | "
                "Giorno d'uscita nella direzione attesa |", "|---|---|---|---|---|"]
        for ev, dg in diagnosi.items():
            out.append(f"| {ev} | {f(dg['corr_IS'])} | {f(dg['corr_OOS'])} | {dg['n_grandi']} | "
                       f"{f(dg['coerenti_%'], 0)}% |")
    for ev, ult in ultime_eia.items():
        out += ["", f"### Ultime uscite: {ev}", "",
                "| Giorno | Variazione scorte | Normale per la settimana | Sorpresa (dev. std) | "
                "Prezzo quel giorno % | +1 gg % | +2 gg % |", "|---|---|---|---|---|---|---|"]
        for g, v, a, zz, rg, d1, d2 in ult:
            out.append(f"| {g.strftime('%d/%m/%Y')} | {f(v, 0)} | {f(a, 0)} | {f(zz)} | {f(rg)} | {f(d1)} | {f(d2)} |")

    def tabella(x):
        t = ["| Evento | Strumento | Regola | Giorni | Trade 2010-19 | t 2010-19 | Rend. % | Trade dal 2020 | "
             "t dal 2020 | Rend. % | In utile dal 2020 | Ultimo anno: trade, rend. % | Valida |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for _, r in x.iterrows():
            t.append(f"| {r['Evento']} | {r['Strumento']} | {r['Variante']} | {r['Giorni']} | {r['Trade_IS']} | "
                     f"{f(r.get('t_IS'))} | {f(r.get('RetMedio_IS_%'))} | {r['Trade_OOS']} | {f(r.get('t_OOS'))} | "
                     f"{f(r.get('RetMedio_OOS_%'))} | {f(r.get('Hit_OOS_%'), 0)}% | "
                     f"{int(r.get('Trade_ultimo_anno', 0) or 0)}, {f(r.get('RetMedio_ultimo_anno_%'))} | "
                     f"{'SI' if r['Segnale_valido'] else ('solo qui' if r['Robusta'] else 'no')} |")
        return t

    out += ["", "## Le 3 regole migliori per ogni appuntamento (anche se non superano l'esame)", ""]
    migliori = ris.dropna(subset=["min_t"]).sort_values("min_t", ascending=False).groupby("Evento").head(3)
    out += tabella(migliori.sort_values(["Evento", "min_t"], ascending=[True, False]))
    out += ["", "Nota: dati giornalieri. Non si misura l'ingresso subito dopo l'annuncio (es. alle 16:30), "
            "ma solo da chiusura/apertura in poi. Date di uscita EIA ricostruite dal calendario standard "
            "(qualche festività può spostarle di un giorno)."]
    testo = "\n".join(out)
    print("\n" + testo)
    with open(os.path.join(cartella, "backtest_eventi_riepilogo.md"), "w", encoding="utf-8") as fh:
        fh.write(testo)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(testo)


if __name__ == "__main__":
    main()
