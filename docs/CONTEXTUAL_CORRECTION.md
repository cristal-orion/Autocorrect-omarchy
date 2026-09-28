# Correzione contestuale con Leipzig

28 settembre 2026. Abbiamo collegato al laboratorio Fcitx un correttore
contestuale basato sui conteggi del training Leipzig. Recupera alcune astensioni
di SymSpell, compresi i typo di tre e quattro lettere. L'utente aveva segnalato
`stao → stato` e mostrato `ieri ho mangiato una piza` nella finestra.

Aggiornamento: la prova supporta anche [apprendimento personale](LEARNING.md)
con `--learn`. Le coppie confermate dall'utente possono recuperare astensioni
del modello generale senza richiedere la stessa frase.

## Prova manuale

```sh
bash scripts/build-fcitx-probe.sh
python scripts/run-fcitx-probe.py --client qt --mode surrounding --engine core \
  --context --frequency 5000
```

La finestra **Autocorrect - contesto Leipzig, da 3 lettere** parte con frequenza
5.000, margine baseline 1,30 e Hunspell attivo. **Alt+C** cambia l'interruttore
del contesto; **Alt+T** riporta al paragrafo. Le modifiche valgono per la prossima
parola. Digitare, includendo lo spazio finale:

| Input | Output verificato |
|---|---|
| `ieri ho mangiato una piza ` | `ieri ho mangiato una pizza ` |
| `sono stao ` | `sono stato ` |
| `ti devo dire una csa ` | `ti devo dire una cosa ` |
| `oggi ho mangiato del prosciutto nel pne ` | `oggi ho mangiato del prosciutto nel pane ` |
| `comune di piza ` | `comune di pisa ` |
| `una pipa ` | `una pipa ` |
| `piza ` senza parole precedenti | `piza ` |
| `ho lavato il piato ` | `ho lavato il piato ` |

Backspace dopo la sostituzione ripristina l'originale; lo spazio successivo lo
conserva. Per confrontare i due modi occorre cancellare e riscrivere la parola.
Il correttore non riesamina i paragrafi incollati o il testo già scritto.

Il pannello distingue il margine contestuale richiesto da quello baseline.
Mostra le parole precedenti usate, le occorrenze a sostegno del candidato e la
sua posizione nel ranking originale. Per `una piza`, `pizza` passa dal posto
16 al primo: 8 occorrenze di `una pizza` contro una di `una pipa`.

Per una richiesta dalla CLI:

```sh
.venv/bin/python -m autocorrect_core.contextual piza \
  --previous 'ieri ho mangiato una '
.venv/bin/python -m autocorrect_core.contextual stao --previous 'sono '
```

Il launcher richiede il corpus in `benchmark-data/leipzig-ita-news-2023-100k`.
Preparazione e provenienza: [LEIPZIG_CORPUS.md](LEIPZIG_CORPUS.md).

## Politica sperimentale

La baseline continua a prendere la prima decisione. Il correttore contestuale
interviene soltanto su `ambiguous` o `short_word`, con input minuscolo di almeno
tre caratteri. Conserva le sostituzioni già automatiche e i blocchi per
parole note, Hunspell, glossario, elisioni, campi disabilitati e token strutturati.
Questa scelta conserva anche gli errori preesistenti della baseline.

Il correttore usa **tutti i candidati** prima del limite del pannello. Il modello
calcola un punteggio per ciascuno a partire dagli unigrammi del training:

```text
p0(w) = (conteggio(w) + 0,5) / (totale_unigrammi + 0,5 * tipi_unigramma)
p(w | contesto) = (conteggio(contesto,w) + 20 * p_backoff(w)) / (totale_contesto + 20)
penalità = 3 per input di tre lettere, altrimenti 2
score = log10(p) - penalità * distanza
```

Prima usa il bigramma, poi il trigramma quando la riga esiste. La formula mantiene
un contributo del livello precedente anche per combinazioni assenti. I dati
includono i marcatori di confine del corpus. Le probabilità del modello e il
margine risultante non costituiscono una confidenza di correzione calibrata.

