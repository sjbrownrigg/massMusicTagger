# Metadata sources — massMusicTagger

massMusicTagger supports multiple metadata sources that are tried in a
configurable priority order. This document describes each source, its search
strategy, and configuration.

---

## Source priority

Configured in `conf/config_personal.yaml`:

```yaml
source:
  priority:
    - discogs          # try Discogs first
    - musicbrainz      # fall back to MusicBrainz
    - existing_tags    # organise from embedded tags if no API match
```

Each source is tried in order. The first confident match wins. A match is
accepted only when the release track count matches the local file count
(within a tolerance of ±2).

Override the priority for a single run with `--source`:

```bash
mmt --source musicbrainz  # MB only
mmt --source discogs      # Discogs only
mmt --source auto         # use priority list (default)
```

---

## Discogs

> **Full reference:** [discogstagger3 README](https://github.com/sjbrownrigg/discogstagger3#readme)

The Discogs source uses discogstagger3's search engine directly. Configuration
lives in `conf/discogs.yaml` / `conf/discogs_personal.yaml`.

### Search tiers (discogstagger3)

1. `id.txt` containing a Discogs release ID
2. Existing `discogs_id` tag in audio files (validated against track count)
3. `DiscogsSearch` — artist + title + year + duration matching

### Discogs-specific config keys

```yaml
discogs:
  user_token: ""          # personal access token (recommended)
  consumer_key: ""        # OAuth — only needed without user_token
  consumer_secret: ""
  skip_auth: false
```

```yaml
batch:
  searchdiscogs: true     # enable automatic search (required for tiers 2-3)
  tracklength_tolerance: 5.0   # seconds — max avg duration difference to accept
  title_similarity_threshold: 60
```

---

## MusicBrainz

Configuration lives in `conf/musicbrainz.yaml` / `conf/musicbrainz_personal.yaml`.

### Search tiers

| Tier | Method | Dependency |
|---|---|---|
| 1 | `id.txt` with `mbid=<UUID>` | — |
| 2 | Existing `musicbrainz_releaseid` tag (validated) | — |
| 3 | Text search — artist + album title + track count (with artist similarity scoring; tries parent directory name if albumartist tag absent) | — |
| 4 | Barcode lookup via MB API | — |
| 5 | DiscID — CD TOC hash from file durations | `pip install massmusictagger[discid]` + `apt install libdiscid0` |
| 6 | Single-track AcoustID fingerprint | `pip install massmusictagger[acoustid]` + `apt install libchromaprint-tools` |
| 7 | Multi-track AcoustID — all tracks fingerprinted; release with most matching recordings wins | same as tier 6 |

### MusicBrainz-specific config keys

```yaml
musicbrainz:
  user_agent: "YourApp/1.0 (your@email.com)"   # required by MB API
  acoustid_api_key: ""   # register at https://acoustid.org/login
  cache_directory: "~/.cache/massmusictagger/mb"
```

### Installing fingerprinting support

```bash
# System libraries
sudo apt install libdiscid0 libchromaprint-tools   # Debian/Ubuntu

# Python packages
pip install "massmusictagger[fingerprint]"   # installs both discid + pyacoustid
```

---

## existing_tags

A fallback source that requires no API calls. When all other sources fail to
find a confident match, `existing_tags` reads metadata already embedded in
the audio files and organises them using the configured format strings.

**No new tags are written** — only file names and directory structure change.
The original metadata is preserved intact.

Useful for:
- Bootlegs and rarities not in any database
- Partial rips / incomplete albums (where track count doesn't match any release)
- Maintaining a consistent folder structure for untagged files

---

## Image source preference

Images can be fetched from a different source than the metadata:

```yaml
details:
  image_source: auto         # images from the same source as metadata (default)
  image_source: musicbrainz  # always use Cover Art Archive (typed: Front/Back/Medium/…)
  image_source: discogs      # always use Discogs images
```

When `image_source: musicbrainz` and metadata came from Discogs, massMusicTagger
attempts a barcode lookup to find the MBID for Cover Art Archive.

---

## id.txt format

Place an `id.txt` file inside the album directory to pin a specific release:

```
# Discogs release ID (plain number):
4319687

# MusicBrainz release MBID (mbid= key):
mbid=4b8a0e1b-249b-4d11-8e6e-42aa23466b96

# Both in one file:
4319687
mbid=4b8a0e1b-249b-4d11-8e6e-42aa23466b96

# Barcode (for MB barcode search):
barcode=5099749939523
```

Explicit IDs are validated against the local track count. A mismatch produces
a warning but still proceeds (the user chose this ID deliberately).
