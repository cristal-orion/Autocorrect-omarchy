# Parole attaccate e apostrofo

Stato: 29 settembre 2026. Blocco sperimentale nel core e nel bridge Fcitx, verificato
nelle finestre di prova Qt/GTK, **non ancora installato nel desktop**.

Allo spazio il motore può ora staccare due parole scritte unite e rimettere
un apostrofo mancante:

| Input | Output | Motivo |
|---|---|---|
| `nonlo` | `non lo` | `segmentation_split` |
| `vabene,` | `va bene,` | punteggiatura finale conservata |
| `allinizio` | `all'inizio` | `segmentation_elision` |
| `cè`, `lho`, `dovè` | `c'è`, `l'ho`, `dov'è` | elisione breve |
| `lagente` | `lagente` | `la gente` e `l'agente` troppo vicini |
| `nè` | `nè` | più probabile `né` sbagliato che `n'è` |
| `Lacqua` | `Lacqua` | maiuscola: possibile nome |
| `perpiacere` | `perpiacere` | poca evidenza, finché il corpus colloquiale non cresce |

Backspace subito dopo annulla anche queste sostituzioni. L'annullamento viene
registrato dalla memoria personale come per le altre correzioni.

## Regole

Codice: `src/autocorrect_core/segmentation.py`.

1. **Quando interviene.** Solo dopo che il motore lessicale, e il contesto se
   attivo, si sono astenuti. Non tocca mai parole note, parole valide per
   Hunspell, parole protette, token con maiuscole, campi esclusi o correzioni
   già decise.
2. **Letture candidate.**
   - Separazione in due parti, entrambe nel lessico SymSpell con frequenza
     almeno pari alla soglia corrente (5.000 nella prova).
   - Apostrofo davanti a una vocale o a `h`, solo se Hunspell o il lessico
     accettano la forma: `l'acqua` e `l'ho` sì, `un'altro` no.
3. **Evidenza.** È il numero di volte in cui la forma esatta compare nei
   conteggi di training: il bigramma `non → lo` per le separazioni, la forma
   `l'acqua` per le elisioni. Si sommano Leipzig (peso 1) e, se caricato, il
   corpus colloquiale (peso regolabile, predefinito 1).
4. **Concorrenza con le correzioni normali.** Le correzioni a una lettera
   (`trada → strada`) competono sulla stessa scala, con una penalità
   `log10` di 1 per ogni lettera modificata. Così una separazione non ruba un
   typo ordinario.
5. **Elisioni brevi.** Sotto le 5 lettere il motore non applica mai correzioni
   di lettere, quindi `lo` o `è` non sono alternative reali per `lho` e `cè`.
   Fa eccezione lo scambio fra accento grave e acuto più frequente della forma
   elisa (`nè → né`), che resta in gara e porta all'astensione.
6. **Soglie.** Evidenza almeno 3 e rapporto almeno 5 sulla seconda lettura
   (margine `log10(5)` ≈ 0,70). Sono scelte di sviluppo, non una probabilità.

## Misure di sviluppo

Comando, dati e report:

```sh
.venv/bin/python -m autocorrect_core.segmentation_benchmark \
  --colloquial-corpus benchmark-data/colloquial-it-llm/prepared \
  --output-dir benchmark-results/NUOVA-CARTELLA
```

Riferimento: `benchmark-results/segmentation-development-v3/report.json`,
con frequenza 5.000, Hunspell e 423 frasi colloquiali. La griglia prova
rapporto 2/5/20, penalità 0/1/2 ed evidenza 2/3. Con la configurazione
predefinita:

| Gruppo | Casi | Cambi giusti | Cambi sbagliati |
|---|---:|---:|---:|
| Unioni di parole adiacenti | 102.528 | 25.838 | 2 |
| Elisioni senza apostrofo | 1.934 | 978 | 0 |
| Esempi scritti a mano | 20 | 17 | 0 |
| Parole sconosciute reali (controllo) | 4.783 | — | 22 |
| Parole valide manuali (controllo) | 88 | — | 0 |
| Typo sintetici a parola singola | 6.352 | — | 6 |

