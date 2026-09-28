# Dati italiani AOSP: importazione e prima misura

27 settembre 2026. Questo blocco separa dati e motore prima della prova LatinIME.
Il core mantiene le sue regole; la CLI può usare una base sperimentale più ampia.

## Riproduzione

```sh
.venv/bin/python -m autocorrect_core.aosp_data --output-dir benchmark-data/aosp-it

.venv/bin/python -m autocorrect_core.data_ablation \
  benchmark-data/it-seed42/development.json \
  --aosp-wordlist benchmark-data/aosp-it/main_it.combined \
  --context-dataset data/it_context_diagnostic.json \
  --hunspell --output-dir benchmark-results/aosp-data-development

./autocorrect --interactive --no-learn \
  --aosp-wordlist benchmark-data/aosp-it/main_it.combined
```

L'importazione verifica revisione e checksum, conserva `main_it.combined`,
esporta `lexicon-scores.txt` e scrive `manifest.json`. Una seconda esecuzione
riusa la copia verificata senza rete. `--source FILE` importa una copia locale
della stessa revisione. I file esistenti con contenuto diverso causano un errore.

La CLI mantiene il lessico SymSpell predefinito e sostituisce la base demo con
i pesi AOSP. Per provare anche il lessico alternativo nei suggerimenti espliciti:

```sh
./autocorrect --interactive --no-learn \
  --dictionary benchmark-data/aosp-it/lexicon-scores.txt \
  --aosp-wordlist benchmark-data/aosp-it/main_it.combined
```

`--aosp-wordlist` e `--corpus` sono alternativi. `--no-learn` evita lettura e
scrittura della memoria personale. Il pannello indica `aosp-pesi`; i suggerimenti
richiedono Tab/F1/F2/F3. Il bridge Fcitx continua a interrogare il core a token.

## Contenuto e limiti del formato

Fonte e attribuzioni: [THIRD_PARTY.md](../THIRD_PARTY.md).

| Misura | Valore |
|---|---:|
| Voci originali | 202.588 |
| Bigrammi originali | 100.446 |
| Forme utilizzabili dopo normalizzazione | 185.605 |
| Bigrammi utilizzabili | 99.773 |
| Parole precedenti con almeno un bigramma | 46.562 |
| Forme condivise con le 100.000 voci baseline | 89.701 |
| Forme presenti solo nella nuova lista | 95.904 |
| Forme baseline assenti dalla nuova lista | 10.299 |

Il parser esclude 13.182 forme incompatibili col tokenizer (per esempio composti
con trattino) e combina 3.801 collisioni da normalizzazione usando il massimo
punteggio. La lista contiene anche nomi, forme con apostrofo e possibili errori:
il numero di voci non misura da solo la qualità lessicale.

Nel file italiano `f` degli unigrammi varia da **1 a 254**: è un codice compresso.
Nei bigrammi `f=1,2,3` indica il rango delle continuazioni, con 1 come prima
scelta. Ogni voce originale conserva al massimo tre continuazioni. Le collisioni
da normalizzazione possono riunire più voci. Non abbiamo i conteggi delle
occorrenze né le continuazioni eliminate; non possiamo ricostruirli dal file.

L'adattatore sperimentale usa:

- codice unigramma come peso relativo, normalizzato sulla somma;
- `1/rango` come peso relativo di ciascun bigramma;
- interpolazione già presente nel modello Python, senza taratura sui casi;
- massimo codice e minimo rango nelle collisioni, evitando di sommare codici
  compressi come fossero conteggi.

Questa trasformazione serve a provare i dati nel nostro predittore. Non riproduce
lo scoring di LatinIME e non genera probabilità calibrate. La soglia automatica
`min_frequency=100000` non è compatibile con i codici 1..254.

## Confronto sullo sviluppo sintetico

11.146 casi, di cui 6.352 typo e 4.794 parole da conservare. Hunspell attivo,
glossario tecnico del progetto, nessuna lista personale o memoria appresa.
Il runner usa la stessa politica per tre condizioni:

1. **Baseline**: dizionario e frequenze originali.
2. **Solo appartenenza al lessico**: mantiene le frequenze baseline; aggiunge
   le forme nuove con peso 1, sotto la soglia automatica. Misura l'effetto di
   riconoscere più parole e aggiungere candidati, senza inventarne le frequenze.
3. **Codici compressi diretti**: sostituisce il dizionario con `lexicon-scores.txt`.
   È un controllo dell'incompatibilità numerica, non una politica ottimizzata.

| Condizione | Giuste | Sbagliate rispetto alla sorgente | Precisione | Copertura typo | Target candidato n.1 |
|---|---:|---:|---:|---:|---:|
| Baseline | 2.670 | 37 | 98,63% | 42,03% | 78,64% |
| Solo appartenenza | 2.670 | 37 | 98,63% | 42,03% | 78,62% |
| Codici compressi diretti | 0 | 0 | non definita | 0% | 79,35% |

Tutte le 4.794 parole da conservare rimangono intatte. Il controllo con codici
compressi non supera la soglia di frequenza. Il lessico alternativo contiene
il 94,27% dei target di questo set, contro il 100% della baseline: il generatore
aveva scelto le sorgenti proprio dalla baseline. Il confronto quindi non misura
il beneficio di nuove parole target assenti dal vecchio lessico.

