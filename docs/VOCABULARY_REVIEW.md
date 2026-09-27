# Confronto sul vocabolario personale

Prima misura del 27 settembre 2026. Usiamo `vocabulary.txt` come elenco di input
non etichettati, senza caricarlo nelle parole protette o nella memoria personale.
Il confronto ignora anche `~/.config/autocorrect/protected.txt`; mantiene solo
il glossario tecnico di 80 voci distribuito con il core, identico nei due motori.

## Risultati iniziali

| Insieme | Input | Proposte baseline | Proposte con Hunspell |
|---|---:|---:|---:|
| Voci originali, con maiuscole e struttura originali | 5.816 | 32 | 23 |
| Forme alfabetiche normalizzate, anche con apostrofo | 4.776 | 40 | 31 |
| Di queste, assenti dalle 100.000 frequenze | 1.338 | 40 | 31 |

La normalizzazione rimuove distinzioni di maiuscole e unifica apostrofi e NFC.
Questo è uno stress test distinto dalla valutazione dell'input originale:
le maiuscole sono già una protezione nella baseline.

Fra le 1.338 forme sconosciute:

- Hunspell riconosce 255 forme; la baseline ne modificherebbe 9, il filtro zero.
- Hunspell non riconosce 1.083 forme; entrambi i motori ne modificherebbero 31.
- 11 forme sono già nel glossario tecnico del progetto.

Questi sono **conteggi di sostituzioni proposte, non falsi positivi verificati**.
Il vocabolario appreso può contenere typo; l'accettazione di Hunspell non è una
revisione indipendente. La prima esecuzione ha zero etichette manuali, quindi
i campi relativi ai falsi positivi verificati sono `null`.

## Ripetere e revisionare

```sh
.venv/bin/python -m autocorrect_core.vocabulary_audit vocabulary.txt \
  --output-dir benchmark-results/swiftkey-vocabulary-review
```

La cartella deve essere nuova. La prima esecuzione ha prodotto, in quella cartella:

- `summary.json`: conteggi aggregati, configurazione e checksum.
- `review.json`: tutte le 1.338 forme sconosciute, con le varianti originali,
  riconoscimento Hunspell, decisioni dei due motori e candidati.
- `changes.json`: i 40 casi in cui la baseline propone una modifica, per iniziare
  la revisione dai casi più urgenti.
- `approved-protected.txt`: solo le voci etichettate `valid`; inizialmente contiene
  soltanto un commento, senza voci approvate.

I file restano locali nella cartella ignorata da Git. Lo strumento crea la
cartella con permessi `0700` e i file con `0600`; lo stdout mostra solo aggregati.

Modificare il campo `label` in una copia di `review.json` o `changes.json`:

- `valid`: forma corretta da conservare nell'uso dell'utente.
- `typo`: errore appreso, da non proteggere.
- `uncertain`: decisione rimandata, per esempio un nome non riconosciuto.
- `unreviewed`: non ancora esaminata.

Si può fornire anche una revisione parziale. Per ricalcolare, scegliere un'altra
cartella, così da conservare i file annotati:

```sh
.venv/bin/python -m autocorrect_core.vocabulary_audit vocabulary.txt \
  --labels benchmark-results/swiftkey-vocabulary-review/changes.json \
  --output-dir benchmark-results/swiftkey-vocabulary-reviewed
```

Lo strumento conta le alterazioni indesiderate solo fra le voci `valid` e genera
una lista protetta proposta nello stesso output. Le etichette non modificano
la politica dei motori durante la misura. Nessuna lista viene installata nella
configurazione utente. Una revisione limitata ai casi modificati stima il danno
in quei casi, non una frequenza rappresentativa di tutta la digitazione.

## Riproducibilità

I report includono SHA-256 del vocabolario, del dizionario di frequenze, dei
file Hunspell, del glossario tecnico e dell'eventuale file di etichette. Il
vocabolario analizzato ha SHA-256:
`a73ad53a81fbaaae10fb44bc7432c6edb9d0208deae848cfc6c743ed74b049b4`.

Politica e versioni dei dizionari coincidono con il primo esperimento in
[HUNSPELL.md](HUNSPELL.md). I test del nuovo strumento usano voci sintetiche,
senza incorporare parole personali nel repository.
