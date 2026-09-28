#!/usr/bin/env python3
"""Build the pinned, unmodified AOSP typing core as a Linux laboratory CLI."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "latinime": ("https://android.googlesource.com/platform/packages/inputmethods/LatinIME",
                 "127336e9f29d69607eab55982324b210279ae8c5"),
    "nativehelper": ("https://android.googlesource.com/platform/libnativehelper",
                     "aef2939781fc0b57b4477df7160935cdf5697919"),
}


def run(args, **kwargs):
    return subprocess.check_output([str(arg) for arg in args], text=True, **kwargs).strip()


def checkout(path, url, revision):
    if not path.exists():
        path.mkdir(parents=True)
        run(["git", "init", path])
        run(["git", "-C", path, "fetch", "--depth", "1", url, revision])
        run(["git", "-C", path, "checkout", "--detach", "FETCH_HEAD"])
    if run(["git", "-C", path, "rev-parse", "HEAD"]) != revision:
        raise ValueError(f"Revisione inattesa: {path}")
    if run(["git", "-C", path, "status", "--porcelain"]):
        raise ValueError(f"Sorgenti modificati: {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "build/latinime-probe")
    parser.add_argument("--latinime-source", type=Path)
    parser.add_argument("--nativehelper-source", type=Path)
    parser.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs deve essere positivo")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, (url, revision) in SOURCES.items():
        path = (getattr(args, f"{name}_source") or output / "vendor" / name).resolve()
        checkout(path, url, revision)
        paths[name] = path

    jni = paths["latinime"] / "native/jni"
    blueprint = (jni / "Android.bp").read_text()
    section = blueprint.split('name: "LATIN_IME_CORE_SRC_FILES",', 1)[1].split("\n}", 1)[0]
    core = [jni / name for name in re.findall(r'"(src/[^"\n]+\.cpp)"', section)]
    if len(core) != 82:
        raise ValueError(f"Lista sorgenti AOSP inattesa: {len(core)} file")
    wrapper = ROOT / "probes/latinime/main.cpp"
    sources = core + [wrapper]
    compiler = shlex.split(os.environ.get("CXX", "g++"))
    flags = ["-std=c++17", "-O2", "-DHOST_TOOL", "-include", "cstdint", "-include", "cstdlib",
             "-I" + str(jni / "src"), "-I" + str(paths["nativehelper"] / "include_jni")]
    if args.sanitize:
        flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-g"]
    json_flags = shlex.split(run(["pkg-config", "--cflags", "--libs", "json-c"]))
    objects_dir = output / "objects"
    objects_dir.mkdir(exist_ok=True)
    objects = [objects_dir / f"{index:03}.o" for index in range(len(sources))]
    # A build always recompiles the pinned sources: no stale header/object cache.
    def compile_one(pair):
        source, obj = pair
        subprocess.run(compiler + flags + [f for f in json_flags if f.startswith("-I")]
                       + ["-c", str(source), "-o", str(obj)], check=True)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(compile_one, zip(sources, objects)))
    binary = output / "latinime-probe"
    subprocess.run(compiler + flags + [str(obj) for obj in objects] + json_flags
                   + ["-o", str(binary)], check=True)
    hashed = {}
    for name, base in paths.items():
        files = list((base / "native/jni").rglob("*.h")) + core if name == "latinime" else [base / "include_jni/jni.h"]
        files += [base / "NOTICE"] if (base / "NOTICE").exists() else []
        for path in files:
            hashed[f"{name}/{path.relative_to(base)}"] = hashlib.sha256(path.read_bytes()).hexdigest()
    hashed["probes/latinime/main.cpp"] = hashlib.sha256(wrapper.read_bytes()).hexdigest()
    manifest = {
        "sources": {name: {"url": url, "revision": rev} for name, (url, rev) in SOURCES.items()},
        "compiler": run(compiler + ["--version"]), "flags": flags, "json_c": run(["pkg-config", "--modversion", "json-c"]),
        "files_sha256": hashed, "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "core_modified": False, "runtime": "native Linux; small array-only JNI adapter, no JVM or Android",
    }
    (output / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(binary)


if __name__ == "__main__":
    main()
