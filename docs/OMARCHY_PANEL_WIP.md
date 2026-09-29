# Pannello Omarchy: punto di ripresa

Aggiornamento: 29 settembre 2026. Sessione ripresa dopo la pausa.

**Aggiornamento successivo:** il Fcitx desktop carica l'addon BrowserOS, con
attivazione automatica, componente per i campi web e pulsante AC nella barra.
L'utente ha confermato anche Claude dopo la configurazione del suo profilo.
Riepilogo finale: [SESSION_2026-09-29.md](SESSION_2026-09-29.md).
Stato attuale e istruzioni: [BROWSEROS_PROBE.md](BROWSEROS_PROBE.md).
I paragrafi seguenti conservano la cronologia delle verifiche precedenti.

## Ripresa: widget aperto, motore collegato

L'utente ha chiarito che ieri il widget si apriva già: il problema osservato
era il motore indicato come scollegato. Il precedente appunto sul caricamento
del widget descriveva un errore intermedio, non il punto di ripresa corretto.

Alla ripresa il plugin era disabilitato e `autocorrect.service` era inattivo.
Abbiamo riabilitato il plugin e avviato il servizio con il controller:

```sh
omarchy plugin enable michele.autocorrect
omarchy-shell shell rescanPlugins
.venv/bin/python -m autocorrect_core.control start
```

Verifiche del 29 settembre:

- Apertura del pannello reale riuscita; `autocorrect-panel inspect` restituisce
  `connected: true` ed errore vuoto dopo l'aggiornamento dello stato.
- Controller e helper installato confermano servizio `active/running`, contesto
  e apprendimento disponibili. Avvio al login disabilitato.
- Richieste al socket condiviso verificate: `quesot → questo`, `una piza → una
  pizza`, `sono stao → sono stato`. Il campo `previous` del protocollo include
  lo spazio finale, come il testo precedente ricevuto dal bridge.
- Aperta la finestra «Autocorrect - prova con pannello Omarchy» tramite
  `control open-probe`: legge frequenza 5.000, margine 1,30, contesto e memoria
  attivi e la diagnostica prodotta dal servizio condiviso.
- Suite Python completa: **142 test superati**.

Stato lasciato: plugin abilitato, servizio attivo, finestra di prova aperta.
Il collegamento alle app del desktop resta il lavoro successivo. Le regressioni
con digitazione Qt/GTK e i pulsanti del pannello devono ancora essere collaudati
in questa sessione.

## Launcher Wayland delle app prioritarie

Sempre il 29 settembre, su indicazione dell'utente, verificati e predisposti i
flag IME per Slack e BrowserOS:

- Slack installato: **4.52.155-1**. Il launcher utente
  `~/.local/share/applications/slack.desktop` forzava `--ozone-platform=x11`.
  Sostituito con `--ozone-platform=wayland --enable-wayland-ime
  --wayland-text-input-version=3`, conservando `--gtk-version=3 -s` e `%U`.
- BrowserOS installato: **151.0.8160.137**. Il processo normale era già Wayland,
  senza flag IME espliciti. Aggiunti gli stessi tre flag al wrapper
  `~/.local/bin/browseros`, conservando classe, gesture del trackpad e argomenti.
  Il wrapper è necessario perché `omarchy-launch-browser` prende solo il primo
  elemento di `Exec=` dal desktop file e scarta eventuali flag.
- Copie precedenti in
  `~/.local/state/autocorrect/wayland-launchers-20260929/` (`slack.desktop` e
  `browseros`). Il wrapper attuale conserva il permesso di esecuzione.
- `desktop-file-validate` sui due launcher e `bash -n` sul wrapper superati.
- Prova BrowserOS con profilo temporaneo e `WAYLAND_DEBUG=client`: osservati
  `get_text_input` ed `enable` su `zwp_text_input_v3`. Il compositor espone sia
  text-input-v1 sia v3, oltre a input-method-v2. Nel breve avvio non sono stati
  osservati `set_surrounding_text`; lettura e sostituzione effettive restano da
  collaudare con digitazione in un campo controllato.
- Le istanze normali delle app già aperte richiedono un'uscita completa e un
  nuovo avvio dai launcher aggiornati. Slack con i nuovi flag non è ancora
  collaudato.

Il servizio `omarchy-fcitx5.service` è attivo e segnala l'uso del protocollo
input method nativo Wayland. Il profilo desktop contiene però solo
`keyboard-us`: l'addon Autocorrect è ancora caricato esclusivamente nella prova.
I flag predispongono il trasporto, non installano il correttore nel desktop.

