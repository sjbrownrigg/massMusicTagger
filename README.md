# massMusicTagger

Multi-source mass audio tagger built on [discogstagger3](https://github.com/sjbrownrigg/discogstagger3).

Adds MusicBrainz metadata, Cover Art Archive typed images, AcoustID fingerprinting, concurrent processing, and Docker deployment — while keeping the Discogs path from discogstagger3 working unchanged.

---

## Documentation

| Document | Description |
|---|---|
| [sources.md](https://github.com/sjbrownrigg/massMusicTagger/blob/master/docs/sources.md) | Metadata sources — Discogs, MusicBrainz, existing_tags; search tiers; id.txt format |
| [tagging_reference.md](https://github.com/sjbrownrigg/massMusicTagger/blob/master/docs/tagging_reference.md) | Format string variables and tags added by massMusicTagger |
| [docker/README.md](https://github.com/sjbrownrigg/massMusicTagger/blob/master/docker/README.md) | Docker deployment guide for NAS / WSL2 environments |
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
