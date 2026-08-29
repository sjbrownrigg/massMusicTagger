# massMusicTagger

Multi-source mass audio tagger. Discogs and MusicBrainz are peer sources
feeding one pipeline, with Cover Art Archive typed images, AcoustID
fingerprinting, concurrent processing, foobar2000-style format strings and
Docker deployment.

Since 3.0.0 it carries its own tagging core, absorbed from
[discogstagger3](https://github.com/sjbrownrigg/discogstagger3), which it no
longer depends on. discogstagger3 continues as its own project.

---

> ## ⚠ Breaking changes in 3.0.0 — read before upgrading
>
> **A 2.x `config.yaml` will not work as written.** `[details]` had grown to
> 28 keys and its contents moved to `[naming]`, `[artwork]`, `[archiving]`,
> `[tags]` and `[source]`. The old names are **not** honoured: a setting that
> looks present simply does not apply.
>
> Migrate in place — comments preserved, original kept as `config.yaml.bak`:
>
> ```bash
> mmt --migrate-config              # the configuration directory in use
> mmt --migrate-config /path/to/dir # or a specific one
> ```
>
> It prints what it moved and what it dropped. Afterwards a clean start logs
> no `moved to [section]` or `was removed in 3.0.0` warnings — if it does,
> that setting is not being applied.
>
> **3.1.0 is a security release.** `$inarray` and `$flatten` fell back to
> `eval()` on their argument, and both are meant to be pointed at metadata,
> so an album title could execute code during tagging. Discogs titles are
> editable by anyone with an account. Upgrade rather than staying on 3.0.0.
>
> Full detail: [docs/HISTORY.md](docs/HISTORY.md).

---

## Documentation

| Document | Description |
|---|---|
| [sources.md](https://github.com/sjbrownrigg/massMusicTagger/blob/master/docs/sources.md) | Metadata sources — Discogs, MusicBrainz, existing_tags; search tiers; id.txt format |
| [tagging_reference.md](https://github.com/sjbrownrigg/massMusicTagger/blob/master/docs/tagging_reference.md) | Format string variables and tags added by massMusicTagger |
| [docker-mmt](https://github.com/sjbrownrigg/docker-mmt) | Docker deployment — compose files, NAS mounts, WSL2 notes (separate repo) |
| [HISTORY.md](https://github.com/sjbrownrigg/massMusicTagger/blob/master/docs/HISTORY.md) | Changelog |

### discogstagger3 documentation (the tagging engine)

| Document | Description |
|---|---|
| [tagging_reference.md](https://github.com/sjbrownrigg/discogstagger3/blob/master/docs/tagging_reference.md) | Complete format string variable and function reference |
| [README](https://github.com/sjbrownrigg/discogstagger3#readme) | discogstagger3 overview, installation, and config |

---

## Quick start

```bash
pip install "massmusictagger[fingerprint] @ git+https://github.com/sjbrownrigg/massMusicTagger.git@master"

# Create a configuration (once)
mmt --new-config

# Tag a single album (tries Discogs then MusicBrainz automatically)
mmt ~/Music/incoming/Artist/Album

# Tag a whole incoming directory
mmt ~/Music/incoming

# Dry run (shows what would happen without writing)
mmt --dry-run ~/Music/incoming
```

## Configuration

Configuration is a **directory**, not a single file. `config.yaml` is the entry
point, and everything beside it is found by name:

```
config.yaml              your settings
formats.ini              your file and directory naming (optional)
credentials/             API tokens — every *.yaml here is loaded
  discogs.yaml
  musicbrainz.yaml
```

It is found via `MMT_CONFIG_DIR`, else `$XDG_CONFIG_HOME/massmusictagger`, else
`~/.config/massmusictagger`. There is no `-c` switch — the configuration is a
directory, so it is selected by pointing `MMT_CONFIG_DIR` at one:

```bash
MMT_CONFIG_DIR=~/configs/vinyl mmt ~/Music/incoming
```

Create one with `mmt --new-config`. Credentials can also come from the
environment (`DISCOGS_USER_TOKEN`), which overrides the file.

Settings are grouped by what they affect:

| Section | Holds |
|---|---|
| `[common]` | source and destination directories, user agent |
| `[source]` | which sources to try, in order, and source hints |
| `[naming]` | filename casing, character profiles, format codes |
| `[artwork]` | cover art: embedding, policy, which source to take it from |
| `[archiving]` | what happens to the source directory after a successful tag |
| `[batch]` | concurrency, the audit log, `id_file` |
| `[tags]` | tags to keep, and `suppress_tags` |

In 3.0.0 these came out of a single `[details]` section that had grown to 28
keys. A configuration still using the old names is told where each setting
went; see [HISTORY.md](docs/HISTORY.md).

### Pinning a release

Three ways to say which release an album is, strongest first:

```bash
mmt -r 14726546 ~/Music/incoming/album          # one album
mmt -r musicbrainz:4fe0825c-... ~/Music/album   # qualify when not Discogs
```

For a whole tree, put an `id.txt` beside each release that needs pinning —
it travels with the album, so one run can pin a different release for each:

```ini
[source]
name = discogs
discogs_id = 14726546
```

A bare release number on its own line also works, and means Discogs.

Failing both, a `discogs_id` or `musicbrainz_releaseid` already in the file
tags is used before searching. The difference is deliberate: an ID you gave
is used even if the track count disagrees, because you chose it, while an
embedded tag falls through to searching, because it may be stale after a
reissue.

## Source priority

Configured in `config.yaml` — see [sources.md](https://github.com/sjbrownrigg/massMusicTagger/blob/master/docs/sources.md):

```yaml
source:
  priority:
    - discogs
    - musicbrainz
    - existing_tags
```

## Format strings

massMusicTagger uses discogstagger3's format string engine plus additional
variables. See [tagging_reference.md](https://github.com/sjbrownrigg/massMusicTagger/blob/master/docs/tagging_reference.md)
for what massMusicTagger adds, and [discogstagger3's tagging_reference.md](https://github.com/sjbrownrigg/discogstagger3/blob/master/docs/tagging_reference.md)
for the complete format string reference.

## Fingerprinting (optional)

```bash
sudo apt install libdiscid0 libchromaprint-tools
pip install "massmusictagger[fingerprint]"
```

Enables tier 5 (DiscID) and tiers 6–7 (AcoustID) in the MusicBrainz search.
