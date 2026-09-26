# Generatore automatico di typo

## Uso

Il generatore produce esempi etichettati dal dizionario già scaricato. Non
richiede di scrivere errori a mano né di addestrare SymSpell. Dopo il setup,
funziona offline:

```sh
.venv/bin/autocorrect-generate-typos \
  --seed 42 --words 2000 --typos-per-word 4 --extra-clean-words 4000 \
  --exclude-cases data/it_smoke.json \
  --output-dir benchmark-data/it-seed42
```

Se la `.venv` precede l'aggiunta del comando, aggiornarne l'installazione con
`.venv/bin/python -m pip install --no-deps -e .`. In alternativa, lo stesso
comando è disponibile come `.venv/bin/python -m autocorrect_core.generate_typos`.

La cartella di destinazione deve essere nuova: un dataset esistente non viene
sovrascritto. Su questa macchina `benchmark-data/it-seed42` è già stato creato.
Per ripetere la generazione, usare per esempio `benchmark-data/it-seed42-repeat`.

File prodotti:

- `development.json`: casi per lo sviluppo e la taratura;
- `evaluation.json`: casi separati per valutare la politica scelta;
- `manifest.json`: parametri, checksum, distribuzioni ed esempi scartati.

Con questa configurazione sono stati generati **14.000 casi**:

| Split | Typo | Parole da preservare | Totale |
|---|---:|---:|---:|
| Sviluppo | 6.352 | 4.794 | 11.146 |
| Valutazione | 1.648 | 1.206 | 2.854 |
| Totale | 8.000 | 6.000 | 14.000 |

Ogni parola sorgente compare anche nella forma intatta. `--extra-clean-words`
aggiunge altre parole intatte, diverse dalle sorgenti: 2.000 + 4.000 = 6.000.

## Tipi di errore

Ogni variante ha **una sola modifica** secondo la distanza Damerau OSA:

| Categoria | Operazione | Esempio |
|---|---|---|
| `transposition` | Scambio di lettere adiacenti diverse | `progetto → progetot` |
| `missing_letter` | Rimozione di una lettera non appartenente a una doppia | `progetto → progtto` |
| `extra_letter` | Ripetizione di una lettera | `progetto → progeetto` |
| `double_letter_missing` | Rimozione di una lettera di una doppia | `progetto → progeto` |
| `nearby_key` | Sostituzione con una lettera su un tasto vicino | `progetto → progettp` |

La mappa `qwerty-us-letters-v1` usa i centri approssimati delle tre file di lettere
QWERTY, con scarti orizzontali 0, 0,25 e 0,75 e raggio di vicinanza 1,3 tasti.
È coerente con la disposizione delle lettere della tastiera US attuale.
Non modella tasti accentati, Shift, AltGr, tempi di digitazione o probabilità
reali di errore. Le altre operazioni preservano gli accenti come caratteri Unicode.

Per parola si alternano le categorie disponibili e si scelgono al massimo
`--typos-per-word` varianti distinte. Una parola senza doppie non produce una
doppia mancante: le categorie non hanno necessariamente le stesse dimensioni.
Se i filtri lasciano pochi candidati, il generatore non inventa esempi per
raggiungere la quota; il manifest riporta anche sorgenti rimaste senza typo.

## Campionamento e riproducibilità

Il vocabolario viene letto e normalizzato come nel core, **senza costruire
l'indice SymSpell e senza chiamare il correttore**. Non selezioniamo i casi in
base al successo o all'errore del motore.

Il campione è bilanciato, per quanto consentito dai dati, tra nove combinazioni:

- frequenza alta (`common`, almeno 1.000.000), media (`medium`, almeno 100.000),
  bassa (`rare`, sotto 100.000);
- lunghezza breve (fino a 6), media (7–10), lunga (oltre 10).

Le soglie sono conteggi nel corpus, non frequenze universali o etichette
linguistiche. Le lunghezze ammesse predefinite sono 4–20 caratteri, modificabili
con `--min-length` e `--max-length`.

Ordinamenti e scelte usano SHA-256 con seed, non l'ordine delle righe del file
né il generatore casuale globale Python. A parità di codice, dizionario,
parametri, parole protette ed esclusioni, i file prodotti sono identici byte
per byte. Il manifest registra anche il checksum del file del generatore.

