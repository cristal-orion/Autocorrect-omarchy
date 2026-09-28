# LatinIME su Linux: prima prova e decisione

28 settembre 2026. Abbiamo compilato il core AOSP su Linux e realizzato una CLI
con candidati, punteggi e contesto. **La configurazione provata non supera i
criteri per sostituire SymSpell:** precisione 93,52% contro 98,63%, tre modifiche
indesiderate su nomi di pacchetti contro una, p95 nativo sui typo 17,88 ms contro
l'obiettivo di 10 ms.

Questa misura riguarda il nostro adattatore, la geometria QWERTY simulata e la
politica descritta sotto. Non misura la tastiera Android o FUTO completa.

## Riprodurre la prova

Servono Git, Python, un compilatore C++17, `pkg-config` e gli header di `json-c`.
Sulla macchina di sviluppo abbiamo usato GCC 16.2.1. Il programma di build usa
il compilatore direttamente; non richiede CMake, JDK, Android SDK o una JVM.

Dalla radice del progetto:

```sh
python scripts/build-latinime-probe.py

# Se la wordlist non è già presente:
.venv/bin/python -m autocorrect_core.aosp_data --output-dir benchmark-data/aosp-it

# La destinazione deve essere nuova; nella macchina di sviluppo esiste già.
.venv/bin/python -m autocorrect_core.latinime_probe prepare

.venv/bin/python -m autocorrect_core.latinime_probe query domnai \
  --previous 'ci sentiamo '

.venv/bin/python -m autocorrect_core.latinime_probe query '' \
  --previous 'grazie ' \
  --native-dictionary benchmark-data/latinime-it/rank-bigrams
```

Il primo esempio propone e applica `domani`; il secondo propone `alle`, `ai`,
`agli`. La CLI mostra la decisione della politica di prova, i candidati nativi,
i tempi e la memoria del processo. Il filtro Hunspell è attivo. Il glossario del
progetto protegge le parole tecniche; la prova non carica la memoria personale.

Per il confronto completo, scegliere un nome di report nuovo:

```sh
.venv/bin/python -m autocorrect_core.latinime_benchmark \
  benchmark-data/it-seed42/development.json \
  --output benchmark-results/latinime-development-NUOVO.json
```

Report finale di questa sessione:
`benchmark-results/latinime-development-final.json`. Il report conserva
checksum, revisioni, politica, errori per caso, distribuzioni dei tempi e
confronti separati. Il runner rifiuta dataset con `split=evaluation`.

## Componenti e portabilità

- `scripts/build-latinime-probe.py` acquisisce revisioni fisse, rifiuta sorgenti
  modificati e compila gli 82 file del gruppo `LATIN_IME_CORE_SRC_FILES` AOSP.
- `probes/latinime/main.cpp` collega il core e offre compilazione dei dizionari
  v403 e richieste JSON Lines. Per le chiamate native usate dalla prova abbiamo
  implementato un piccolo adattatore degli array JNI e del logging assente.
  Non avviamo un runtime Java.
- `src/autocorrect_core/latinime_probe.py` prepara i dati, gestisce il processo
  persistente e applica la politica di prova. Dopo un timeout chiude il processo
  per evitare di associare una risposta tardiva alla richiesta successiva.
- `src/autocorrect_core/latinime_benchmark.py` confronta decisioni automatiche,
  ranking a lessico condiviso e 24 casi contestuali diagnostici.

Il manifest di build conserva i checksum dei sorgenti nativi, degli header,
del wrapper e del binario. Il core AOSP resta senza patch. Per usare checkout
già disponibili si possono passare `--latinime-source` e
`--nativehelper-source`; valgono gli stessi controlli di revisione e pulizia.
Revisioni e licenze: [THIRD_PARTY.md](../THIRD_PARTY.md).

Il protocollo nativo accetta, per esempio:

```json
{"input":"domnai","previous":["ci","sentiamo"]}
```

