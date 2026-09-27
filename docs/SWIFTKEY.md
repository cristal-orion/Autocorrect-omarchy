# Esportazione SwiftKey: struttura e possibilità di riuso

Analisi locale del 27 settembre 2026 di `com.touchtype.swiftkey.7z`.
L'archivio originale e la sua eventuale cartella estratta sono ignorati da Git.
L'analisi qui riportata contiene struttura e conteggi, senza vocabolario personale.

## Contenuto utile

| Percorso interno | Contenuto osservato | Possibile uso |
|---|---|---|
| `dynamic_model_debug/user/dynamic.lm` | Modello personale `DynamicNgramTermModel` | Vocabolario e sequenze personali, dopo decodifica |
| `dynamic_model_debug/userbackup/dynamic.lm` | Modello distinto con meno nodi | Confronto con il backup, evitando duplicazioni |
| `dynamic_model_debug/keyboard_delta/dynamic.lm` | Modello con tag `sync-model` | Studio della sincronizzazione; semantica del delta da chiarire |
| `dynamic_model_debug/user/learned.json` | Parametri adattivi e pesi dei modelli | Indicazioni sull'architettura, non un elenco di frasi |
| `key_press_model_debug/*.im` | 42 JSON con coordinate, precisioni e parametri dei tasti | Studio del modello di tocco; poco trasferibile alla tastiera fisica |
| `language_packs_debug/downloadedLanguagePacks.json` | Italiano `it_IT`, versione 338, abilitato | Identificazione della lingua configurata |

`languagePacks.json` è metadato dei pacchetti: l'archivio non contiene il modello
italiano generale `it_IT.lm` citato in `learned.json`. I log servono alla diagnostica;
non li abbiamo usati come corpus di apprendimento.

## Cosa abbiamo letto nel modello binario

L'intestazione contiene `Fluency language model file` e
`Dynamic language model created in DynamicNgramTermModel::write()`.
La struttura ha marcatori `flue`, `voca` e `dmap`.

Abbiamo verificato le dimensioni dei blocchi, la versione 7 del vocabolario,
la somma delle lunghezze delle voci e l'albero numerico `dmap`. Il numero di nodi
decodificati coincide con il contatore dichiarato nei tre file, e la lettura
raggiunge le chiusure previste dei blocchi e del file.

| Misura | user | userbackup | keyboard_delta |
|---|---:|---:|---:|
| Byte | 1.235.313 | 1.203.342 | 570.089 |
| Slot del vocabolario | 12.911 | 12.769 | 5.687 |
| Identificativi distinti al primo livello | 12.910 | 12.768 | 5.686 |
| Nodi a profondità 1 | 12.910 | 12.768 | 5.686 |
| Nodi a profondità 2 | 36.555 | 35.690 | 17.464 |
| Nodi a profondità 3 | 38.915 | 37.576 | 20.216 |
| Nodi a profondità 4 | 32.813 | 31.530 | 18.308 |
| Nodi totali | 121.193 | 117.564 | 61.674 |

La profondità è compatibile con sequenze fino a quattro identificativi.
Questi numeri non contano messaggi o frasi complete, né dimostrano che ciascuna
voce sia una parola italiana valida: possono esserci simboli e token speciali.
I campi numerici associati ai nodi non hanno ancora una semantica verificata
rispetto a frequenze, normalizzazioni o decadimento temporale.

## Ostacolo all'importazione

Il blocco del vocabolario contiene 89.449 byte di dati codificati nel modello
`user`. Abbiamo letto gli slot e le lunghezze, ma non i testi associati agli ID.
Non abbiamo quindi una mappa verificata `identificativo → parola`.

Possiamo percorrere l'albero numerico, ma non convertirlo in n-grammi testuali
affidabili per la CLI. Non basta estrarre sequenze di byte stampabili, e non
abbiamo stabilito se la codifica del vocabolario sia cifratura o un'altra forma
di rappresentazione. La CLI usa ancora la base demo o il corpus testuale fornito
con `--corpus`, più la propria memoria locale.