## Separazione dei dataset

L'assegnazione a uno split dipende dall'hash della **parola sorgente** e dal seed.
La quota di valutazione predefinita è 20%, approssimata, non imposta a ogni
categoria. La parola intatta e tutti i suoi typo rimangono nello stesso split.
La stessa parola mantiene lo split se si aumenta la dimensione del campione.

Sono esclusi dalle sorgenti e dagli input generati:

- glossario tecnico e parole personali protette;
- input e forme attese nei file indicati con `--exclude-cases`;
- varianti che coincidono con **qualsiasi** voce del dizionario, anche non campionata;
- varianti generabili da più sorgenti del campione, anche tra split diversi.

Esempio: `carta → cara` non viene etichettato come errore se `cara` è nel
dizionario. Se due sorgenti producono lo stesso typo con destinazioni diverse,
quel typo viene scartato da entrambe. La ricerca di queste collisioni considera
tutte le proposte delle sorgenti campionate, prima di selezionare i quattro casi.

Nella prova seed 42 i filtri hanno scartato 2.046 proposte coincidenti con voci
note, 893 proposte con sorgenti multiple e 3 protette/escluse. Sono conteggi di
proposte sorgente/operazione, non necessariamente di stringhe uniche.

La separazione è **per forma scritta, non per lemma o famiglia morfologica**.
Inoltre le parole di entrambi gli split rimangono nel dizionario del motore:
si separano gli esempi per la valutazione, non la conoscenza lessicale.

Per una futura prova realmente nuova, cambiare seed non basta: usare anche
`--exclude-cases` sui dataset precedenti. L'opzione è ripetibile. Una valutazione
già usata per scegliere le modifiche del motore non è più una conferma indipendente.

## Eseguire il benchmark

```sh
.venv/bin/autocorrect-benchmark benchmark-data/it-seed42/development.json \
  --iterations 3 --details errors \
  --output benchmark-results/it-seed42-development.json

.venv/bin/autocorrect-benchmark benchmark-data/it-seed42/evaluation.json \
  --iterations 5 --details errors \
  --output benchmark-results/it-seed42-evaluation.json
```

Il tool accetta sia le liste del vecchio smoke test sia il nuovo formato
`{"metadata": {...}, "cases": [...]}`. Nei report include metadati e checksum,
risultati per categoria e fascia di frequenza, primo candidato e presenza della
forma attesa nei primi cinque candidati.

`--details errors` conserva i dettagli solo delle sostituzioni sbagliate,
compresi i candidati e il margine. `--details all` include anche le astensioni;
`--details none` omette i dettagli per caso. **Le metriche restano identiche**.
I gruppi per categoria/frequenza contengono i conteggi, mentre gli esempi
dettagliati sono raccolti una volta sola in `quality.errors` e `quality.abstentions`.

Le ripetizioni servono per misurare la latenza: non moltiplicano i casi nel
calcolo della qualità. Le statistiche di memoria comprendono anche il dataset
e le decisioni conservate dal benchmark.

## Limiti del test sintetico

- Usa parole del dizionario, che può contenere prestiti, nomi, varianti rare,
  grafie storiche o rumore. Il riferimento è la sorgente generativa, non una
  revisione linguistica di ogni voce.
- Filtra le collisioni note, ma una stringa assente dal vocabolario può ancora
  essere una parola valida, e possono esistere origini alternative non campionate.
- Le parole pulite sono tutte già note al motore: conservarle è un controllo
  utile, ma non misura i falsi positivi su parole valide **sconosciute**.
- Il bilanciamento delle fasce sovrarappresenta intenzionalmente parole rare
  rispetto alla digitazione comune. I risultati non sono una stima pesata
  dell'uso quotidiano.
- Le varianti della stessa parola sono correlate. L'intervallo di Wilson
  riportato dal benchmark non va interpretato come confidenza sull'uso reale.
- Questa versione non genera frasi, elisioni, errori a più modifiche o errori
  contestuali tra due parole valide.

Dataset generati e report sono locali e ignorati da Git. I dati derivati
mantengono le questioni di provenienza/licenza del dizionario: vedere
[DICTIONARIES.md](DICTIONARIES.md).

Risultati della prima esecuzione: [BENCHMARK_GENERATED.md](BENCHMARK_GENERATED.md).
