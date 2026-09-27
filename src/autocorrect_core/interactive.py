"""Editable terminal sandbox: explicit suggestions and learning on Enter."""

from importlib.resources import files
from pathlib import Path
import sys

from .personal import PersonalMemory, default_memory
from .prediction import ContextPredictor, NgramModel, apply_suggestion


HELP = """Scrivi liberamente: i tre suggerimenti si aggiornano con la frase.
  Tab / F1       scegli il primo suggerimento
  F2 / F3        scegli il secondo / terzo (anche Alt+1/2/3)
  Invio          conferma la frase e apprendi, poi inizia una nuova frase
  Ctrl+Z         annulla una modifica alla riga corrente
  Ctrl+C         scarta la riga corrente, senza apprenderla
  Ctrl+D         esci quando la riga è vuota
  /help          mostra questa guida
  /stats         mostra i conteggi della memoria
  /new           nuova riga senza apprendere il comando
  /exit          esci
Le correzioni sono suggerimenti: scegli tu se applicarle.
La memoria locale apprende solo le righe confermate con Invio.
"""


def load_base(corpus_paths: list[Path]) -> tuple[NgramModel, str, int]:
    model = NgramModel()
    count = 0
    if corpus_paths:
        for path in corpus_paths:
            with path.open(encoding="utf-8-sig") as source:
                for line in source:
                    if not line.lstrip().startswith("#"):
                        count += model.learn(line)
        label = "corpus"
    else:
        for line in files("autocorrect_core").joinpath("context_demo.txt").read_text(encoding="utf-8").splitlines():
            if not line.startswith("#"):
                count += model.learn(line)
        label = "demo"
    if not count:
        raise ValueError("Il corpus non contiene frasi utilizzabili.")
    return model, label, count


def run_session(predictor: ContextPredictor, memory: PersonalMemory | None, *, input=None, output=None):
    # Lazy imports: the token CLI and core do not need a terminal interface.
    from prompt_toolkit import PromptSession
    from prompt_toolkit.document import Document
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style

    bindings = KeyBindings()
    session = None

    def suggestions():
        buffer = session.default_buffer
        if buffer.selection_state or buffer.text.startswith("/"):
            return None
        return predictor.suggest(buffer.text, buffer.cursor_position)

    def choose(event, index):
        current = suggestions()
        if current is None or index >= len(current.items):
            event.app.output.bell()
            return
        buffer = event.current_buffer
        text, cursor = apply_suggestion(buffer.text, current, index)
        buffer.save_to_undo_stack()
        buffer.document = Document(text, cursor)

    for index in range(3):
        def select(event, index=index):
            choose(event, index)
        bindings.add(f"f{index + 1}")(select)
        bindings.add("escape", str(index + 1))(select)

    @bindings.add("tab")
    def select_first(event):
        choose(event, 0)

    @bindings.add("c-z")
    def undo(event):
        event.current_buffer.undo()

    def toolbar():
        current = suggestions()
        fragments = []
        if current and current.items:
            for index, item in enumerate(current.items, 1):
                order = {0: "", 1: " · unigramma", 2: " · bigramma", 3: " · trigramma"}[item.order]
                fragments.extend([
                    ("class:key", ("\n" if index > 1 else "") + f" F{index} "),
                    ("class:word", f"{item.word} "),
                    ("class:detail", f"({item.kind}; {item.source}{order})"),
                ])
        else:
            fragments.append(("class:detail", " Nessun suggerimento in questa posizione."))
        mode = f"memoria: {memory.sentence_count} frasi" if memory else "memoria disattivata"
        fragments.append(("class:detail", f"\n Tab/F1–F3 scegli · Invio conferma · Ctrl+Z annulla · /help · {mode}"))
        return fragments

    session = PromptSession(
        "> ", key_bindings=bindings, bottom_toolbar=toolbar,
        history=InMemoryHistory(), enable_history_search=False,
        complete_while_typing=False, input=input, output=output,
        style=Style.from_dict({"key": "bold ansicyan", "word": "bold",
                              "detail": "ansibrightblack"}),
    )
    while True:
        try:
            text = session.prompt()
        except KeyboardInterrupt:
            print("Riga scartata.")
            continue
        except EOFError:
            print("A presto.")
            return 0
        command = text.strip()
        if not command:
            continue
        if command in ("/exit", "/quit"):
            print("A presto.")
            return 0
        if command == "/help":
            print(HELP)
        elif command == "/stats":
            if memory:
                print(f"Memoria: {memory.sentence_count} frasi; {len(memory.model.rows.get((), {}))} token (inclusa fine frase).")
                print(f"File: {memory.path}")
            else:
                print("Memoria personale disattivata per questa sessione.")
        elif command == "/new":
            continue
        elif command.startswith("/"):
            print("Comando sconosciuto. Usa /help.")
        elif len(text) > 16_384:
            print("Riga troppo lunga: massimo 16.384 caratteri; nessun apprendimento.")
        elif memory:
            count = memory.learn(text)
            print(f"Confermata. Apprese {count} frasi; totale {memory.sentence_count}.")
        else:
            print("Confermata; memoria disattivata.")


def run(engine, *, corpus_paths=(), memory_path=None, learn=True, aosp_wordlist=None) -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError("--interactive richiede un terminale. Per JSONL usa --stdin --json.")
    if aosp_wordlist is not None:
        if corpus_paths:
            raise ValueError("Scegli corpus oppure wordlist AOSP.")
        from .aosp_data import load_wordlist
        data = load_wordlist(aosp_wordlist)
        base, label = data.model(), "aosp-pesi"
        description = f"{len(data.scores)} voci, {len(data.bigrams)} bigrammi. Pesi euristici, non conteggi di corpus."
    else:
        base, label, count = load_base(list(corpus_paths))
        description = f"{count} frasi. " + ("Piccolo campione dimostrativo, non italiano generale." if label == "demo" else "Corpus fornito dall'utente.")
    memory = PersonalMemory(memory_path or default_memory()) if learn else None
    try:
        predictor = ContextPredictor(engine, base, memory.model if memory else None, base_label=label)
        print("Autocorrect · laboratorio contestuale offline")
        print(f"Base: {label}, {description}")
        print(f"Memoria personale: {memory.path}" if memory else "Memoria personale disattivata: nessuna lettura o scrittura.")
        print("Prova: ci vediamo [spazio], poi Tab. Oppure scrivi una frase tua.")
        print(HELP)
        return run_session(predictor, memory)
    finally:
        if memory:
            memory.close()
