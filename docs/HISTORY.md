## Changelog

---

## Version 1.2.0 (2026-06-01)

---

### massMusicTagger

#### MusicBrainz search improvements

- **`acoustid_early` flag** — AcoustID fingerprinting can now run before text
  search (tier 2.5) by setting `acoustid_early: true` in
  `conf/musicbrainz_personal.yaml`.  This prevents popular-artist releases from
  matching the wrong pressing via title-score alone.  When early AcoustID
  returns a match, tiers 6-7 are skipped to avoid redundant fingerprinting.

  ```yaml
  musicbrainz:
    acoustid_early: true   # run fingerprinting before text search
  ```

- **Source format hints** — keyword lists in `conf/source_hints.yaml` are
  matched case-insensitively against the source folder name to infer whether
  files are digital or vinyl-rip origin.  When the inferred hint conflicts with
  the matched MB release's medium format, a `WARNING` is logged.  The match is
  still accepted — this is an audit signal, not a rejection.  Configurable via
  `musicbrainz.source_hints_file`; override with your own YAML for custom keywords.

- **DiscID false-match validation** — DiscID hits are now checked against the
  file's embedded artist and album tags using fuzzy scoring.  Hits with a low
  score on both fields are discarded, preventing false-positive CD-TOC collisions
  (e.g. a 1-track digital file matching an unrelated CD rip via identical disc
  length).

- **Normalise MB compound vinyl formats** — MusicBrainz returns compound format
  strings such as `12" Vinyl` instead of Discogs-style `Vinyl` + size in
  descriptions.  These are now split into `format='Vinyl'` with the size prepended
  to `format_description`, so the `vinyl_sizes` lookup in `format_codes.yaml`
  fires identically for both sources.

#### Format code fixes

- **12" vinyl albums display as `LP`** — the 12" size override now applies only
  to non-album release types (Single, EP, Maxi-Single).  A 12" LP album stays
  as `LP`; a 12" single still shows `12″`.  This is configured in
  `conf/format_codes.yaml` via the new `vinyl_sizes_conditional` section.

#### Source post-processing: `source_action`

A new `details.source_action` config key controls what happens to the source
directory after a successful tag:

| Value | Behaviour |
|---|---|
| `done_file` | Write a `.done` marker and leave source in place (default) |
| `remove` | Delete the source directory (verifies audio exists in output first) |
| `move` | Relocate the source into an archive tree |

`source_action: move` uses `source_archive_dir` (root) and
`source_move_template` (path template supporting all format variables plus
`%current_folder%` for the original folder name):

```yaml
details:
  source_action: move
  source_archive_dir: "~/Music/archive"
  source_move_template: "%source%/%albumartist%/%current_folder%"
```

#### Format string preview tool

`format_preview.py` evaluates format strings against fixture cases defined in
`conf/preview_cases.yaml` and prints results to stdout.  Useful for checking
directory naming and custom variable output without running a real tag operation.

```bash
python format_preview.py           # one-shot
python format_preview.py --watch   # re-run on file change
```

The tool loads the same config chain as MMT (base → personal overlay →
extra_configs), so output matches a real run exactly.

#### MusicBrainz caching

- **CAA image index cached** — the Cover Art Archive image index per release is
  stored so repeat runs do not re-fetch it.
- **Search results cached** — text search and barcode search MBIDs are cached
  keyed by query hash.  Set `cache_search: false` to re-run searches without
  clearing the cache.
- **CAA rate limit handling** — 429 responses from the Internet Archive are
  retried with backoff; 404s (no artwork) are distinguished cleanly.  A
  configurable `caa_request_delay` (default 0.5 s) keeps requests within safe
  rate limits.
- **Release-group CAA fallback** — when a specific pressing has no Cover Art
  Archive images, massMusicTagger tries the release group's artwork instead.

#### Logging and UI

- **Rich console handler** — the terminal log now uses `RichHandler` for
  readable, coloured output.  The log file always captures `DEBUG`-level output
  regardless of console level.
- **End-of-run summary table** — a per-album table is printed at exit showing
  the matched source (Discogs, MB, existing_tags), release ID, title, and
  elapsed time.  Albums that were already tagged in a previous run are tracked
  and excluded from the summary count.
- **EBUSY / locked file handling** — file-in-use errors on Windows/NAS mounts
  are caught and reported cleanly rather than crashing.

