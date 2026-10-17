"""
BACKTEST DELL'ULTIMO ANNO - quanti e quali segnali avrebbe dato il sistema
==========================================================================
Ricostruisce, giorno per giorno degli ultimi 12 mesi, cosa avrebbe pubblicato
trend_knockout.py usando SOLO i dati disponibili in quel momento:
  - la selezione delle regole robuste viene rifatta all'inizio di ogni mese
    con i dati fino a quel giorno (come se il sistema girasse allora);
  - ogni giorno del mese si calcola lo stato di ogni strumento con le stesse
    regole della pagina (precedenza Geo, conferme nella classe, "da confermare").

Risultati:
  docs/dati/backtest_1anno_segnali.csv      un rigo per ogni segnale, con esito
  docs/dati/backtest_1anno_giornaliero.csv  stato di ogni strumento giorno per giorno
  riepilogo nel registro di GitHub (pagina dell'esecuzione, sezione "Summary")
"""

import multiprocessing as mp
import os
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

import trend_knockout as tk

MESI = 12
DATI = {}           # nome -> (df, regole, classe); globale per i processi paralleli


def selezione(cutoff):
    """Ricerca delle regole robuste con i soli dati precedenti a 'cutoff'."""
    t0 = time.time()
    sub = {n: (df[df.index < cutoff], {k: v[v.index < cutoff] for k, v in R.items()}, c)
           for n, (df, R, c) in DATI.items()}
    ris = tk.ricerca(sub)
    n_rob = int(ris["Robusta"].sum()) if not ris.empty else 0
    print(f"   selezione al {cutoff:%d/%m/%Y}: {n_rob} regole robuste ({time.time() - t0:.0f} s)", flush=True)
    return cutoff, ris


def valore(R, riga, pos):
    s = R[riga["Regola"]].iloc[pos]
    if riga["Modo"] == "Solo long":
        s = max(s, 0)
    elif riga["Modo"] == "Solo short":
        s = min(s, 0)
    return int(s)


def stato_al(R, sub, pos):
    """Stessa logica di segnali_oggi() di trend_knockout.py, applicata al giorno 'pos'."""
    if sub.empty:
        return "nessuna", None
    best = sub.iloc[0]
    geo = sub[sub["Regola"].str.startswith("Geo:")]
    for _, g in geo.sort_values("Robustezza", ascending=False).iterrows():
        if valore(R, g, pos) != 0:
            best = g
            break
    stato = {1: "rialzo", -1: "ribasso"}.get(valore(R, best, pos), "fuori")
    if stato != "fuori" and int(best["Conferme_classe"]) < tk.MIN_CONFERME:
        stato += "-debole"
    return stato, best


def esito(df, classe, pos, direzione, h):
    """Rendimento del segnale: ingresso all'apertura successiva (chiusura per le valute), uscita dopo h giorni."""
    if tk.ENTRATA_APERTURA[classe]:
        if pos + 1 >= len(df):
            return None, "in attesa"
        entrata = df["Open"].iloc[pos + 1]
    else:
        entrata = df["Close"].iloc[pos]
    if pos + h >= len(df):
        return None, "in corso"
    uscita = df["Close"].iloc[pos + h]
    r = direzione * (uscita / entrata - 1) * 100
    return r, ("positivo" if r > 0 else "negativo")


def carica_dati():
    vdf = tk.scarica("^VIX")
    vix = vdf["Close"] if vdf is not None else None
    os.makedirs(os.path.join(tk.CARTELLA, "dati"), exist_ok=True)
    gpr = tk.scarica_gpr()
    picchi, regime_geo = tk.date_picchi_geo(gpr, tk.carica_storico_radar())
    macro = tk.scarica_macro()
    for nome, (ticker, classe) in tk.STRUMENTI.items():
        print(f"Scarico {nome} ({ticker})...", flush=True)
        df = tk.scarica(ticker)
        if df is None or len(df) < 800 or df.index[-1] <= tk.SPLIT:
            print("   dati insufficienti, strumento saltato")
            continue
        df = tk.indicatori(df)
        DATI[nome] = (df, tk.regole(df, vix, picchi, regime_geo, macro), classe)


