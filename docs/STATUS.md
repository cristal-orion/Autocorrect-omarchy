# Autocorrect Omarchy: stato del progetto

Aggiornamento: 29 settembre 2026.
Cartella: `/home/michele/Projects/autocorrect`.
Repository: https://github.com/cristal-orion/Autocorrect-omarchy

**Sessione ripresa: pannello Omarchy collegato al motore.** Il widget si apre;
il servizio era spento ed è stato avviato. Plugin abilitato, servizio attivo,
avvio al login abilitato. Il pannello ora mostra l'ambito della prova
BrowserOS. **143 test Python superati**, incluso lo stato desktop.
Regressioni: **62 controlli Qt e 15 GTK** passati.
Cronologia del pannello:
[OMARCHY_PANEL_WIP.md](OMARCHY_PANEL_WIP.md).

**BrowserOS quotidiano collegato:** addon Fcitx limitato all'app ID BrowserOS,
attivazione automatica al focus e piccolo componente browser per i campi web.
Correzione e undo verificati anche su **Google Ricerca, Gemini, ChatGPT e
Google Traduttore** nel profilo quotidiano. **25 controlli** sul laboratorio
browser e sulle app escluse, più **2 controlli dopo riapertura**. Risolti il
controllo ortografico disabilitato nel profilo e i campi con indicazioni IME
assenti o disabilitate. Suggerimenti attivati:
**Alt+1/2/3** selezionano i candidati, F1 resta al browser; verificata anche
la regressione dei 35 controlli Qt di apprendimento. Slack, ZapFast e terminale
sono ancora esclusi. Avvio, limiti e accorgimento di sincronizzazione per
Fcitx 5.1.22: [BROWSEROS_PROBE.md](BROWSEROS_PROBE.md).

**Conferma manuale finale:** dopo la configurazione del profilo aggiuntivo,
l'utente conferma il funzionamento su Claude e riferisce che funziona anche
su Chrome nei campi provati. I test automatici riguardano BrowserOS.
Riepilogo della sessione: [SESSION_2026-09-29.md](SESSION_2026-09-29.md).

## Punto centrale emerso dalla prova manuale

**A frequenza minima 5.000 l'utente riferisce che quasi tutto funziona bene.
I casi rimasti includono parole corte e candidati ordinati male. Ora il
laboratorio Fcitx offre anche il contesto Leipzig, attivabile per la prova.**

L'utente ha confermato il buon comportamento meccanico, poi ha scritto frasi
libere e osservato molte correzioni mancate. Abbiamo verificato che quei token
raggiungono il motore: spesso il core si astiene per ambiguità, oppure conserva
una voce già presente nel dizionario. Gli esempi favorevoli usati nei test
dimostrano il collegamento, non l'affidabilità o la copertura nell'uso reale.

I casi `stao → stato` e `una piza → una pizza` hanno guidato il nuovo blocco
contestuale. Il prossimo lavoro è provarlo su nuove frasi naturali: la scelta
dei parametri ha usato esempi e risultati di sviluppo, non valutazione indipendente.

## Aggiornamenti successivi al riepilogo iniziale

- **Parole attaccate e apostrofo (29 settembre, pomeriggio):**
  - **Cosa fa:** `nonlo → non lo`, `allinizio → all'inizio`, `cè → c'è`. Si
    astiene su letture vicine (`lagente`) e sulle confusioni d'accento (`nè`).
  - **Evidenza:** conteggi Leipzig più un corpus colloquiale generato
    dall'utente, filtrato con Hunspell e tenuto separato.
  - **Sviluppo:** 25.838 unioni giuste e 2 sbagliate; 978 elisioni giuste e
    nessuna sbagliata; 6 typo a parola singola rubati su 6.352.
  - **Test:** 161 test Python.
  - **Prove Qt/GTK con `--segmentation`:** 72 controlli Qt e 19 GTK superati.
  - **Regressione dell'apprendimento:** 35 controlli Qt e 35 GTK superati.
  - **Desktop:** non ancora installato.
  - **Dettagli:** [SEGMENTATION.md](SEGMENTATION.md).