#### Tags

- **`tagger_source` tag** — records which source (discogs, musicbrainz,
  existing_tags) wrote the tags.  Useful for auditing which albums were matched
  and from where.

#### Bug fixes

- **`--force` on collection directories** — fixed a crash when `--force` was
  used on a directory containing multiple album subdirectories.
- **`existing_tags` artist inference** — the current directory name and parent
  directory name are both tried as artist candidates when the embedded artist
  tag is absent.

---

## Version 1.1.0 (2026-05-21)

This release covers improvements across both massMusicTagger and its
discogstagger3 core library.

---

### massMusicTagger

#### Source cascade

- **id.txt: old discogstagger3 INI format now recognised** — releases
  previously tagged by dt3 write an `[source]` / `discogs_id=N` style id.txt.
  The cascade reader now skips INI section headers and also tries the
  `discogs_id=VALUE` key, so these releases are correctly identified from
  Discogs rather than falling through to `existing_tags`.
- **id.txt: `mbid=` also supported in old INI format** — MusicBrainz MBIDs
  stored as `mbid=<UUID>` inside `[source]` sections are read correctly.
- **`existing_tags` format recovery** — when no API match is found,
  `album.format` and `format_description` are now parsed from the embedded
  `media` tag (`"1 x Cassette Bootleg"` → `format="Cassette"`), so directory
  names produced by the fallback source include a meaningful format code
  (`MC.B`, `LP`, …) rather than being blank.

#### MusicBrainz

- **Disambiguation → edition** — the MusicBrainz disambiguation string
  (e.g. `Beatport expanded version (US)`) is used as the `%edition%` value
  when `compute_edition()` finds no keyword match in the descriptions list.
- **DiscID tier 5 crash fixed** — `discid.put()` is now called with
  positional arguments; the installed library does not accept keyword form.
- **`Promotional` normalised to `Promo`** — MB's "Promotional" release status
  is normalised to match Discogs vocabulary so `%status%` is consistent across
  both sources.
- **Track count validation extended** — applied to all search result tiers
  (not only explicit IDs), so a mismatched result falls through to the next
  source rather than producing an incorrectly-tracked album.

#### Format string variables

- **`%disctotal%`** — added as the canonical name (matches the `disctotal`
  MediaFile attribute). `%totaldiscs%` remains a working deprecated alias.
- **`%status%`** — exposes release status (`Official`, `Promo`, `Bootleg`,
  `Pseudo-Release`) in format strings for use in directory naming.
- **Digital format code → `DM`** — `File`, `Web`, and `Digital Media` Discogs
  formats now produce `DM` instead of `file`/`web`.

#### Boolean format functions — `$any`, `$all`, `$neg`

Three new composable boolean functions eliminate deeply-nested `$if1()` chains
when testing multiple conditions:

- `$any(c1, c2, …)` — `True` if at least one argument is truthy (boolean OR)
- `$all(c1, c2, …)` — `True` if every argument is truthy (boolean AND)
- `$neg(cond)` — inverts truthiness (boolean NOT)

All three return `True`/`False` and are designed to nest inside `$if1()`.

#### Documentation

- **id.txt guide** — step-by-step instructions for finding Discogs release IDs
  and MusicBrainz MBIDs from their respective websites.  Old INI format
  documented and working.
- **Combined tag mapping table** in `docs/tagging_reference.md` — every tag
  written by discogstagger3 and massMusicTagger, with Discogs and MB sources,
  underlying tag names by format, and image handling.

---

### discogstagger3 (core library, pulled via git dependency)

#### Format code simplification

`%format_code%` now encodes only **physical medium + quantity**.  Release type
and edition qualifiers have been removed from the format code and are available
as separate variables:

| Before | After | Now via |
|---|---|---|
| `CDS` | `CD` | `%releasetype%` = `Single` |
| `LCDS` | `CD` | `%edition%` = `Limited Edition` |
| `7″S` | `7″` | `%releasetype%` = `Single` |
| `LDCD` | `DCD` | `%edition%` = `Limited Edition` |

New and updated variables:

