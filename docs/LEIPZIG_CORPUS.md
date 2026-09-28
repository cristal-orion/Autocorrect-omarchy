# Corpus italiano di Lipsia: preparazione locale

27 settembre 2026. Abbiamo scaricato dal server ufficiale il campione
**`ita_news_2023_100K`**, con 100.000 frasi di notizie italiane del 2023, e
preparato conteggi completi per il nostro tokenizer.

## Provenienza e verifica

- URL: <https://downloads.wortschatz-leipzig.de/corpora/ita_news_2023_100K.tar.gz>
- Dimensione archivio: 26.686.860 byte.
- SHA-256: `5db4079d208b80a1cab4fed9f2995bbc1433c32edad99d00d5b0e79d006e6869`.
- Data di build dichiarata nei metadati: 12 gennaio 2024.
- Metadati upstream: 100.000 frasi, 2.216.325 token, 134.864 tipi e 88.646 fonti.

**La licenza specifica dell'archivio resta da verificare.** Le pagine ufficiali
di download e condizioni d'uso mostrano una verifica Anubis che richiede un
browser; l'archivio scaricabile contiene metadati statistici, ma nessun avviso di
licenza. Il manifest registra `unverified_for_this_archive`. La dichiarazione
CC BY 4.0 della wordlist AOSP non basta ad attribuire una licenza a questo archivio.
Fonte e stato della verifica sono anche in [THIRD_PARTY.md](../THIRD_PARTY.md).

Il repository conserva il codice di acquisizione e preparazione. Archivio,
testi, database e manifest rimangono nelle cartelle locali ignorate da Git.

## Riproduzione

```sh
.venv/bin/python -m autocorrect_core.leipzig_corpus \
  --output-dir benchmark-data/leipzig-ita-news-2023-100k
```

Il comando scarica e verifica l'archivio in
`benchmark-data/leipzig-downloads/`. Se il file verificato esiste già, lo riusa.
Per usare una copia locale dello stesso archivio:

```sh
.venv/bin/python -m autocorrect_core.leipzig_corpus \
  --archive /percorso/ita_news_2023_100K.tar.gz \
  --output-dir benchmark-data/leipzig-ita-news-2023-100k
```

L'output deve essere una nuova cartella. Il programma prepara i file in una
cartella temporanea e pubblica il risultato alla fine, senza sostituire dataset
esistenti. Legge due membri regolari dell'archivio tramite stream, senza estrarre
percorsi o collegamenti. Un checksum diverso interrompe l'importazione.

## Tokenizzazione e split

Il file sorgente contiene `ID<TAB>frase`. Il programma valida gli identificativi,
poi usa `prediction.sentences_from`, lo stesso tokenizer della CLI:

- normalizzazione NFC, minuscole e apostrofi;
- interruzione della sequenza per confini di frase, numeri e token strutturati;
- nessun n-gramma attraverso quei confini;
- deduplicazione dei segmenti normalizzati prima dell'assegnazione allo split.

Ogni segmento normalizzato ha un solo split, indipendente dall'ordine dei record:
SHA-256 di `autocorrect-leipzig-v1`, NUL e segmento; primi otto byte big endian
modulo 100. Bucket 0–79 training, 80–89 sviluppo, 90–99 valutazione.

La separazione riguarda segmenti testuali identici, **non articoli, siti, lemmi
o parafrasi**. Segmenti dello stesso articolo possono finire in split diversi.
Per una futura valutazione forte servirà anche una separazione per documento
o fonte. Non abbiamo interrogato i target dello split di valutazione per tarare
il predittore: in questo blocco lo abbiamo soltanto prodotto e verificato tramite
checksum.

## Risultato della preparazione

| Misura | Valore |
|---|---:|
| Record sorgente | 100.000 |
| Segmenti prodotti dal tokenizer | 142.967 |
| Segmenti duplicati scartati | 10.846 |
| Segmenti training | 105.798 |
| Segmenti sviluppo | 13.010 |
| Segmenti valutazione | 13.313 |
| Token lessicali nel training | 1.518.247 |
| Tipi unigramma, incluso fine-frase | 81.485 |
| Tipi bigramma | 641.084 |
| Tipi trigramma | 1.216.612 |

Il training contiene 1.624.045 occorrenze per ordine, contando anche il marcatore
di fine frase. Ogni n-gramma osservato conserva il proprio conteggio intero;
non limitiamo le continuazioni a tre e non applichiamo un filtro top-k ai dati.
I conteggi descrivono lo split di training normalizzato e deduplicato, quindi
non coincidono con le statistiche del corpus grezzo.

File prodotti:

- `train.txt`, `development.txt`, `evaluation.txt`: un segmento normalizzato per riga;
- `ngrams.sqlite3`: tabella `ngrams(n,c1,c2,word,count)`, con indice primario sul
  contesto; righe per ordini 1, 2 e 3, soltanto dal training;
- `unigrams.txt`: conteggi lessicali del training, senza marcatore di fine frase;
- `source-meta.txt`: metadati upstream;
- `manifest.json`: origine, checksum, tokenizer, regole di split, statistiche e
  stato della verifica di licenza.

Un conteggio di un corpus da 1,5 milioni di token non ha la stessa scala della
lista di frequenze baseline. `unigrams.txt` serve per analisi e modello linguistico;
non va confrontato con la soglia automatica 100.000 senza una nuova calibrazione.

## Uso nel laboratorio esistente

Aggiornamento del 28 settembre: il [correttore contestuale](CONTEXTUAL_CORRECTION.md)
legge ora `ngrams.sqlite3` in sola lettura, con cache limitata delle righe, e può
guidare le sostituzioni nella prova Fcitx con `--context`. Il percorso CLI
descritto sotto continua a caricare le frasi in RAM.

La CLI sa già caricare frasi, quindi si può provare il solo training:

```sh
./autocorrect --interactive --no-learn \
  --corpus benchmark-data/leipzig-ita-news-2023-100k/train.txt
```

Questo comando ricostruisce i conteggi in RAM dal testo. Il database preparato
conserva gli stessi conteggi per le prossime prove; non abbiamo aggiunto in questo
blocco un backend SQLite al predittore. Avvio, memoria e latenza del modello
esteso vanno misurati prima del collegamento a Fcitx.

Le notizie sono una prima fonte riproducibile, non una base conversazionale già
validata. Il prossimo confronto dovrà tenere separati corpus, motore e politica
di applicazione. L'indice per prefisso e il caching dei candidati restano un
intervento da misurare prima dell'integrazione nel budget del bridge.

## Verifica

I test controllano conteggi esatti, confini di frase, deduplicazione, esclusione
dei dati di valutazione dal training, indipendenza dello split dall'ordine,
identificativi malformati e checksum dell'archivio. La preparazione completa ha
letto i 100.000 record e prodotto il manifest con i checksum dei sei file derivati.
