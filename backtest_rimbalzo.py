"""
BACKTEST "RIMBALZO DOPO UN TREND FORTE" - regola fissata prima di vedere i risultati
====================================================================================
Ipotesi: dopo l'avvio di un "Ribasso in corso" il prezzo tende a rimbalzare
(e dopo un "Rialzo in corso" a ripiegare).

Regola (definita PRIMA del test, nessun parametro ottimizzato):
  - Long dopo ribasso : acquisto all'apertura successiva all'avvio di un "Ribasso in corso"
  - Short dopo rialzo : vendita all'apertura successiva all'avvio di un "Rialzo in corso"
  - Entrambe          : le due insieme
  - mantenimento 1, 3 o 5 giorni; operazioni sovrapposte escluse; costi inclusi.

Esame (identico a quello del sistema principale):
  - deve battere il semplice mantenimento con t >= 2 sia nel 2010-2019 sia dal 2020,
    ed essere in utile in entrambi i periodi;
  - per diventare un segnale deve valere su almeno 2 strumenti della stessa classe.
L'ipotesi riguarda gli INDICI; gli altri strumenti sono mostrati solo per informazione.

Risultati: docs/dati/backtest_rimbalzo.csv e docs/dati/backtest_rimbalzo_riepilogo.md
"""

import os

import numpy as np
import pandas as pd

import trend_knockout as tk

GIORNI = (1, 3, 5)
VARIANTI = ("Long dopo ribasso", "Short dopo rialzo", "Entrambe")


def segnali_rimbalzo(st):
    v = st.values
    nuovo = (v != 0) & (np.r_[0, v[:-1]] != v)
    long_ = np.where(nuovo & (v == -1), 1.0, 0.0)
    short = np.where(nuovo & (v == 1), -1.0, 0.0)
    return {"Long dopo ribasso": pd.Series(long_, index=st.index),
            "Short dopo rialzo": pd.Series(short, index=st.index),
            "Entrambe": pd.Series(long_ + short, index=st.index)}


def f(x, d=2):
    return "-" if x is None or pd.isna(x) else f"{x:.{d}f}".replace(".", ",")