Non abbiamo consultato lo split di valutazione in questo esperimento né
modificato le soglie per migliorare il risultato.

## Diagnosi del contesto

`data/it_context_diagnostic.json` contiene **24 casi originali costruiti**,
fissati prima della prima esecuzione: 12 typo in frase e 12 continuazioni
colloquiali desiderate. Il runner non li carica come dati di apprendimento.
Non sono testo naturale raccolto dall'utente o un benchmark rappresentativo.
Per la prossima parola possono esistere molte continuazioni corrette.

La tabella misura il target al primo posto tra suggerimenti espliciti, senza
applicare sostituzioni automatiche:

| Lessico dei candidati | Pesi del predittore | Typo: target n.1 / 12 | Continuazione: target n.1 / 12 |
|---|---|---:|---:|
| Baseline | Frequenze baseline | 7 | 0 |
| Baseline | Unigrammi AOSP | 10 | 0 |
| Baseline | Unigrammi + bigrammi AOSP | 10 | 1 |
| AOSP | Unigrammi AOSP | 11 | 0 |
| AOSP | Unigrammi + bigrammi AOSP | 11 | 1 |

Il cambiamento sui typo in questi esempi dipende da pesi e lessico, senza un
ulteriore miglioramento del conteggio grazie ai bigrammi. Per le continuazioni,
la singola risposta desiderata compare nelle prime tre in 1 caso su 12 con
bigrammi. Esempi dei dati sorgente e dei suggerimenti:

- `grazie` → `alle`, `ai`, `agli`; manca `mille` nella riga contestuale.
- `buona` → `parte`, `notizia`, `salute`; manca `sera` nella riga contestuale.

Le alternative sono plausibili in altre frasi. Questi casi mostrano il limite
di una lista troncata per un uso colloquiale; non dimostrano che il motore
Android originale abbia la stessa qualità del nostro adattatore.

Su queste 24 richieste senza risposta in cache, il p95 del predittore è circa
18 ms con gli unigrammi baseline e 36–37 ms con i pesi AOSP. Il modello Python
scorre il vocabolario per cercare candidati: questa misura include quel costo,
esclude startup, IPC e UI, e non è una misura di LatinIME. I benchmark dei
singoli token hanno p95 circa 2,3–2,5 ms. I report conservano p99 e massimi.

Report completo locale: `benchmark-results/aosp-data-development/report.json`.
Il report contiene checksum dei dati e dei sorgenti, politica, versioni,
errori per token e suggerimenti per ciascun caso.

## Criteri della prova LatinIME

**Esito del 28 settembre:** abbiamo completato la prima sessione con una CLI
Linux funzionante. La configurazione provata non supera i criteri di precisione,
conservazione dei nomi validi e p95. Risultati e comandi:
[LATINIME_PROBE.md](LATINIME_PROBE.md). Seguono i criteri fissati prima della prova.

Il prossimo blocco ha un budget massimo di **due sessioni di lavoro**; alla
fine della prima registreremo ostacoli e parte ancora necessaria. Prima di
collegarlo a Fcitx richiediamo due verifiche distinte:

**Portabilità tecnica:** CLI o libreria su Linux senza runtime Android;
correzioni e previsioni con contesto; QWERTY virtuale con tocchi al centro dei
tasti come prima ipotesi da confrontare; identificazione delle regole Java
necessarie alla scelta della sostituzione. Misurare a motore caricato p50, p95,
p99 e massimo, con obiettivo p95 sotto 10 ms su richieste distinte. Startup e
latenza IPC vanno riportati a parte. Una media sotto 10 ms non basta.

**Qualità:** confronto appaiato sullo stesso insieme, con identici dati di
partenza quando il formato lo consente; distinguere ranking e decisione
automatica. Sullo sviluppo attuale con Hunspell il riferimento è precisione
98,63% e copertura 42,03%. Come criterio operativo preliminare richiediamo
precisione almeno pari e copertura maggiore di almeno 5 punti percentuali,
senza aumentare le modifiche sui casi da conservare. L'esito va confermato su
testo naturale annotato e casi nuovi: i sintetici da soli non bastano.

Se i codici richiedono trasformazioni diverse tra i motori, il report deve
esplicitarle: non sarebbe una differenza attribuibile al solo algoritmo.
Una compilazione riuscita non implica il superamento del criterio linguistico.
Al termine del budget decidiamo in base alle misure se proseguire il porting;
per il percorso Python restano disponibili parser, dati e confronto separato.

Prima di parlare di un modello italiano adeguato servono conteggi n-gramma più
completi e testi più vicini all'uso quotidiano. Il file sperimentale fornisce
un lessico e alcune associazioni utili per le prove, ma non risolve quel bisogno.

Aggiornamento: abbiamo preparato un primo archivio ufficiale di notizie italiane
di Lipsia, con split e conteggi completi del training. Comandi e verifica di
licenza ancora aperta: [LEIPZIG_CORPUS.md](LEIPZIG_CORPUS.md).
