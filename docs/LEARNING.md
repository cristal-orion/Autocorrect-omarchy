# Apprendimento dai gesti nella prova Fcitx

28 settembre 2026. Il laboratorio può ora ricordare le correzioni esplicite
dell'utente. Una coppia come `pne → pane` contribuisce anche in frasi diverse e
sopravvive al riavvio. La correzione silenziosa allo spazio resta l'interazione
principale; i candidati selezionabili sono opzionali.

## Avvio

```sh
bash scripts/build-fcitx-probe.sh
python scripts/run-fcitx-probe.py --client qt --mode surrounding --engine core \
  --context --frequency 5000 --learn
```

La finestra si chiama **Autocorrect - apprendimento personale**. Il launcher
abilita Hunspell. Il contesto Leipzig richiede il corpus già preparato; per
provare la sola memoria si può omettere `--context`.

### Provare l'apprendimento

1. Scrivere una frase con un typo che il motore conserva, per esempio `con il pne `.
2. Correggere quella parola: rimuovere lo spazio e `pne` con Backspace, poi
   scrivere `pane `, incluso lo spazio finale. Si può anche inserire la vocale
   all'interno della parola e completare la modifica uscendo dalla parola.
3. Controllare il messaggio **Coppia appresa: pne → pane**.
4. Scrivere una frase diversa, per esempio `vorrei pne `. La diagnosi diventa
   `personal_correction` e il testo contiene `pane`.
5. Chiudere e riaprire con lo stesso comando: la memoria resta disponibile.

I test automatici usano memorie isolate. Non insegnano coppie al profilo personale
aperto con il comando sopra.

### Comandi nella finestra Qt

| Comando | Effetto |
|---|---|
| Alt+T | Torna al paragrafo |
| Alt+L | Sospende/riprende uso e raccolta della memoria nella sessione |
| Alt+S | Abilita/disabilita i suggerimenti opzionali |
| F1/F2/F3 o clic sul popup | Applica un candidato offerto e registra la scelta |
| Backspace subito dopo una sostituzione | Ripristina l'originale; lo Spazio successivo registra un rifiuto |
| Backspace, poi `, . ; : ! ?` | Rimette la correzione prima della punteggiatura; nessun rifiuto |
| Alt+D, digitare il typo, Invio | Dimentica gli eventi associati a quell'input |

I suggerimenti partono disabilitati. Se abilitati, il popup Fcitx compare solo
quando il motore conserva il token e ha candidati. F1–F3 non selezionano nulla
quando il popup opzionale è disabilitato. Per abilitarlo già all'avvio si può
aggiungere `--candidates` a `--learn`.

Per dimenticare `pne → pane`, indicare **pne**, cioè l'input originale. Il motore
torna alla decisione senza quel contributo personale: in certi contesti il
correttore di base potrebbe comunque proporre `pane`.

## Regole dell'apprendimento

Registriamo due segnali positivi:

- una modifica manuale locale alla stessa parola, osservata durante i tasti
  dell'utente e completata con spazio, Invio o uscita del cursore dalla parola;
- una scelta esplicita di candidato, dopo che il client mostra il testo atteso.

Per creare una **coppia di correzione** richiediamo:

- originale assente dal lessico, rifiutato da Hunspell e fuori dal glossario
  protetto;
- originale di almeno tre lettere, parole alfabetiche latine fino a 64 caratteri;
- distanza Damerau-OSA 1 o 2, con originale e destinazione digitati in minuscolo;
- destinazione riconosciuta dal lessico, da Hunspell o dal glossario.

Se si cambia `cane` in `pane`, il motore registra solo l'uso di `pane` nel
contesto. Conserva `cane` nelle richieste successive. Un cambio tra parole valide
può essere un ripensamento o un refuso reale: il gesto da solo non permette di
stabilire quale dei due.

Le modifiche normali non ancora riconosciute come coppie possono quindi fornire
solo usi contestuali. Le destinazioni sconosciute non entrano in questo primo
workflow: la diagnostica restituisce `ignored_unknown_target`.

**Le autocorrezioni non producono conferme positive.** Nemmeno digitare più
volte una parola o lasciare una correzione automatica non annullata conta come
conferma. Per ora non apprendiamo passivamente tutte le frasi digitate.

### Come influisce la memoria

Le coppie hanno un saldo `conferme - rifiuti`. Una prima conferma esplicita
può attivare la sostituzione, purché abbia saldo positivo e maggiore di ogni
destinazione alternativa imparata per lo stesso input. In caso di parità il
motore si astiene. Il saldo è una regola di questa versione, non una probabilità.

La preferenza per la coppia vale fra contesti diversi. Le parole valide,
protette, maiuscole e i contesti esclusi conservano i propri blocchi. Un uso
contestuale senza coppia modifica l'ordine dei suggerimenti, ma non autorizza
da solo una sostituzione automatica. Il motore prende al massimo 64 destinazioni
dalla riga personale del contesto esatto.

Le conferme personali possono prevalere sull'astensione o su una proposta
automatica diversa del motore generale. Il pannello mostra il motivo
`personal_correction`, le conferme e i rifiuti; indica come baseline la soglia
di frequenza, che non è il criterio delle coppie confermate.

Annullare una correzione automatica e poi premere Spazio, cioè tenere
l'originale, aggiunge un rifiuto alla coppia. Se dopo l'annullamento si
continua a modificare la parola, si digita una lettera o si cambia campo, non
viene registrato niente. Backspace si usa spesso anche solo per aggiungere
punteggiatura: in quel caso il bridge rimette la correzione prima del segno.

