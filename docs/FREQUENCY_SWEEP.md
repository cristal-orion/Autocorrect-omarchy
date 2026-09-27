# Soglia di frequenza: sweep sullo sviluppo

27 settembre 2026. Il caso reale `maglioner` propone `maglione` a distanza 1,
con frequenza 44.882 e margine 2,159. Il filtro `min_frequency=100000` impedisce
la correzione anche abbassando il margine della finestra.

Abbiamo confrontato frequenze minime **100.000, 20.000, 5.000 e 1.000**, con
**margine fisso 1,3**. Hunspell è obbligatorio per questa prova. Il motore conserva
le forme riconosciute, applica tutte le altre regole e valuta di nuovo anche
il margine dopo aver superato il filtro di frequenza.

## Riproduzione

```sh
.venv/bin/python -m autocorrect_core.policy_sweep \
  benchmark-data/it-seed42/development.json \
  --frequencies 100000 20000 5000 1000 --margin 1.3 \
  --extra-keep-dataset data/it_valid_package_names_development.json \
  --probe maglioner \
  --output benchmark-results/frequency-sweep-development.json
```

Il runner usa il glossario tecnico del progetto, senza lista personale o memoria
appresa. Riporta separatamente dati sintetici, parole valide e nomi di pacchetti.
Registra i checksum di input, dizionari, glossario e sorgenti. Rifiuta dataset
che dichiarano `split=evaluation`, per evitare di usarli nella scelta delle soglie.

## Risultati

6.352 typo sintetici e 4.794 parole da conservare, stessi casi dello sviluppo
precedente. Gli errori indicano divergenze dalla sorgente del generatore.

| Frequenza minima | Giuste | Sbagliate | Precisione | Copertura typo | Giuste aggiuntive / errori aggiuntivi |
|---|---:|---:|---:|---:|---:|
| 100.000 | 2.670 | 37 | 98,63% | 42,03% | 0 / 0 |
| 20.000 | 2.969 | 37 | 98,77% | 46,74% | 299 / 0 |
| 5.000 | 3.430 | 37 | 98,93% | 54,00% | 760 / 0 |
| 1.000 | 3.523 | 37 | 98,96% | 55,46% | 853 / 0 |

Le 4.794 parole note restano intatte. `maglioner` diventa `maglione` già a 20.000.
Tutte le nuove sostituzioni riguardano input alfabetici assenti dal lessico di
frequenze e rifiutati da Hunspell. Il runner verifica questa condizione per ogni
decisione diversa dalla baseline.

La curva è più favorevole di quella del margine: a 5.000 recuperiamo 11,96 punti
percentuali di copertura senza aggiungere errori in questo set. I 37 errori
preesistenti rimangono. Il risultato sostiene una frequenza minima più bassa
come candidata per la prova manuale; non dimostra che 1.000 sia una soglia
ottimale o che le nuove correzioni siano prive di rischi in testo naturale.

## Parole valide non riconosciute

L'assenza da due dizionari non rende un token un errore certo.

Nel campione preesistente di 64 parole valide:

- 8 compaiono nel lessico di frequenze;
- 40 le riconosce solo Hunspell;
- 16 risultano sconosciute a entrambi, comprese 3 protette dal glossario.

Tutte restano intatte alle quattro soglie. Questo controllo è poco sensibile
alla modifica: nella baseline nessuno dei 64 casi si asteneva per `low_frequency`.
Per gli sconosciuti operavano distanza, assenza di candidati o glossario.

Abbiamo quindi fissato, prima di consultarne le decisioni, altri **24 nomi reali
di pacchetti Python** usabili in una frase italiana, in minuscolo e senza
aggiungerli alle protezioni. Dei 24 nomi, Hunspell ne riconosce uno e 23 sono
sconosciuti a entrambi i lessici. Risultato: **23/24 conservati a tutte le soglie**.

L'errore è `manim → mani`, già presente a 100.000, con margine 1,395. `manim` è
un nome valido di progetto, benché i due dizionari lo rifiutino. Abbassare la
frequenza non introduce altri errori in questo campione; il caso conferma il
bisogno di valutare nomi e termini tecnici anche quando si lavora sulle non-parole.

I campioni sono piccoli, costruiti e di sviluppo. Prima di promuovere una
politica occorrono casi nuovi, in particolare parole valide vicine a destinazioni
fra 1.000 e 100.000 che supererebbero anche il margine. Il report mantiene gli
insiemi distinti: non somma questi controlli a un'unica percentuale di precisione.

## Relazione con gli altri interventi

Lo sweep varia solo la frequenza; non modifica il ranking degli errori. Per
`maglioner` il candidato corretto era già nettamente primo. Il modello QWERTY
potrà aiutare altre ambiguità, ma qui è sufficiente superare il filtro di frequenza.

La regressione fra codice AOSP e log-frequenza potrebbe produrre pseudo-frequenze.
Andrà valutata su parole condivise escluse dal fit, con residui per fascia e tipo
di parola: i due lessici provengono da corpora diversi. Una stima non ricostruisce
i conteggi originali e non garantisce automaticamente soglie equivalenti.

Il modello degli errori Python rimane successivo alla prova LatinIME. I conteggi
del corpus italiano preparato a parte serviranno a confrontare il contesto con
entrambi i motori.