def main():
    righe = []
    for nome, (ticker, classe) in tk.STRUMENTI.items():
        print(f"Scarico {nome} ({ticker})...", flush=True)
        df = tk.scarica(ticker)
        if df is None or len(df) < 800 or df.index[-1] <= tk.SPLIT:
            print("   dati insufficienti, strumento saltato")
            continue
        df = tk.indicatori(df)
        st = tk.stati_trend(tk.punteggio_trend(df), tk.forza_movimento(df))
        st.iloc[:200] = 0                       # stesso periodo di avvio del sistema principale
        costo, ap = tk.COSTO[classe], tk.ENTRATA_APERTURA[classe]
        for h in GIORNI:
            _, fwd, _, _ = tk.rendimenti(df, h, ap)
            mu_is, mu_oos = fwd[fwd.index < tk.SPLIT].mean(), fwd[fwd.index >= tk.SPLIT].mean()
            for variante, sig in segnali_rimbalzo(st).items():
                t = tk.valuta(df, sig, h, costo, ap)
                riga = {"Strumento": nome, "Classe": classe, "Variante": variante, "Giorni": h,
                        "Trade_IS": 0, "Trade_OOS": 0}
                if len(t):
                    is_ = (t["data"] < tk.SPLIT).values
                    t["excess"] = t["ret"] - t["dir"] * np.where(is_, mu_is, mu_oos)
                    for nome_p, mask in (("IS", is_), ("OOS", ~is_)):
                        x = t[mask]
                        riga[f"Trade_{nome_p}"] = len(x)
                        if len(x) >= 2:
                            riga[f"Hit_{nome_p}_%"] = float((x["ret"] > 0).mean() * 100)
                            riga[f"RetMedio_{nome_p}_%"] = float(x["ret"].mean() * 100)
                            riga[f"t_{nome_p}"] = tk.tstat(x["excess"])
                    ultimi = t[t["data"] >= df.index[-1] - pd.DateOffset(months=12)]
                    riga["Trade_ultimo_anno"] = len(ultimi)
                    riga["RetMedio_ultimo_anno_%"] = float(ultimi["ret"].mean() * 100) if len(ultimi) else np.nan
                    riga["Hit_ultimo_anno_%"] = float((ultimi["ret"] > 0).mean() * 100) if len(ultimi) else np.nan
                ok = (riga["Trade_IS"] >= tk.MIN_TRADE and riga["Trade_OOS"] >= tk.MIN_TRADE
                      and riga.get("t_IS", 0) >= tk.T_MIN and riga.get("t_OOS", 0) >= tk.T_MIN
                      and riga.get("RetMedio_IS_%", 0) > 0 and riga.get("RetMedio_OOS_%", 0) > 0)
                riga["Robusta"] = bool(ok)
                righe.append(riga)

    ris = pd.DataFrame(righe)
    if ris.empty:
        raise SystemExit("Nessun dato scaricato.")
    conf = ris.groupby(["Classe", "Variante", "Giorni"])["Robusta"].sum().rename("Conferme_classe").reset_index()
    ris = ris.merge(conf, on=["Classe", "Variante", "Giorni"], how="left")
    ris["Segnale_valido"] = ris["Robusta"] & (ris["Conferme_classe"] >= tk.MIN_CONFERME)
    os.makedirs(os.path.join(tk.CARTELLA, "dati"), exist_ok=True)
    ris.round(3).to_csv(os.path.join(tk.CARTELLA, "dati", "backtest_rimbalzo.csv"),
                        sep=";", decimal=",", index=False, encoding="utf-8-sig")

    # ---------------- riepilogo ----------------
    ind = ris[ris["Classe"] == "Indici"]
    validi_ind = ind[ind["Segnale_valido"]]
    out = ["# Backtest 'rimbalzo dopo un trend forte'", "",
           "Regola fissata prima del test. Esame: t >= 2 contro il semplice mantenimento sia nel 2010-2019 "
           "sia dal 2020, in utile in entrambi i periodi, valida su almeno 2 indici.", ""]
    if validi_ind.empty:
        out.append("## Esito sugli indici: **NON SUPERATO** — nessuna combinazione valida su almeno 2 indici.")
    else:
        out.append(f"## Esito sugli indici: **SUPERATO** da {len(validi_ind)} combinazioni:")
        for _, r in validi_ind.iterrows():
            out.append(f"- {r['Strumento']}: {r['Variante']}, {r['Giorni']} gg "
                       f"(t {f(r['t_IS'])} / {f(r['t_OOS'])}, esito positivo {f(r['Hit_OOS_%'], 0)}% dal 2020)")
    robuste_singole = ind[ind["Robusta"] & ~ind["Segnale_valido"]]
    if len(robuste_singole):
        out.append("")
        out.append("Valide su un solo indice (non bastano): " + "; ".join(
            f"{r['Strumento']} {r['Variante'].lower()} {r['Giorni']} gg" for _, r in robuste_singole.iterrows()))

    def tabella(x):
        t = ["| Strumento | Variante | Giorni | Trade 2010-19 | t 2010-19 | Rend. medio % | Trade dal 2020 | t dal 2020 | "
             "Rend. medio % | Esito + dal 2020 | Ultimo anno: trade, rend. medio % | Valida |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for _, r in x.iterrows():
            t.append(f"| {r['Strumento']} | {r['Variante']} | {r['Giorni']} | {r['Trade_IS']} | {f(r.get('t_IS'))} | "
                     f"{f(r.get('RetMedio_IS_%'))} | {r['Trade_OOS']} | {f(r.get('t_OOS'))} | {f(r.get('RetMedio_OOS_%'))} | "
                     f"{f(r.get('Hit_OOS_%'), 0)}% | {int(r.get('Trade_ultimo_anno', 0) or 0)}, "
                     f"{f(r.get('RetMedio_ultimo_anno_%'))} | "
                     f"{'SI' if r['Segnale_valido'] else ('solo qui' if r['Robusta'] else 'no')} |")
        return t

    out += ["", "## Dettaglio indici", ""] + tabella(ind)
    altri = ris[(ris["Classe"] != "Indici") & ris["Robusta"]]
    out += ["", "## Altri strumenti (solo informazione, non era l'ipotesi del test)", ""]
    out += tabella(altri) if len(altri) else ["Nessuna combinazione supera l'esame sugli altri strumenti."]
    testo = "\n".join(out)
    print("\n" + testo)
    with open(os.path.join(tk.CARTELLA, "dati", "backtest_rimbalzo_riepilogo.md"), "w", encoding="utf-8") as fh:
        fh.write(testo)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(testo)


if __name__ == "__main__":
    main()