Riferimento: [Fcitx 5 su Wayland, Chromium/Electron](https://fcitx-im.org/wiki/Using_Fcitx_5_on_Wayland#Chromium_/_Electron).
XWayland da solo non identifica il frontend IME: su Chromium/Electron X11 può
essere usato anche il modulo GTK, secondo configurazione e variabili d'ambiente.

## Scelte confermate

- App prioritarie: BrowserOS, ZapFast, Slack e chat nel terminale.
- Escludere Obsidian e LibreOffice dal collaudo prioritario.
- Terminale: solo chat, con attivazione manuale; il prompt dei comandi resta escluso.
- Interfaccia: pannello compatto nella barra, con colori/font/componenti Omarchy.

## Lavoro presente, ancora da completare

- `shell/omarchy/`: manifest `michele.autocorrect`, pannello QML, riga di controllo
  e anteprima degli otto stati, helper `autocorrectctl`.
- `src/autocorrect_core/control.py` e `settings.py`: API JSON per stato, servizio,
  configurazione, memoria e dimenticanza; salvataggio atomico delle impostazioni.
- Il server supporta `status`, `configure` e pausa globale, compreso il blocco
  del feedback mentre è in pausa.
- Il launcher ha `--shared-engine` per una prova collegata al servizio del pannello.
  La finestra Qt usa aggiornamenti parziali via RPC e legge le impostazioni esterne.
- Installer: `.venv/bin/python scripts/install-omarchy-panel.py`; conserva backup
  e rifiuta di sovrascrivere file modificati dall'utente.

## Verifiche già eseguite

- 8 test in `tests/test_control.py` superati; anche i 10 test del server e i 13
  della memoria passano dopo le modifiche.
- Build Fcitx riuscita; manifest Omarchy validato.
- Anteprima nativa degli otto stati verificata a 320, 375, 414 e 768 px.
  Immagini in `build/omarchy-panel-preview/`.
- Un errore di quoting in `WorkingDirectory` della unit è stato corretto;
  `systemd-analyze --user verify` ora passa.

## Installazione locale e cronologia della pausa

File installati:

- `~/.config/omarchy/plugins/michele.autocorrect/`
- `~/.config/systemd/user/autocorrect.service`
- `~/.config/autocorrect/settings.json`
- `~/.local/bin/autocorrect-control`
- `~/.local/share/applications/autocorrect-control.desktop`

Backup in `~/.local/state/autocorrect/panel-backups/`.
Alla pausa la unit risultava caricata ma **inattiva**, con avvio al login disabilitato.
Non abbiamo collegato il correttore al Fcitx ordinario del desktop.

Il plugin era stato abilitato, ma il comando per aprirlo termina con il messaggio
`summon: no live bar widget for: michele.autocorrect`; l'IPC `autocorrect-panel`
non compare. Non risultano errori QML espliciti nel log, solo notifiche di
ricaricamento del plugin. Prima di fermarsi è stato **disabilitato** con
`omarchy plugin disable michele.autocorrect`.

Il caricamento è stato verificato alla ripresa, come riportato sopra.
Riferimenti letti durante la diagnosi precedente:

- `/usr/share/omarchy/shell/shell.qml`: `syncPluginWidgets`, `loadPluginWidget`,
  `summon` (circa righe 1130 e 1370).
- `/usr/share/omarchy/shell/plugins/bar/Bar.qml`: `findPanelWidget` (circa 726),
  `ModuleSlot` (circa 1773).
- `/usr/share/omarchy/shell/services/PluginRegistry.qml`: scansione e watcher.

Comandi utili:

```sh
omarchy plugin enable michele.autocorrect
omarchy-shell shell rescanPlugins
omarchy-shell shell toggle michele.autocorrect '{}'
omarchy-shell autocorrect-panel inspect
.venv/bin/python -m autocorrect_core.control status
```

## Passi annotati al checkpoint precedente

1. Collaudare i pulsanti di avvio/arresto, i controlli live e l'apertura della
   prova dal pannello; verificare la dimenticanza con memorie di test.
2. Verificare la digitazione nella prova condivisa.
3. Eseguire le regressioni Qt/GTK dopo il cambio di protocollo; la suite Python
   completa è già passata alla ripresa.
4. Completare documentazione e accesso dal menu/barra.
5. Collegare l'addon al Fcitx desktop e collaudare il trasporto nelle app
   prioritarie. Slack e BrowserOS hanno i launcher predisposti come descritto
   sopra; ZapFast è un binario nativo e richiede una verifica dedicata.
   Il terminale non è stato abilitato.

Questo checkpoint conserva il lavoro incompleto. L'ultimo commit
pubblicato resta `ad6b476`. La memoria personale esistente è stata solo letta
per mostrarne lo stato, non svuotata né usata dai test automatici.