- **Parole sconosciute.** Molti dei 22 cambi sono veri errori del testo di
  notizie (`lasorella`, `cheha`, `suointervento`). Sono falsi positivi reali
  `startup`, `trail`, `aldi` e `perin`. Nomi come `sanpaolo` compaiono in
  minuscolo solo perché il corpus è normalizzato: scritti con la maiuscola
  restano protetti.
- **Typo rubati.** Sono 6: `stampail`, `viail`, `farela`, `frale`, `londa` e
  `ildi`. Per esempio `londa` diventa `l'onda` invece di `londra`.
- **p95 del solo passo di separazione** sotto 0,1 ms, con i conteggi in
  memoria del benchmark. Senza cache resta sotto 0,5 ms negli esempi CLI.

**Questi numeri non misurano la digitazione reale.** Le unioni sono
artificiali: due parole adiacenti delle frasi di sviluppo, scritte insieme.

## Corpus colloquiale

Le notizie Leipzig non contengono il parlato: `per piacere` vi compare 0
volte. Le frasi generate dall'utente con un modello linguistico vanno in
`benchmark-data/colloquial-it-llm/raw/*.txt`, una per riga, con modello e data
annotati in `GENERATION.txt`. Il prompt usato è nella conversazione del 29
settembre.

```sh
.venv/bin/python -m autocorrect_core.colloquial_corpus
```

L'importatore (`src/autocorrect_core/colloquial_corpus.py`):

- scarta intestazioni, recinti di codice, elenchi e ogni riga con una parola
  sconosciuta a lessico e Hunspell;
- usa la stessa divisione 80/10/10 per hash di Leipzig;
- conta solo il training e ricostruisce `prepared/` da zero a ogni esecuzione.

Il peso resta separato perché i conteggi riflettono lo stile del modello, che
ripete le locuzioni del prompt. **Non si valuta mai il correttore su queste
frasi.**

Il tokenizzatore conserva ora `po'`, `mo'`, `be'`, `va'`, `fa'`, `di'`, `da'` e
`sta'` come parole. Gli altri apostrofi finali restano virgolette di chiusura.

## Prove Fcitx

```sh
bash scripts/build-fcitx-probe.sh
python scripts/run-fcitx-probe.py --client qt --mode surrounding --engine core \
  --context --segmentation --test
python scripts/run-fcitx-probe.py --client gtk --mode surrounding --engine core \
  --context --segmentation --test
```

Le prove automatiche partono dalla frequenza predefinita, poi il test la porta
a 5.000. Con `--frequency 5000` la prova Qt si blocca per timeout.

**Risultati del 29 settembre:**

- **72 controlli Qt**, compresi 10 sulla separazione: separazione, apostrofo,
  `cè`, punteggiatura, casi ambigui, maiuscola, `nè`, parola nota, annullamento
  e continuazione dopo l'annullamento.
- **19 controlli GTK**, compresi 4 sulla separazione.
- **Regressione dell'apprendimento:** 35 controlli Qt e 35 GTK.

Per la prova manuale: `--context --frequency 5000 --segmentation`, con
`--colloquial` facoltativo.

`--colloquial` aggiunge il corpus colloquiale nelle prove manuali. Le prove
`--test` usano solo Leipzig, così gli esiti attesi non cambiano mentre il
corpus cresce.

L'addon accetta ora una sostituzione con al massimo uno spazio interno
(`engine_client.h`). Test nativo: `tests/test_engine_client.py`.

## Limiti e prossimi passi

- **Solo due parti.** `nonloso` non diventa `non lo so`.
- **Solo dentro un token.** `un amica → un'amica` richiede di unire il token
  precedente e non è trattato.
- **Correzione manuale non osservata.** Il tracker nativo non riconosce ancora
  lo spazio inserito a mano in `perpiacere` come correzione da imparare. La
  memoria Python accetta già questi target, e la separazione rifiutata con
  Backspace viene ricordata.
- **Accenti sbagliati** come `perchè` sono un problema distinto. Oggi li
  corregge il motore base solo quando il margine basta.
- **Servizio desktop.** `autocorrect.service` non passa ancora
  `--segmentation`: l'installazione è un passo separato, dopo le prove Qt/GTK.
