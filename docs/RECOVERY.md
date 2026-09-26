# Ripristino dell'input su questa macchina

## Recupero rapido

**Super + Ctrl + Alt + F12** esegue il red button. Se i tasti funzione sono
multimediali, potrebbe essere necessario premere anche Fn.

Lo stesso comando, dal terminale o da una console TTY, è:

```sh
~/.local/bin/input-rescue
```

Eseguirlo come utente normale, **senza sudo**. Non richiede rete, Git,
ambiente virtuale, motore di autocorrezione o finestra di conferma.

Il comando:

1. Ferma `omarchy-fcitx5.service` e l'eventuale `autocorrect.service`, mascherandoli
   per la sessione corrente. Questo impedisce il riavvio automatico di Fcitx.
2. Termina eventuali istanze Fcitx avviate manualmente dallo stesso utente.
3. Verifica l'integrità del backup prima di ripristinare i file.
4. Sposta le configurazioni correnti in un archivio di recupero, poi ripristina
   quelle del baseline. I percorsi inizialmente assenti tornano assenti.
5. Mantiene la scorciatoia di emergenza, ricarica Hyprland se eseguito nella
   sessione grafica e verifica gli errori della configurazione.
6. Lascia Fcitx **spento**, per usare la digitazione diretta. Compose e altri
   servizi forniti da Fcitx rimangono indisponibili fino alla riattivazione.

Per riavviare Fcitx dopo il ripristino:

```sh
~/.local/bin/input-rescue resume
```

`resume` non ripristina file: avvia Fcitx con le configurazioni presenti in quel
momento. Usarlo dopo il red button per ritrovare il baseline, oppure dopo uno
stop volontario. L'eventuale servizio sperimentale rimane mascherato.

## Se l'input grafico non risponde

1. Premere **Ctrl + Alt + F3** (eventualmente anche Fn).
2. Accedere come `michele` con la propria password. È la console Linux, che non
   usa Fcitx; durante la password non vengono mostrati caratteri.
3. Eseguire `~/.local/bin/input-rescue`.
4. Tornare alla sessione grafica con **Ctrl + Alt + F1**: al momento della
   preparazione Hyprland è su `tty1`.
5. Se necessario, chiudere e riaprire le applicazioni interessate. Per applicare
   completamente variabili d'ambiente ripristinate, fare logout/login.
6. Eseguire `~/.local/bin/input-rescue resume` per riattivare Fcitx.

Le maschere sono runtime: un riavvio le elimina. Dopo il ripristino, la normale
configurazione di avvio di Fcitx torna quindi operativa al prossimo boot.
La sola azione `stop`, senza ripristino, non disinstalla un esperimento.

## Altri comandi

```sh
# Verifica backup e stato del servizio, senza modificare l'input
~/.local/bin/input-rescue status

# Ferma soltanto Fcitx e il servizio sperimentale, senza ripristinare file
~/.local/bin/input-rescue stop
```

Se il backup risulta danneggiato il ripristino dei file non parte, ma Fcitx viene
comunque fermato. Gli errori vengono stampati nel terminale e, quando possibile,
mostrati con una notifica sul desktop.

## Baseline e ambito

Baseline creato il **26 settembre 2026**, prima dell'integrazione autocorrect.
Profilo iniziale: `keyboard-us`; servizio `omarchy-fcitx5.service` abilitato.
L'intera lista dei 18 percorsi si trova in `PATHS` nello script e nel manifest.

Backup privato, fuori dal repository:

```text
~/.local/state/autocorrect-recovery/baseline/
  manifest.json
  files/
```

Stati spostati durante i ripristini:

```text
~/.local/state/autocorrect-recovery/rescues/<data-UTC>/
```

Il baseline non viene sovrascritto da `capture`. Include:

- configurazione e dati utente Fcitx;
- **tutta la configurazione utente Hyprland**, comprese impostazioni monitor,
  binding e relativi backup già presenti;
- configurazioni utente UWSM, `environment.d` e `.XCompose`;
- override e collegamento di avvio del servizio Fcitx;
- percorsi riservati al futuro esperimento autocorrect.

Il red button riporta quindi anche eventuali personalizzazioni Hyprland
successive al baseline; la loro versione precedente al ripristino è conservata
in `rescues`. La scorciatoia di emergenza viene riaggiunta dopo il ripristino.

Non ripristina pacchetti, `/etc`, applicazioni aperte o documenti. Le variabili
d'ambiente già ereditate dai processi richiedono il riavvio delle applicazioni
o della sessione. La digitazione diretta dipende anche dal comportamento
dell'applicazione: la console TTY resta la via indipendente dall'IME grafico.

## Contratto per la futura integrazione

- Usare il nome `autocorrect.service` per l'eventuale servizio separato.
- Configurazioni in `~/.config/autocorrect`, dati in `~/.local/share/autocorrect`,
  librerie sperimentali in `~/.local/lib/autocorrect`.
- Registrazioni Fcitx locali in `~/.local/share/fcitx5`; eventuali collegamenti
  puntano alle librerie nella directory dedicata.
- Non installare addon in `/usr/lib` durante le prime prove.
- Se servono altri percorsi, estendere e verificare il recupero **prima** di
  usarli, senza sovrascrivere questo baseline.
- La copia installata di `input-rescue` è un file indipendente dal repository,
  non un link. Rotture o spostamenti del progetto non la alterano.

## Recupero di sistema

Esiste anche lo **snapshot Snapper root #6**, descrizione
`Prima del progetto autocorrect Linux`, creato il 26 settembre 2026 alle 21:17 CEST.
Omarchy permette di selezionare gli snapshot al boot; usare il suo percorso di
ripristino (`omarchy snapshot restore`) per un rollback di sistema.

Su questa macchina `/home` è il sottovolume separato `@home`: lo snapshot root
**non sostituisce** il backup utente descritto sopra. Nessuno dei due è una copia
esterna del disco.

## Verifica dello strumento

```sh
python -B -m unittest discover -s tests -p 'test_input_rescue.py' -v
```

I test usano home temporanee e simulano i comandi di sistema: verificano
integrità, ripristino, conservazione dei file spostati, percorsi assenti,
permessi, link simbolici, ripetibilità e gestione di `Restart=always`.
Non eseguono un ripristino della sessione reale.

Verifiche eseguite durante la preparazione:

- nove test automatici superati, compresa l'intera sequenza del red button con
  comandi di sistema simulati;
- arresto e riavvio **reali** di Fcitx riusciti, con ritorno a `keyboard-us`;
- scorciatoia registrata in Hyprland e nessun errore dopo `hyprctl reload`;
- integrità del backup locale verificata con `input-rescue status`.

Non è stato eseguito un rollback completo della sessione reale né dello
snapshot root. Il passaggio TTY è documentato, non è stato forzato durante il lavoro.

Il prototipo standalone scarica il dizionario in `~/.local/share/autocorrect`,
uno dei percorsi coperti dal ripristino. Dopo un red button, riscaricarlo con
`.venv/bin/autocorrect-fetch-dictionary` dalla cartella del progetto.
