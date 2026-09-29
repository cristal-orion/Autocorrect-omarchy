# Autocorrect Omarchy

Prototipo standalone di autocorrezione italiana conservativa, basato su
**SymSpell**. Il core è indipendente da Fcitx e restituisce candidati e una
decisione esplicita: correggere oppure conservare l'input.

Stato corrente, risultati della prova manuale e prossime priorità:
[docs/STATUS.md](docs/STATUS.md).

### Prova nel BrowserOS reale

Sulla macchina predisposta, `.venv/bin/python scripts/run-browseros-probe.py`
apre BrowserOS con una pagina locale e il correttore collegato al Fcitx desktop.
Digitare `quesot` e Spazio; Backspace annulla. La prova è limitata a BrowserOS.
Installazione, verifiche e limiti: [docs/BROWSEROS_PROBE.md](docs/BROWSEROS_PROBE.md).

Il profilo BrowserOS quotidiano è ora collegato con attivazione automatica e
adattamento dei campi web: correzione e undo verificati su Google Ricerca,
Gemini, ChatGPT e Google Traduttore. La guida descrive anche il componente
browser necessario e la sua attivazione persistente.

### Prova attuale con apprendimento personale

```sh
python scripts/run-fcitx-probe.py --client qt --mode surrounding --engine core \
  --context --frequency 5000 --learn
```

Correggere una parola con Backspace/riscrittura o inserendo la lettera mancante,
poi terminare con spazio: il pannello conferma l'apprendimento. Una coppia come
`pne → pane` può funzionare anche in frasi diverse e dopo il riavvio. Alt+L
sospende la memoria; Alt+D permette di dimenticare un typo. I suggerimenti
selezionabili sono opzionali (Alt+S), disabilitati all'avvio.
Regole, file della memoria e verifiche: [docs/LEARNING.md](docs/LEARNING.md).

### Parole attaccate e apostrofo (sperimentale)

`nonlo → non lo`, `allinizio → all'inizio`, `cè → c'è`, con Backspace per
annullare. Si attiva con `--segmentation` nel server e nel launcher Fcitx.
Regole, corpus colloquiale e misure: [docs/SEGMENTATION.md](docs/SEGMENTATION.md).

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

La CLI può anche caricare la wordlist italiana AOSP sperimentale con
`--aosp-wordlist FILE`. Importazione verificata, confronto separato di lessico e
bigrammi e risultati: [docs/AOSP_DATA.md](docs/AOSP_DATA.md). I valori upstream
sono punteggi compressi e ranghi; non sostituiscono i conteggi richiesti dalle
soglie automatiche del core.

Per preparare conteggi completi da un primo corpus italiano di notizie, vedere
[docs/LEIPZIG_CORPUS.md](docs/LEIPZIG_CORPUS.md). Lo sweep della frequenza a margine
fisso è in [docs/FREQUENCY_SWEEP.md](docs/FREQUENCY_SWEEP.md).

È disponibile anche una [CLI LatinIME nativa per Linux](docs/LATINIME_PROBE.md).
La prima prova corregge più typo, ma la precisione scende al 93,52% rispetto
al 98,63% della baseline; il p95 nativo sui typo è 17,88 ms. La guida contiene
build, comandi, confronto a lessico condiviso e limiti della politica sperimentale.

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
SymSpell. È disponibile una [prova Fcitx isolata](docs/FCITX_PROBE.md) con
correzioni prefissate: 36 controlli superati nei widget Qt/GTK su Wayland.
Per aprirla: `python scripts/run-fcitx-probe.py --client qt --mode surrounding`,
dopo `bash scripts/build-fcitx-probe.sh`.

Per provare **SymSpell + Hunspell su un paragrafo digitato**, usare:

```sh
python scripts/run-fcitx-probe.py --client qt --mode surrounding --engine core
```

La finestra offre un campo multilinea: spazio valuta la parola precedente,
Backspace annulla l'ultima correzione. Il bridge reale ha superato 16 controlli
Qt e 9 GTK; dettagli e limiti nella [guida Fcitx](docs/FCITX_PROBE.md).
Il pannello diagnostico mostra anche il motivo delle astensioni e i candidati;
la prova Qt aggiornata comprende 17 controlli di integrazione superati.

La finestra Qt permette ora di confrontare **frequenza minima 100.000 e 5.000**
con due pulsanti (Alt+1 / Alt+5), oppure inserire una soglia con Alt+F. Per questa
prova lasciare il margine a 1,30. La diagnostica mostra la frequenza dei candidati
e le soglie effettive. Ultima verifica: **35 controlli Qt e 9 GTK superati**.

Per provare anche il **contesto Leipzig** e i typo da tre lettere:

```sh
python scripts/run-fcitx-probe.py --client qt --mode surrounding --engine core --context --frequency 5000
```

Alt+C attiva o disattiva il contesto. Nella prova `una piza` diventa `una pizza`
e `sono stao` diventa `sono stato`. Su 1.000 typo sintetici in frasi di sviluppo
le correzioni giuste salgono da 575 a 731, con gli stessi 2 errori. La modalità
recupera anche `ti devo dire una csa → cosa` e `prosciutto nel pne → pane` con
regole dedicate alle tre lettere. Ha superato 62 controlli Qt e 15 GTK; politica e limiti in
[docs/CONTEXTUAL_CORRECTION.md](docs/CONTEXTUAL_CORRECTION.md).

## Recupero dell'input

Sulla macchina di sviluppo è predisposto un red button indipendente dal progetto:

**Super + Ctrl + Alt + F12**, oppure `~/.local/bin/input-rescue`.

Ripristina le configurazioni salvate e lascia Fcitx spento. Per riattivarlo:
`~/.local/bin/input-rescue resume`.

Vedere [la guida di recupero](docs/RECOVERY.md) per accesso da TTY, ambito del
backup e recupero tramite lo snapshot Omarchy. I backup personali restano
fuori dal repository.
