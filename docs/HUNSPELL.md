# Filtro Hunspell: primo confronto sullo sviluppo

Esperimento del 27 settembre 2026. Abbiamo aggiunto un filtro opzionale che
conserva le parole riconosciute da Hunspell prima di cercare candidati SymSpell.
Manteniamo la politica iniziale: distanza automatica 1, frequenza minima
100.000, lunghezza minima 5 e margine minimo 1,3.

## Origine della scelta

Lomiri Keyboard usa Hunspell per l'ortografia e Presage per la predizione.
Abbiamo preso come riferimento il controllo lessicale, implementando un binding
Python all'API C di Hunspell. Per questa prova usiamo solo `Hunspell_spell`.

Sorgenti Lomiri consultati alla revisione
`bd4e9713120f47e5c0691cae0ee187b065dce0bc`:

- [spellpredictworker.cpp](https://gitlab.com/ubports/development/core/lomiri-keyboard/-/blob/bd4e9713120f47e5c0691cae0ee187b065dce0bc/plugins/westernsupport/spellpredictworker.cpp)
- [wordengine.cpp](https://gitlab.com/ubports/development/core/lomiri-keyboard/-/blob/bd4e9713120f47e5c0691cae0ee187b065dce0bc/src/lib/logic/wordengine.cpp)

## Uso

```sh
./autocorrect --hunspell quesot compilaste --json
./autocorrect --hunspell --stdin --json
./autocorrect --hunspell-dictionary /percorso/it_IT quesot
```

Il prefisso non include `.aff` o `.dic`. Il percorso predefinito è
`/usr/share/hunspell/it_IT`; `--hunspell-dictionary` abilita anche il filtro.
La libreria e il lessico restano caricati per tutta la sessione. Non occorre
un ulteriore package Python. Un caricamento fallito interrompe il comando con
un errore invece di eseguire una prova etichettata Hunspell senza validatore.

## Risultati sul dataset sintetico di sviluppo

11.146 casi: 6.352 typo sintetici e 4.794 parole note da conservare.

| Misura | Baseline | Con Hunspell |
|---|---:|---:|
| Sostituzioni applicate | 2.714 | 2.707 |
| Correzioni uguali alla sorgente attesa | 2.674 | 2.670 |
| Sostituzioni sbagliate rispetto alla sorgente | 40 | 37 |
| Precisione delle sostituzioni | 98,53% | 98,63% |
| Copertura dei typo | 42,10% | 42,03% |
| Astensioni sui typo | 3.638 | 3.645 |
| Parole note alterate | 0 | 0 |

Hunspell riconosce 45 input sintetici assenti dal dizionario di frequenze.
La baseline si asteneva già su 38 di essi. Negli altri sette casi il filtro
sostituisce una correzione con un'astensione:

| Input | Sorgente del generatore | Output baseline | Esito del veto rispetto alla sorgente |
|---|---|---|---|
| `onico` | `ionico` | `unico` | Evita una sostituzione sbagliata |
| `sfati` | `sfatti` | `stati` | Evita una sostituzione sbagliata |
| `agirò` | `aggirò` | `agire` | Evita una sostituzione sbagliata |
| `avvenienti` | `avvenimenti` | `avvenimenti` | Perde una correzione giusta |
| `riflessone` | `riflessione` | `riflessione` | Perde una correzione giusta |
| `divisone` | `divisione` | `divisione` | Perde una correzione giusta |
| `imperale` | `imperiale` | `imperiale` | Perde una correzione giusta |

Queste etichette misurano il recupero della parola sorgente. Alcune mutazioni
producono altre parole valide: `agirò`, per esempio, è una forma di *agire*.
Il generatore esclude le voci note alle 100.000 frequenze, ma non tutte le forme
riconosciute da Hunspell. Manteniamo il dataset e le etichette originali per
rendere confrontabili i risultati. Hunspell può inoltre accettare forme rare
o produttive che un utente non intendeva scrivere: la sua risposta non misura
la probabilità dell'intenzione.

La riduzione di tre errori è piccola. Restano 37 sostituzioni sbagliate nello
sviluppo, e il filtro non risolve la scelta fra due destinazioni plausibili.

## Parole valide fuori dalla lista di frequenze

Abbiamo scritto `data/it_valid_words_development.json` prima di osservare
le decisioni: 64 input da conservare, di cui 56 assenti dalla lista di frequenze.
Tre di quei 56 sono già protetti dal glossario tecnico.

| Misura | Baseline | Con Hunspell |
|---|---:|---:|
| Input conservati | 64/64 | 64/64 |
| Input sconosciuti conservati | 56/56 | 56/56 |
| Decisioni con motivo `valid_word` | 0 | 40 |

Per esempio Hunspell riconosce `compilaste`, `ricontrollassimo`,
`ricompilandolo` e `rilegatrici`. La baseline li conservava già per distanza,
frequenza o assenza di candidati. Su questo piccolo campione non osserviamo
quindi una riduzione dei falsi positivi. Molti input sono lunghi: la prossima
raccolta dovrà includere forme valide vicine a parole comuni e testo reale.

## Prestazioni osservate

Abbiamo eseguito i quattro benchmark sotto riportati in sequenza, sulla stessa
macchina, con Python 3.14.7 e symspellpy 6.10.0. Ogni esecuzione usa un processo
distinto. Tre ripetizioni temporizzate sullo sviluppo, dieci sul campione manuale.
Il tempo di caricamento comprende anche Hunspell quando attivo.

| Sviluppo sintetico | Baseline | Con Hunspell |
|---|---:|---:|
| Caricamento | 4,071 s | 4,070 s |
| p95 su tutti i token | 2,775 ms | 3,133 ms |
| p95 sui token con candidati | 3,540 ms | 4,056 ms |
| RSS a fine benchmark | 158,71 MiB | 171,05 MiB |

Sul campione manuale di parole valide il p95 di tutti i token passa da
1,492 ms a 0,392 ms: con Hunspell il core salta molte ricerche di candidati.
Il sottoinsieme dei token con candidati cambia fra le due configurazioni.
Queste misure descrivono le esecuzioni, non isolano il costo della singola
chiamata Hunspell; carico della macchina e scheduling possono influire.
La memoria include dataset, decisioni e campioni temporali del benchmark.

## Riproduzione

```sh
.venv/bin/autocorrect-benchmark benchmark-data/it-seed42/development.json \
  --iterations 3 --details errors \
  --output benchmark-results/it-seed42-development-baseline-hunspell-comparison.json

.venv/bin/autocorrect-benchmark benchmark-data/it-seed42/development.json \
  --hunspell --iterations 3 --details errors \
  --output benchmark-results/it-seed42-development-hunspell.json

.venv/bin/autocorrect-benchmark data/it_valid_words_development.json \
  --iterations 10 --output benchmark-results/it-valid-words-development-baseline.json

.venv/bin/autocorrect-benchmark data/it_valid_words_development.json \
  --hunspell --iterations 10 --output benchmark-results/it-valid-words-development-hunspell.json
```

Versioni locali: `hunspell 1.7.3-1`, `hunspell-it 2.4-13`.
Libreria: `libhunspell-1.7.so.0`; encoding: UTF-8.

| File | SHA-256 |
|---|---|
| `it_IT.aff` | `47ab462d8554102ea28600387f9cab51ac43295cfac5b842ab2deb415967ec5e` |
| `it_IT.dic` | `829da6ebee3fcf2a4342bb12944ced8ba64ffc24546c0e0bd6baa76cb13c93d3` |
| `development.json` | `3a9cccc971ba514515962153c5f82864b09e3b6bfe0b4d1bd317034b9ad81fc8` |
| `it_valid_words_development.json` | `45df205f528f6967170745bbe1981172a7c0b119a973bd4f408b87fcb83dcf02` |

I report registrano anche checksum del dizionario di frequenze e del glossario
protetto, politica, piattaforma e versione Python. Restano locali sotto
`benchmark-results/`. In questa iterazione abbiamo misurato solo lo sviluppo;
i risultati precedenti di `evaluation.json` si riferiscono alla baseline.

## Decisione

Manteniamo Hunspell come opzione sperimentale. Il filtro fornisce una protezione
lessicale esplicita per forme flesse e pronomi e riduce di poco gli errori
sintetici, con una lieve perdita di copertura. Prima di adottarlo come default
servono più casi validi a rischio e misure su testo quotidiano. Per l'ambiguità
fra candidati occorre ancora lavorare sulla selezione e sull'astensione.
