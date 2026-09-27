// Dedicated GTK3 fields for exercising the actual Fcitx input-method module.
#include <gtk/gtk.h>
#include <stdio.h>
#include <string.h>

static GtkWidget *fields[4];
static gboolean status(gpointer unused) {
    (void)unused;
    const char *path = g_getenv("AUTOCORRECT_PROBE_STATUS");
    if (!path) return TRUE;
    GString *out = g_string_new("");
    const char *names[] = {"normal", "password", "code", "second"};
    for (int i = 0; i < 4; ++i) {
        // Preserve trailing spaces through INI parsers.
        const char *text = gtk_entry_get_text(GTK_ENTRY(fields[i]));
        gchar *encoded = g_base64_encode((const guchar *)text, strlen(text));
        g_string_append_printf(out, "[%s]\ntext_base64=%s\ncursor=%d\nfocus=%d\n", names[i], encoded,
            gtk_editable_get_position(GTK_EDITABLE(fields[i])), gtk_widget_has_focus(fields[i]));
        g_free(encoded);
    }
    g_file_set_contents(path, out->str, -1, NULL);
    g_string_free(out, TRUE);
    return TRUE;
}

int main(int argc, char **argv) {
    g_set_prgname("autocorrect-probe-gtk");
    gtk_init(&argc, &argv);
    GtkWidget *window = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    gtk_window_set_title(GTK_WINDOW(window), "Autocorrect Fcitx Probe GTK");
    gtk_window_set_default_size(GTK_WINDOW(window), 650, 260);
    GtkWidget *box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 8);
    gtk_container_add(GTK_CONTAINER(window), box);
    gtk_box_pack_start(GTK_BOX(box), gtk_label_new("Fcitx probe: quesot + spazio; Backspace annulla. Tab cambia campo."), FALSE, FALSE, 0);
    const char *labels[] = {"Testo normale", "Password sintetica", "NoSpellCheck", "Secondo campo normale"};
    for (int i = 0; i < 4; ++i) {
        fields[i] = gtk_entry_new();
        gtk_entry_set_placeholder_text(GTK_ENTRY(fields[i]), labels[i]);
        gtk_box_pack_start(GTK_BOX(box), fields[i], FALSE, FALSE, 0);
    }
    gtk_entry_set_visibility(GTK_ENTRY(fields[1]), FALSE);
    gtk_entry_set_input_purpose(GTK_ENTRY(fields[1]), GTK_INPUT_PURPOSE_PASSWORD);
    gtk_entry_set_input_hints(GTK_ENTRY(fields[2]), GTK_INPUT_HINT_NO_SPELLCHECK);
    g_signal_connect(window, "destroy", G_CALLBACK(gtk_main_quit), NULL);
    gtk_widget_show_all(window);
    gtk_widget_grab_focus(fields[0]);
    g_timeout_add(50, status, NULL);
    gtk_main();
    return 0;
}
