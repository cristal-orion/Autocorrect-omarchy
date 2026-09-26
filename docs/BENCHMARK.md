# Prima misura del prototipo — 26 settembre 2026

Comando eseguito dalla cartella del progetto:

```sh
.venv/bin/autocorrect-benchmark data/it_smoke.json --iterations 30 \
  --output benchmark-results/it-smoke.json
```

Ambiente: Linux x86-64, kernel `7.2.5-3-omarchy`, Python 3.14.7,
`symspellpy==6.10.0`, implementazione Python senza estensioni opzionali.

## Qualità sul campione manuale

| Misura | Risultato |
|---|---:|
| Casi totali | 147 |
| Casi con correzione attesa | 76 |
| Casi da preservare | 71 |
| Sostituzioni automatiche | 55 |
| Sostituzioni corrette | 55 / 55 |
| Sostituzioni sbagliate | 0 |
| Casi da preservare rimasti invariati | 71 / 71 |
| Copertura delle correzioni attese | 55 / 76 = 72,37% |
| Primo candidato esattamente uguale alla forma attesa | 69 / 76 = 90,79% |
| Astensioni sui casi con correzione attesa | 21 |

Il confronto tra candidato e forma attesa è sensibile alle maiuscole. La CLI
mostra candidati minuscoli anche per `Quesot`, ma conserva l'input originale.

Questi risultati descrivono **soltanto il dataset di sviluppo**. Non dimostrano
precisione del 100% nell'uso quotidiano. Anche il calcolo binomiale di Wilson
riportato dal tool darebbe un intervallo al 95% di circa **93,47–100%** sulle
55 sostituzioni; il campione manuale non è comunque casuale o rappresentativo,
quindi tale intervallo non va interpretato come garanzia sull'uso reale.

La politica non è stata allentata per correggere gli esempi rimasti fuori.
Per esempio:

- `proggeto`: suggerisce `progetto`, ma due modifiche impediscono la sostituzione;
- `domnai`: suggerisce `domani`, ma il vantaggio sul secondo score è 1,275,
  inferiore alla soglia iniziale di 1,3;
- `sopratutto`: è già presente nel dizionario, quindi viene conservato;
- `lacqua`, `laltro`, `unamica`: possibili elisioni, conservate;
- `Quesot`, `QUESOT`: maiuscole conservate.

## Prestazioni

| Misura | Risultato |
|---|---:|
| Caricamento e indicizzazione del dizionario | 2.704 ms, circa 2,70 s |
| Memoria residente a fine prova | 140,78 MiB |
| Picco di memoria del processo corrente | 144,88 MiB |
| Latenza mediana, token con candidati | 0,544 ms |
| Latenza p95, token con candidati | 1,902 ms |
| Latenza p99, token con candidati | 2,271 ms |
| Latenza massima misurata | 2,716 ms |

4410 valutazioni temporizzate (147 casi × 30 ripetizioni), di cui 2310 con
candidati. Le decisioni di qualità sono contate una sola volta per caso.
Le misure a caldo escludono caricamento, avvio Python e stampa JSON.
Non misurano il percorso end-to-end di una futura integrazione Fcitx.

La memoria viene letta da `/proc/self/status` (VmRSS/VmHWM). Su questa macchina
`getrusage().ru_maxrss` riportava anche un picco ereditato precedente a `exec`,
circa 1,17 GiB, non attribuibile al motore: non viene usato nel report.

Per digitazione continua il motore deve rimanere caricato, come già avviene con
`./autocorrect --stdin --json`. Lanciare una nuova CLI per ogni parola
pagherebbe ogni volta il costo di avvio di circa 2,7 secondi.

## Identificatori per riprodurre la prova

- Dizionario SHA-256:
  `5f746afb7e6ae802872061ef025ce883cfa2a8779780968fa285dfd0907e9cfc`
- Dataset SHA-256:
  `765ee540cb63f07c5fe0145dc811f7f320e815fe53f5978ad4d7bd2d2ed273e0`
- Lista effettiva di parole protette: 80 voci, SHA-256 della lista normalizzata
  ordinata e separata da newline:
  `36fbb031975918253ab8f0a51c613a3959f58aa620d7d575b79876da6097dd9c`
- Politica: distanza di ricerca 2, distanza automatica 1, lunghezza minima 5,
  frequenza minima 100.000, penalità per modifica 2, margine minimo 1,3.

Il report JSON locale conserva anche risultati per categoria, motivi di
astensione, tutte le correzioni mancate e gli eventuali errori.

## Esito

La CLI costituisce una prima base funzionante e misurabile. Il passo seguente
è una valutazione indipendente più ampia, soprattutto sulle parole corrette
assenti dal dizionario, prima di abilitare sostituzioni nelle applicazioni.
