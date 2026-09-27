# Prototipo standalone

## Componenti

```text
argomenti CLI / una parola per riga
             ↓
      autocorrect_core
      ├─ protezioni e normalizzazione
      ├─ validazione Hunspell opzionale
      ├─ candidati SymSpell
      └─ politica di astensione
             ↓
  Decision(original, output, reason, candidates, ...)
```

Il package non legge tastiere, clipboard o applicazioni. Non importa Fcitx e
non contiene servizi in background. L'accesso alla rete è limitato al comando
esplicito di acquisizione del dizionario.

- `engine.py`: API e politica conservativa.
- `hunspell.py`: validatore opzionale attraverso l'API C di Hunspell, caricato
  una volta e usato per riconoscere parole, senza generare candidati.
- `dictionary.py`: fonte fissata, checksum e download atomico.
- `cli.py`: interfaccia testuale/JSONL e caricamento delle parole protette.
- `benchmark.py`: metriche di qualità, latenza a motore caldo e costo di avvio.
- `generate_typos.py`: campionamento stratificato, mutazioni QWERTY e split
  deterministici per parola; opera sul lessico senza interrogare il correttore.
- `protected.txt`: glossario tecnico esplicito, caricato come risorsa del package.
- `prediction.py`: suggerimenti contestuali espliciti, n-grammi e completamenti.
- `personal.py`: conteggi personali in SQLite, aggiornati alla conferma della frase.
- `interactive.py`: editor terminale con tre suggerimenti tramite prompt_toolkit.
- `probe_server.py`: processo persistente del core per la prova Fcitx, raggiungibile
  solo tramite socket Unix locale. Applica la politica del core, senza apprendimento.
- `swiftkey_inspect.py`: lettura strutturale dei modelli Fluency; produce statistiche,
  senza decodificare il vocabolario o importare i modelli nella memoria personale.

Il port scelto è `symspellpy==6.10.0` (Python, MIT), con distanza Damerau OSA.
OSA include trasposizioni adiacenti, ma non è la distanza Damerau-Levenshtein
senza restrizioni. Non usiamo `lookup_compound` nel percorso automatico.

## Politica iniziale

Prima della ricerca vengono preservati contesti disabilitati, token troppo
lunghi, parole protette, voci già nel dizionario, token con apostrofo, stringhe
strutturate/non latine e possibili elisioni.

Il controllo delle possibili elisioni cerca un prefisso tra `l`, `dell`, `all`,
`dall`, `nell`, `sull`, `coll`, `un`, `quest`, `quell`, seguito da una parola
nota che inizia con vocale. È una protezione euristica, non un'analisi grammaticale.

Per le altre parole chiediamo **tutti** i candidati entro distanza 2 e usiamo:

```text
score = log10(frequenza + 1) − 2 × distanza
```

L'ordinamento è per score decrescente, poi distanza e ordine lessicografico.
La formula può preferire una parola molto frequente a distanza 2 a una rara
a distanza 1: se succede, la politica predefinita si astiene.

La sostituzione automatica richiede tutte le seguenti condizioni:

- input interamente minuscolo;
- candidato non protetto;
- input di almeno 5 caratteri;
- candidato a distanza massima 1;
- frequenza del candidato almeno 100.000;
- vantaggio sul secondo score almeno 1,3, oppure assenza di un secondo candidato.

Anche un candidato unico deve rispettare tutti gli altri requisiti. Il margine
viene calcolato **prima** di limitare il numero di candidati mostrati nella CLI.
Le parole protette presenti nel dizionario restano tra i concorrenti, così
non aumentiamo artificialmente il margine degli altri candidati.

Questi sono parametri iniziali espliciti, non una confidence calibrata.
La frequenza minima è specifica della scala del corpus usato: con un dizionario
diverso va valutata nuovamente. `confidence` nel JSON è sempre `null`.

## Contratto API

