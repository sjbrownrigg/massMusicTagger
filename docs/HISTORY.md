## Changelog

---

## Version 3.5.0 (2026-08-30)

### Added

**`batch.cpu_jobs` — one global cap on CPU-heavy external work.** Concurrent
decode threads were `batch.workers` x `os.cpu_count()`: each worker started
its own `r128gain`, and nothing passed `-c`, so r128gain fell back to
`os.cpu_count()`. On a four-core host at `workers: 4` that is up to 32 decode
threads on four cores — thrash rather than throughput.

Workers and CPU concurrency are different concerns and now have separate
dials. Workers exist to overlap *waiting*, which still dominates: reading a
345 MB album from the NAS took 33.0s against 19.1s to scan it, with the
container at 1.5% CPU. Keep `workers` high for the link; `cpu_jobs`
(default 1) bounds the CPU-heavy subprocesses they start.

One semaphore covers all of them — `r128gain`, `shntool` and `flac` for CUE
splitting, `ffmpeg` for transcoding, `fpcalc` for fingerprinting — because
the contended resource is the CPU itself. Per-stage queues would each run at
their own cap simultaneously and rebuild the problem a level up.

**`replaygain.thread_count`** (default 2) is passed as r128gain's `-c`.
Measured on 12 FLAC / 345 MB from local disk it saturates at two threads:
35.1s, 19.1s, 20.1s, 20.6s at `-c 1/2/4/8`. Everything above two was already
contention. The effective ceiling is now `cpu_jobs` x `thread_count` — on a
`workers: 4` deployment, 2 threads rather than 32.

Both keys are new with defaults, so an existing configuration keeps working
and simply gains the cap. `mmt --new-config` writes them documented; run
`mmt --annotate-config` to add the reference comments to a config you
already have.

### Fixed

**A stale error told you to pass `-c <config.yaml>`,** a switch removed in
3.0.0. It now names the discovery order: `$MMT_CONFIG_DIR`, then
`$XDG_CONFIG_HOME/massmusictagger`, then `~/.config/massmusictagger`.

---

## Version 3.4.1 (2026-08-30)

### Fixed

**`--annotate-config` refused on a configuration holding a setting the
reference does not describe.** Those were appended under a fresh section
header — a duplicate key, and YAML keeps the last one, so the section built
from the reference was silently discarded along with every other setting in
it. On a real configuration that meant `source_dir`, `dest_dir` and
`watch_poll_interval` reported as lost.

The check that runs before writing caught it and refused, which is the only
reason this was an error message rather than a wrecked configuration.
Unrecognised settings are now inserted into their existing section, marked
`# Not described by the reference configuration.`, and a new header is only
created for a section that is genuinely new.

---

## Version 3.4.0 (2026-08-30)

### Added

**`mmt --annotate-config`** puts the reference comments back into a
configuration that has lost them. A file carried forward for years holds the
right settings and none of the explanation — the comments were in the sample
it was first copied from, and nothing has ever put them back.

It walks the packaged sample and substitutes the value you have for each
setting, so the result is the reference's structure and commentary with your
answers in it. On a real deployment: 68 comment lines to 197, 49 settings
unchanged.

Nothing changes but the comments. The result is compared with the original
before anything is written, in both directions — gaining a setting is as much
a change as losing one — and the command refuses rather than guessing. A
setting you have not set is written out commented, documented but not
applied. The original is kept as `config.yaml.bak`.

### Fixed

**The sample pinned the user agent.** `common.user_agent` is built from the
running version precisely so it cannot go stale, and the sample carried a
literal copy — so every configuration made with `--new-config` froze it at
whatever that line said, which was `2.0.0` through two major versions. The
sample now shows it commented out, with the reason.

---

## Version 3.3.0 (2026-08-30)

Configuration you can see and change, and one wrong-artist match closed.

### A different artist is a different record

