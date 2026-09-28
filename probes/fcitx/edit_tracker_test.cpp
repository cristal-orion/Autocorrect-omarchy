#include "edit_tracker.h"
#include <cassert>

int main() {
    EditTracker edit;
    assert(edit.begin("con il pne ", 11, 11, true, true));
    edit.authorize("con il pne ", 11, 11, true, true, false, "");
    edit.observe("con il pne", 10, 10);
    for (const auto &text : {"con il pn", "con il p", "con il ", "con il p", "con il pa", "con il pan", "con il pane"}) {
        const std::string value(text);
        const bool deletion = value.size() < edit.lastText.size();
        edit.authorize(edit.lastText, edit.lastText.size(), edit.lastText.size(), deletion, deletion, false,
                       deletion ? "" : value.substr(edit.lastText.size()));
        edit.observe(value, value.size(), value.size());
        assert(edit.active);
    }
    auto result = edit.finish("con il pane", 11);
    assert(result && result->original == "pne" && result->target == "pane" && result->previous == "con il ");
    assert(!edit.finish("con il pane", 11));
    // Appending letters is normal typing, not a correction.
    assert(!edit.begin("pn", 2, 2, false, false));
    assert(!edit.begin("con il pne ", 11, 0, true, true));
    // A same-word selection can be replaced; whole-field/multiword clearing cannot.
    assert(edit.begin("con il pne ", 10, 7, false, false));
    edit.authorize("con il pne ", 10, 7, false, false, false, "p");
    edit.observe("con il p ", 8, 8);
    for (const auto &value : {"con il pa ", "con il pan ", "con il pane "}) {
        const std::string next(value);
        const auto cursor = edit.lastText.size() - 1;
        edit.authorize(edit.lastText, cursor, cursor, false, false, false, next.substr(cursor, 1));
        edit.observe(next, next.size() - 1, next.size() - 1);
    }
    edit.observe("con il pane ", 11, 11);
    result = edit.finish("con il pane ", 11);
    assert(result && result->target == "pane");
    // A programmatic/paste edit without an authorized key is discarded.
    assert(edit.begin("con il pne ", 11, 11, true, true));
    edit.authorize("con il pne ", 11, 11, true, true, false, "");
    edit.observe("con il pne", 10, 10);
    edit.observe("con il pane", 11, 11);
    assert(!edit.active);
    // Cursor movement inside the word is fine. Exiting it explicitly completes
    // the edit; inserting a space in its middle must not teach the unsplit word.
    assert(edit.begin("con il pne ", 8, 8, false, false));
    edit.authorize("con il pne ", 8, 8, false, false, false, "a");
    edit.observe("con il pane ", 9, 9);
    assert(!edit.finish("con il pane ", 9));
    assert(edit.begin("con il pne ", 8, 8, false, false));
    edit.authorize("con il pne ", 8, 8, false, false, false, "a");
    edit.observe("con il pane ", 9, 9);
    result = edit.observe("con il pane ", 12, 12);
    assert(result && result->target == "pane");
    // Changing text outside the captured word invalidates the edit.
    assert(edit.begin("con il pne ", 11, 11, true, true));
    edit.authorize("con il pne ", 11, 11, true, true, false, "");
    edit.observe("con pane", 8, 8);
    assert(!edit.active);
    // Bounds, paragraphs and UTF-8 prefixes.
    assert(!edit.begin("pne\n", 4, 4, true, true));
    assert(!edit.begin("pne", 99, 99, true, true));
    assert(edit.begin("è pne ", 7, 7, true, true));
    edit.authorize("è pne ", 7, 7, true, true, false, "");
    edit.observe("è pne", 6, 6);
    edit.authorize("è pne", 4, 4, false, false, false, "a");
    edit.observe("è pane", 5, 5);
    result = edit.finish("è pane", 7);
    assert(result && result->previous == "è ");
    assert(boundedPrevious(std::string(1100, 'x') + " una ") == "una ");
    // GTK3 may omit selection anchors. Whole-field deletion must not be
    // mistaken for the single Backspace actually observed by the IM.
    assert(edit.begin("pne ", 4, 4, true, true));
    edit.authorize("pne ", 4, 4, true, true, false, "");
    edit.observe("", 0, 0);
    assert(!edit.active);
}