- **Apprendimento personale nel bridge Fcitx:** avvio con `--learn`, memoria
  locale persistente in `~/.local/share/autocorrect/feedback.sqlite3` (rispetta
  XDG_DATA_HOME). Impara da modifiche manuali alla stessa parola e scelte esplicite;
  `pne → pane` si trasferisce a frasi nuove e riavvii. Le autocorrezioni non
  aggiungono conferme; `cane → pane` registra solo uso contestuale. Backspace
  immediato registra il rifiuto. Alt+L sospende la memoria, Alt+D dimentica,
  Alt+S abilita i candidati opzionali. **35 controlli Qt e 35 GTK** verificano
  anche password/NoPredictiveText e dimenticanza dopo riavvio. Dettagli:
  [LEARNING.md](LEARNING.md). Prossimo blocco: backoff unificato e modello degli
  errori, come concordato, per migliorare anche i typo mai corretti prima.

- **Typo di tre lettere:** verificati nella finestra `ti devo dire una csa → cosa`
  e `oggi ho mangiato del prosciutto nel pne → pane`. Il primo usa il trigramma
  esatto; il secondo un ripiego per vocali interne mancanti basato su famiglie
  di articoli. Su 500 typo corti di sviluppo recupera 56 correzioni senza errori;
  conserva 144 controlli di parole corte valide. Le soglie sono state scelte
  sullo sviluppo. **62 controlli Qt, 15 GTK e 120 test Python superati**.
  Report: `benchmark-results/context-three-letters-v2/report.json`.
  [CONTEXTUAL_CORRECTION.md](CONTEXTUAL_CORRECTION.md) descrive regole e limiti.

- **Contesto Leipzig nel bridge Fcitx:** avvio con `--context --frequency 5000`,
  interruttore Qt Alt+C. Recupera astensioni, con una politica dedicata alle
  quattro lettere. Verificati `una piza → una pizza` e `sono stao → sono stato`.
  Su 1.000 nuovi typo sintetici in frasi Leipzig di sviluppo passa da 575 a
  728 correzioni giuste, mantenendo 2 errori; nessuna modifica alle 1.000 parole
  sorgenti corrette. Sono risultati di sviluppo. p95 del correttore sulle
  richieste contestuali di quel campione: 6,38 ms. **50 controlli Qt e 12 GTK
  superati**. Politica, limiti e comandi: [CONTEXTUAL_CORRECTION.md](CONTEXTUAL_CORRECTION.md).

- **Frequenza regolabile nella finestra Fcitx Qt:** campo Alt+F e pulsanti
  100.000 (Alt+1) / 5.000 (Alt+5), con margine iniziale 1,30 e Hunspell attivo.
  La diagnostica mostra frequenze dei candidati e soglie usate. Verificati
  `maglioner → maglione` a 5.000, annullamento e ripristino a 100.000:
  **35 controlli Qt e 9 GTK superati**. La finestra è pronta per raccogliere
  casi da testo naturale. Istruzioni: [FCITX_PROBE.md](FCITX_PROBE.md).

- **Prova LatinIME nativa completata il 28 settembre:** CLI Linux con dizionari
  italiani v403, candidati e contesto, senza runtime Android/Java. Sullo sviluppo
  la politica di prova applica 4.347 correzioni giuste e 301 sbagliate: precisione
  93,52%, copertura 68,44%. SymSpell a frequenza 5.000 ottiene 3.430 giuste e
  37 sbagliate. LatinIME cambia 3/24 nomi di pacchetti contro 1/24 e ha p95 nativo
  sui typo 17,88 ms. A parità di lessico/codici il ranking non migliora. La prova
  non supera i criteri per il collegamento a Fcitx. Comandi, dati e decisione:
  [LATINIME_PROBE.md](LATINIME_PROBE.md).
- L'esame di FUTO ha confermato l'interesse del motore ibrido, ma il modello
  neurale incluso supporta l'inglese. Per la prova abbiamo usato il core AOSP
  Apache-2.0. Priorità consigliata: frequenza SymSpell 5.000 su testo naturale
  e contesto con i conteggi Leipzig.

- Preparato l'archivio ufficiale Leipzig `ita_news_2023_100K`: 105.798 segmenti
  di training, 13.010 di sviluppo e 13.313 riservati alla valutazione, con
  deduplicazione e split per hash. Il database contiene 641.084 tipi bigramma
  e 1.216.612 trigrammi, con conteggi completi dal solo training. La licenza
  specifica resta da verificare: la pagina delle condizioni richiede una verifica
  browser e l'archivio non contiene un avviso. [LEIPZIG_CORPUS.md](LEIPZIG_CORPUS.md).