MusicBrainz tier 3 ranked candidates by a lexicographic
`(title, artist, date)` tuple, so a perfect title beat *any* artist score,
and nothing rejected a candidate on the artist alone. Tier 3 compares title
and track count and nothing else, so once ranking failed to express "wrong
artist", there was nothing left to catch it: **"Pariah" by Anja Huwe (2024)
was tagged as "Pariah" by Red Dons (2010)** — same title, same two tracks.

A candidate whose credited artist scores below 60% against ours is now
skipped rather than ranked lower. That mismatch scores 35; every legitimate
variation measured scores 62 or more, and all six are tested.

**A cached search hid the fix.** The search cache stores the chosen MBID, not
the API response, so a cached answer bypasses ranking entirely and the fix
appeared not to work. The cache key now carries a logic version that retires
old answers when the matching rules change.

Discogs was never affected: it validates on track durations, or track-title
similarity when durations are missing.

### The rule tables are yours to read

`--new-config` now writes `format_codes.yaml`, `char_substitutions.yaml` and
`source_hints.yaml` into a new configuration, **entirely commented out**.
They were not written at all, which kept them improving with each upgrade and
left nobody able to find out what the rules were.

A commented template answers both: the file is there to read and edit, and
until a line is uncommented it changes nothing. What you do uncomment is
merged over the packaged table, so changing one abbreviation keeps the rest
and keeps gaining later additions.

`--migrate-config` retires deprecated keys too. It handled moved and removed
ones, so a migrated configuration still carried live `format_codes`,
`char_substitutions` and `source_hints_file` keys — each naming a `conf/`
path that resolves to nothing, each warning on every run. They are commented
out in place with the reason written above them. **A configuration migrated
before 3.3.0 should be migrated again**; the second pass is otherwise a no-op.

### The format hint missed the bit depth in use

`source_hints.yaml` is meant to spot a hi-res source from its folder name,
and its digital list had `24 Bit`, `24bit` and `24-Bit` — none of which match
`[FLAC] [24B-44.1kHz]`. No hint was produced, so nothing distinguished a
24-bit download from a CD rip. The abbreviated spellings are now included,
written with their surrounding punctuation so "Symphony No 24b" does not
match, and a user's hints file **adds to** the packaged one rather than
replacing it — a copy otherwise froze the token list at whatever shipped that
day.

### Artwork and archiving

- **An MP3 kept one embedded image out of four.** ID3 keys a picture frame by
  its description and every image was written with the same empty one, so each
  overwrote the last: an album ended up with a 165×165 untyped thumbnail as
  its only artwork. FLAC was unaffected, which is why it went unseen.
- **The archive path is sanitised** with the same character profile as the
  destination. `:wumpscut:` was filed as `-wumpscut-` in sorted and
  `:wumpscut:` in archive — one artist in two places, and a path a
  Windows-hosted share would refuse outright.

---

## Version 3.2.0 (2026-08-29)

Everything here was found by re-tagging a real 413-album library and looking
at what came out.

### Settings that silently did nothing

Three settings decide how a release is named, and all three were reached
through a config key naming a `conf/` path that only resolves from a source
checkout. All three failed the same way: quietly, with the feature off.

- **`format_codes`** — a release on Digital Media was filed as
  `Digital Media` rather than `DM`, because a missing file returned an empty
  rule table and every abbreviation switched off.
- **`char_substitutions`** — already warned, but still applied nothing, which
  is what left `char_profile: windows` inert across a whole library.
- **`source_hints_file`** — the same shape.

They now behave identically: found by name in the configuration directory
like `formats.ini`, a packaged table as the default so it keeps improving
with upgrades, a named-but-missing file warns and falls back rather than
switching off, and a user table is **merged over** the packaged one so
overriding a single abbreviation does not discard the rest. The path keys are
deprecated — still honoured, and honoured first, since an explicit setting is
a request.

`conf/` now holds only the samples `--new-config` writes from and those
packaged tables. `logger_default.conf` is deleted; nothing had read it since
`logging.config_file` was removed.

### A warning that fired on 97% of albums

