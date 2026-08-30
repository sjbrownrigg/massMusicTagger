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

## Installing

Two supported routes. **Docker** keeps the tool and everything it needs inside
one image and is the maintainer's own deployment. A **virtual environment**
runs it as an ordinary program on the machine. Both end at the same place: an
`mmt` command and a configuration directory you own.

### What it needs, either way

Python **3.10 or newer**, and a handful of external programs that the tagger
runs as commands:

| Program | Needed for | Required? |
|---|---|---|
| `ffmpeg` | ReplayGain scanning, `.m4a` conversion, single-track CUE albums | **Yes** |
| `shntool` and `flac` | Splitting a multi-track CUE album into separate tracks | Only if you have CUE rips |
| `libdiscid` | MusicBrainz Disc ID lookup — search tier 5 | Optional |
| `fpcalc` (chromaprint) | AcoustID fingerprinting — search tiers 6 and 7 | Optional |

`flac` also supplies `metaflac`, which matters only if you set
`replaygain.application: metaflac` instead of the default `r128gain`.

Everything else — mutagen, Mako, Pillow, rapidfuzz and the rest — is a Python
dependency and installs itself.

---

### Route 1 — Docker

The deployment lives in its own repository,
[docker-mmt](https://github.com/sjbrownrigg/docker-mmt): compose file, NAS
mount examples, and scheduling.

```bash
git clone https://github.com/sjbrownrigg/docker-mmt.git
cd docker-mmt
cp .env.example .env          # your Discogs token goes in here
docker compose build
docker compose run --rm mmt --new-config
```

Its README covers mounts, upgrading and unattended running. One ordering trap
is worth repeating here: **build first, migrate second.** Running
`--migrate-config` before `docker compose build` migrates your configuration
using last month's tool, which does not know about this month's settings.

---

### Route 2 — a virtual environment

#### 1. System packages

Package names differ between distributions; the four programs do not. Pick
yours:

**Debian, Ubuntu, Mint, Raspberry Pi OS** — verified on Ubuntu 24.04:

```bash
sudo apt update
sudo apt install python3-venv ffmpeg shntool flac libdiscid0 libchromaprint-tools
```

**Fedora** — `ffmpeg` and `shntool` come from RPM Fusion, not the main repository:

```bash
sudo dnf install \
  https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm
sudo dnf install python3 ffmpeg shntool flac libdiscid chromaprint-tools
```

**RHEL, Rocky, AlmaLinux** — EPEL and RPM Fusion first, then as Fedora. On
RHEL 8 the system Python is 3.6, which is too old: install `python3.11` (or
newer) and use that interpreter to build the environment below.

**Arch, Manjaro, EndeavourOS** — `shntool` is in the AUR rather than the
official repositories:

```bash
sudo pacman -S python ffmpeg flac libdiscid chromaprint
paru -S shntool          # or yay, or build it by hand
```

**openSUSE** — a full `ffmpeg` comes from Packman:

```bash
sudo zypper install python3 ffmpeg-7 shntool flac libdiscid0 chromaprint-fpcalc
```

**Alpine** — `shntool` is not packaged, so CUE splitting is unavailable:

```bash
doas apk add python3 py3-virtualenv ffmpeg flac libdiscid chromaprint
```

Now check what you actually got. This matters more than the list above,
because a name that differs on your distribution shows up here rather than
halfway through a run:

```bash
for b in ffmpeg shntool flac metaflac fpcalc; do
  printf '%-10s %s\n' "$b" "$(command -v $b || echo MISSING)"
done
```

`ffmpeg` must be found. The others may say `MISSING` without harm — the table
above says what each one costs you.

#### 2. The environment

Keep it **outside** the source tree. A virtual environment inside a project
directory gets swept up by backups, syncs and recursive scans, and rebuilding
it means touching the checkout:

```bash
python3 -m venv ~/.venvs/massmusictagger
~/.venvs/massmusictagger/bin/pip install \
  "massmusictagger[fingerprint] @ git+https://github.com/sjbrownrigg/massMusicTagger.git@master"
```

Drop `[fingerprint]` if you skipped `libdiscid` and `fpcalc` — it pulls in the
Python bindings for both, and they fail to build without the libraries there.

Put the command on your `PATH`:

```bash
mkdir -p ~/.local/bin
ln -s ~/.venvs/massmusictagger/bin/mmt ~/.local/bin/mmt
mmt --version
```

If that last line is not found, `~/.local/bin` is not on your `PATH`; add it in
`~/.bashrc` or call the full path `~/.venvs/massmusictagger/bin/mmt` instead.

#### 3. A configuration

```bash
mmt --new-config
```

That fills `~/.config/massmusictagger` — or `$XDG_CONFIG_HOME/massmusictagger`,
or wherever `MMT_CONFIG_DIR` points — with every file the tagger looks for by
name:

```
config.yaml                  settings, commented throughout
formats.ini                  the format strings that name your files
format_codes.yaml            format abbreviations (Digital Media -> DM)
char_substitutions.yaml      per-profile illegal-character replacements
source_hints.yaml            folder words that identify a rip's source
credentials/discogs.yaml     your Discogs token
credentials/musicbrainz.yaml your MusicBrainz user agent
templates/info.txt           the per-album info file
templates/m3u.txt            the playlist
```

**Existing files are never overwritten**, so run it again after an upgrade to
pick up anything newly added — it will leave everything you have edited alone.
The three rule tables and the two templates are all optional: delete any of
them and the packaged version is used instead, so keep only what you have
actually changed.

Then put your Discogs token in `credentials/discogs.yaml`, or in the
environment as `DISCOGS_USER_TOKEN`, and give MusicBrainz a user agent that
identifies you. See [docs/sources.md](docs/sources.md).

#### 4. Upgrading later

```bash
~/.venvs/massmusictagger/bin/pip install --upgrade \
  "massmusictagger[fingerprint] @ git+https://github.com/sjbrownrigg/massMusicTagger.git@master"
mmt --migrate-config      # moves settings that changed section
mmt --new-config          # adds any new files, overwrites nothing
```

Upgrade the code **before** migrating, for the reason given under Docker above.

---

### macOS

> **Untested.** Neither the maintainer nor CI runs macOS, so this route is
> reasoned from the dependencies rather than verified on a machine. It should
> work — nothing here is Linux-specific — but if it does not, please open an
> issue and it will be corrected.

[Homebrew](https://brew.sh) has all four programs:

```bash
brew install python ffmpeg shntool flac libdiscid chromaprint
```

Then follow **Route 2** from step 2 onwards unchanged; `python3 -m venv` and
the `pip install` line behave the same way.

Two things to suspect first if something misbehaves:

- On Apple Silicon, Homebrew installs into `/opt/homebrew`, and the `discid`
  Python module locates the library through `ctypes.util.find_library`, which
  does not always search there. `export DYLD_LIBRARY_PATH=/opt/homebrew/lib`
  is the usual fix. Only Disc ID lookup is affected.
- The configuration goes to `~/.config/massmusictagger`, following the XDG
  convention rather than `~/Library/Application Support`.

---

### WSL

WSL runs a real distribution, so use the Linux instructions above for whichever
one you installed — Ubuntu unless you chose otherwise. Four differences are
worth knowing, and the first two are the ones that will actually bite:

**Work on the Linux filesystem, not `/mnt/c`.** Windows drives are reached
through a translation layer, and per-file operations on them are slow enough to
dominate a run. Keep the incoming and destination trees on the WSL side, or on
a share mounted as below.

**Mount a NAS share inside Linux rather than through Windows.** Reaching a
share via `/mnt/c` means WSL → Windows → SMB, and tagging copies each album
twice. Measured on this setup:

| Path | Throughput |
|---|---|
| NAS → local disk | 31 MiB/s |
| local disk → NAS | 21 MiB/s |
| **NAS → NAS (what tagging does)** | **9.8 MiB/s** |
| local → local | 1280 MiB/s |

Tagging is bound by that link, not by the processor — raising `batch.workers`
from 1 to 4 changed a 313 MiB album from 145 to 139 seconds, with the container
at 1.5% CPU throughout. If a run feels slow, this is why, and more workers will
not help.

**Keep `char_profile: windows` if the library will be read from Windows.** NTFS
forbids characters that Linux allows — a colon in `:wumpscut:` among them — and
the profile substitutes them at naming time. Without it you get filenames that
Linux writes happily and Windows cannot open.

**Watch mode needs systemd.** `mmt --watch` runs until stopped, and by default
WSL ends everything when the last terminal closes. On Windows 11, or Windows 10
with a recent WSL, enable it:

```ini
# /etc/wsl.conf
[boot]
systemd=true
```

Then `wsl --shutdown` from PowerShell, reopen, and a user service with
`loginctl enable-linger $USER` will survive the terminal closing.

---

## First run

```bash
# Tag a single album — tries Discogs, then MusicBrainz
mmt ~/Music/incoming/Artist/Album

# See what would happen, writing nothing
mmt --dry-run ~/Music/incoming

# Tag a whole incoming tree
mmt ~/Music/incoming

# Confirm each album before it is written
mmt --review ~/Music/incoming

# Watch for new albums and tag them as they arrive
mmt --watch
```

Start with `--dry-run` on a handful of albums, and read what it says it will
name them. Format strings decide the entire shape of your library, and the
cheapest time to change one is before the first run rather than after.

---

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

Disc ID (search tier 5) and AcoustID (tiers 6 and 7) let MusicBrainz identify a
release from the audio itself when a search by name has failed. They need the
`libdiscid` and `chromaprint` system packages — see [Installing](#installing)
for your distribution — and the extra Python bindings:

```bash
pip install "massmusictagger[fingerprint]"
```

AcoustID additionally needs a free application key from
[acoustid.org](https://acoustid.org/login):

```yaml
musicbrainz:
  acoustid_api_key: ""
  acoustid_early: false    # fingerprint before searching by name
```

Disc ID needs no key. Details of when each tier runs are in
[docs/sources.md](docs/sources.md).