Per applicare il primo candidato richiediamo:

- distanza automatica massima 1 e frequenza minima della sessione;
- destinazione fuori dal glossario protetto;
- **tre lettere:** margine almeno 1,30 (o il valore di sessione, se maggiore),
  destinazione di almeno tre lettere e almeno 3 occorrenze del trigramma esatto;
  un ripiego limitato alle vocali mancanti è descritto sotto;
- **quattro lettere:** almeno 5 occorrenze nel bigramma o trigramma e margine
  contestuale almeno `log10(5) ≈ 0,699`;
- **cinque o più lettere:** almeno 3 occorrenze e margine pari alla soglia
  della sessione, inizialmente 1,30;
- per parole di almeno cinque lettere, se il nuovo primo candidato differisce
  dal primo della baseline, almeno 3 occorrenze del trigramma esatto.

Con dati assenti, contesto mancante o errore di lettura si torna alla decisione
baseline. Il solo abbassamento della frequenza non attiva questa modalità.
I motivi specifici sono `context_high_margin`, `context_low_evidence`,
`context_ambiguous` e `context_weak_rerank`.

### Tre lettere e vocali mancanti

`dire una cosa` compare 3 volte nel training. Questo consente di recuperare
`ti devo dire una csa` con un margine contestuale di circa 1,537. Il solo `una`
non basta per scegliere fra `cosa` e `casa`.

Per `prosciutto nel pne`, il corpus non contiene `nel pane` né `prosciutto nel`.
Contiene però `il pane` 8 volte, `del pane` 2 e `sul pane` una volta. La modalità
a tre lettere può aggregare i conteggi di articoli e preposizioni articolate
della stessa famiglia:

- `il/del/al/dal/nel/sul/col`;
- `lo/dello/allo/dallo/nello/sullo`;
- `la/della/alla/dalla/nella/sulla/colla`;
- `i/dei/ai/dai/nei/sui/coi`;
- `gli/degli/agli/dagli/negli/sugli`;
- `le/delle/alle/dalle/nelle/sulle/colle`.

È un segnale grammaticale aggregato, non l'osservazione della frase digitata.
Lo usiamo solo se nessun candidato a distanza automatica ha un'occorrenza nel
bigramma o trigramma esatto, ed esiste almeno un candidato ottenibile inserendo
una vocale interna. Il vincitore deve poi rispettare entrambe queste condizioni:

- una sola vocale interna mancante, senza altre modifiche;
- almeno 10 occorrenze nella famiglia e margine almeno 1,30.

Gli score usano la distribuzione aggregata con lo stesso smoothing 20 e prior
unigramma. Manteniamo nel confronto anche candidati a distanza 2 e destinazioni
non applicabili, evitando di gonfiare il margine eliminandoli prima del ranking.
Il punteggio penalizza di più la seconda modifica negli input di tre lettere.

Per `pne`, `pane` raccoglie 11 occorrenze aggregate e un margine circa 1,649.
La diagnostica lo esplicita con **Evidenza aggregata dagli articoli**. Prepariamo
le sei distribuzioni all'avvio per tenere quelle query fuori dal budget della
richiesta Fcitx. I conteggi del corpus restano in sola lettura.

Gli input di una o due lettere seguono la baseline. Le parole valide riconosciute
restano protette: `callo → caldo` richiede una politica diversa.

## Scelte durante lo sviluppo

Abbiamo scelto la soglia dedicata alle quattro lettere dopo aver esaminato
`piza`: il margine contestuale fra `pizza` e `pipa` è circa 0,903. Il caso ha
quindi informato la politica e non vale come valutazione indipendente.

La prima versione usava il margine 0,699 anche sulle parole più lunghe. Sullo
sviluppo produceva `ho lavato il piato → piano`: il bigramma `il piano` prevaleva,
mentre il corpus offriva poca evidenza per `lavato il`. Abbiamo mantenuto il
margine più severo sulle parole lunghe e richiesto evidenza di trigramma per
cambiarne il primo candidato. La versione finale conserva `piato`.