Il riferimento pubblico
[Samsung-User-Dictionary-Parser](https://github.com/nabbb/Samsung-User-Dictionary-Parser)
di Nabila Agni descrive la lettura di un trie `dynamic.lm`. Il suo programma
richiede anche una lista esterna di parole e ID esportata da UFED: non risolve
da solo il vocabolario di questo archivio. Il nostro ispettore aggiunge verifiche
di dimensioni e conteggi e non richiede né incorpora quei dati esterni.

## Ripetere l'ispezione

```sh
.venv/bin/python -m autocorrect_core.swiftkey_inspect com.touchtype.swiftkey.7z

# Oppure su un singolo file già estratto
.venv/bin/python -m autocorrect_core.swiftkey_inspect /percorso/user/dynamic.lm
```

Per l'archivio serve `bsdtar` (presente sulla macchina); per un file `.lm` basta
Python. L'ispettore legge i tre modelli dall'archivio senza estrarli nella cartella
del progetto e stampa solo metadati. Il report include
`vocabulary_decoded: false` e `ready_for_context_import: false`.

## Ricerca online: decoder e un'esportazione leggibile

Ricerca del 27 settembre 2026, concentrata su `dynamic.lm`, Fluency,
`DynamicNgramTermModel` e sul blocco `voca`. Nei progetti e nelle discussioni
consultati non abbiamo trovato un decoder pubblico completo del nostro
vocabolario versione 7. Questo esito non prova che un decoder non esista.

Fonti esaminate:

- [Samsung-User-Dictionary-Parser](https://github.com/nabbb/Samsung-User-Dictionary-Parser):
  il codice `create_word_list()` legge parole, ID e frequenze da un report UFED
  esterno; `parse_node()` legge il trie. La issue sul report di input rimanda
  ai file di esempio, senza aggiungere un decoder del vocabolario.
- [Swiftkey-Dictionary-Importer](https://github.com/SergiuMucea/Swiftkey-Dictionary-Importer/blob/main/main.py):
  legge un JSON già decodificato, campo `terms`, per trasferire parole a Gboard.
- [swiftkey-gboard-dictionaryConverter](https://github.com/tonyPooyappallil/swiftkey-gboard-dictionaryConverter/blob/main/src/App.jsx):
  apre `services/sync_words.json` da uno ZIP e usa il suo array `terms`.
  Il nostro archivio di supporto non contiene questo file.
- [Discussione XDA del 2013](https://xdaforums.com/t/q-editing-learnt-words-personalization-data.2302884/):
  domanda sullo stesso formato Fluency, senza una soluzione nella pagina consultata.

### Percorso attuale documentato da Microsoft

La guida ufficiale
[SwiftKey Backup and Sync with OneDrive](https://support.microsoft.com/en-us/swiftkey-keyboard/swiftkey-backup-and-sync-with-onedrive)
dichiara che, con Backup e sincronizzazione attivo, SwiftKey salva in
**OneDrive → Apps → SwiftKey**:

1. Il dizionario personale in un formato leggibile da una persona.
2. Il modello di digitazione in formato leggibile dal motore.

Abbiamo verificato che `https://data.swiftkey.com/` ora risponde con un redirect
alla guida OneDrive. La vecchia pagina di supporto del Data Portal è ancora
consultabile e descrive `Export all`, ma non rappresenta il percorso raggiunto
dal portale attuale. La nuova guida colloca il completamento della migrazione
al 31 maggio 2026.

La documentazione non specifica nome, schema, ordine delle voci, ID o presenza
di frequenze. L'utente ha poi fornito `vocabulary.txt`, analizzato qui sotto.

## Vocabolario leggibile ricevuto

`vocabulary.txt` contiene una voce per riga, preceduta da cinque righe di
intestazione. SwiftKey descrive il file come elenco delle parole apprese e
precisa che il motore usa una versione ottimizzata separata. Il file personale
è ignorato da Git; questi conteggi non ne riportano le voci.

| Misura | Conteggio |
|---|---:|
| Byte | 47.089 |
| Righe totali | 5.821 |
| Voci dopo l'intestazione, tutte distinte | 5.816 |
| Voci distinte dopo NFC, minuscole e normalizzazione apostrofi | 5.611 |
| Forme alfabetiche latine, anche con apostrofo, normalizzate | 4.776 |
| Di queste, presenti nella lista di frequenze | 3.438 |
| Di queste, assenti dalla lista di frequenze | 1.338 |

Le altre voci includono numeri, simboli e frammenti strutturati. Tre righe
contengono spazi: il file non è una raccolta di frasi in ordine di digitazione.
Non ci sono colonne con ID o frequenze esplicite. Le forme alfabetiche sono
candidati lessicali, non una lista verificata di parole corrette: un vocabolario
appreso può contenere anche typo.

Il conteggio non coincide con alcuno dei tre modelli già ricevuti: 12.910 ID
alla radice di `user`, 12.768 in `userbackup`, 5.686 in `keyboard_delta`.
Non si può quindi associare il numero di riga all'ID. Possibili differenze tra
istantanee o filtri di esportazione richiedono verifica, non assunzioni.

Il file può contribuire a un glossario personale e a completamenti lessicali,
ma non fornisce frequenze o transizioni fra parole per inizializzare il modello
contestuale. L'opzione esistente `--protected-words` legge questo formato come
lista di protezione; non lo importa nella memoria a n-grammi e può proteggere
anche typo presenti nell'elenco. Non usare `--corpus` per simulare contesti:
tratterebbe le singole voci come frasi separate, inventando inizi e fini frase.

## Modello OneDrive ricevuto con il vocabolario

L'utente ha fornito anche `dynamic.lm` nella root. Il file è ignorato da Git,
insieme all'eventuale cartella `swiftkey-onedrive/`.

SHA-256: `509c6f8c0d9263a8fa266dab1cb51311bc9d8db312b9f181669207b1cefcba8a`.

| Misura | OneDrive | Supporto: user | Supporto: keyboard_delta |
|---|---:|---:|---:|
| Byte | 587.185 | 1.235.313 | 570.089 |
| Identificativi al primo livello | 5.823 | 12.910 | 5.686 |
| Nodi totali | 63.597 | 121.193 | 61.674 |
| Profondità massima | 4 | 4 | 4 |

Il file OneDrive supera tutte le verifiche dell'ispettore: dimensione dichiarata,
versione 7 del vocabolario, somma delle lunghezze, numero di nodi e chiusure dei
blocchi. La dimensione inferiore corrisponde a un modello con meno voci e nodi;
non osserviamo un troncamento. Il file è più vicino per dimensioni e conteggi al
`keyboard_delta` del dump, ma questo non prova che derivi da quel file. Non abbiamo
ancora stabilito le regole di selezione o riduzione usate nella sincronizzazione.

Nodi OneDrive per profondità: 5.823, 17.980, 20.872, 18.922.

### Corrispondenza con vocabulary.txt

Il nuovo binario contiene 5.824 slot, incluso lo slot vuoto iniziale, e 5.823
identificativi al primo livello. Il testo contiene 5.816 voci. Abbiamo confrontato
le lunghezze in **byte UTF-8**, mantenendo maiuscole e grafia originali:

- Le voci testuali occupano 40.787 byte senza intestazione e separatori di riga.
- Il blocco codificato del binario occupa 40.831 byte.
- L'istogramma delle lunghezze testuali è contenuto per intero in quello binario.
- Rimangono sette voci binarie: lunghezze `1, 1, 4, 5, 6, 13, 14`, per 44 byte.

È un indizio di corrispondenza fra le due esportazioni. Le sette voci aggiuntive
potrebbero essere token interni o differenze dell'istantanea, ma non ne abbiamo
verificato il contenuto. L'istogramma non identifica le singole parole: molte
voci condividono la stessa lunghezza. La corrispondenza in ordine fra le lunghezze
delle righe e quelle degli slot è scarsa (588 posizioni su 5.816 confrontate),
quindi non giustifica l'associazione `riga → ID`.

Il vocabolario rimane codificato. Un sondaggio delle coincidenze tra byte nel
blocco, per distanze da 1 a 1.024, non ha indicato una semplice maschera XOR
ciclica corta; questo test non identifica l'algoritmo e non dimostra cifratura.

Per verificare il nuovo modello con l'ispettore esistente:

```sh
.venv/bin/python -m autocorrect_core.swiftkey_inspect dynamic.lm
```

## Prossimo passo utile

Il modello personale è un candidato concreto per inizializzare la memoria
contestuale. Prima occorre decodificare il vocabolario e verificare orientamento
delle sequenze, token speciali e significato dei conteggi. Un'eventuale ulteriore
esportazione testuale di parole e ID aiuterebbe; un semplice elenco di parole
senza ID potrebbe servire come glossario, ma non ricostruirebbe da solo i contesti.
La coppia OneDrive ora disponibile fornisce un insieme di possibili testi per
studiare la codifica del vocabolario e verificare un eventuale decoder. Le
lunghezze compatibili restringono il problema, ma occorre ancora ottenere una
mappa verificata degli ID prima di importare le sequenze nella CLI.
