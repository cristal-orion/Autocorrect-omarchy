#!/usr/bin/env bash
set -euo pipefail
root="$(dirname "$(dirname "$(readlink -f "$0")")")"
out="$root/build/fcitx-probe"
mkdir -p "$out"
g++ -std=c++20 -Wall -Wextra -Werror -O2 -fPIC -shared \
  "$root/probes/fcitx/probe.cpp" -o "$out/libautocorrectprobe.so" \
  $(pkg-config --cflags --libs Fcitx5Core)
g++ -std=c++20 -Wall -Wextra -Werror -O2 -fPIC \
  "$root/probes/fcitx/qt_client.cpp" -o "$out/autocorrect-probe-qt" \
  $(pkg-config --cflags --libs Qt6Widgets)
cc -std=c11 -Wall -Wextra -Werror -O2 \
  "$root/probes/fcitx/gtk_client.c" -o "$out/autocorrect-probe-gtk" \
  $(pkg-config --cflags --libs gtk+-3.0)
printf 'Probe compilato in: %s\n' "$out"
