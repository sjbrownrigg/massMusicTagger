# massMusicTagger

Multi-source mass audio tagger. Discogs and MusicBrainz are peer sources
feeding one pipeline, with Cover Art Archive typed images, AcoustID
fingerprinting, concurrent processing, foobar2000-style format strings and
Docker deployment.

Since 3.0.0 it carries its own tagging core, absorbed from
[discogstagger3](https://github.com/sjbrownrigg/discogstagger3), which it no
longer depends on. discogstagger3 continues as its own project.

---

> ## ⚠ Upgrading from 2.x — read before you do
>
> **Your `config.yaml` will not work as written.** In 3.0.0 the `[details]`
> section — which had grown to 28 keys covering unrelated things — was split
> into `[naming]`, `[artwork]`, `[archiving]`, `[tags]` and `[source]`. The old
> names are **not** honoured, so a setting that looks present in the file
> simply does not apply.
>
> One command moves it, keeping every comment and leaving the original as
> `config.yaml.bak`:
>
> ```bash
> mmt --migrate-config
> ```
>
> It prints what it moved and what it dropped. Run it again after any upgrade,
> even if you have run it before: each version has taught it something new, and
> it does nothing when there is nothing left to do.
>
> Afterwards a clean start should log no warnings at all. If it does, that
> setting is not being applied.
>
> **3.1.0 is a security release.** `$inarray` and `$flatten` fell back to
> Python's `eval()` on whatever they were given, and both exist to be pointed
> at metadata — so an album title could run code during tagging. Anyone with a
> Discogs account can edit a title. Do not stay on 3.0.0.
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

### discogstagger3

A separate project, and no longer part of this one. massMusicTagger began as a
wrapper around it and absorbed its tagging core in 3.0.0; since then the two
share history but no code. Its documentation describes *its* behaviour, which
has drifted from this one's — use the pages above for massMusicTagger.

| Document | Description |
|---|---|
| [discogstagger3](https://github.com/sjbrownrigg/discogstagger3#readme) | The Discogs-only tagger this was forked from |

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
formats.ini              how files and folders are named
credentials/             API tokens — every *.yaml here is loaded
  discogs.yaml
  musicbrainz.yaml
templates/               the templates that produce .nfo and .m3u
  info.txt
  m3u.txt
format_codes.yaml        how a release's format becomes a code: CD, DM, 2xLP
char_substitutions.yaml  characters replaced per char_profile
source_hints.yaml        words in a folder name that identify the rip
```

`mmt --new-config` writes all of it and never overwrites a file you already
have, so it is safe to re-run to pick up anything new.

The last four are optional and behave differently from the first two. The
three rule tables arrive **entirely commented out** and are merged over the
packaged ones: uncomment one line and only that line changes, while
everything else keeps coming from the package and keeps improving with each
upgrade. The templates arrive live — a commented-out template produces
nothing — and shadow the packaged ones **per file**, so editing `info.txt`
leaves `m3u.txt` alone. Delete any of them to go back to the packaged
version.

It is found via `MMT_CONFIG_DIR`, else `$XDG_CONFIG_HOME/massmusictagger`, else
`~/.config/massmusictagger`. There is no `-c` switch — the configuration is a
directory, so it is selected by pointing `MMT_CONFIG_DIR` at one:

```bash
MMT_CONFIG_DIR=~/configs/vinyl mmt ~/Music/incoming
```

Credentials can also come from the environment (`DISCOGS_USER_TOKEN`), which
wins over the file — handy for containers, where a token in a file can end up
in an image layer.

Three commands look after a configuration:

| Command | What it does |
|---|---|
| `mmt --new-config` | Creates one, or fills in files an existing one is missing |
| `mmt --migrate-config` | Moves settings an upgrade has relocated, keeping your comments |
| `mmt --annotate-config` | Puts the explanatory comments back, changing no values |

`--annotate-config` is for a configuration that has been carried forward for
years and holds the right settings with none of the explanation. It refuses to
write if anything but the comments would change.

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

File and directory names are built from format strings in the foobar2000
style — literal text with `%variables%` and `$functions()` that nest:

```ini
dir  = %albumartist%/[%year%] %album%
song = $num('%tracknumber%','2') $if1($neg($strcmp('%artist%','%albumartist%')),'%artist% - ')%title%%fileext%
```

That dialect is why this project exists. See
[tagging_reference.md](docs/tagging_reference.md) for the variables and
functions available.

Preview a change before running it against your library:

```bash
python format_preview.py --conf ~/.config/massmusictagger
```

## Fingerprinting (optional)

```bash
sudo apt install libdiscid0 libchromaprint-tools
pip install "massmusictagger[fingerprint]"
```

Enables tier 5 (DiscID) and tiers 6–7 (AcoustID) in the MusicBrainz search.
