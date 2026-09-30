# Componenti e dati di terzi

## Dipendenze del prototipo

- **symspellpy 6.10.0**: port Python di SymSpell, MIT. Il progetto installa il
  pacchetto tramite `pyproject.toml`.
- **prompt_toolkit 3.0.52**: editor della CLI, BSD-3-Clause.
- **Fcitx5, Qt6, GTK3, json-c e Hunspell**: librerie installate sul sistema per
  le prove. Il repository contiene il nostro addon, client e binding, senza
  copie di quelle librerie.
- **Lista italiana SymSpell e dizionario Hunspell di sistema**: provenienza,
  checksum e condizioni dei dati in [docs/DICTIONARIES.md](docs/DICTIONARIES.md).

## Wordlist italiana AOSP-compatible sperimentale

- Curatore: **Helium314**, progetto `aosp-dictionaries`.
- Repository: <https://codeberg.org/Helium314/aosp-dictionaries>.
- Revisione: `55e6d1c64ad72481d5615113b1c94f0716617016`.
- File: `wordlists_experimental/main_it.combined`.
- SHA-256: `50e0c819848e5d7b527dfcb0d21ca85fef3e90d99bd0f5f1d2435cacfa48301d`.
- [Avviso di provenienza fissato](https://codeberg.org/Helium314/aosp-dictionaries/src/commit/55e6d1c64ad72481d5615113b1c94f0716617016/wordlists_experimental/main_it.source):
  liste da **Leipzig Corpora Collection**, <https://wortschatz.uni-leipzig.de/en/download/>,
  con licenza dichiarata **CC BY 4.0**, <https://creativecommons.org/licenses/by/4.0/>.

L'avviso upstream non identifica i singoli archivi di corpus usati. Registriamo
la dichiarazione disponibile, senza attribuire al file una licenza derivata da
quella del codice della tastiera. Per distribuire i dati occorre conservare
attribuzioni, avvisi applicabili e indicazione delle modifiche.

Il comando di importazione scarica i dati su richiesta. La copia grezza,
l'esportazione dei punteggi e il manifest restano nelle cartelle locali ignorate
da Git. L'adattatore applica NFC, minuscole e normalizzazione degli apostrofi;
esclude forme incompatibili col tokenizer; combina collisioni con massimo
punteggio e minimo rango. Per i suggerimenti usa il codice unigramma come peso
e `1/rango` per i bigrammi. Il manifest descrive queste trasformazioni.

Abbiamo consultato `scripts/wordlist.py` e `scripts/wordlist_combined.py` nella
stessa revisione per capire il formato. Il parser Python in questo repository
è una nostra implementazione; non incorpora quegli script o i tool binari.

## Archivio Leipzig `ita_news_2023_100K`

- Editore: **Leipzig Corpora Collection**, Università di Lipsia.
- Download ufficiale: <https://downloads.wortschatz-leipzig.de/corpora/ita_news_2023_100K.tar.gz>.
- SHA-256: `5db4079d208b80a1cab4fed9f2995bbc1433c32edad99d00d5b0e79d006e6869`.
- I metadati nell'archivio dichiarano build 2024-01-12 e 100.000 frasi.
- **Licenza dell'archivio non ancora verificata**: il 27 settembre 2026 le pagine
  ufficiali `/en/usage` e `/en/download/Italian` hanno restituito una verifica
  Anubis; l'archivio non include un avviso di licenza. Non deduciamo la licenza
  di questi dati da quella dichiarata per le liste sorgenti AOSP.

La preparazione locale normalizza e deduplica segmenti, li separa per hash e conta
gli n-grammi del solo training. Il repository versiona il programma originale;
testi e dati derivati rimangono fuori da Git. Comandi, limitazioni dello split e
metadati: [docs/LEIPZIG_CORPUS.md](docs/LEIPZIG_CORPUS.md).

## Frasi italiane Tatoeba

- Editore: **Tatoeba**, <https://tatoeba.org>, frasi scritte da volontari.
- Download: <https://downloads.tatoeba.org/exports/per_language/ita/ita_sentences.tsv.bz2>.
- Licenza: **CC BY 2.0 FR**, <https://creativecommons.org/licenses/by/2.0/fr/>.
  Condizioni: <https://tatoeba.org/en/downloads>.
- Esportazione del 26 settembre 2026 (intestazione `Last-Modified`), scaricata il 29:
  SHA-256 `55c220482848cb9402c94e53750902744301fb700ca0cce5a938c8fd13644ca2`,
  9570218 byte. L'esportazione cambia ogni settimana, quindi il manifest
  registra il file effettivamente usato.

L'importatore `src/autocorrect_core/tatoeba_corpus.py`:
- scarta le frasi con parole sconosciute a lessico e Hunspell, tranne i nomi
  scritti con la maiuscola;
- normalizza e deduplica;
- divide per hash e conta gli n-grammi del solo training.

Frasi e conteggi derivati restano fuori da Git. Per distribuirli occorre
citare Tatoeba, indicare la licenza e segnalare le modifiche.

## LatinIME: selezione del codice per la prossima prova

Fonte preferita: **Android Open Source Project**,
<https://android.googlesource.com/platform/packages/inputmethods/LatinIME/>.
I file AOSP consultati del motore dichiarano Apache-2.0. Prima di importarli
fisseremo revisione, elenco dei file e relative intestazioni, conservando LICENSE
e gli eventuali NOTICE richiesti. La licenza del nostro codice non sostituisce
gli obblighi del codice o dei dati riutilizzati.

HeliBoard dichiara GPL-3.0 per il progetto e mantiene componenti AOSP Apache-2.0.
In questo blocco abbiamo consultato il fork per individuare le API; non abbiamo
importato sorgenti, APK o librerie native di HeliBoard/LatinIME.

### Prova nativa del 28 settembre 2026

Il builder `scripts/build-latinime-probe.py` acquisisce e compila:

- **AOSP LatinIME**, revisione `127336e9f29d69607eab55982324b210279ae8c5`,
  <https://android.googlesource.com/platform/packages/inputmethods/LatinIME/>.
  Usa gli 82 `.cpp` del gruppo `LATIN_IME_CORE_SRC_FILES` in `native/jni/Android.bp`
  e i relativi header. Il gruppo dichiara Apache-2.0; il checkout include `NOTICE`
  con il testo della licenza. Il core resta senza modifiche.
- **AOSP libnativehelper**, revisione `aef2939781fc0b57b4477df7160935cdf5697919`,
  <https://android.googlesource.com/platform/libnativehelper/>. Usa solo
  `include_jni/jni.h`, con intestazione Apache-2.0; conserva anche il `NOTICE`
  del checkout. L'adattatore host usa gli array senza caricare una JVM.
- **json-c** di sistema per il protocollo JSON del processo nativo. Il builder
  usa `pkg-config` e registra la versione nel manifest; json-c usa licenza MIT.

Il percorso predefinito dei checkout è `build/latinime-probe/vendor/`, escluso
da Git, insieme al binario. Il manifest registra revisioni e checksum dei file
usati, inclusi gli avvisi `NOTICE`. Per ridistribuire il binario occorre
accompagnarlo con gli avvisi e le licenze delle dipendenze.

I dizionari nativi derivano dalla wordlist Helium314 descritta sopra; il manifest
dei dati esplicita la normalizzazione e la trasformazione sperimentale dei
ranghi bigramma. Codici e ranghi non diventano conteggi attraverso la compilazione.
Il codice FUTO consultato resta fuori dalla build. La sua licenza di progetto
è FUTO Source First 1.1-kb, distinta da quella dei sorgenti AOSP qui selezionati.
Dettagli della prova: [docs/LATINIME_PROBE.md](docs/LATINIME_PROBE.md).
