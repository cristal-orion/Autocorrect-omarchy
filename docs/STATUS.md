# Autocorrect Omarchy: stato del progetto

Aggiornamento: 27 settembre 2026.
Cartella: `/home/michele/Projects/autocorrect`.
Repository: https://github.com/cristal-orion/Autocorrect-omarchy

## Punto centrale emerso dalla prova manuale

**Il meccanismo Fcitx di sostituzione allo spazio e annullamento funziona nelle
finestre di prova. La qualità dell'autocorrezione sul testo quotidiano è ancora
insufficiente: molte parole con typo rimangono invariate.**

L'utente ha confermato il buon comportamento meccanico, poi ha scritto frasi
libere e osservato molte correzioni mancate. Abbiamo verificato che quei token
raggiungono il motore: spesso il core si astiene per ambiguità, oppure conserva
una voce già presente nel dizionario. Gli esempi favorevoli usati nei test
dimostrano il collegamento, non l'affidabilità o la copertura nell'uso reale.

Il prossimo lavoro deve concentrarsi sulla scelta dei candidati e sul contesto,
con dati adeguati e valutazione separata. Abbassare soltanto il margine può
trasformare un'astensione in una correzione grammaticalmente sbagliata.

## Aggiornamenti successivi al riepilogo iniziale

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
  per la previsione colloquiale desiderata. Non abbiamo ancora portato LatinIME
  o collegato il contesto a Fcitx. Risultati e criteri: [AOSP_DATA.md](AOSP_DATA.md).
- Suite Python aggiornata: **85 test superati**.

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

**Il ranking contestuale di questa CLI non guida ancora le sostituzioni Fcitx.**
Il bridge Fcitx attuale interroga il core su una parola alla volta.

## Prova Fcitx disponibile

```sh
bash scripts/build-fcitx-probe.sh
python scripts/run-fcitx-probe.py --client qt --mode surrounding --engine core
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
2. Migliorare selezione e astensione sullo sviluppo; introdurre il contesto con
   un corpus italiano adeguato, distinto dai casi usati per valutarlo.
3. Revisionare il vocabolario personale prima di proteggere nuove voci.
4. Verificare il trasporto Fcitx nelle applicazioni quotidiane, oltre ai widget
   di prova, prima dell'attivazione ordinaria.
5. Riprendere SwiftKey solo con un obiettivo circoscritto e un limite di tempo.

## Git e recupero

I blocchi di codice sono committati localmente. Commit principali:

- `c7ceb03`: prototipo standalone e benchmark iniziali.
- `a43c0ce`: Hunspell, CLI contestuale e ispezione SwiftKey.
- `266beda`: confronto sul vocabolario personale e workflow di revisione.
- `a7faad6`: prima prova Fcitx isolata.
- `a0ac4c4`: collegamento del core reale e campo multilinea.
- `ea86018`: diagnostica delle astensioni nella finestra Fcitx.

Regola concordata: commit locale dopo ogni blocco verificato; push su richiesta
separata. Non abbiamo eseguito push in questa sessione. Il PDF di riferimento
resta non tracciato; dati personali, build e report locali sono esclusi dai commit.

Recupero già predisposto: snapshot Snapper root #6 e backup separato delle
configurazioni utente. Red button **Super+Ctrl+Alt+F12** oppure
`~/.local/bin/input-rescue`; per riattivare Fcitx: `~/.local/bin/input-rescue resume`.
Il ripristino riporta il baseline e ferma Fcitx: usarlo seguendo `docs/RECOVERY.md`.

Documenti: `README.md`, `docs/ARCHITECTURE.md`, `docs/HUNSPELL.md`,
`docs/PREDICTION.md`, `docs/FCITX_PROBE.md`, `docs/VOCABULARY_REVIEW.md`,
`docs/SWIFTKEY.md`, `docs/BENCHMARK_GENERATED.md`.