def main():
    t0 = time.time()
    if not DATI:
        carica_dati()
    if not DATI:
        raise SystemExit("Nessun dato scaricato.")

    oggi = max(df.index[-1] for df, _, _ in DATI.values())
    inizio = (oggi - pd.DateOffset(months=MESI)).normalize()
    cutoff = list(pd.date_range(inizio.to_period("M").to_timestamp(), oggi, freq="MS"))
    if cutoff[0] < inizio:
        cutoff[0] = inizio
    print(f"\nBacktest dal {cutoff[0]:%d/%m/%Y} al {oggi:%d/%m/%Y}: {len(cutoff)} selezioni mensili", flush=True)

    with ProcessPoolExecutor(max_workers=os.cpu_count() or 2, mp_context=mp.get_context("fork")) as pool:
        selezioni = dict(pool.map(selezione, cutoff))

    giorni, segnali = [], []
    limiti = cutoff[1:] + [oggi + pd.Timedelta(days=1)]
    for nome, (df, R, classe) in DATI.items():
        precedente = None
        for c, fine in zip(cutoff, limiti):
            ris = selezioni[c]
            sub = ris[(ris["Strumento"] == nome) & ris["Robusta"]] if not ris.empty else ris
            for pos in np.flatnonzero((df.index >= c) & (df.index < fine)):
                d = df.index[pos]
                stato, best = stato_al(R, sub, pos)
                giorni.append({"Data": d, "Strumento": nome, "Stato": stato,
                               "Regola": best["Regola"] if best is not None else ""})
                if stato in ("rialzo", "ribasso", "rialzo-debole", "ribasso-debole") and stato != precedente:
                    h = int(best["Orizzonte_gg"])
                    direzione = 1 if stato.startswith("rialzo") else -1
                    r, e = esito(df, classe, pos, direzione, h)
                    segnali.append({
                        "Data": d.strftime("%d/%m/%Y"), "Strumento": nome, "Classe": classe,
                        "Segnale": tk.ETICHETTE[stato],
                        "Operativo": "si" if stato in ("rialzo", "ribasso") else "no (da confermare)",
                        "Regola": best["Regola"], "Modo": best["Modo"], "Giorni": h,
                        "Prezzo": round(float(df["Close"].iloc[pos]), 4),
                        "Rendimento_%_senza_leva": round(r, 2) if r is not None else None,
                        "Esito": e})
                precedente = stato

    giorni = pd.DataFrame(giorni)
    segnali = pd.DataFrame(segnali)
    opts = dict(sep=";", decimal=",", index=False, encoding="utf-8-sig")
    giorni.assign(Data=giorni["Data"].dt.strftime("%d/%m/%Y")).to_csv(
        os.path.join(tk.CARTELLA, "dati", "backtest_1anno_giornaliero.csv"), **opts)
    segnali.to_csv(os.path.join(tk.CARTELLA, "dati", "backtest_1anno_segnali.csv"), **opts)

    # ---------------- riepilogo ----------------
    righe = [f"# Backtest ultimo anno ({cutoff[0]:%d/%m/%Y} - {oggi:%d/%m/%Y})", ""]
    rob = {c.strftime("%m/%Y"): int(r["Robusta"].sum()) if not r.empty else 0 for c, r in selezioni.items()}
    righe.append("Regole robuste trovate a ogni selezione mensile: "
                 + ", ".join(f"{m}: {n}" for m, n in rob.items()))
    righe.append("")
    if segnali.empty:
        righe.append("**Nessun segnale in tutto l'anno, né operativo né da confermare.**")
    else:
        op = segnali[segnali["Operativo"] == "si"]
        righe.append(f"**Segnali operativi: {len(op)}** — segnali da confermare: {len(segnali) - len(op)}")
        chiusi = op[op["Rendimento_%_senza_leva"].notna()]
        if len(chiusi):
            righe.append(f"Operativi chiusi: {len(chiusi)}, positivi {int((chiusi['Rendimento_%_senza_leva'] > 0).sum())}, "
                         f"rendimento medio {chiusi['Rendimento_%_senza_leva'].mean():.2f}% senza leva")
        righe += ["", "| Data | Strumento | Segnale | Operativo | Regola | Giorni | Rend. % | Esito |",
                  "|---|---|---|---|---|---|---|---|"]
        for _, s in segnali.iterrows():
            rr = "" if pd.isna(s["Rendimento_%_senza_leva"]) else f"{s['Rendimento_%_senza_leva']:.2f}"
            righe.append(f"| {s['Data']} | {s['Strumento']} | {s['Segnale']} | {s['Operativo']} | {s['Regola']} | "
                         f"{s['Giorni']} | {rr} | {s['Esito']} |")
    righe += ["", "Giorni per stato, per strumento:", "", "| Strumento | Stato | Giorni |", "|---|---|---|"]
    for (n, st), k in giorni.groupby(["Strumento", "Stato"]).size().items():
        righe.append(f"| {n} | {tk.ETICHETTE[st]} | {k} |")
    righe.append(f"\nTempo totale: {time.time() - t0:.0f} s")
    testo = "\n".join(righe)
    print("\n" + testo)
    with open(os.path.join(tk.CARTELLA, "dati", "backtest_1anno_riepilogo.md"), "w", encoding="utf-8") as f:
        f.write(testo)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(testo)


if __name__ == "__main__":
    main()
