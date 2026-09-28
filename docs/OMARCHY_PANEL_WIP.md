# Pannello Omarchy: punto di ripresa

L'utente ha chiesto di fermarsi e riprendere domani.

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

## Installazione locale e blocco da risolvere

File installati:

- `~/.config/omarchy/plugins/michele.autocorrect/`
- `~/.config/systemd/user/autocorrect.service`
- `~/.config/autocorrect/settings.json`
- `~/.local/bin/autocorrect-control`
- `~/.local/share/applications/autocorrect-control.desktop`

Backup in `~/.local/state/autocorrect/panel-backups/`.
La unit risulta caricata ma **inattiva**, con avvio al login disabilitato.
Non abbiamo collegato il correttore al Fcitx ordinario del desktop.

Il plugin era stato abilitato, ma il comando per aprirlo termina con il messaggio
`summon: no live bar widget for: michele.autocorrect`; l'IPC `autocorrect-panel`
non compare. Non risultano errori QML espliciti nel log, solo notifiche di
ricaricamento del plugin. Prima di fermarsi è stato **disabilitato** con
`omarchy plugin disable michele.autocorrect`.

Riprendere dalla registrazione del componente nel bar, senza modificare i file
pacchettizzati di Omarchy. Riferimenti letti:

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

## Passi successivi

1. Risolvere il caricamento del widget e verificare il pannello reale.
2. Verificare avvio/arresto del servizio, controlli live, apertura della prova
   condivisa e dimenticanza con memorie di test.
3. Eseguire la suite completa e le regressioni Qt/GTK dopo il cambio di protocollo.
4. Completare documentazione e accesso dal menu/barra.
5. Collaudare poi il trasporto nelle app prioritarie. Slack ha un launcher locale
   con `--ozone-platform=x11`; BrowserOS è Wayland nativo; ZapFast è un binario
   nativo e richiede una verifica dedicata. Il terminale non è stato abilitato.

Questo checkpoint conserva il lavoro incompleto. L'ultimo commit
pubblicato resta `ad6b476`. La memoria personale esistente è stata solo letta
per mostrarne lo stato, non svuotata né usata dai test automatici.