L'array `previous` usa l'ordine del testo, dal meno al più recente, fino a tre
parole. La stringa vuota in `input` richiede previsioni. Il client Python
normalizza il testo, rispetta i confini del tokenizer esistente e rimuove i
candidati duplicati mantenendo la prima occorrenza. Il limite nativo è 47 code
point per parola. Il processo apre il dizionario compilato in sola lettura.

## Ipotesi della prova

### Tastiera fisica simulata

Usiamo una QWERTY italiana virtuale: tasti da 100 unità, righe sfalsate,
coordinate al centro del tasto, griglia da 50 unità e vicini entro 150 unità.
I timestamp distano 100 unità. Questa geometria è un'ipotesi iniziale, non una
misura degli errori della tastiera fisica dell'utente. Creiamo una sessione di
ricerca nuova per ogni richiesta, mantenendo caricato il dizionario; così la
cache dei prefissi non favorisce richieste consecutive simili.

### Dati

Partiamo dalla wordlist italiana AOSP sperimentale già verificata nel progetto:
185.605 forme normalizzate e 99.773 bigrammi. Compiliamo due dizionari v403:

- **unigrams:** codici unigramma originali dopo la normalizzazione del parser;
- **rank-bigrams:** gli stessi unigrammi, più un adattamento sperimentale dei ranghi.

Per i bigrammi calcoliamo `p = (1/rango) / somma(1/rango)` nella riga e lo
codifichiamo con la formula AOSP `255 + log2(p) * 8.58923700372`, arrotondando e
limitando a 0..255. **È una distribuzione surrogata sulle sole continuazioni
conservate.** Non ricostruisce i conteggi, non riproduce la decodifica del file
binario Android originale e attribuisce tutta la massa alle righe troncate.
Usiamo questo ramo per diagnosticare il collegamento del contesto, non per
stimare probabilità affidabili o promuovere una politica automatica.

Il compilatore esegue la garbage collection del formato nativo durante
l'importazione, riapre il dizionario e controlla i conteggi finali. Il manifest
registra anche i checksum dei TSV e dei file binari. Il corpus Leipzig resta
disponibile per un confronto successivo con conteggi completi.

### Decisione automatica

La politica `latinime-probe-v1` richiede il flag nativo di idoneità e uno score
normalizzato di almeno **0,185**, il valore AOSP “modest”. Lo score non è una
probabilità. Manteniamo i controlli baseline su contesti disabilitati, parole
note, Hunspell, glossario, elisioni, maiuscole e lunghezza minima di 5 caratteri.
Conserviamo anche le parole riconosciute dal nuovo lessico. Le destinazioni con
spazi, apostrofi o maiuscole non possono attivare una sostituzione.

Non applichiamo il margine 1,3, la frequenza minima o la distanza automatica
massima 1 di SymSpell. Quindi il confronto delle decisioni misura **motore,
lessico e politica insieme**. Non abbiamo portato tutte le regole Java di
`Suggest.java`, né tarato la soglia sui risultati di questa prova.

## Risultati sullo sviluppo

6.352 typo sintetici e 4.794 casi da conservare:

| Configurazione | Correzioni giuste | Sbagliate | Precisione | Copertura typo |
|---|---:|---:|---:|---:|
| SymSpell + Hunspell, frequenza 100.000 | 2.670 | 37 | 98,63% | 42,03% |
| SymSpell + Hunspell, frequenza 5.000 | 3.430 | 37 | 98,93% | 54,00% |
| LatinIME unigrammi + politica di prova | 4.347 | 301 | 93,52% | 68,44% |

Tutte le configurazioni conservano le 4.794 parole del dataset e gli ulteriori
64 controlli validi. Sui 24 nomi di pacchetti, LatinIME cambia `polars → polare`,
`marimo → marino` e `altair → altari`; SymSpell cambia `manim → mani` a entrambe
le soglie. I due gruppi di controllo restano separati dalle metriche sintetiche.

### Ranking con gli stessi dati

Confrontiamo i candidati prima dell'astensione usando lo stesso lessico da
185.605 forme e gli stessi codici unigramma. SymSpell usa la ricerca a distanza
massima 2 e il ranking esistente `log10(codice+1) - 2*distanza`; LatinIME usa il
proprio modello spaziale/linguistico.

