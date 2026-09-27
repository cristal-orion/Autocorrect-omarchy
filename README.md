# Autocorrect Omarchy

Prototipo standalone di autocorrezione italiana conservativa, basato su
**SymSpell**. Il core è indipendente da Fcitx e restituisce candidati e una
decisione esplicita: correggere oppure conservare l'input.

## Avvio rapido

Richiede Python 3.10+ con `venv` e accesso a Internet per il setup iniziale:

```sh
./scripts/setup.sh
./autocorrect quesot
./autocorrect quesot proggeto domnai qaundo interesasnte --json
```

Il setup installa le dipendenze nella `.venv` del progetto e scarica una revisione
verificata del dizionario italiano (100.000 voci) nei dati locali dell'utente.
Il funzionamento successivo è offline; non serve `sudo`.

### Prova interattiva con contesto

```sh
./autocorrect --interactive
```

Scrivi `ci vediamo `, incluso lo spazio: il terminale mostra tre suggerimenti.
Usa **Tab/F1**, **F2** o **F3** per sceglierli. **Invio** conferma e apprende la
frase; **Ctrl+Z** annulla una modifica, **Ctrl+C** scarta la riga, `/exit` esce.
La memoria personale sopravvive al riavvio della CLI.

La base iniziale contiene **91 frasi dimostrative originali**, non un modello
generale dell'italiano. La CLI mostra l'origine di ciascun suggerimento:
`demo`, `corpus`, `personale` o `frequenza`. Puoi sostituire la base demo con
un file UTF-8 di frasi:

```sh
./autocorrect --interactive --corpus /percorso/frasi.txt
./autocorrect --interactive --no-learn
```

`--no-learn` esclude lettura e scrittura della memoria personale. Per aggiornare
un ambiente creato prima della CLI interattiva:
`.venv/bin/python -m pip install -e .`.
Comandi, apprendimento e limiti: [docs/PREDICTION.md](docs/PREDICTION.md).

### Correzione di token singoli

Esempi del comportamento iniziale:

| Input | Output automatico | Motivo |
|---|---|---|
| `quesot` | `questo` | candidato nettamente favorito |
| `qaundo` | `quando` | candidato nettamente favorito |
| `interesasnte` | `interessante` | candidato nettamente favorito |
| `proggeto` | `proggeto` | `progetto` è suggerito ma richiede due modifiche |
| `domnai` | `domnai` | `domani` è primo ma il margine non basta |
| `Quesot` | `Quesot` | conservazione delle maiuscole e dei possibili nomi |
| `lacqua` | `lacqua` | elisione rimandata alla fase successiva |

Lo **score non è una probabilità**. Il campo JSON `confidence` è `null`.
La politica e il formato delle decisioni sono descritti in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

### Uso persistente e contesti

```sh
# Una parola per riga: carica il dizionario una volta sola. Ctrl+D per uscire.
./autocorrect --stdin --json

# Contesto esplicito: la parola resta invariata
./autocorrect quesot --context code

# Dati propri: file UTF-8 con una parola e un intero positivo per riga
./autocorrect quesot --dictionary /percorso/parole.txt

# Parole personali da proteggere (non destinazioni di correzione)
./autocorrect quesot --protected-words /percorso/parole-personali.txt
```

Viene letta anche `~/.config/autocorrect/protected.txt`, se presente.
Accetta una parola per riga e commenti con `#`.

Ogni argomento è un token completo. Frasi, URL, percorsi e parole con
punteggiatura non vengono segmentati. Non c'è rilevamento automatico di app,
campi password o lingua: `--context` serve a provare il contratto del core.

### Filtro Hunspell sperimentale

```sh
./autocorrect --hunspell quesot compilaste --json
./autocorrect --hunspell --stdin --json

# Prefisso senza estensione: legge /percorso/it_IT.aff e /percorso/it_IT.dic
./autocorrect --hunspell-dictionary /percorso/it_IT quesot
```

Con `--hunspell` il motore conserva anche le parole che Hunspell riconosce e
che mancano nella lista di frequenze (`reason: valid_word`). SymSpell continua
a generare i candidati per gli altri token. Il filtro è opzionale e richiede
la libreria di sistema `hunspell` e il dizionario `hunspell-it`, già presenti
sulla macchina di sviluppo. Il percorso predefinito è `/usr/share/hunspell/it_IT`.
Un errore nel caricamento del filtro richiesto interrompe il comando.

