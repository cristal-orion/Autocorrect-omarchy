# Prova nel BrowserOS reale

Verificata il 29 settembre 2026 con BrowserOS 151.0.8160.137, Hyprland 0.56.2
e Fcitx 5.1.22. Il trasporto è Wayland nativo, text-input-v3.

## BrowserOS quotidiano: collegamento completo

Il solo riavvio con i flag Wayland non era sufficiente. Nel profilo quotidiano
`browser.enable_spellchecking` era disabilitato, la lista dei dizionari era vuota
e i nuovi contesti Fcitx partivano su `keyboard-us`. Inoltre, su Chromium un
`spellcheck=true` ereditato può non diventare un'indicazione positiva per l'IME;
Google Ricerca e Traduttore impostano esplicitamente `spellcheck=false`.

La configurazione ora comprende:

- attivazione **locale al contesto BrowserOS** al focus, senza cambiare lo stato
  della tastiera nelle altre applicazioni; l'addon viene caricato all'avvio;
- controllo ortografico del browser abilitato, con dizionari italiano e inglese;
- estensione locale `Autocorrect — campi di scrittura`, in
  `~/.local/share/autocorrect/browser-ime`, caricata dal wrapper ad ogni avvio
  tramite `--load-extension` se la cartella è presente;
- adattamento del solo attributo `spellcheck`, senza leggere né sostituire il
  testo. Rende esplicito il consenso ereditato nei campi normali; abilita inoltre
  i campi identificati di Google Ricerca, Traduttore, Gemini e ChatGPT. Conserva
  le esclusioni esplicite degli altri siti, password, campi sola lettura e
  contenitori di editor di codice riconosciuti.

La configurazione del profilo aperto si può applicare senza scrivere direttamente
nel file Preferences e senza cancellare le bozze:

```sh
# Usare la porta CDP locale del processo BrowserOS quotidiano (può cambiare).
node scripts/configure-browseros-profile.mjs http://127.0.0.1:9150
```

Lo script conserva le preferenze precedenti in
`~/.local/state/autocorrect/browser-backups/`, abilita i dizionari, carica
l'estensione e applica il solo adattamento IME alle pagine già aperte.
Il caricamento CDP da solo non è persistente: per gli avvii successivi serve
il flag nel wrapper, già aggiunto su questa macchina.

Verifica sul profilo quotidiano: **`quesot → questo` e annullamento con Backspace
passati su Google Ricerca, Gemini, ChatGPT e Google Traduttore**, in schede
dedicate senza inviare messaggi. Per ChatGPT è stata usata una chat temporanea
con campo vuoto; le bozze esistenti sono state conservate.

### Profili distinti e Claude

Claude era aperto in un altro profilo BrowserOS, privo del componente. Il suo
campo `contenteditable` consentiva già il controllo ortografico: abbiamo
configurato quel profilo senza aggiungere un'eccezione per il sito. L'utente
ha completato la prova manuale e confermato il funzionamento.

Ogni profilo conserva dizionari, preferenze ed estensioni separate. Il
configuratore opera sul profilo predefinito dell'endpoint CDP scelto; non
installa l'estensione in tutti i profili presenti sul disco. Se un sito funziona
in una finestra ma non in un'altra, verificare anche il profilo della finestra.

## Aprire la prova

Il pannello Omarchy si apre dal pulsante **AC** nella parte destra della barra.
Mostra gli interruttori e i contatori della memoria personale. La scritta
sostituisce il precedente simbolo poco visibile. Per applicare questo cambio
è stato necessario `omarchy restart shell`: la sola scansione dei plugin
continuava a usare il componente QML precedente.

Dalla cartella del progetto:

```sh
.venv/bin/python scripts/run-browseros-probe.py
```

Si apre BrowserOS con la pagina locale `probes/browseros.html`, un profilo
dedicato in `build/browseros-profile` e il Fcitx del desktop. Non è il widget Qt
del laboratorio. Il launcher avvia il motore se necessario, abilita le
correzioni e seleziona il metodo `autocorrect-probe-surrounding` nel browser.

I nuovi profili vengono predisposti con i dizionari ortografici **italiano e
inglese**. Le sottolineature rosse sono del browser, distinte dalle sostituzioni
del nostro motore. Il profilo di prova già creato è stato aggiornato dalle API
delle impostazioni di BrowserOS; il dizionario italiano risulta scaricato e
pronto. Per modificare le lingue usare `chrome://settings/languages`.

Nel campo **Testo normale**:

1. Digitare `quesot` e premere Spazio: diventa `questo `.
2. Premere subito Backspace: torna `quesot`.
3. Premere di nuovo Spazio: il typo appena ripristinato non viene ricorretto.
4. Provare `una piza ` e `sono stao `, con lo spazio finale.

### Scegliere un suggerimento

Attivare **Suggerimenti** nel pannello Omarchy (attivo nella prova utente
corrente). Dopo una parola che il motore non corregge automaticamente e Spazio,
i candidati si scelgono con **Alt+1**, **Alt+2**, **Alt+3**. Per esempio `domnai `
propone `domani`, `donna`, `romani`; Alt+1 sceglie `domani` e Backspace annulla.
Le scorciatoie vengono intercettate solo se esiste il relativo candidato e il
testo/cursore sono ancora quelli della proposta. F1 resta al browser.
Nel laboratorio Qt/GTK rimangono F1/F2/F3.

