# The wisp list

The plugins [wisp](https://github.com/eeshaansarda/wisp) finds by name: `plugin install timers`.
Each is built by this repository's CI from the source it is pinned to here, checked by wisp itself, and published with its SHA-256; wisp keeps a listed plugin only if it is byte for byte the file this list vouches for.
How wisp runs plugins, what they may ask for and what no plugin may ever do: [docs/plugins.md](https://github.com/eeshaansarda/wisp/blob/main/docs/plugins.md).

## What is here

| File | What it is |
|---|---|
| `plugins.toml` | The list: each plugin's id and the commit its source is pinned to, and the wisp that checks them |
| `scripts/build.py` | Builds every listed plugin from its pinned commit for `wasm32-unknown-unknown`, runs `wisp plugin check` on it, and writes `index.toml` |
| `.github/workflows/list.yml` | On a pull request, builds and checks; on `main`, publishes one release with every `<id>.wasm` and `index.toml` |

wisp reads `releases/latest/download/index.toml`, then `releases/download/<release>/<id>.wasm`.
These are release downloads, not API calls, so they do not count against GitHub's limit of 60 API requests an hour.

## Adding a plugin

Open a pull request adding one entry to `plugins.toml`:

```toml
[[plugin]]
id = "dice"                                                   # the id in its wisp-plugin.toml
source = "github:owner/repo@<40-hex commit>#path/to/plugin"   # the plugin's cdylib crate, with Cargo.lock
```

A plugin is admitted by wisp's rule for commands: it serves capture, lists or recall, and is not a text transform.
It needs a licence that lets this list redistribute what it builds.
Every update is a new commit pin, reviewed as a pull request like the first one.

## Building it here

```sh
python3 scripts/build.py --out dist --release try
```

`--local eeshaansarda/wisp=../wisp` builds a repository from a folder on this computer instead of its pinned commit, to try a change before it is pushed.

A source in a private repository (wisp itself, while it is private) is fetched with the repository secret `SOURCE_TOKEN`, a read-only token, in a CI step of its own: no plugin's build runs while it is set.
