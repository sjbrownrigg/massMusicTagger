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
| 2.5 | Early AcoustID — runs before text search when `acoustid_early: true` | `pip install massmusictagger[acoustid]` + `apt install libchromaprint-tools` |
| 3 | Text search — artist + album title + track count (with artist similarity scoring; tries parent directory name if albumartist tag absent) | — |
| 4 | Barcode lookup via MB API | — |
| 5 | DiscID — CD TOC hash from file durations; validated against embedded artist/title tags to prevent false matches | `pip install massmusictagger[discid]` + `apt install libdiscid0` |
| 6 | Single-track AcoustID fingerprint (skipped when tier 2.5 fired) | `pip install massmusictagger[acoustid]` + `apt install libchromaprint-tools` |
| 7 | Multi-track AcoustID — all tracks fingerprinted; release with most matching recordings wins (skipped when tier 2.5 fired) | same as tier 6 |

### MusicBrainz-specific config keys

```yaml
musicbrainz:
  user_agent: "YourApp/1.0 (your@email.com)"   # required by MB API
  acoustid_api_key: ""   # register at https://acoustid.org/login
  acoustid_early: false  # run fingerprinting before text search (tier 2.5)
  cache_directory: "~/.cache/massmusictagger/mb"
  cache_metadata: true   # release JSON + CAA image index
  cache_images:   true   # downloaded Cover Art Archive image files
  cache_search:   true   # text search and barcode search result MBIDs
  caa_request_delay: 0.5 # seconds between CAA requests (increase if rate-limited)
  source_hints_file: "conf/source_hints.yaml"  # keyword lists for format hint warnings
```

### Source format hints

When `source_hints_file` is set, massMusicTagger checks the source folder name
against keyword lists to infer whether the files are digital or vinyl-rip origin.
If the inferred hint conflicts with the matched MB release's medium format, a
`WARNING` is logged.  The match is still accepted.

```yaml
# conf/source_hints.yaml
source_hints:
  digital:
    - "24 Bit"
    - "Remaster"
    - "WEB"
    - "Hi-Res"
  vinyl:
    - "Vinyl Rip"
    - "Needle Drop"
```

Point `source_hints_file` at a personal file (`conf/source_hints_personal.yaml`,
gitignored) to extend or override the defaults without modifying the shipped file.

### Installing fingerprinting support

```bash
# System libraries
sudo apt install libdiscid0 libchromaprint-tools   # Debian/Ubuntu

# Python packages
pip install "massmusictagger[fingerprint]"   # installs both discid + pyacoustid
```

---

## Post-processing: source_action

After a successful tag, `details.source_action` controls what happens to the
source directory:

| Value | Behaviour |
|---|---|
| `done_file` | Write a `.done` marker and leave the source in place (default) |
| `remove` | Delete the source directory (verifies audio files exist in output first) |
| `move` | Relocate the source directory into an archive tree |

```yaml
details:
  source_action: move
  source_archive_dir: "~/Music/archive"
  # Path template for source_action=move. Supports all format variables plus:
  #   %current_folder% — original source directory basename
  source_move_template: "%source%/%albumartist%/%current_folder%"
```

The `remove` and `move` actions verify that the output directory contains at
least one audio file before deleting or moving the source, guarding against
data loss if the sort step failed silently.

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

Place an `id.txt` file inside the album directory to pin a specific release.
Explicit IDs are validated against the local track count — a mismatch logs a
warning but still proceeds (you chose this ID deliberately).

### Supported entries

```
# Discogs release ID — the number from the release URL:
4319687

# MusicBrainz release MBID — the UUID from the release URL:
mbid=4b8a0e1b-249b-4d11-8e6e-42aa23466b96

# Both in one file (uses Discogs for metadata, MB MBID for CAA images):
4319687
mbid=4b8a0e1b-249b-4d11-8e6e-42aa23466b96

# Barcode lookup (MusicBrainz barcode search — useful when no MBID is known):
barcode=5099749939523

# Old discogstagger3 INI-style format also accepted:
[source]
discogs_id=4319687
```

### How to find the Discogs release ID

1. Search for the release at [discogs.com](https://www.discogs.com) and open
   the release page.
2. The release ID is the number at the end of the URL:
   `https://www.discogs.com/release/**4319687**-Artist-Album`
3. It is also shown at the bottom of the release page under
   *Release page* → *Discogs release ID*.

Use the most specific pressing — e.g. the original UK first press rather than
a generic master entry — for the most accurate tracklist and label data.

### How to find the MusicBrainz release MBID

1. Search for the release at [musicbrainz.org](https://musicbrainz.org) and
   open the **Release** page (not Release Group — the Release has the specific
   pressing details).
2. The MBID is the UUID in the URL:
   `https://musicbrainz.org/release/**4b8a0e1b-249b-4d11-8e6e-42aa23466b96**`
3. It is also shown on the release page under *Release information* →
   *MusicBrainz Release ID*.

The MB release page also links to the Cover Art Archive if typed images
(Front, Back, Medium) are available — useful to confirm before tagging.

### Tip: use both IDs together

When a release exists in both databases, pin both IDs and set
`image_source: musicbrainz` in your config. massMusicTagger will use Discogs
for metadata (often more complete for vinyl / older releases) and Cover Art
Archive for typed, higher-resolution images:

```
4319687
mbid=4b8a0e1b-249b-4d11-8e6e-42aa23466b96
```