- Sweep della frequenza con Hunspell e margine 1,3: a 5.000, 3.430 correzioni
  giuste contro 2.670 a 100.000, con gli stessi 37 errori sintetici. A 1.000
  le giuste salgono a 3.523. Nei 64 controlli validi nessuna modifica; nei 24
  nuovi nomi di pacchetti un errore (`manim → mani`) già presente nella baseline.
  `maglioner → maglione` si sblocca a 20.000. Dettagli: [FREQUENCY_SWEEP.md](FREQUENCY_SWEEP.md).

- La finestra Qt offre ora **Margine minimo** (Alt+M), da 0,01 a 5,00, con
  ripristino a 1,30. La modifica vale dalla prossima parola nella sola sessione.
  Verifica: 22 controlli Qt, inclusi soglia, diagnostica e annullamento.
- Abbiamo importato la wordlist italiana AOSP sperimentale: 185.605 forme e
  99.773 bigrammi utilizzabili. I valori sono codici compressi e ranghi, non
  conteggi. Nel confronto sullo sviluppo, l'espansione del lessico mantenendo
  le frequenze baseline lascia invariate le correzioni giuste e sbagliate.
- La CLI può provare i dati con `--aosp-wordlist FILE`. Nei 24 casi diagnostici
  costruiti, i nuovi pesi aiutano alcuni typo; i bigrammi troncati non bastano
  per la previsione colloquiale desiderata. Il nuovo percorso Fcitx usa invece
  i conteggi Leipzig. Risultati e criteri: [AOSP_DATA.md](AOSP_DATA.md).
- Suite aggiornata: **134 test superati**. I 9 controlli del laboratorio
  LatinIME passano anche con AddressSanitizer e UndefinedBehaviorSanitizer.

## Obiettivo

Correttore italiano per tastiera fisica su Linux/Omarchy, Wayland e Hyprland:
correzione affidabile allo spazio, annullamento con Backspace ed esclusione
dei contesti sensibili. Anche i suggerimenti contestuali e la personalizzazione
interessano all'utente, prendendo come riferimento l'esperienza SwiftKey/Gboard.

## Core attuale

- Python con `symspellpy==6.10.0`, dizionario italiano da 100.000 voci con
  frequenze, revisione fissa e checksum; funzionamento offline dopo il setup.
- Glossario tecnico e supporto a parole personali protette.
- Politica conservativa: minuscole, almeno 5 caratteri, distanza automatica
  massima 1, frequenza minima 100.000 e margine minimo di score 1,3.
- Score euristico, non probabilità calibrata.
- Hunspell opzionale per conservare ulteriori forme riconosciute; non aggiunge
  destinazioni di correzione a SymSpell.
- Le condizioni applicabili al dizionario di frequenze derivato restano da
  chiarire prima di redistribuirlo; provenienza e checksum sono documentati.

```sh
./autocorrect quesot
./autocorrect --hunspell --stdin --json
```

### Risultati di riferimento

Il generatore riproducibile ha prodotto 14.000 casi sintetici, con sviluppo e
valutazione separati per parola sorgente. Nella valutazione della baseline:
668 correzioni giuste e 12 sbagliate su 680 sostituzioni, precisione 98,24%,
copertura dei typo 40,53%; tutte le 1.206 parole note conservate.

Sul solo sviluppo, con 6.352 typo e 4.794 parole note:

| Misura | Baseline | Con Hunspell |
|---|---:|---:|
| Correzioni giuste | 2.674 | 2.670 |
| Sostituzioni sbagliate rispetto alla sorgente | 40 | 37 |
| Precisione delle sostituzioni | 98,53% | 98,63% |
| Copertura dei typo | 42,10% | 42,03% |

I 64 casi manuali aggiunti, di cui 56 fuori dalla lista di frequenze, restano
intatti con entrambe le versioni. Questi campioni non dimostrano le stesse
prestazioni nella digitazione quotidiana.

## CLI contestuale separata

```sh
./autocorrect --interactive
```