The bad-match warning fired whenever the album artist equalled the first
track's artist — which on a single-artist album is true by definition. It
fired on 371 of 379 albums. It now fires only on compilations, where an album
artist equal to the track artist genuinely does mean the various-artists
credit was missed.

### Artwork

- **Local covers are matched without regard to case.** `LOCAL_COVER_NAMES` is
  lowercase and the lookup used the exact spelling, so on a case-sensitive
  share `Front.jpg` was invisible and `prefer_larger` had nothing to compare.
- **Artwork subdirectories are searched** — `Covers/`, `scans/`, `artwork/`
  and friends, where 58 of 412 albums keep their best scan. Within one, only
  a name that says front cover is accepted: these directories mostly hold
  `cd.jpg`, `back.jpg` and booklet scans, and `quality/` holds spectrograms.
- **A subdirectory cover must be the same *shape*** to win, not merely
  larger. Of the 18 that are larger, 15 are around 2.4:1 — front and back
  scanned on one sheet — so choosing on size alone embeds a sleeve spread as
  the front cover 17 times out of 18.
- **A second front cover no longer deletes the first.** Cover Art Archive
  returns two for some releases; the supersede step removed the earlier
  download, leaving `front-01.jpg` and no `front.jpg`.
- **`image_policy` decides the front cover once.** It was applied to every
  front slot, comparing each against a local cover that a previous slot had
  already superseded and deleted.
- A kept local cover keeps **its own** extension, and one promoted out of
  `Covers/` is copied rather than moved, so the scan set stays complete.

### CUE handling

- **A single-file album with two cue sheets is now split.** A ripper often
  leaves `album.cue` beside `album.flac.cue`, or `album FLAC.CUE` beside
  `album WAV.CUE`; counted separately they outnumber the audio, and the test
  for a single-file rip is that the counts match — so the album reached the
  tagger as one untagged track and matched nothing.
- A dry run says why it cannot match a CUE album, rather than reporting a
  failure that reads as a prediction about the real run.

---

## Version 3.1.0 (2026-08-29)

### Security

**Metadata could execute code during tagging.** `$inarray` and `$flatten`
both parse a list, both tried `json.loads` first, and both **fell back to
`eval()`** on the value. Both are meant to be pointed at metadata:

```
$if1($inarray('%album%','Box Set'),'B','')
```

so an album titled `__import__('sys')…` ran that code. Discogs titles are
editable by anyone with an account, and the release being tagged is chosen
by matching against them, so this was reachable in ordinary use. Closed with
`ast.literal_eval`, which reads the same literals and cannot call anything.
JSON and Python-literal lists still work.

Anyone tagging against Discogs with a version before 3.1.0 should upgrade.

### Format strings are parsed, not `eval`ed

The foobar2000 dialect is unchanged — all 50 dialect cases and all 70
renderings of a real `formats.ini` come out byte-identical. What changed is
how it is evaluated.