```python
from pathlib import Path
from autocorrect_core import AutocorrectEngine

engine = AutocorrectEngine(Path("dizionario.txt"), protected_words={"nomeproprio"})
decision = engine.evaluate("quesot", context="text")
print(decision.output)
```

`context` è uno tra `text`, `terminal`, `password`, `url`, `email`, `code`.
È fornito dal chiamante. La CLI **non rileva** automaticamente il campo di input
né la lingua. Il futuro adapter Fcitx dovrà fornire indicazioni affidabili.

L'oggetto engine si carica una volta e si riutilizza. Le decisioni conservano
l'input originale in caso di astensione, senza ripulire spazi, accenti o maiuscole.
La CLI è orientata ai token: una frase passata come argomento resta invariata;
non viene spezzata per evitare correzioni all'interno di URL o codice.

### Validazione lessicale opzionale

```python
from autocorrect_core.hunspell import HunspellValidator

with HunspellValidator(Path("/usr/share/hunspell/it_IT")) as validator:
    engine = AutocorrectEngine(Path("dizionario.txt"), word_validator=validator)
    decision = engine.evaluate("compilaste")
```

Il core accetta un `WordValidator` con metodo `spell(word)` e metadati
`metadata`. Passa al validatore il token normalizzato, dopo aver controllato
contesto, lunghezza, glossario, voci note, apostrofi e struttura del token.
Se il validatore riconosce la parola, il core restituisce l'input originale con
`action: keep`, `reason: valid_word` e nessun candidato. Altrimenti prosegue
con le protezioni delle elisioni e la politica SymSpell.

Le parole Hunspell non diventano destinazioni di correzione. Il chiamante API
gestisce la durata del validatore; `close()` e il context manager liberano
l'istanza nativa. Un finalizzatore libera anche le istanze abbandonate dalla CLI.
Il validatore richiede uso da un singolo thread e rispetta l'encoding del
dizionario. Non accede al testo dei contesti disabilitati.

La CLI abilita il filtro con `--hunspell` o `--hunspell-dictionary PREFISSO`.
Il benchmark registra `word_validator` (oppure `null` per la baseline), inclusi
percorsi e checksum dei file, e `by_lexicon_membership` per distinguere gli input
presenti o assenti dalla lista di frequenze. Per i casi `valid_word`, le metriche
dei candidati misurano il percorso completo, che ora può saltare la ricerca:
un calo del recall dei candidati non indica un cambiamento di SymSpell.

## Passi successivi

È disponibile anche la [CLI contestuale](PREDICTION.md), con una base demo e
apprendimento locale. Questa interfaccia usa il contesto per ordinare suggerimenti
che l'utente sceglie; il percorso `AutocorrectEngine.evaluate()` continua ad
applicare la politica di astensione sui singoli token. I confronti di qualità
precedenti misurano quel percorso, non la predizione contestuale.

Il generatore automatico e il benchmark esteso sono ora disponibili. Il primo
set separato di valutazione mostra 12 sostituzioni sbagliate su 680 applicate:
vedere [BENCHMARK_GENERATED.md](BENCHMARK_GENERATED.md). Le priorità diventano:

- Corpus di valutazione indipendente e analisi delle parole sconosciute valide.
- Estensione del [primo confronto Hunspell](HUNSPELL.md) con parole valide
  sconosciute vicine a termini comuni e campioni di digitazione reale.
- Vocabolario verificato per elisioni e apostrofi, prima di abilitarne la correzione.
- Modello di errore per tastiera fisica e contesto precedente, se i dati lo giustificano.
- Misure di memoria/avvio e confronto con implementazione nativa prima di
  incorporare il motore in Fcitx. Il prototipo Python è una base di misura.
- Adapter Fcitx, annullamento con Backspace e prove sulle applicazioni reali.

I suggerimenti non costituiscono un'autorizzazione a modificare testo: l'adapter
deve rispettare `action` e gestire separatamente la transazione di sostituzione.