Tre suggerimenti selezionabili con Tab/F1/F2/F3; Invio conferma e apprende la
frase; Ctrl+Z annulla una modifica alla riga; Ctrl+C la scarta; `/exit` esce.
Il modello usa unigrammi, bigrammi e trigrammi e una memoria personale SQLite.

La base iniziale contiene **91 frasi dimostrative originali**, non un modello
generale dell'italiano. `--corpus FILE` permette di usare frasi UTF-8 proprie;
`--no-learn` esclude lettura e scrittura della memoria personale. La memoria
predefinita è `~/.local/share/autocorrect/personal-ngrams.sqlite3`, rispettando
`XDG_DATA_HOME`.

Questa CLI interattiva resta un laboratorio separato. Per le sostituzioni Fcitx
abbiamo aggiunto `ContextualCorrector`: usa conteggi Leipzig in SQLite e il
testo precedente ricevuto dal bridge. Si abilita con `--context` nel launcher;
la modalità base continua a usare la sola parola.

## Prova Fcitx disponibile

```sh
bash scripts/build-fcitx-probe.sh
python scripts/run-fcitx-probe.py --client qt --mode surrounding --engine core

# Prova attuale, con contesto e soglia 5.000
python scripts/run-fcitx-probe.py --client qt --mode surrounding --engine core --context --frequency 5000 --learn
```

La finestra **Autocorrect - testo reale e diagnostica** offre un campo multilinea
e mostra l'ultima analisi: input, output, motivo, primi tre candidati e margine.
Una parola non modificata può quindi avere una spiegazione osservabile, come
`ambiguous`, `known_word` o `valid_word`.

- Spazio valuta il token precedente; Backspace subito dopo annulla la correzione.
- Lo spazio successivo all'annullamento conserva l'originale.
- Il bridge tratta una punteggiatura finale semplice e gestisce offset Unicode.
- La correzione parte allo spazio, non a Invio; incollare un paragrafo non
  corregge retroattivamente tutte le parole.
- Il motore Python resta caricato in un processo separato; il socket Unix ha
  un budget di attesa di 50 ms. Errori o timeout conservano l'input.
- La diagnostica è la decisione del motore, non la conferma dell'applicazione:
  una risposta tardiva può essere scartata.

Il launcher usa D-Bus e percorsi XDG privati sotto `build/fcitx-probe-sessions/`.
Non abbiamo installato il correttore nel profilo Fcitx ordinario del desktop.
Le finestre Qt/GTK sono Wayland native, collegate tramite i moduli IM e D-Bus;
la seconda istanza Fcitx ha `waylandim` disabilitato.

Verifiche eseguite:

- Motore finto con tre sostituzioni: 36 controlli superati, su Qt/GTK e nelle
  modalità preedit/surrounding.
- Motore reale: 16 controlli Qt e 9 GTK superati; dopo la diagnostica, 17 Qt.
- Copertura di spazio, annullamento, cursore, prefisso Unicode, password,
  NoSpellCheck, focus, paragrafo multilinea e motore sospeso/arrestato.
- Ultima esecuzione completa della suite Python: 76 test superati. Dopo
  l'aggiunta della diagnostica, 4 test mirati del server superati, incluso
  un nuovo test sulle astensioni.

Browser/Electron, text-input-v3, altri widget e popup candidati restano da
verificare. Il popup dimostrativo è separato e non è necessario alla correzione
silenziosa. La qualità linguistica richiede una valutazione distinta da questi
controlli di integrazione.

## Vocabolario personale: confronto e revisione

`vocabulary.txt` contiene 5.816 voci apprese da SwiftKey. Fra le 4.776 forme
alfabetiche normalizzate, 1.338 mancano dalla lista di frequenze del core.
Non sono tutte parole corrette: possono esserci typo, nomi o altre lingue.

Abbiamo confrontato i motori senza proteggere il vocabolario e senza caricare
la lista personale dell'utente; resta solo il glossario tecnico del progetto.

| Insieme | Proposte baseline | Proposte con Hunspell |
|---|---:|---:|
| Voci originali | 32 | 23 |
| 1.338 forme sconosciute normalizzate | 40 | 31 |

Hunspell riconosce 255 delle 1.338 forme e blocca nove proposte. Le altre 1.083
restano da classificare. **Questi conteggi non sono falsi positivi verificati.**
Non abbiamo ancora approvato o installato una lista personale derivata.

