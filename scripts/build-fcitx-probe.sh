#!/usr/bin/env bash
set -euo pipefail
root="$(dirname "$(dirname "$(readlink -f "$0")")")"
out="$root/build/fcitx-probe"
mkdir -p "$out"
stage="$(mktemp -d "$out/.compile-XXXXXX")"
trap 'rm -rf "$stage"' EXIT
g++ -std=c++20 -Wall -Wextra -Werror -O2 -fPIC -shared \
  "$root/probes/fcitx/probe.cpp" -o "$stage/libautocorrectprobe.so" \
  $(pkg-config --cflags --libs Fcitx5Core json-c)
g++ -std=c++20 -Wall -Wextra -Werror -O2 -fPIC \
  "$root/probes/fcitx/qt_client.cpp" -o "$stage/autocorrect-probe-qt" \
  $(pkg-config --cflags --libs Qt6Widgets)
cc -std=c11 -Wall -Wextra -Werror -O2 \
  "$root/probes/fcitx/gtk_client.c" -o "$stage/autocorrect-probe-gtk" \
  $(pkg-config --cflags --libs gtk+-3.0)
# Atomic replacement keeps already-open probe windows on their old binaries.
mv "$stage/libautocorrectprobe.so" "$stage/autocorrect-probe-qt" "$stage/autocorrect-probe-gtk" "$out/"
printf 'Probe compilato in: %s\n' "$out"
