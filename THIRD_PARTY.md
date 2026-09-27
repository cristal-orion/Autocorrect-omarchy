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
