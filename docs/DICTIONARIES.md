# Dizionario italiano del prototipo

Il download è esplicito (`autocorrect-fetch-dictionary`). Il core e la CLI non
accedono alla rete. I dati scaricati non vengono aggiunti al repository.

## Fonte fissata

- Progetto: <https://github.com/wolfgarbe/SymSpell>
- Revisione: `b8b2905bdea6835b04e9a026a1b83e3210665237`
- File: `SymSpell.FrequencyDictionary/it-100k.txt`
- URL: <https://raw.githubusercontent.com/wolfgarbe/SymSpell/b8b2905bdea6835b04e9a026a1b83e3210665237/SymSpell.FrequencyDictionary/it-100k.txt>
- SHA-256: `5f746afb7e6ae802872061ef025ce883cfa2a8779780968fa285dfd0907e9cfc`
- Dimensioni verificate: 1.592.580 byte; 100.000 voci uniche.
- Formato: `parola frequenza`, UTF-8. Frequenze assolute, non probabilità di correzione.

Percorso predefinito:
`$XDG_DATA_HOME/autocorrect/dictionaries/it-100k.txt`, oppure
`~/.local/share/autocorrect/dictionaries/it-100k.txt`.

Lo script non sovrascrive un file esistente con checksum diverso. La CLI
verifica anche il checksum del dizionario predefinito. Per provare dati propri
si usa esplicitamente `--dictionary /percorso/parole.txt`.

## Provenienza e licenze

Il [README upstream dei dizionari](https://github.com/wolfgarbe/SymSpell/tree/master/SymSpell.FrequencyDictionary)
descrive l'intersezione di Google Books Ngrams e liste generate da dizionari
Hunspell. Lo script di generazione fa riferimento ai dati Ngrams 2012.

Il codice SymSpell (Wolf Garbe) e il port Python symspellpy (mmb L) dichiarano
licenza MIT. Questo **non basta a stabilire la licenza dei dati derivati**.
Il dizionario italiano di `wooorm/dictionaries`, indicato nella catena delle
fonti, distingue il wrapper MIT dai file linguistici GPL-3.0:
<https://github.com/wooorm/dictionaries/tree/main/dictionaries/it>.

La specifica combinazione di condizioni applicabile a `it-100k.txt` rimane da
chiarire prima di redistribuire una nostra copia o una versione derivata.
Il prototipo registra origine e checksum e scarica il file originale per la
valutazione locale. Non dichiara il file italiano MIT, e il download separato
non elimina gli obblighi delle licenze originarie.

Ulteriori fonti considerate:

- Hunspell/LibreOffice italiano: lessico e morfologia, con condizioni proprie.
- PAISÀ: possibile ricerca futura sul contesto, ma il corpus distribuito è
  CC BY-NC-SA 3.0 e le liste pronte sono di lemmi, non di tutte le forme flesse.

## Normalizzazione e protezioni

All'interno del motore: Unicode NFC, minuscole e apostrofi tipografici ricondotti
all'apostrofo semplice per il confronto. Le frequenze di voci normalizzate
identiche vengono sommate. Il file originale resta intatto.

Il motore conserva esattamente l'input quando si astiene, anche se è in forma
Unicode decomposta. Non elimina gli accenti per cercare corrispondenze.
La prima versione conserva le parole con apostrofo e le possibili elisioni
senza apostrofo: non genera ancora nuove forme elise.

Il glossario `src/autocorrect_core/protected.txt` è una piccola lista tecnica
esplicita, non un dizionario inglese. Parole personali aggiuntive:

```text
~/.config/autocorrect/protected.txt
```

Una parola per riga, commenti con `#`. È rispettato anche `XDG_CONFIG_HOME`.
Si può aggiungere una lista per una prova con `--protected-words FILE`.
Le parole personali impediscono correzioni, senza diventare automaticamente
destinazioni per correggere altre parole. Non c'è apprendimento automatico.