`parseString` used to find a balanced `$fn(...)`, rewrite `$` to `self.`,
and hand the result to `eval()`; nesting worked because Python's parser did
it. The cost was that metadata had to be spliced into Python source, so
every character meaningful to Python was neutralised on the way in — `'`
became `\x27`, `$` became a private-use codepoint, and `\` was never
handled at all, so an album called `AC\` could not be tagged.

`naming/formatparser.py` parses the dialect directly. Two contexts: text is
literal, with `$name(` and `%name%` embedded in it; an argument list is an
expression, where terms concatenate, `+` joins them as it did under `eval`,
and `\+` is a literal plus.

**Values are data now**, resolved at evaluation time and never parsed. A
title containing an apostrophe, dollar, bracket, comma, plus or backslash is
simply a string, and all three escaping hacks are gone.

### An ambiguous index entry is settled by the file count

Discogs groups sub-tracks under a `type='index'` entry. Two shapes are
unambiguous; anything else — both durations present, or neither — reads
equally as one file or several. Across 23,102 cached releases that is 12% of
index entries (85 of 711), and nothing in the data settles them.

So nothing guesses: collapsing stays the default, and the number of files on
disk chooses when it disagrees. One rule, used by the search, by explicit-ID
validation, and by the mapper — a release accepted with *N* tracks and
tagged with *N−1* would be worse than rejecting it.

### Added

- **`mmt --migrate-config`** moves a 2.x configuration to the 3.0.0 section
  names in place, keeping every comment and writing a `.bak` first.
- **`format_preview.py` works again.** It still imported `discogstagger`, so
  it had been dead since the core was absorbed. `--conf <dir>` previews
  against a real configuration rather than the sample.

---

## Version 3.0.0 (2026-08-29)

massMusicTagger no longer depends on discogstagger3. It carries the tagging
core itself, and Discogs and MusicBrainz are peer sources feeding one
pipeline.

discogstagger3 is untouched — same repo, same CLI, same behaviour, still
standing alone for its own users. It simply stops being a dependency.

### Breaking changes

**`[details]` is gone.** It had grown to 28 of 69 keys, covering filename
casing, character profiles, artwork policy, source archiving and tag
handling — settings with nothing in common but having nowhere else to go. It
was the single biggest reason the configuration read as confusing. Its keys
are now:

| Section | Holds |
|---|---|
| `[naming]` | casing, character profiles, format codes, artist joining |
| `[artwork]` | embedding, image policy and source, `folder.jpg` |
| `[archiving]` | `source_action`, archive directory, move template, done file |
| `[tags]` | `keep_tags`, beside `suppress_tags` |
| `[source]` | `source_hints_file`, beside `priority` |

The old names are **not** honoured. A configuration still using them is told
which section each setting moved to and that it is not being applied — an
"unknown key" warning is not something a person can act on. A genuine typo
still reads as a typo.

**Settings removed**, because nothing read them. Each loaded without
complaint and did nothing:

- `details.split_discs` — multi-disc layouts come from the directory tree
- `tags.encoder` — the encoder is chosen per target format in `[conversion]`
- `logging.config_file` — logging is `logging.level` and `logging.log_file`
- `source.discogs`, `source.amg`, `source.local` — the source-to-tag-field
  mapping, whose only remaining user was `id.txt`, which reads `<source>_id`
  directly now. AllMusic has not been a source for a long time.

**`use_lower_filenames`** moves to `[naming]` and is properly deprecated: it
sets all six case keys at once, which they can now differ from.

### Things that claimed to work and did not

The theme of this release. None of these raised an error; each produced a run
that looked successful.

- **`--releaseid` was accepted and thrown away.** argparse took it, `--help`
  documented it, `cascade.search_and_map` implemented it in full — and
  `MassProcessor` never passed it, so `-r <id>` searched anyway. It also
  accepts `musicbrainz:<mbid>` now, because the sources number releases
  differently.

- **`--dry-run` rewrote the files it was reporting on.** CUE splitting and
  `.m4a` conversion happened inside the function that lists directories, which
  runs before the flag is consulted. Scanning and preparing are separate
  stages now: `scan()` reads, `prepare()` writes and reports.

- **`id.txt` was honoured as a marker and its contents ignored.** The reader
  that pulls the release ID out of it had no callers. There were also two
  parsers, and the one that ran only ever looked for `discogs_id`. One reader
  now accepts every format there has been, and routes the ID to the source
  the file names.

- **A Discogs token was trusted without being checked.** The connector logged
  "Authenticated" because the string was non-empty. Discogs issues one token
  per account, so registering a second application invalidates the first — and
  with a warm cache a whole run completed while every live call was refused.

- **`prefer_larger` always lost against the Cover Art Archive**, which never
  reports dimensions, so the comparison was skipped and the download won. A
  1400×1400 local scan sat beside a 600×600 download, with `folder.jpg` copied
  from the smaller one.

- **`logging.level` did nothing.** A daemon container runs `mmt -w` with no
  tty, so the config file was the only place the level could come from.

- **Credentials vanished under a bracketed config path.** `[` and `]` are glob
  character classes, and this project puts brackets in directory names by
  convention.

- **A release with no year became `[1900]`**, and a missing year is now taken
  from the Discogs master where there is one.

### Artwork

Artwork follows the Cover Art Archive naming convention, from every source.
There is one type table where there were two, already drifted apart on five
types: `Tray`, `Spine`, `Sticker`, `Poster` and `Liner` were being flattened
to `image-01.jpg`, discarding what the source had told us.

Untyped album art — Discogs says only primary/secondary — is `cover.jpg`.
Anything untypeable is `image-01.jpg`, `image-02.jpg`. A file is named for
what its bytes are, not what its URL claims. `file-formatting.image` is
deprecated: it no longer names anything.

The second image pipeline is gone. `FileHandler.get_images()` had been
unreachable since the Attachment work but still carried its own copy of the
policy logic, including the `prefer_larger` bug above.

### Internals

- Every config key has a default, in one table. Fifteen of massMusicTagger's
  own had none — a leftover of the era when the schema lived in the other
  package — so each call site carried its own idea of the fallback.
- `register_known_keys` and `register_freeform_sections` are gone: extension
  points for an embedding package, and there is one package now.
- The suite is 358 tests, up from 211. The image tests run against a real
  directory rather than mocks, which is how several of the above were found.

---

## Version 2.0.0 (2026-08-27)

Configuration follows discogstagger3 4.0.0: a **directory** massMusicTagger
finds for itself, holding only files the user owns.

### Breaking changes

**`-c` / `--config` is gone.** A configuration is `config.yaml`, `formats.ini`
and `credentials/` resolving relative to each other — it moves as a unit, so the
directory is what gets selected:

```bash
MMT_CONFIG_DIR=/path/to/config mmt
```

Found via `MMT_CONFIG_DIR`, else `$XDG_CONFIG_HOME/massmusictagger`, else
`~/.config/massmusictagger`.

**No more running from the sample config.** `_default_config_path()` walked up
from `__file__` looking for a `conf/` directory at a repo root — which only
worked from a source checkout — and fell back to `config_sample.yaml` when it
found nothing, so a pip-installed copy silently ran on sample settings. A
missing configuration now refuses to run (exit 78) and says how to create one.

**`extra_configs` deprecated.** Every `credentials/*.yaml` beside `config.yaml`
is loaded automatically, in name order. With one configuration directory there
was nowhere else for these files to be, so listing them was a list to keep in
sync for no benefit. The setting still works and warns.

### New

- **`ACOUSTID_API_KEY`** in the environment overrides
  `musicbrainz.acoustid_api_key`, matching how `DISCOGS_USER_TOKEN` already
  worked — so neither credential has to be written into a file that could be
  committed or reach an image layer.
- **`musicbrainz.acoustid_submitter_key`** (and `ACOUSTID_SUBMITTER_KEY`) added
  as a documented home for the AcoustID submitter key, which is a different
  credential from the application key and not interchangeable with it.

  AcoustID calls **both** an "API key", which is the whole confusion — the page
  at `https://acoustid.org/api-key` hands you the *submitter* key, while
  `acoustid_api_key` wants the *application* key from registering an app at
  `https://acoustid.org/login`. Ours is named for its role so it collides with
  neither.

  ```
  acoustid.match(api_key, path)             lookup      — application key
  acoustid.submit(api_key, user_key, data)  submission  — both
  ```

  Reserved: massMusicTagger only looks up, so nothing reads it yet. It exists
  so the key has somewhere to live other than `acoustid_api_key`, where it
  fails quietly.
- **`--new-config [DIR]`** writes `config.yaml`, `formats.ini` and a
  `credentials/` directory seeded with `discogs.yaml` and `musicbrainz.yaml`.
  Never overwrites; `--force-new-config` overrides.
- **`--version`**, reporting the installed version.

### The config directory

```
config.yaml              your settings
formats.ini              your file and directory naming (found automatically)
credentials/             API tokens, one file per source (all loaded)
  discogs.yaml
  musicbrainz.yaml
```

Nothing references anything else by path. Mako templates and the tagging rule
tables belong to discogstagger3 and ship inside that package.

### Fixes

- **`extra_configs` resolved against the working directory first**, and the
  config file's own directory only as a fallback — the opposite of what its
  docstring said. In the container the working directory is `/app` and the image
  carried defaults at `/app/conf`, so a bare `conf/discogs.yaml` in a mounted
  `/config/config.yaml` resolved to the image's empty sample: credentials
  appeared configured and were silently not loaded.
- **Credentials were baked into image layers.** `COPY . /src/mmt` with no
  `.dockerignore` wrote `conf/discogs.yaml`, `conf/musicbrainz.yaml` and
  `docker/.env` into the image, where they persist regardless of later layers.
  Rotate any credentials used with an image built before this release.
- **Credentials supplied via the environment were rejected at startup.**
  Validation read `discogs.user_token` from the config only, so a container
  passing `DISCOGS_USER_TOKEN` — which is what `compose.yaml` does — was
  refused for a credential it had. Validation now honours the same environment
  overrides discogstagger3 applies when connecting.
- **The MusicBrainz cache defaulted under `HOME`.** In the container the `mmt`
  user's home is `/app`, which is not writable, so the run died before doing
  anything. `MMT_CACHE_DIR` now sets it, defaulting to `$XDG_CACHE_HOME`. The
  bundled samples no longer hardcode `~/` paths for
  `musicbrainz.cache_directory` or `batch.audit_log` either.
- **massMusicTagger's own config keys were reported as typos** by
  discogstagger3's unknown-key check. They are now registered via
  `config_schema.register_known_keys()`, so checking covers both sets and a typo
  in a massMusicTagger setting is still caught.

### Packaging

Three things massMusicTagger shipped were only ever reachable from a source
checkout, and each failed quietly rather than loudly:

- **The reference samples are now inside the package.** They are the source
  `--new-config` copies from, and the lookup walked up from `__file__` to a
  repo-root `conf/` — nonsense once installed. `mmt --new-config` was writing
  discogstagger3's sample with none of massMusicTagger's settings and skipping
  the credentials files entirely.
- **`source_hints.yaml` is now inside the package.** It was named by a
  working-directory-relative path and was not in the wheel, so
  `_load_source_hints()` found nothing and returned `{}` — the source-hint
  feature was inert for every installed copy, indistinguishable from having
  configured no hints.
- **`conf/format_codes.yaml` and `conf/char_substitutions.yaml` are gone.** Both
  were stale copies of tables discogstagger3 owns and ships. `char_substitutions`
  was byte-identical; `format_codes` differed only in comments and list order
  while *missing* `unknown_format_code`. An installed copy was already using
  discogstagger3's, so this removes a divergence only a checkout could see.

`conf/` is also ignored by default now rather than by name, so a new
configuration or credentials file added there is not committed by accident.

### Testing

The suite pointed `MMT_CONFIG` at `conf/config.yaml` — a gitignored live
configuration that only exists on a machine where someone has configured the
tool. **68 tests were passing for that reason** and would have failed on a fresh
clone or in CI. They now use the packaged sample.

Two tests in `test_mb_album.py` loaded `conf/format_codes.yaml` behind an
`if fc:` guard, turning a missing file into a silent skip. Those assertions had
already stopped running; they now load the packaged table and assert it loaded.

### Housekeeping

The Docker deployment moved to its own repository,
[docker-mmt](https://github.com/sjbrownrigg/docker-mmt).

### Upgrading

```bash
mmt --new-config
```

Then copy your settings across, and move `conf/discogs.yaml` and
`conf/musicbrainz.yaml` into `credentials/`. To keep your existing directory
instead, point `MMT_CONFIG_DIR` at it and remove `extra_configs`.

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
