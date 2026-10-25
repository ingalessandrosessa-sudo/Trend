# Backtest 'appuntamenti fissi' (Knock-Out tenuto 1-2 giorni)

Combinazioni provate: 320. Esame: costi inclusi, almeno 20 operazioni per periodo, t >= 2 contro il semplice mantenimento sia nel 2010-2019 sia dal 2020, in utile in entrambi, valida su almeno 2 strumenti della stessa classe (le regole EIA bastano da sole).

## Esito: **NON SUPERATO** — nessuna regola diventa un segnale.

Valide su un solo strumento della classe (non bastano): Occupazione USA EUR/CHF continua reazione 2 gg

## Date trovate per ogni appuntamento (controllo delle fonti)

| Evento | Date | Prima | Ultima | 2010-19 | Dal 2020 | Fonte |
|---|---|---|---|---|---|---|
| Decisione Fed | 139 | 27/01/2010 | 16/09/2026 | 81 | 58 | federalreserve.gov (12/12 pagine lette) |
| Inflazione USA | 1 | 14/10/2026 | 14/10/2026 | 0 | 1 | bls.gov archivio (non raggiungibile) |
| Occupazione USA | 202 | 01/01/2010 | 02/10/2026 | 120 | 82 | bls.gov archivio (non raggiungibile); integrato con la regola del primo venerdi' del mese (date approssimate) |
| Decisione BCE | 76 | 27/04/2017 | 10/09/2026 | 22 | 54 | ecb.europa.eu (17/17 anni letti) |
| Scorte gas EIA | 668 | 03/01/2014 | 16/10/2026 | 313 | 355 | eia.gov |
| Scorte petrolio EIA | 2094 | 05/09/1986 | 16/10/2026 | 1739 | 355 | eia.gov |

## La misura della sorpresa EIA funziona?

Se la misura è buona, nel giorno di uscita del dato scorte più alte del normale devono coincidere con prezzi in calo (correlazione negativa).

| Evento | Correlazione 2010-19 | Correlazione dal 2020 | Sorprese forti | Giorno d'uscita nella direzione attesa |
|---|---|---|---|---|
| Scorte petrolio EIA | -0,19 | -0,09 | 286 | 60% |
| Scorte gas EIA | -0,07 | 0,00 | 143 | 52% |

### Ultime uscite: Scorte petrolio EIA

| Giorno | Variazione scorte | Normale per la settimana | Sorpresa (dev. std) | Prezzo quel giorno % | +1 gg % | +2 gg % |
|---|---|---|---|---|---|---|
| 02/09/2026 | -4450 | -690 | -0,75 | 0,88 | 0,32 | 0,52 |
| 09/09/2026 | -391 | 949 | -0,27 | 3,25 | 6,69 | 4,16 |
| 16/09/2026 | -640 | -3078 | 0,49 | -3,21 | -0,51 | -2,08 |
| 23/09/2026 | 2969 | -577 | 0,71 | -2,57 | 2,66 | 0,27 |
| 30/09/2026 | 922 | 889 | 0,01 | 1,16 | 2,71 | 0,76 |
| 07/10/2026 | -3186 | 7134 | -2,09 | -1,30 | 3,64 | 4,04 |
| 14/10/2026 | -8557 | -1063 | -1,49 | 1,01 | 3,03 | 6,65 |
| 21/10/2026 | -3060 | 2548 | -1,10 | -4,56 | 2,39 | 6,30 |

### Ultime uscite: Scorte gas EIA

| Giorno | Variazione scorte | Normale per la settimana | Sorpresa (dev. std) | Prezzo quel giorno % | +1 gg % | +2 gg % |
|---|---|---|---|---|---|---|
| 03/09/2026 | 30 | 39 | -0,20 | -1,45 | 2,13 | 0,10 |
| 10/09/2026 | 40 | 66 | -0,55 | 0,43 | -0,11 | 2,19 |
| 17/09/2026 | 44 | 78 | -0,74 | 0,35 | 0,38 | -2,24 |
| 24/09/2026 | 53 | 81 | -0,60 | 9,06 | -3,06 | -9,01 |
| 01/10/2026 | 64 | 88 | -0,52 | -1,95 | 2,29 | 3,34 |
| 08/10/2026 | 85 | 90 | -0,12 | -1,09 | 1,64 | -0,03 |
| 15/10/2026 | 67 | 91 | -0,53 | 1,19 | -3,71 | -5,50 |
| 22/10/2026 | 77 | 76 | 0,03 | 0,22 | 9,08 | - |

