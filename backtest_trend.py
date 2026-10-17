"""
BACKTEST "TREND IN ATTO" - ultimo anno
======================================
Per ogni strumento ricostruisce, giorno per giorno, lo stato "Trend in atto"
(rialzo / ribasso / laterale) e registra ogni avviso che sarebbe arrivato,
con il movimento nei 1, 3 e 5 giorni successivi nella direzione del trend.
Lo stato di ogni giorno usa solo i prezzi fino a quel giorno.

Risultati:
  docs/dati/backtest_trend_avvisi.csv     un rigo per ogni avviso
  docs/dati/backtest_trend_riepilogo.md   riepilogo (anche nella pagina dell'esecuzione su GitHub)
"""

import os

import numpy as np
import pandas as pd

import trend_knockout as tk

MESI = 12
SETTIMANA = 7        # giorni di calendario mostrati nel dettaglio "ultima settimana"


def num(x, d=2, segno=True):
    if x is None or pd.isna(x):
        return "-"
    return (f"{x:+.{d}f}" if segno else f"{x:.{d}f}").replace(".", ",")


def main():
    avvisi, sintesi, settimana = [], [], []
    oggi = None
    for nome, (ticker, classe) in tk.STRUMENTI.items():
        print(f"Scarico {nome} ({ticker})...", flush=True)
        df = tk.scarica(ticker)
        if df is None or len(df) < 300:
            print("   dati insufficienti, strumento saltato")
            continue
        p = tk.punteggio_trend(df)
        st = tk.stati_trend(p, tk.forza_movimento(df))
        fine = df.index[-1]
        oggi = fine if oggi is None else max(oggi, fine)
        inizio = fine - pd.DateOffset(months=MESI)
        a = tk.avvii_trend(df, st, classe, dal=inizio)
        a_tutti = tk.avvii_trend(df, st, classe)          # dal 2015, per confronto

        # giorni in ogni stato nell'ultimo anno
        anno = st[st.index >= inizio]
        for _, r in a.iterrows():
            avvisi.append({"Data": r["data"].strftime("%d/%m/%Y"), "Strumento": nome, "Classe": classe,
                           "Avviso": tk.TREND_ETICHETTE[int(r["dir"])], "Prezzo": round(r["prezzo"], 4),
                           **{f"Mov_{h}gg_%": round(r[f"r{h}"], 2) if not pd.isna(r[f"r{h}"]) else None
                              for h in tk.TREND_GIORNI}})
        riga = {"Strumento": nome, "Avvisi": len(a),
                "Rialzo": int((a["dir"] == 1).sum()), "Ribasso": int((a["dir"] == -1).sum()),
                "Giorni_trend_%": float((anno != 0).mean() * 100)}
        for h in tk.TREND_GIORNI:
            r = a[f"r{h}"].dropna()
            riga[f"cont{h}"] = float((r > 0).mean() * 100) if len(r) else np.nan
            riga[f"media{h}"] = float(r.mean()) if len(r) else np.nan
        r3 = a_tutti["r3"].dropna()
        riga["cont3_2015"] = float((r3 > 0).mean() * 100) if len(r3) else np.nan
        riga["avvii_2015"] = len(a_tutti)
        sintesi.append(riga)

        # dettaglio ultima settimana
        for d in df.index[df.index >= fine - pd.Timedelta(days=SETTIMANA)]:
            settimana.append({"Data": d, "Strumento": nome, "Punteggio": p.loc[d],
                              "Stato": tk.TREND_ETICHETTE[int(st.loc[d])],
                              "Chiusura": df["Close"].loc[d]})

    if not sintesi:
        raise SystemExit("Nessun dato scaricato.")
    avvisi = pd.DataFrame(avvisi)
    sintesi = pd.DataFrame(sintesi)
    settimana = pd.DataFrame(settimana)
    os.makedirs(os.path.join(tk.CARTELLA, "dati"), exist_ok=True)
    avvisi.to_csv(os.path.join(tk.CARTELLA, "dati", "backtest_trend_avvisi.csv"),
                  sep=";", decimal=",", index=False, encoding="utf-8-sig")

    # ---------------- riepilogo ----------------
    tot = avvisi[[f"Mov_{h}gg_%" for h in tk.TREND_GIORNI]] if len(avvisi) else None
    righe = [f"# Backtest 'Trend in atto' - ultimi {MESI} mesi (fino al {oggi:%d/%m/%Y})", ""]
    righe.append(f"**Avvisi totali: {len(avvisi)}** su {len(sintesi)} strumenti "
                 f"(circa {len(avvisi) / 52:.1f} a settimana).")
    if tot is not None:
        for h in tk.TREND_GIORNI:
            r = tot[f"Mov_{h}gg_%"].dropna()
            righe.append(f"- Dopo {h} gg: movimento nella direzione dell'avviso nel {num((r > 0).mean() * 100, 0, False)}% "
                         f"dei casi, media {num(r.mean())}% (senza leva, ingresso all'apertura successiva)")
    righe += ["", "## Per strumento", "",
              "| Strumento | Avvisi | Rialzo | Ribasso | % giorni in trend | Continua a 1 gg | a 3 gg | a 5 gg | Media 3 gg | Continua a 3 gg dal 2015 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for _, s in sintesi.iterrows():
        righe.append(f"| {s['Strumento']} | {s['Avvisi']} | {s['Rialzo']} | {s['Ribasso']} | "
                     f"{num(s['Giorni_trend_%'], 0, False)}% | {num(s['cont1'], 0, False)}% | {num(s['cont3'], 0, False)}% | "
                     f"{num(s['cont5'], 0, False)}% | {num(s['media3'])}% | "
                     f"{num(s['cont3_2015'], 0, False)}% su {s['avvii_2015']} |")

    righe += ["", "## Ultima settimana, giorno per giorno", "",
              "| Strumento | " + " | ".join(d.strftime("%a %d/%m") for d in sorted(settimana["Data"].unique())) + " |",
              "|---|" + "---|" * settimana["Data"].nunique()]
    giorni = sorted(settimana["Data"].unique())
    breve = {"Rialzo in corso": "RIALZO", "Ribasso in corso": "RIBASSO", "Laterale": "lat."}
    for nome, g in settimana.groupby("Strumento", sort=False):
        g = g.set_index("Data")
        celle = [f"{breve[g.loc[d, 'Stato']]} ({int(g.loc[d, 'Punteggio']):+d})" if d in g.index else ""
                 for d in giorni]
        righe.append(f"| {nome} | " + " | ".join(celle) + " |")

    righe += ["", "## Elenco degli avvisi", "",
              "| Data | Strumento | Avviso | Prezzo | 1 gg % | 3 gg % | 5 gg % |", "|---|---|---|---|---|---|---|"]
    for _, a in avvisi.iterrows():
        righe.append(f"| {a['Data']} | {a['Strumento']} | {a['Avviso']} | {a['Prezzo']} | "
                     f"{num(a['Mov_1gg_%'])} | {num(a['Mov_3gg_%'])} | {num(a['Mov_5gg_%'])} |")
    testo = "\n".join(righe)
    print("\n" + testo)
    with open(os.path.join(tk.CARTELLA, "dati", "backtest_trend_riepilogo.md"), "w", encoding="utf-8") as f:
        f.write(testo)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(testo)


if __name__ == "__main__":
    main()
