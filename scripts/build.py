#!/usr/bin/env python3
"""Builds the wisp list: every plugin in plugins.toml from the commit it is pinned to, checked by
wisp itself, into one folder ready to publish as a release (each <id>.wasm and index.toml).

    python3 scripts/build.py --out dist --notes notes.md --release 2026-10-25.1

--local OWNER/REPO=FOLDER builds that repository from a folder on this computer instead of its
pinned commit, to try a change before it is pushed; the index then says so in each source.
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = re.compile(
    r"^github:(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@(?P<commit>[0-9a-f]{40})(?:#(?P<path>[A-Za-z0-9_./-]+))?$"
)
ID = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
MANIFEST_SECTION = "wisp-plugin"


def fail(message):
    sys.exit(f"build.py: {message}")


def run(command, cwd, capture=False):
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=capture)
    if result.returncode != 0:
        fail(f"{' '.join(command)} failed in {cwd}:\n{result.stderr if capture else ''}")
    return result.stdout


def source(text, what):
    found = SOURCE.match(text)
    if not found:
        fail(f"{what}: source {text!r} is not github:owner/repo@<40-hex commit>[#path]")
    return found["repo"], found["commit"], found["path"] or ""


def checkout(repo, commit, work, local):
    """The repository at the commit, fetched alone (or the local folder standing in for it)."""
    if repo in local:
        return local[repo]
    folder = work / f"{repo.replace('/', '-')}-{commit}"
    if not folder.exists():
        folder.mkdir(parents=True)
        run(["git", "init", "-q"], folder)
        run(["git", "fetch", "-q", "--depth", "1", f"https://github.com/{repo}", commit], folder)
        run(["git", "checkout", "-q", "FETCH_HEAD"], folder)
    return folder


def build_wasm(folder):
    """Builds the plugin crate in `folder` for WebAssembly, as it ships, and returns the file."""
    manifest = (folder / "Cargo.toml").resolve()
    # Run from the crate, so the repository's rust-toolchain.toml picks the compiler.
    output = run(
        ["cargo", "build", "--release", "--locked", "--target", "wasm32-unknown-unknown",
         "--manifest-path", str(manifest), "--message-format=json"],
        folder,
        capture=True,
    )
    for line in output.splitlines():
        message = json.loads(line)
        if message.get("reason") == "compiler-artifact" and Path(message["manifest_path"]).resolve() == manifest:
            for name in message["filenames"]:
                if name.endswith(".wasm"):
                    return Path(name)
    fail(f"{folder} built no .wasm: is its crate-type cdylib?")


def build_wisp(folder):
    run(["cargo", "build", "--release", "--locked", "-p", "wisp-cli"], folder)
    return folder / "target" / "release" / "wisp"


def leb128(data, at):
    value, shift = 0, 0
    while True:
        byte = data[at]
        at += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, at
        shift += 7


def embedded_manifest(wasm):
    """The manifest wisp reads from the module: its `wisp-plugin` custom section."""
    data = wasm.read_bytes()
    if data[:8] != b"\0asm\x01\0\0\0":
        fail(f"{wasm} is not a WebAssembly module")
    at = 8
    while at < len(data):
        kind = data[at]
        size, at = leb128(data, at + 1)
        end = at + size
        if kind == 0:
            length, name_at = leb128(data, at)
            if data[name_at:name_at + length] == MANIFEST_SECTION.encode():
                return tomllib.loads(data[name_at + length:end].decode())
        at = end
    fail(f"{wasm} has no {MANIFEST_SECTION} section")


def toml_string(text):
    return json.dumps(text, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--release", required=True, help="the tag of the release the files will be attached to")
    parser.add_argument("--notes", type=Path, help="where to write the release's notes")
    parser.add_argument("--local", action="append", default=[], metavar="OWNER/REPO=FOLDER")
    args = parser.parse_args()

    local = {}
    for item in args.local:
        repo, _, folder = item.partition("=")
        local[repo] = Path(folder).resolve()
    listed = tomllib.loads((ROOT / "plugins.toml").read_text())
    work = ROOT / "work"
    shutil.rmtree(args.out, ignore_errors=True)
    args.out.mkdir(parents=True)

    wisp_repo, wisp_commit, _ = source(listed["wisp"]["source"], "[wisp]")
    wisp = build_wisp(checkout(wisp_repo, wisp_commit, work, local))

    entries, rows, seen = [], [], set()
    for plugin in listed.get("plugin", []):
        plugin_id = plugin["id"]
        if not ID.match(plugin_id) or plugin_id in seen:
            fail(f"plugin id {plugin_id!r} is not lowercase letters, digits and hyphens, or is listed twice")
        seen.add(plugin_id)
        repo, commit, path = source(plugin["source"], plugin_id)
        wasm = build_wasm(checkout(repo, commit, work, local) / path)
        report = run([str(wisp), "plugin", "check", str(wasm)], ROOT, capture=True)
        manifest = embedded_manifest(wasm)
        if manifest["id"] != plugin_id:
            fail(f"{plugin['source']} builds the plugin {manifest['id']}, not {plugin_id}")
        file = args.out / f"{plugin_id}.wasm"
        shutil.copyfile(wasm, file)
        sha = hashlib.sha256(file.read_bytes()).hexdigest()
        built_from = plugin["source"] if repo not in local else f"{plugin['source']} (built from a local folder)"
        capabilities = list(manifest.get("capabilities", {}))
        entries.append("\n".join([
            "[[plugin]]",
            f"id = {toml_string(plugin_id)}",
            f"name = {toml_string(manifest['name'])}",
            f"summary = {toml_string(manifest.get('summary', ''))}",
            f"version = {toml_string(manifest['version'])}",
            f"api = {int(manifest['api'])}",
            f"capabilities = [{', '.join(toml_string(c) for c in capabilities)}]",
            f"sha256 = {toml_string(sha)}",
            f"source = {toml_string(built_from)}",
        ]))
        rows.append(f"| {manifest['name']} ({plugin_id}) | {manifest['version']} | {', '.join(capabilities) or 'none'} | `{sha}` | `{built_from}` |")
        print(f"{plugin_id}: {sha}\n{report}")

    header = f"# The wisp list, built by its CI: every plugin `plugin install <id>` finds.\nrelease = {toml_string(args.release)}\n"
    (args.out / "index.toml").write_text(header + "\n" + "\n\n".join(entries) + "\n")
    if args.notes:
        args.notes.write_text(
            f"Checked by `wisp plugin check` from `{listed['wisp']['source']}`.\n\n"
            "| Plugin | Version | Capabilities | SHA-256 | Built from |\n|---|---|---|---|---|\n" + "\n".join(rows) + "\n"
        )


if __name__ == "__main__":
    main()