## Le 3 regole migliori per ogni appuntamento (anche se non superano l'esame)

| Evento | Strumento | Regola | Giorni | Trade 2010-19 | t 2010-19 | Rend. % | Trade dal 2020 | t dal 2020 | Rend. % | In utile dal 2020 | Ultimo anno: trade, rend. % | Valida |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Decisione BCE | EUR/USD | Long attraverso l'evento | 1 | 22 | 1,02 | 0,08 | 54 | 1,66 | 0,13 | 57% | 8, -0,20 | no |
| Decisione BCE | EUR/USD | Inverte reazione | 2 | 8 | 1,70 | 0,53 | 16 | 0,63 | 0,15 | 50% | 2, 0,07 | no |
| Decisione BCE | EUR/CHF | Long attraverso l'evento | 1 | 22 | 0,51 | 0,02 | 54 | 2,23 | 0,12 | 59% | 8, 0,14 | no |
| Decisione Fed | Argento | Long attraverso l'evento | 1 | 79 | 1,35 | 0,27 | 58 | 1,31 | 0,44 | 55% | 8, 0,89 | no |
| Decisione Fed | FTSE MIB | Short attraverso l'evento | 1 | 79 | 0,92 | 0,17 | 58 | 0,92 | 0,18 | 57% | 8, -0,18 | no |
| Decisione Fed | DAX | Short attraverso l'evento | 1 | 79 | 1,02 | 0,13 | 58 | 0,83 | 0,19 | 55% | 8, 0,11 | no |
| Occupazione USA | EUR/CHF | Continua reazione | 2 | 37 | 2,21 | 0,23 | 27 | 2,46 | 0,21 | 63% | 6, -0,02 | solo qui |
| Occupazione USA | EUR/CHF | Continua reazione | 1 | 37 | 1,29 | 0,09 | 27 | 2,68 | 0,24 | 67% | 6, -0,03 | no |
| Occupazione USA | GBP/USD | Short attraverso l'evento | 1 | 117 | 1,29 | 0,08 | 82 | 1,19 | 0,08 | 48% | 12, -0,02 | no |
| Scorte gas EIA | Gas naturale | Contro la sorpresa | 1 | 70 | 1,43 | 0,51 | 73 | 1,05 | 0,46 | 53% | 12, 0,25 | no |
| Scorte gas EIA | Gas naturale | Contro la sorpresa | 2 | 70 | 0,78 | 0,59 | 73 | 1,99 | 2,10 | 56% | 12, 6,13 | no |
| Scorte gas EIA | Gas naturale | Short attraverso l'evento | 1 | 313 | 0,49 | 0,08 | 355 | 0,81 | 0,10 | 51% | 52, 0,45 | no |
| Scorte petrolio EIA | Petrolio WTI | Continua reazione | 2 | 174 | 0,27 | 0,06 | 110 | -0,02 | -0,01 | 51% | 16, -0,06 | no |
| Scorte petrolio EIA | Petrolio WTI | Continua reazione | 1 | 174 | 0,30 | 0,04 | 110 | -0,26 | -0,08 | 47% | 16, 0,22 | no |
| Scorte petrolio EIA | Petrolio WTI | Contro la sorpresa | 2 | 176 | -0,65 | -0,13 | 110 | 1,64 | 0,92 | 55% | 24, 0,63 | no |

Nota: dati giornalieri. Non si misura l'ingresso subito dopo l'annuncio (es. alle 16:30), ma solo da chiusura/apertura in poi. Date di uscita EIA ricostruite dal calendario standard (qualche festività può spostarle di un giorno).