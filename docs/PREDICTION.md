# CLI contestuale interattiva

## Avvio e tasti

```sh
./autocorrect --interactive
```

Il motore carica la lista di frequenze, poi apre una riga modificabile e tre
suggerimenti. Puoi muovere il cursore e modificare la frase. La CLI ricalcola
i suggerimenti usando il testo a sinistra del cursore.

| Tasto o comando | Azione |
|---|---|
| Tab oppure F1 | Sceglie il primo suggerimento |
| F2 / F3 | Sceglie il secondo / terzo |
| Alt+1 / Alt+2 / Alt+3 | Scorciatoie alternative |
| Invio | Conferma la riga, apprende le frasi e apre una nuova riga |
| Ctrl+Z | Annulla una modifica alla riga corrente |
| Ctrl+C | Scarta la riga corrente senza apprenderla |
| Ctrl+D su riga vuota, `/exit` | Esce |
| `/help` | Mostra i tasti |
| `/stats` | Mostra il numero di frasi apprese e il percorso della memoria |
| `/new` | Apre una riga vuota senza apprendere il comando |

L'editor propone completamenti durante la parola e parole successive dopo lo
spazio. Il punto `.` è una proposta di fine frase. Per applicare una correzione
devi sceglierla: premere spazio non sostituisce il testo in questo laboratorio.
Ctrl+Z opera sulla riga corrente; non annulla una frase già confermata con Invio.

## Una prima prova

1. Scrivi `ci vediamo `, con lo spazio finale.
2. Seleziona `domani`, poi una continuazione fra quelle disponibili, ad esempio
   `mattina`, oppure il punto per terminare la frase.
3. Premi Invio per confermare.

Per provare la personalizzazione, scrivi una continuazione tua, ad esempio
`ci vediamo venerdì pomeriggio`, e confermala. Digita ancora `ci vediamo `:
il modello personale può ora favorire `venerdì`. Ripetere una frase aumenta
il suo conteggio. I suggerimenti visualizzati o scelti non aggiornano il modello
finché non confermi la riga.

La base demo comprende anche `ho comprato il caglio` e `ho parlato con carlo`.
Con `ho comprato il caglo` il contesto favorisce `caglio`, mentre il core isolato
preferisce `carlo`. È un esempio costruito per verificare il percorso del codice,
non una misura indipendente di qualità.

## Dati e memoria

`src/autocorrect_core/context_demo.txt` contiene 91 frasi originali brevi.
Servono a provare l'interazione al primo avvio. Per una base più ampia puoi
fornire uno o più file UTF-8, con una frase per riga:

```sh
./autocorrect --interactive --corpus /percorso/frasi.txt
./autocorrect --interactive --corpus /percorso/frasi.txt --corpus /percorso/altre.txt
```

I file sostituiscono la base demo; le righe che iniziano con `#` sono commenti.
La CLI carica il corpus come base della sessione senza importarlo nella memoria
personale. Un corpus grande richiederà più tempo e memoria; questa versione
costruisce i conteggi in RAM.

Percorso predefinito della memoria:

```text
$XDG_DATA_HOME/autocorrect/personal-ngrams.sqlite3
```

In assenza di `XDG_DATA_HOME`: `~/.local/share/autocorrect/personal-ngrams.sqlite3`.
Puoi scegliere un file diverso o avviare una sessione senza memoria:

```sh
./autocorrect --interactive --memory /percorso/prova.sqlite3
./autocorrect --interactive --no-learn
```

`--no-learn` non legge né scrive la memoria. I file SQLite nuovi hanno permessi
`0600`. Il database conserva conteggi di token e contesti e il numero di frasi,
senza una tabella delle righe complete; anche questi conteggi contengono dati
personali. La cronologia dell'editor resta nella RAM della sessione.

## Modello e ordinamento

Il modello contiene unigrammi, bigrammi e trigrammi, con marcatori di inizio e
fine frase. Normalizza Unicode NFC, maiuscole e apostrofi tipografici. Per un
termine, interpola il bigramma con l'unigramma (peso locale 0,85), poi il
trigramma con il risultato (peso locale 0,9), quando il contesto esiste.

Il ranking combina:

- Modello base: 98% n-grammi e 2% frequenza del dizionario per il ripiego.
- Modello personale: peso 0,7 quando conosce il contesto; altrimenti 0,15
  quando contiene dati, oppure zero se vuoto.
- Penalità di 1,8 per modifica sulle proposte di correzione, sottratta al
  logaritmo del punteggio combinato.

Questi sono coefficienti iniziali scelti per il prototipo, non tarati su un
corpus indipendente. Il punteggio non è una probabilità calibrata di correzione.
Il generatore usa al massimo 32 termini per sorgente/contesto e 32 candidati
SymSpell prima dell'ordinamento finale dei tre suggerimenti.

La CLI indica `personale`, `demo`/`corpus` o `frequenza` in base al contributo
prevalente. L'indicazione unigramma/bigramma/trigramma descrive la presenza del
termine nel modello, non una garanzia sull'affidabilità della proposta.

## Limiti della prima versione

- Il contesto massimo è di due parole precedenti. Non c'è comprensione semantica
  della frase né accesso alle parole future.
- Il tokenizer è orientato a prosa con spazi; numeri, URL e stringhe strutturate
  interrompono le sequenze. Le abbreviazioni e la punteggiatura complessa
  richiedono lavoro ulteriore.
- La CLI non propone sostituzioni nel mezzo di una parola o su una selezione.
  Accetta righe fino a 16.384 caratteri per suggerimenti e apprendimento.
- Il dizionario Hunspell opzionale continua a proteggere l'input nel percorso
  ortografico (`--interactive --hunspell`); non è un modello contestuale.
- La memoria impara il testo che confermi, inclusi eventuali typo rimasti.
- Il prototipo non applica automaticamente il ranking contestuale alle
  decisioni del core. Serve una valutazione su frasi nuove prima di farlo.

L'esportazione SwiftKey ricevuta contiene un modello personale, ma l'ispettore
attuale legge solo la struttura numerica. Non alimenta questa CLI:
[analisi dell'esportazione](SWIFTKEY.md).

## Verifica

I test coprono il cambio di ranking con il contesto, la scelta e l'annullamento,
il cursore, i confini di frase, l'apprendimento su conferma, la persistenza e il
rollback delle transazioni fallite. Una sessione su pseudo-terminale ha verificato
anche l'avvio di `./autocorrect --interactive --no-learn`, la resa dei tre
suggerimenti, Tab, Invio e `/exit`.
