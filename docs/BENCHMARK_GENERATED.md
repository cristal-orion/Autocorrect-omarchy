# Benchmark sintetico esteso — 27 settembre 2026

Prima valutazione con il generatore v1, seed 42. La politica del correttore
rimane quella iniziale: distanza automatica 1, frequenza minima 100.000,
lunghezza minima 5 e margine minimo 1,3. Non è stata tarata su questi risultati.

Comandi e metodologia: [TYPO_GENERATOR.md](TYPO_GENERATOR.md).

## Risultati

| Misura | Sviluppo | Valutazione separata |
|---|---:|---:|
| Casi totali | 11.146 | 2.854 |
| Typo sintetici | 6.352 | 1.648 |
| Parole note intatte | 4.794 | 1.206 |
| Sostituzioni applicate | 2.714 | 680 |
| Sostituzioni uguali alla sorgente attesa | 2.674 | 668 |
| Sostituzioni diverse dalla sorgente attesa | 40 | 12 |
| Precisione delle sostituzioni | 98,53% | 98,24% |
| Copertura dei typo | 42,10% | 40,53% |
| Astensioni sui typo | 3.638 | 968 |
| Parole note alterate | 0 | 0 |
| Forma attesa al primo posto tra i candidati | 78,92% | 78,88% |
| Forma attesa tra i primi cinque candidati | 93,66% | 93,99% |

L'assenza di alterazioni sulle parole note **non dimostra** la conservazione
di nomi o parole valide assenti dal dizionario. Le quote di frequenza sono
bilanciate per mettere in evidenza i limiti, non pesate sulla digitazione reale.

## Cosa emerge dalla valutazione

| Fascia della parola sorgente | Typo | Correzioni giuste | Correzioni sbagliate | Astensioni |
|---|---:|---:|---:|---:|
| Comune | 488 | 345 | 0 | 143 |
| Media | 580 | 323 | 2 | 255 |
| Rara | 580 | 0 | 10 | 570 |

La fascia rara è sotto la frequenza minima richiesta per una destinazione
automatica. La politica attuale non può quindi correggere automaticamente
verso queste parole: la copertura nulla è in parte conseguenza esplicita della
soglia. Il problema sono i dieci casi in cui sceglie invece una parola comune.

Esempi dall'elenco degli errori:

| Typo generato | Parola sorgente attesa | Output del motore |
|---|---|---|
| `caglo` | `caglio` | `carlo` |
| `istabilite` | `ristabilite` | `stabilite` |
| `viyere` | `vigere` | `vivere` |
| `risultta` | `risultata` | `risulta` |
| `rcasi` | `crasi` | `casi` |
| `pvaese` | `pavese` | `paese` |

Nel set di valutazione gli errori si distribuiscono in 6 omissioni, 4 inversioni
e 2 sostituzioni di tasto vicino. Ripetizioni di lettere e doppie mancanti non
hanno prodotto correzioni sbagliate in questo campione.

Il punteggio iniziale dà abbastanza peso alla frequenza da preferire talvolta
una parola molto comune a una parola rara ugualmente vicina. Questo è un
obiettivo concreto per la prossima iterazione: confrontare su **development**
politiche di astensione e un modello degli errori di tastiera che distinguano
meglio le alternative. Non basta abbassare la soglia per aumentare la copertura.

Prima di interpretare ogni discrepanza come errore linguistico reale bisogna
considerare il lessico di origine. Nel set di sviluppo, per esempio, il
generatore eredita anche forme discutibili come `averebbe`: il benchmark conta
la ricostruzione della sorgente, non decide da solo quale forma sia normativa.

## Prestazioni del set di valutazione

Python 3.14.7, `symspellpy==6.10.0`, Linux x86-64, kernel
`7.2.5-3-omarchy`. I due benchmark sono stati eseguiti in sequenza.

| Misura | Risultato |
|---|---:|
| Caricamento e indicizzazione | 2,57 s |
| Mediana sui token con candidati | 0,532 ms |
| p95 sui token con candidati | 2,633 ms |
| p99 sui token con candidati | 4,104 ms |
| Massimo osservato | 6,265 ms |
| Memoria residente a fine benchmark | 144,05 MiB |
| Picco del processo corrente | 146,54 MiB |

14.270 valutazioni temporizzate, di cui 8.240 con candidati; la qualità viene
contata su 2.854 casi distinti, non sulle ripetizioni. I numeri escludono stampa,
avvio Python e qualunque futura integrazione nel desktop.

## Riproducibilità

Manifest locale: `benchmark-data/it-seed42/manifest.json`.

- Generatore SHA-256:
  `ece3f9f7bd84d5506ad8169e98e5492f53093e37e427959f6cafc6654471b0f5`
- Dizionario SHA-256:
  `5f746afb7e6ae802872061ef025ce883cfa2a8779780968fa285dfd0907e9cfc`
- Development SHA-256:
  `3a9cccc971ba514515962153c5f82864b09e3b6bfe0b4d1bd317034b9ad81fc8`
- Evaluation SHA-256:
  `d964e296127e51536b3e934e702dbd0138f4ab1d2a3481dbc76f34c5d2642f49`

I dati del primo smoke test sono stati esclusi dalla generazione. Gli split
non condividono sorgenti o input, ma non garantiscono separazione per lemma.
Ora che la valutazione è stata osservata, una conferma finale richiederà anche
casi nuovi non usati per scegliere le modifiche del motore.

Report completi locali:

- `benchmark-results/it-seed42-development.json`
- `benchmark-results/it-seed42-evaluation.json`

Gli errori completi, con cinque candidati e margine, sono in `quality.errors`.
L'esecuzione usa `--details errors`: l'array delle astensioni è vuoto per scelta,
ma il loro conteggio e i motivi restano nelle metriche.

## Esito

Il generatore ha trasformato un test manuale di 147 casi in una prova
riproducibile di 14.000 casi. Il risultato giustifica il lavoro sul motore:
**98,24% di precisione in questa prova non soddisfa ancora l'obiettivo di
correzioni silenziose quasi sempre corrette**. La prossima taratura deve ridurre
le sostituzioni sbagliate e affiancare controlli su lessico valido sconosciuto.