Funziona anche nel campo rich text della pagina. Password e campi con
`spellcheck=false` sono esclusi, salvo i campi dei siti adattati come sopra.
Per mettere in pausa usare **Correzione
automatica** oppure **Ferma** nel pannello Omarchy.

La prova è limitata all'app ID `BrowserOS`. Slack, ZapFast e terminale sono
esclusi. Non è limitata all'URL della pagina: anche altre pagine aperte in questo
BrowserOS possono usare il correttore, se il loro campo abilita il controllo
ortografico o è tra quelli adattati dall'estensione. Gli editor dei singoli siti
devono comunque essere collaudati.
La memoria personale è quella del motore condiviso; le modifiche manuali e gli
annullamenti della prova utente possono quindi registrare feedback.

Il BrowserOS quotidiano già aperto va chiuso completamente e riavviato dal
wrapper aggiornato per ricevere i flag IME. La prova dedicata permette di
verificare il collegamento prima di questo passaggio. Il metodo Fcitx ora si
seleziona automaticamente quando BrowserOS riceve il focus. L'avvio del motore
al login dipende dal relativo interruttore del pannello.

## Installazione locale

```sh
bash scripts/build-fcitx-probe.sh
.venv/bin/python scripts/install-browseros-probe.py
```

L'installer conserva i metodi esistenti, aggiunge quello della prova al gruppo
corrente via D-Bus e riavvia `omarchy-fcitx5.service`. Installa:

- `~/.local/lib/autocorrect/libautocorrectprobe.so`;
- i descrittori in `~/.local/share/fcitx5/addon/` e `inputmethod/`;
- `~/.config/systemd/user/omarchy-fcitx5.service.d/autocorrect.conf`;
- i file dell'estensione in `~/.local/share/autocorrect/browser-ime/`;
- il registro dei file in `~/.config/autocorrect/desktop-install.json`.

Il drop-in collega l'addon a `%t/autocorrect/engine.sock`, limita l'app a
BrowserOS e abilita il feedback. Backup per ogni installazione in
`~/.local/state/autocorrect/desktop-backups/`; il primo di questa sessione è
`20260929T091406.148059Z`. I file modificati dall'utente non vengono sovrascritti.
Tutti i percorsi installati rientrano nell'ambito del [recupero input](RECOVERY.md).

## Accorgimento per Fcitx 5.1.22

I soli flag `--enable-wayland-ime --wayland-text-input-version=3` attivavano il
protocollo, ma il testo circostante non arrivava aggiornato all'addon.
Chromium attende il messaggio `done` prima di pubblicare altro stato; Fcitx
5.1.22 sopprime gli aggiornamenti ripetuti del preedit vuoto e non ha il
parametro `forceUpdate` delle versioni upstream successive.

Il percorso opzionale `AUTOCORRECT_PROBE_WAYLAND_ACK=1` emette un commit vuoto
all'attivazione e agli aggiornamenti di testo/cursore: produce la conferma
Wayland senza inserire testo. È limitato al metodo surrounding attivo, al
frontend `wayland_v2` e all'app ID configurato. Con questo accorgimento sono
stati verificati ricezione del testo, cancellazione, inserimento e undo.
Va rivalutato dopo aggiornamenti di Fcitx/Chromium.

Su Wayland il controllo ortografico è un'indicazione positiva: per questa prova
richiediamo `SpellCheck`, oltre ai normali blocchi su password, URL, email e
terminale. Cercare solo `NoSpellCheck` non preservava `spellcheck=false`.

## Verifiche

```sh
node scripts/test-browseros-probe.mjs
node scripts/test-browseros-probe.mjs --excluded
node scripts/test-browseros-probe.mjs --reopen --startup-only
```

Richiedono Node con WebSocket integrato, `wtype`, Hyprland e l'installazione
locale. Usano un profilo browser temporaneo; CDP legge i campi e una tastiera
virtuale Wayland invia i tasti passando attraverso Fcitx. L'apprendimento viene
sospeso e ripristinato per evitare feedback dei test nella memoria personale.
Il prefisso Unicode viene inserito via CDP, poi la correzione viene digitata.

**23 controlli BrowserOS e 2 controlli su app ID escluso superati**: spazio,
undo, mancata riapplicazione, contesto, offset Unicode, rich text, password,
spellcheck disabilitato e applicazione non autorizzata. Gli 11 controlli aggiunti
verificano le tre scelte Alt+numero con annullamento, F1 inoltrato al browser e
Alt+1 inoltrato quando non ci sono candidati.
Sono inclusi attivazione automatica e adattamento del controllo ortografico
ereditato. Altri **2 controlli dopo chiusura e riapertura reali** verificano
l'attivazione automatica e il caricamento dell'estensione dal wrapper normale.
Il test non seleziona manualmente il metodo Fcitx, per non nascondere problemi
di attivazione. Interrompe la digitazione se il focus passa ad altre finestre o
a un campo della shell.

Regressioni successive alla modifica dell'addon: **62 controlli Qt e 15 GTK**
superati. Suite Python completa aggiornata: **143 test superati**, incluso
il controllo sullo stato dell'integrazione desktop.
La modifica delle scorciatoie ha inoltre superato i **35 controlli Qt di
apprendimento**, inclusa selezione F1, conferma e annullamento.

Questi risultati e quelli dei quattro siti verificati non certificano tutti
gli editor web né le altre applicazioni.