| Motore | Target primo / 6.352 | Target nei primi 3 | Target nei primi 5 |
|---|---:|---:|---:|
| SymSpell | 5.051 | 5.738 | 5.879 |
| LatinIME | 4.943 | 5.610 | 5.775 |

Il lessico comune contiene 5.988 target su 6.352. La generazione dei typo aveva
usato il lessico baseline; questa selezione limita la generalizzabilità della
misura. Nel confronto a dati condivisi non osserviamo un vantaggio del ranking
LatinIME con la geometria scelta.

### Contesto

Sui 12 typo diagnostici, il target arriva primo in 11 casi con entrambi i
dizionari nativi. Sulle 12 continuazioni desiderate passiamo da 0 a 1 usando
i bigrammi. `grazie → mille` resta irraggiungibile attraverso la riga di
bigrammi disponibile. Sono esempi costruiti e possono avere più risposte valide.

### Tempi e memoria

Una passata di richieste distinte, dizionario caricato, build `-O2` senza
sanitizzatori, filesystem già caldo:

| Misura | p50 | p95 | p99 | Massimo |
|---|---:|---:|---:|---:|
| Nativo, soli 6.352 typo | 6,71 ms | 17,88 ms | 24,79 ms | 60,48 ms |
| Nativo, 11.146 richieste | 6,88 ms | 18,71 ms | 25,63 ms | 62,31 ms |
| Andata/ritorno JSON via pipe, 11.146 richieste | 7,57 ms | 19,60 ms | 27,06 ms | 63,22 ms |
| Inclusa politica Python, 11.146 richieste | 9,05 ms | 20,60 ms | 27,98 ms | 265,51 ms |

Il tempo nativo include creazione della sessione, ricerca ed estrazione dei
risultati; esclude serializzazione JSON e calcolo successivo degli score
normalizzati. La politica Python riusa `baseline.evaluate` per i controlli e
ne paga il costo. Questi sono tempi del laboratorio, non del trasporto Fcitx.

Avvio del processo fino a `ready`: 3,75 ms; apertura nativa e tastiera: 0,43 ms.
Questa misura non forza una lettura da disco freddo. Il processo nativo raggiunge
11,02 MiB RSS di picco e termina la misura a 10,62 MiB; il dato esclude Python.

## Verifiche e prossimo lavoro

- Suite completa: **101 test superati**, inclusi 9 nuovi controlli.
- Gli stessi 9 controlli passano con AddressSanitizer, UndefinedBehaviorSanitizer
  e rilevamento delle perdite attivi: contesto, Unicode, richieste errate,
  isolamento tra richieste, timeout e compilazione dei dizionari.
- Il confronto finale conferma i conteggi di qualità della prima esecuzione.

Abbiamo completato la prima sessione del budget di due descritto in
[AOSP_DATA.md](AOSP_DATA.md). Il porting nativo è praticabile; l'integrazione
linguistica non supera ancora i criteri concordati. Per una seconda sessione
servirebbero una politica di astensione migliore e una misura della geometria
QWERTY, prima di investire nel collegamento a Fcitx.

La priorità consigliata resta la prova manuale della frequenza SymSpell a 5.000
e il ranking contestuale con i conteggi Leipzig. I dati attuali favoriscono
questo percorso rispetto alla sostituzione del motore.

## Collegamento con FUTO

L'esame di FUTO `70a5d390c505a6bbcc4e14966e5628e43ca3f1fc` ha motivato la prova:
il progetto combina LatinIME con un modello neurale offline. Nella revisione
consultata assegna il modello incluso all'inglese; la documentazione conferma
quel limite. Il file italiano nel repository contiene 172.831 voci e zero
bigrammi. Per i dizionari aggiuntivi FUTO rimanda anche a Helium314, fonte già
usata qui. Abbiamo scelto il core AOSP Apache-2.0 per questo laboratorio.
