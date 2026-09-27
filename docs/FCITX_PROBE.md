# Prima prova Fcitx su Hyprland

Prova del 27 settembre 2026: addon C++ con tre sostituzioni prefissate, senza
modello linguistico. Serve a verificare il meccanismo di input nelle applicazioni.

## Avvio manuale

```sh
bash scripts/build-fcitx-probe.sh
python scripts/run-fcitx-probe.py --client qt --mode surrounding
```

Il campo normale corregge `quesot → questo`, `qaundo → quando`, `domnai → domani`
allo spazio. Backspace subito dopo ripristina l'originale; un altro spazio lo
conserva senza ricorreggerlo. La finestra comprende anche password sintetica,
campo NoSpellCheck/NoPredictiveText e secondo campo normale.

Alternative: `--client gtk`, oppure `--mode preedit` per tenere la parola in
composizione fino allo spazio. Chiudere la finestra termina i processi della prova.

## Isolamento

Il launcher crea sotto `build/fcitx-probe-sessions/` una cartella per sessione,
con profilo e percorsi XDG propri, poi avvia un D-Bus privato, una seconda
istanza Fcitx e il client. La libreria compilata rimane sotto `build/fcitx-probe`.
Gli addon di sistema e il servizio `omarchy-fcitx5.service` continuano a usare
il profilo ordinario. Il launcher non richiede installazioni o modifiche del
profilo utente.

I client GTK/Qt sono finestre Wayland native, ma parlano con Fcitx tramite i
rispettivi moduli IM e il frontend D-Bus. Il frontend `waylandim` della seconda
istanza è disabilitato, per non contendergli il metodo di input del compositor.

## Verifica automatica eseguita

```sh
python scripts/run-fcitx-probe.py --client qt --mode preedit --test
python scripts/run-fcitx-probe.py --client qt --mode surrounding --test
python scripts/run-fcitx-probe.py --client gtk --mode preedit --test
python scripts/run-fcitx-probe.py --client gtk --mode surrounding --test
```

Il runner usa l'API Lua di Hyprland 0.56 per inviare pressioni e rilasci alla
sola finestra appena avviata. Alla fine tenta di ripristinare il focus precedente.
Le prove sono sequenziali perché condividono il focus del desktop.

**Risultato: 36 controlli superati, 9 per ogni combinazione.**

1. Correzione allo spazio.
2. Annullamento seguito da spazio, senza ricorrezione.
3. Correzione dopo un prefisso Unicode (`è `).
4. Annullamento con quel prefisso.
5. Movimento del cursore che invalida l'annullamento.
6. Nuova digitazione che invalida l'annullamento.
7. Conservazione nel campo password.
8. Conservazione nel campo NoSpellCheck/NoPredictiveText.
9. Cambio di campo che conserva la composizione originale.

L'utente ha poi provato manualmente la modalità Qt/surrounding e confermato
il buon funzionamento del meccanismo.

Versioni: Fcitx 5.1.22, fcitx5-qt 5.1.15, fcitx5-gtk 5.1.7,
Qt 6.11.2, GTK 3.24.52, Hyprland 0.56.2.

Report delle quattro esecuzioni riuscite:

- `build/fcitx-probe-sessions/qt-preedit-o1ihpveo/report.json`
- `build/fcitx-probe-sessions/qt-surrounding-51z3qjap/report.json`
- `build/fcitx-probe-sessions/gtk-preedit-nl0m5cjg/report.json`
- `build/fcitx-probe-sessions/gtk-surrounding-bnrioexp/report.json`

## Dettagli emersi

Qt può non inviare subito il surrounding text iniziale di un campo vuoto.
Il primo tentativo di annullamento in modalità preedit falliva per questo motivo.
Ora il probe attende una fotografia del testo dopo il commit che termini con
la sostituzione prevista, prima di abilitare l'annullamento. Qualsiasi altro
tasto di modifica cancella la transazione. Se fotografia, cursore o selezione
non corrispondono, il probe lascia Backspace all'applicazione.

L'API `deleteSurroundingText` usa offset in caratteri Unicode, mentre le stringhe
C++ sono UTF-8: il probe converte la posizione del cursore prima di estrarre
il testo. In questa prima prova le sostituzioni sono tutte ASCII.

## Ambito e passi successivi

Il risultato dimostra fattibilità nei widget di prova Qt/GTK tramite moduli IM.
Restano da verificare browser/Electron, widget multilinea, text-input-v3,
incolla, selezioni, cambi di focus più complessi e perdita di disponibilità
del testo circostante. I test usano eventi sintetici del compositor; la prova
manuale aggiunge una prima verifica con tastiera fisica.

Il popup è separato dalla correzione silenziosa. `--popup` abilita un candidato
dimostrativo non selezionabile nella modalità preedit; la verifica visuale e
del posizionamento del popup è ancora da completare. Le quattro esecuzioni
riportate sopra avevano il popup disattivato.

I log Fcitx contengono eventi e capacità, senza il testo dei tasti. I file
`status.json`/`status.ini` del client contengono i valori dei campi della prova
e rimangono sotto `build/`, ignorata da Git.