| Variable | Description |
|---|---|
| `%format_base%` | Physical medium without quantity prefix (`CD`, `LP`, `12″`, `DM`) |
| `%releasetype%` | MB-style release type inferred from Discogs format descriptions |
| `%digital%` | `'1'` for digital formats, `''` for physical |
| `%disctotal%` | Total disc count (canonical; `%totaldiscs%` deprecated) |
| `%status%` | Release status: `Official`, `Promo`, `Bootleg`, `Pseudo-Release` |

#### Vinyl size rules

- **12" vinyl albums → `LP`** — a new `vinyl_sizes_conditional` section in
  `format_codes.yaml` applies the `12″` code only when a non-album type
  (`Single`, `Maxi-Single`, `EP`, `Mini-Album`) is in the descriptions.
  A 12" LP album stays as `LP`; a 12" single still shows `12″`.
- **7" and 10"** always show the size regardless of release type.

#### Vinyl track position labels

- **Full position preserved** — `disc_and_track_no()` now returns the complete
  position string (`A1`, `B3`, `C2`) as `real_tracknumber` so that
  `%tracknumber%` in format strings produces `A1 Title.flac` rather than
  `01 Title.flac`.
- **Sides paired onto physical records** — A+B = record 1, C+D = record 2,
  giving the correct `disctotal` for single and double LPs (previously each
  side was its own disc, doubling the count).
- **Letter-only positions** (`A`, `B`) — single-track-per-side releases now
  correctly produce just `A Title.flac`, not `0A Title.flac`.
- **`$num()` pass-through** — non-numeric values (vinyl positions) are returned
  unchanged by `$num()`; zero-padding only applies to bare integers.

#### New tags

| Tag | Source | Description |
|---|---|---|
| `barcode` | Discogs/MB | EAN / UPC barcode |
| `discogs_release_status` | Discogs/MB | `Official`, `Promo`, `Bootleg`, … |
| `releasetype` | Discogs/MB | MB-style primary release type |
| `musicbrainz_releaseid` | MB | Release UUID |
| `musicbrainz_releasegroupid` | MB | Release-group UUID |
| `musicbrainz_trackid` | MB | Recording UUID per track |
| `isrc` | MB | ISRC code per track |

#### Custom variables (`[custom-variables]`)

- New `[custom-variables]` INI section for reusable format string fragments
  referenced as `%__varname__%`.
- **Nested references** — a custom variable may reference other custom
  variables (up to 5 expansion passes).
- **Critical quoting rule** documented — variables that expand to `$function()`
  calls must not be wrapped in single quotes when used as function arguments.

#### Boolean format functions

`$any()`, `$all()`, `$neg()` — see massMusicTagger section above.  These are
implemented in discogstagger3 and available in both projects.

#### Bug fixes

- `.done` marker file no longer copied into the sorted output directory when
  re-tagging with `--force`.
- Empty year guard prevents `int('')` crash when a release has no date.
- `labels[0]` IndexError fixed when an album has an empty labels list.
- Preliminary target directory: technical properties (`%codec%`, `%quality%`,
  etc.) guarded against `None` to prevent `None--NNone` in directory names.

#### License

GPL-3.0-or-later added to both repositories.

---

## Version 1.0.0 (2026-05-18)

Initial release of massMusicTagger.

Built on discogstagger3 (v3.0.3) as a shared-core dependency.

### Features

- **Configurable source priority** — `source.priority` list controls which
  metadata sources are tried and in what order.  Sources: `discogs`,
  `musicbrainz`, `existing_tags` (fallback organiser).
- **MusicBrainz adapter** — full Release → Album/Disc/Track mapping;
  Cover Art Archive image download; MBID and ISRC tags.
- **MusicBrainz search** — tier 1 (MBID from id.txt), tier 2 (text search
  with fuzzy title matching + track count), tier 3 (AcoustID fingerprinting,
  optional dependency).
- **existing_tags fallback** — when no API match is found, organises files
  using metadata already embedded in the audio files.  No API calls; no
  tag overwrites.
- **Concurrent processing** — `batch.workers` controls the thread pool size.
- **Rich progress display** — per-album status in the terminal.
- **Structured audit log** — JSON log of every processed directory.
- **Dry-run mode** (`--dry-run`) — compute proposed changes without writing.
- **Interactive review mode** (`--review`) — confirm each album match
  interactively before tagging.
- **Rollback** (`--undo DIR`) — remove tagged output and done marker using
  the audit log.
- **Watch / daemon mode** (`--watch`) — PollingObserver for CIFS/NFS mounts.
