# Dataset italiano iniziale

`it_smoke.json` contiene 147 casi scritti manualmente per il prototipo:

- 76 casi con una correzione attesa;
- 71 casi da preservare, inclusi cinque contesti esplicitamente disabilitati.

Gli esempi iniziali `quesot`, `proggeto`, `domnai`, `qaundo`, `interesasnte`
provengono dal piano del progetto. Gli esempi di elisione e di conservazione
di espressioni sono motivati dal documento di Massimiliano Polito condiviso
dall'utente (*Riconoscimento ortografico dell'apostrofo e delle espressioni
polirematiche*, pp. 8–10). Il resto sono casi manuali di sviluppo.

Ogni elemento ha `input`, `expected`, `category` ed eventualmente `context`.
`input != expected` significa che il benchmark misura il recupero della forma
attesa; non significa che ogni alternativa sia linguisticamente impossibile.
Per esempio il dizionario accetta `sopratutto`, mentre qui viene richiesta la
forma comune `soprattutto`: il motore conserva la voce nota.

Sono presenti casi volutamente fuori dal comportamento automatico iniziale:
due modifiche, elisioni, parole con maiuscola e correzioni tra parole.
Un'astensione su questi casi riduce la copertura e non viene contata come
correzione sbagliata. `quesot!` è invece un test di conservazione: l'API riceve
un singolo token, non estrae parole dalla punteggiatura.

Questo è uno **smoke test di sviluppo**, non un corpus indipendente o casuale
di digitazione reale. Il glossario tecnico è noto e gli esempi di inglese non
dimostrano supporto multilingua. Non si devono dedurre precisioni d'uso reale
dalla sola assenza di errori su questi esempi.

Prima dell'integrazione automatica serviranno un insieme di taratura e uno
di valutazione separati, con parole rare, nomi, forme flesse, prestiti, errori
ambigui e proporzioni più realistiche tra testo corretto e typo.

## Dataset sintetici generati

È disponibile `autocorrect-generate-typos`, che produce automaticamente
`development.json`, `evaluation.json` e un manifest riproducibile sotto
`benchmark-data/` (ignorata da Git). La prima esecuzione contiene 8.000 typo e
6.000 parole intatte e usa questo smoke test come elenco di esclusione.

Il nuovo formato è un oggetto con `metadata` (incluso `format_version: 1`) e
`cases`. Ogni caso conserva anche parola sorgente, frequenza e fascia di
lunghezza, per poter interpretare i risultati senza ricostruire a mano i typo.
Il benchmark continua ad accettare anche il formato a lista di questo smoke test.

Vedere [il generatore](../docs/TYPO_GENERATOR.md) e
[i risultati estesi](../docs/BENCHMARK_GENERATED.md). I negativi sintetici sono
parole già presenti nel dizionario; il campione seguente aggiunge una prima
prova sulle parole valide sconosciute.

## Parole valide per il confronto Hunspell

`it_valid_words_development.json` contiene 64 casi manuali di sviluppo:
forme flesse, verbi con pronomi, nomi/aggettivi, termini tecnici e prestiti.
Abbiamo fissato l'elenco prima di osservare le decisioni dei due motori e
conservato tutti i casi, inclusi quelli già nella lista di frequenze e quelli
che Hunspell non riconosce. La validità attesa è un'etichetta manuale per
l'uso indicato; l'accettazione di Hunspell non definisce la correttezza linguistica.

Con la revisione fissata del dizionario SymSpell, 56 input sono sconosciuti e
8 sono già presenti. Il benchmark li separa in `by_lexicon_membership`.
Tre degli sconosciuti appartengono al glossario protetto del progetto.
Entrambe le versioni conservano 64/64 input; con il filtro, 40 casi ricevono
il motivo `valid_word`. Molte forme sono lunghe e già poco esposte a sostituzioni:
occorrono anche esempi validi più vicini a parole comuni.

Tutti i casi richiedono conservazione: da questo file non si possono stimare
precisione delle correzioni o copertura dei typo. Non è un campione indipendente
di valutazione. Risultati e comandi: [HUNSPELL.md](../docs/HUNSPELL.md).