```sh
.venv/bin/python -m autocorrect_core.vocabulary_audit vocabulary.txt \
  --output-dir benchmark-results/NUOVA-CARTELLA
```

Prima esecuzione in `benchmark-results/swiftkey-vocabulary-review/`:
`summary.json`, `review.json`, `changes.json` e `approved-protected.txt`.
La revisione parte dai 40 casi modificabili. Etichette disponibili: `valid`,
`typo`, `uncertain`, `unreviewed`. Solo `valid` alimenta metriche di falsi positivi
verificati e una lista protetta proposta; non modifica il motore durante il test.

## SwiftKey: stato della ricerca

File personali locali esclusi da Git: `com.touchtype.swiftkey.7z`, `vocabulary.txt`,
`dynamic.lm` e relative cartelle previste.

Il dump di supporto contiene il modello personale principale: 1.235.313 byte,
12.910 identificativi e 121.193 nodi. Il modello OneDrive è più piccolo ma
strutturalmente integro: 587.185 byte, 5.823 identificativi e 63.597 nodi.
Entrambi hanno sequenze fino a quattro identificativi, nel formato Fluency,
con vocabolario versione 7 e blocchi `flue/voca/dmap`.

La coppia OneDrive è promettente: le 5.816 voci testuali hanno una distribuzione
delle lunghezze UTF-8 compatibile col binario, salvo sette voci per 44 byte.
L'ordine delle righe non corrisponde direttamente agli ID. **Non abbiamo ancora
una mappa verificata ID→parola, né importato quelle sequenze nella CLI.**

I parser pubblici esaminati richiedono un dizionario già decodificato o un report
UFED esterno. La documentazione Microsoft ci ha permesso di recuperare la coppia
leggibile/binaria da OneDrive → Apps → SwiftKey. La decodifica è ora in pausa.

```sh
.venv/bin/python -m autocorrect_core.swiftkey_inspect dynamic.lm
```

## Prossime priorità

1. Raccogliere e classificare correzioni mancate e indesiderate su testo naturale,
   distinguendo riconoscimento lessicale, ranking e problemi di integrazione.
2. Unificare backoff e modello degli errori per migliorare il primo typo e ridurre
   le discontinuità delle soglie; mantenere separata la valutazione dalla taratura.
3. Revisionare il vocabolario personale prima di proteggere nuove voci.
4. Verificare il trasporto Fcitx nelle applicazioni quotidiane, oltre ai widget
   di prova, prima dell'attivazione ordinaria.
5. Riprendere SwiftKey solo con un obiettivo circoscritto e un limite di tempo.

## Git e recupero

Il repository raccoglie anche la prova LatinIME, la frequenza live Fcitx,
il ranking contestuale e l'apprendimento personale del 28 settembre, con
verifiche e documentazione completate. Commit principali precedenti:

- `c7ceb03`: prototipo standalone e benchmark iniziali.
- `a43c0ce`: Hunspell, CLI contestuale e ispezione SwiftKey.
- `266beda`: confronto sul vocabolario personale e workflow di revisione.
- `a7faad6`: prima prova Fcitx isolata.
- `a0ac4c4`: collegamento del core reale e campo multilinea.
- `ea86018`: diagnostica delle astensioni nella finestra Fcitx.

Regola concordata: commit locale dopo ogni blocco verificato; push su richiesta
separata. Il PDF di riferimento
resta non tracciato; dati personali, build e report locali sono esclusi dai commit.

Recupero già predisposto: snapshot Snapper root #6 e backup separato delle
configurazioni utente. Red button **Super+Ctrl+Alt+F12** oppure
`~/.local/bin/input-rescue`; per riattivare Fcitx: `~/.local/bin/input-rescue resume`.
Il ripristino riporta il baseline e ferma Fcitx: usarlo seguendo `docs/RECOVERY.md`.

Documenti: `README.md`, `docs/ARCHITECTURE.md`, `docs/HUNSPELL.md`,
`docs/PREDICTION.md`, `docs/FCITX_PROBE.md`, `docs/VOCABULARY_REVIEW.md`,
`docs/SWIFTKEY.md`, `docs/BENCHMARK_GENERATED.md`.