Nel campione di notizie, la prima versione modificava anche `persons → persona`
in un segmento sorgente con `contestando la persone`; il generatore aveva scelto
`persone` come target. Registriamo la divergenza senza riclassificarla a favore
del motore. La regola finale si astiene. Questi interventi usano lo sviluppo:
lo split di valutazione resta riservato.

## Prima misura del contesto da quattro lettere

Comando riproducibile, con cartella di output nuova:

```sh
.venv/bin/python -m autocorrect_core.context_benchmark \
  --output-dir benchmark-results/context-NUOVA-PROVA
```

Report finale: `benchmark-results/context-development-final/report.json`.
Il runner salva anche `news-cases.json`, checksum, politiche, errori e differenze
per caso. Il nuovo campione contiene 1.000 typo sintetici, uno per segmento
Leipzig di sviluppo, e le 1.000 parole sorgenti corrette. La selezione usa seed
20260928, esclude le sorgenti `pizza`, `pisa`, `stato` e non consulta le decisioni
del motore. Filtra mutazioni già nel lessico o riconosciute da Hunspell.

| Campione | Base: giuste / sbagliate | Con contesto: giuste / sbagliate |
|---|---:|---:|
| 1.000 typo in notizie + 1.000 sorgenti corrette | 575 / 2 | 728 / 2 |
| 11.146 casi precedenti senza contesto | 3.430 / 37 | 3.430 / 37 |
| 13 casi utente e controlli costruiti | 0 / 1 | 4 / 1 |
| 12 typo diagnostici preesistenti | 5 / 0 | 7 / 0 |
| 88 parole valide in 3 contesti costruiti | 0 / 3 | 0 / 3 |

Nel nuovo campione la copertura dei typo passa da **57,5% a 72,8%**; la precisione
delle sostituzioni da **99,65% a 99,73%**. Le 1.000 sorgenti corrette restano
intatte. Nei controlli validi gli errori residui sono `manim → mani`, già presenti
nella baseline. Il caso utente `stao` senza frase precedente resta invariato;
`sono stao` e `io sono stao` sono esempi costruiti, indicati come tali nei dati.

La fraseologia è giornalistica, gli errori sono sintetici e abbiamo usato i
risultati per scegliere le regole. I conteggi non stimano l'accuratezza della
digitazione quotidiana. La separazione del corpus riguarda segmenti identici,
non articoli o fonti.

Sulle 386 richieste del nuovo campione che consultano il contesto, il tempo del
correttore completo è p50 **2,13 ms**, p95 **6,38 ms**, p99 **10,18 ms**, massimo
**12,18 ms**. Il campione utente/costruito ha solo 6 richieste contestuali e un
p95 di **11,45 ms**. Le misure escludono socket e UI; il bridge conserva il
budget di 50 ms. Il processo di benchmark raggiunge 187,71 MiB RSS, includendo
SymSpell, dataset, report e modello: non è il costo incrementale del contesto.

## Lettura dei dati e integrazione

`TrainingNgrams` verifica archivio e checksum del database contro il manifest
Leipzig. Apre SQLite in sola lettura, carica gli unigrammi in RAM e usa la chiave
primaria per recuperare le righe contestuali. Mantiene al massimo 64 righe nella
cache Python e imposta la cache SQLite a 4 MiB. Le richieste non aggiornano i
conteggi e non apprendono dagli esempi dell'utente.

Il bridge invia il token e fino a 1.024 byte precedenti, tagliando a un confine
di parola UTF-8 valido. Il tokenizer seleziona al massimo le ultime due parole
della sequenza aperta; punto, fine riga, numeri e token strutturati interrompono
il contesto. La diagnostica salva queste parole in `decision.json` nella
cartella locale della sessione, dopo la risposta al client.

## Estensione alle tre lettere: confronto e verifiche

Report della versione finale di questo blocco:
`benchmark-results/context-three-letters-v2/report.json`. Il comando di benchmark
è quello riportato sopra, con una nuova cartella di destinazione. Il runner
confronta anche la versione precedente, impostando `min_length=4`, e verifica che
nessuna nuova decisione riguardi input di lunghezza diversa da tre.