Primo confronto sullo sviluppo: **37 sostituzioni sbagliate invece di 40**,
con 4 correzioni giuste in meno su 6.352 typo. I 64 nuovi casi di parole valide
(56 assenti dalla lista di frequenze) restano intatti con entrambe le versioni.
Metodologia, prestazioni e limiti: [docs/HUNSPELL.md](docs/HUNSPELL.md).

Per misurare le proposte sul vocabolario personale senza proteggerlo durante
il test e preparare una revisione delle voci:
[docs/VOCABULARY_REVIEW.md](docs/VOCABULARY_REVIEW.md).

## Test e benchmark

```sh
.venv/bin/python -B -m unittest discover -s tests -v
.venv/bin/autocorrect-benchmark data/it_smoke.json --iterations 30 \
  --output benchmark-results/it-smoke.json
```

Il benchmark riporta precisione delle sostituzioni, copertura dei typo,
conservazione dei casi validi, errori e astensioni; separa caricamento del
dizionario e latenza a motore caldo. I risultati locali dettagliati sono ignorati
da Git. Dataset e relativi limiti: [data/README.md](data/README.md).

Prima misura: **55 correzioni corrette su 55 applicate**, 71/71 casi da
preservare invariati, copertura 72,37%; p95 a caldo circa 1,90 ms sui token con
candidati. Campione manuale piccolo, non una garanzia per l'uso quotidiano.
Dettagli, risorse e astensioni: [docs/BENCHMARK.md](docs/BENCHMARK.md).

### Generatore automatico e benchmark esteso

```sh
.venv/bin/autocorrect-generate-typos --seed 42 --words 2000 \
  --typos-per-word 4 --extra-clean-words 4000 \
  --exclude-cases data/it_smoke.json --output-dir benchmark-data/it-seed42

.venv/bin/autocorrect-benchmark benchmark-data/it-seed42/development.json \
  --iterations 3 --details errors --output benchmark-results/it-seed42-development.json

.venv/bin/autocorrect-benchmark benchmark-data/it-seed42/evaluation.json \
  --iterations 5 --details errors --output benchmark-results/it-seed42-evaluation.json
```

Il generatore campiona il dizionario e crea inversioni, omissioni, ripetizioni,
doppie mancanti e sostituzioni con tasti QWERTY vicini. Produce **14.000 casi**,
separando le parole sorgenti tra sviluppo e valutazione. Filtra le varianti già
note e le collisioni tra sorgenti del campione; non usa le risposte del motore
per scegliere gli esempi.

La cartella di destinazione deve essere nuova; per ripetere una generazione
già eseguita scegliere un altro `--output-dir`. I dati derivati sono ignorati
da Git. Parametri e dettagli: [docs/TYPO_GENERATOR.md](docs/TYPO_GENERATOR.md).

Il test più ampio ha evidenziato **12 sostituzioni sbagliate su 680 applicate**
nella valutazione separata: precisione **98,24%**, copertura **40,53%**. Le 1.206
parole note sono rimaste invariate. Il campione è sintetico e bilanciato anche
sulle parole rare: non equivale alla distribuzione della scrittura quotidiana.
Analisi: [docs/BENCHMARK_GENERATED.md](docs/BENCHMARK_GENERATED.md).

Fonti, checksum e questione della licenza dei dati:
[docs/DICTIONARIES.md](docs/DICTIONARIES.md).

Il piano originale in `piano_autocorrect_linux_codex.txt` precede la scelta di
SymSpell. L'integrazione Fcitx e le prove di digitazione nelle applicazioni sono
fasi successive al prototipo CLI.

## Recupero dell'input

Sulla macchina di sviluppo è predisposto un red button indipendente dal progetto:

**Super + Ctrl + Alt + F12**, oppure `~/.local/bin/input-rescue`.

Ripristina le configurazioni salvate e lascia Fcitx spento. Per riattivarlo:
`~/.local/bin/input-rescue resume`.

Vedere [la guida di recupero](docs/RECOVERY.md) per accesso da TTY, ambito del
backup e recupero tramite lo snapshot Omarchy. I backup personali restano
fuori dal repository.
