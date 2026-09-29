#include "engine_client.h"
#include <cassert>

int main() {
    for (const char *accepted : {"questo", "l'acqua", "per piacere", "va bene,", "c'è", "perché"}) {
        assert(safeProbeOutput(accepted));
    }
    for (const char *refused : {"", " per", "per ", "non lo so", "per  piacere", "per\tpiacere", "per\npiacere", "a\rb"}) {
        assert(!safeProbeOutput(refused));
    }
    assert(!safeProbeOutput(std::string("per\0piacere", 11)));
    assert(!safeProbeOutput(std::string(513, 'a')));
    assert(!safeProbeOutput("\xff\xfe"));
    return 0;
}