Abbiamo aggiunto 500 typo sintetici di tre lettere in segmenti di sviluppo,
più 500 sorgenti corrette. La selezione esclude le sorgenti `cosa` e `pane`,
oltre ai casi già esclusi, e non consulta le decisioni del motore. Può sovrapporsi
al campione generale di notizie: i risultati dei gruppi non vanno sommati.

| Campione | Versione precedente: giuste / sbagliate | Da tre lettere: giuste / sbagliate |
|---|---:|---:|
| 500 typo di tre lettere + 500 sorgenti corrette | 0 / 0 | 56 / 0 |
| 1.000 typo del campione generale + 1.000 sorgenti | 728 / 2 | 731 / 2 |
| 36 parole corte valide in 4 contesti | 0 / 0 | 0 / 0 |
| 16 casi utente e controlli costruiti | 4 / 1 | 6 / 1 |

Le 144 prove di conservazione includono 24 nomi di strumenti, fra cui `nvi`,
`sed`, `uvx` e `tox`, e 12 parole italiane. Non abbiamo aggiunto queste voci al
glossario per far passare il confronto. Senza contesto, gli 11.146 casi precedenti
restano a 3.430 correzioni giuste e 37 sbagliate.

La prima variante meno restrittiva aveva prodotto 7 errori sui 500 typo e due
modifiche indesiderate sui nomi validi (`nvi → noi`, `sed → sud`). Da questi
risultati abbiamo ricavato il requisito del trigramma esatto per il percorso
ordinario. La versione finale ne recupera meno, con zero errori in quei campioni.
Sono scelte e misure sullo sviluppo, non una garanzia sui casi nuovi.

Sul gruppo dedicato alle tre lettere: 56/500 typo recuperati (11,2%), 444
astensioni. Sulle 484 richieste che consultano il contesto, p50 3,71 ms,
p95 7,96 ms, p99 11,30 ms, massimo 14,91 ms, esclusi socket e UI. L'estensione
mantiene quindi un comportamento prudente; non corregge tutti i typo corti.

- **120 test Python superati**, compresi 15 controlli del modello contestuale,
  del protocollo, degli articoli e dell'interruttore.
- **62 controlli Qt superati** con `--context --test`: i controlli precedenti più
  correzioni contestuali, diagnostica, cambio di contesto, Unicode, confini di
  frase, annullamento, soglie e interruttore.
- **15 controlli GTK superati**, compresi `csa`, `pne` e annullamento.

Report UI:

- `build/fcitx-probe-sessions/qt-surrounding-9uc0zm12/report.json`
- `build/fcitx-probe-sessions/gtk-surrounding-fn7te2ap/report.json`

La prossima misura utile è una nuova raccolta di frasi dell'utente, conservando
anche parole valide sconosciute, nomi e casi in cui il corpus sceglie la forma
grammaticale sbagliata.

### Segnalazioni successive alla prima misura

L'utente ha aggiunto due schermate e poi l'esempio `prosciutto nel pne`; il
dataset di sviluppo contiene ora 16 casi. Il report `context-development-final`
sopra citato riguarda i 13 precedenti.

- `ti devo dire una csa`: la versione da quattro lettere conservava `csa`. Nel
  training `dire una cosa` compare 3 volte, `dire una casa` zero; con il solo
  articolo, `una cosa` compare 134 volte e `una casa` 63. L'estensione alle tre
  lettere descritta sopra usa l'evidenza esatta di `dire una cosa`.
- `di estate al sole fa callo`: il core conserva `callo`, parola riconosciuta.
  È un errore tra parole esistenti. Il training contiene solo 2 occorrenze di
  `fa caldo`, zero di `fa callo` e nessuna riga `sole fa`. Questi dati non bastano
  a giustificare una correzione automatica delle parole valide con la politica
  attuale.

Abbiamo registrato `cosa` e `caldo` come target dedotti dalle frasi, e `pane`
come target esplicito dell'utente. `callo` resta fuori dalla correzione automatica
contestuale perché il lessico lo riconosce.
