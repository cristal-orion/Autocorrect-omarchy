# Prove Fcitx su Hyprland

La prima prova del 27 settembre 2026 usava un addon C++ con tre sostituzioni
prefissate. Il passaggio successivo collega il core reale nella stessa sessione
isolata e aggiunge un campo multilinea.

## Prova con motore reale e testo multilinea

```sh
bash scripts/build-fcitx-probe.sh
python scripts/run-fcitx-probe.py --client qt --mode surrounding --engine core
```

La nuova finestra si chiama **Autocorrect - testo reale e diagnostica**
e apre il focus su un campo multilinea. Scrivere un paragrafo nel campo grande:
ogni spazio valuta il token precedente. Backspace subito dopo una sostituzione
ripristina l'originale. Il motore conserva parole note, parole Hunspell, maiuscole
e casi che non superano le soglie del core.

Sotto il paragrafo compare l'ultima analisi del motore: token, output proposto,
motivo, primi tre candidati e margine rispetto alla soglia. `ambiguous` significa
che il margine non basta; `known_word` indica una voce della lista di frequenze;
`valid_word` indica il riconoscimento Hunspell. La diagnostica riporta una
decisione del motore, non una conferma che l'applicazione l'abbia applicata:
una risposta tardiva può essere scartata dal bridge. Il pannello conserva
l'ultima analisi disponibile quando il server non risponde.

La prova manuale ha evidenziato astensioni su candidati plausibili e parole
valide usate come typo. Il collegamento raggiunge il core, ma per questi casi
la qualità resta limitata dalla valutazione a singolo token. Ridurre il margine
può selezionare una forma grammaticalmente sbagliata per la frase. I test di
integrazione verificano il meccanismo, non la qualità nell'uso quotidiano.

Esempio di input costruito per provare il percorso, premendo spazio dopo il punto:

```text
oggi provo quesot sistema qaundo scrivo un progeto interesasnte.
```

Output verificato:

```text
oggi provo questo sistema quando scrivo un progetto interessante.
```

Questa prova usa il core reale a singolo token, con il dizionario da 100.000
frequenze e Hunspell. La politica conserva anche `proggeto`, che richiede due
modifiche, e può conservare `domnai` per ambiguità: il risultato può differire
dalle tre sostituzioni prefissate della prova iniziale.

Il server Python carica il motore una volta. L'addon C++ gli invia il token
tramite un socket Unix privato, con messaggi separati per richiesta. Il client
assegna un budget di 50 ms all'attesa sul socket; errori, risposte non coerenti
o assenza del server lasciano passare lo spazio con il testo originale. Il
server non apprende. Il launcher abilita un file locale `decision.json` con
l'ultima analisi per il pannello; il server lo pubblica dopo aver risposto sul
socket. Il file ha permessi `0600` e sostituisce l'analisi precedente. I file di
stato della finestra contengono il testo della prova, sotto la cartella di
sessione ignorata da Git. I log testuali del server non contengono i token.

Il bridge gestisce una sequenza finale di `,.!?;:` dopo un token alfabetico,
conservandola nella sostituzione. Tratta URL, percorsi e stringhe strutturate
come token interi. La cancellazione e l'annullamento usano lunghezze Unicode.

Limiti dell'interazione attuale:

- La correzione parte allo **spazio**, non a Invio o alla sola punteggiatura.
- Incollare un paragrafo non avvia una revisione retroattiva di tutte le parole.
- Il modello contestuale della CLI non determina le sostituzioni in questa prova.
- Il bridge reale è disponibile in modalità `surrounding`, senza popup.
- La richiesta breve è sincrona nel processo Fcitx; un adapter destinato all'uso
  continuativo richiederà ulteriori misure di latenza e valutazione del trasporto.

### Verifiche del bridge reale

```sh
python scripts/run-fcitx-probe.py --client qt --mode surrounding --engine core --test
python scripts/run-fcitx-probe.py --client gtk --mode surrounding --engine core --test
```

Risultati iniziali: **16 controlli Qt e 9 GTK superati**. Ai nove casi base, Qt aggiunge
paragrafo multilinea, correzione e annullamento dell'ultima parola, astensione
su due modifiche, motore sospeso con SIGSTOP, ripresa senza risposte obsolete
e arresto del motore. I controlli Python coprono protocollo e punteggiatura.

Dopo l'aggiunta della diagnostica: **17 controlli Qt superati**, incluso il
contenuto del pannello per un'astensione. Un nuovo test Python verifica che
candidati e margine spieghino l'ambiguità senza alterare la decisione. Il report
Qt aggiornato è in `build/fcitx-probe-sessions/qt-surrounding-pulluvsc/report.json`.

Report locali:

- `build/fcitx-probe-sessions/qt-surrounding-ryyinmzm/report.json`
- `build/fcitx-probe-sessions/gtk-surrounding-7bdkitk9/report.json`

La compilazione richiede anche `json-c`; pubblica i binari con rinomina atomica,
così le finestre già aperte possono continuare a usare la versione precedente.

## Avvio manuale con sostituzioni prefissate

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
Restano da verificare browser/Electron, altri widget multilinea, text-input-v3,
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