Annullare una selezione appena effettuata rimuove anche la conferma e l'uso
contestuale di quella selezione. I rifiuti bloccano la proposta del motore
generale solo quando superano le conferme, cioè con saldo negativo.
Il normale Ctrl+Z dell'editor non genera, in questa versione, un evento di rifiuto:
per le proposte del correttore usare Backspace immediato oppure **Dimentica**.

## Riconoscimento dei gesti

Il rilevatore vive nel bridge Fcitx, non nei segnali specifici del campo Qt.
Conserva durante la modifica i confini della parola, il testo ai lati e la modifica
attesa dal tasto. Verifica il testo circostante prima di registrare il gesto.

Questo evita di considerare come correzione l'incolla, una riscrittura estesa o
la cancellazione dell'intero campo. Una selezione visibile di una sola parola
può essere sostituita; la selezione dell'intero campo viene ignorata. Il
rilevatore limita le fotografie del testo a 16 KiB e la parola a 256 byte.

GTK invia reset del metodo di input durante Backspace e navigazione. Il bridge
conserva soltanto l'episodio di modifica ancora compatibile con lo stesso campo,
scartando transazioni di annullamento e candidati. Ogni modifica di testo deve
comunque corrispondere al tasto osservato: un Backspace semplice non autorizza
la cancellazione di un'intera parola quando il toolkit omette la selezione.

I cambi di campo invalidano gli episodi incompleti. I campi password/sensibili,
NoSpellCheck/NoPredictiveText, terminale, URL ed email sono esclusi sia dalle
sostituzioni personali sia dai feedback. Il servizio verifica anche il contesto
esplicito del protocollo.

## Memoria e dimenticanza

Percorso predefinito:

```text
$XDG_DATA_HOME/autocorrect/feedback.sqlite3
# In assenza di XDG_DATA_HOME:
~/.local/share/autocorrect/feedback.sqlite3
```

`--memory /percorso/feedback.sqlite3` permette una memoria alternativa. La
memoria delle frasi della CLI interattiva (`personal-ngrams.sqlite3`) resta un
file distinto, con il proprio formato.

Il nuovo database ha permessi iniziali `0600`, transazioni SQLite e modalità
WAL. Registra tipo del gesto, originale, destinazione, ultime due parole del
contesto, timestamp e identificativo. Le letture non usano una cache di coppie:
la dimenticanza è visibile anche a un'altra sessione già aperta.

Ogni evento ha un identificativo e una ricevuta con hash. Un evento duplicato
non conta due volte. **Dimentica** elimina gli eventi e tutti i loro contributi,
compresi gli usi contestuali e i rifiuti. Conserva soltanto identificativi e hash
delle ricevute, esclusi dal ranking, per impedire che la ritrasmissione di un
evento già gestito ripristini la coppia. Non riproduciamo vecchi log al riavvio.

Comandi da terminale:

```sh
.venv/bin/python -m autocorrect_core.feedback status
.venv/bin/python -m autocorrect_core.feedback status pne
.venv/bin/python -m autocorrect_core.feedback forget pne

# Memoria alternativa:
.venv/bin/python -m autocorrect_core.feedback --memory /percorso/feedback.sqlite3 status pne
```

## Verifiche eseguite

```sh
.venv/bin/python -B -m unittest discover -s tests -v
python scripts/run-fcitx-probe.py --client qt --mode surrounding --engine core --context --learn --test
python scripts/run-fcitx-probe.py --client gtk --mode surrounding --engine core --learn --test
```

- **134 test della suite superati**, inclusi 13 test della memoria e un test
  che compila/esegue i controlli C++ del rilevatore dei gesti.
- **35 controlli di apprendimento Qt e 35 GTK superati**: correzione manuale,
  trasferimento fra frasi, riavvio del server, pausa, mancato auto-rinforzo,
  rifiuti, parole valide, selezione opzionale F1, cancellazione dell'intero campo,
  inserimento dentro la parola, campi esclusi e dimenticanza dopo riavvio.
- **62 controlli Qt del contesto e 9 della modalità preedit superati** dopo
  l'aggiornamento del bridge.

Il launcher crea una memoria nuova dentro la sessione per `--test --learn` e
rifiuta `--memory` insieme a `--test`. I test riavviano il processo del motore
con lo stesso file e controllano il testo applicato nel widget, non solo il JSON.

Report locali:

- `build/fcitx-probe-sessions/qt-surrounding-x_yf8wsy/report.json`
- `build/fcitx-probe-sessions/gtk-surrounding-p_aj9mk0/report.json`
- `build/fcitx-probe-sessions/qt-surrounding-wdlaequl/report.json`
- `build/fcitx-probe-sessions/qt-preedit-95s3ev3e/report.json`

Questi controlli verificano il workflow. Serve ancora una valutazione della
qualità su sessioni di digitazione reali, con errori nuovi e conferme contrastanti.
Il trasporto fuori dai widget Qt/GTK di prova richiede le verifiche già elencate
in [FCITX_PROBE.md](FCITX_PROBE.md).

## FUTO e prossimo blocco

Abbiamo consultato FUTO alla revisione
`70a5d390c505a6bbcc4e14966e5628e43ca3f1fc`, in particolare
`UserHistoryDictionary.java`, `DictionaryFacilitatorImpl.java`,
`inputlogic/InputLogic.java` e `engine/general/GeneralIME.kt`. Il codice collega
commit e modifiche esplicite alla cronologia personale, e ha un percorso per
disimparare all'annullamento. Il nostro modulo introduce coppie esplicite
typo/correzione: non è un port di quel codice né una replica di SwiftKey.

Il blocco successivo concordato è **backoff unificato più modello degli errori**.
La memoria aiuta con errori già corretti dall'utente; la prima occorrenza di un
typo continua a dipendere dal motore generale. Va migliorata con uno score
coerente, senza riprendere la taratura frase per frase.
