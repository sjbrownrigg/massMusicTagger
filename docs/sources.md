# Where the metadata comes from

massMusicTagger asks several places about an album and takes the first
confident answer. This page explains what those places are, how it decides an
answer is confident, and how to overrule it.

You do not need to read this to use the tagger. Read it when a release matched
something you did not expect, or did not match at all.

---

## The order it asks in

```yaml
source:
  priority:
    - discogs          # ask Discogs first
    - musicbrainz      # then MusicBrainz
    - existing_tags    # failing both, use what is already in the files
```

Each source is tried in turn and the first confident match wins. "Confident"
has a specific meaning: the number of tracks on the release has to match the
number of audio files you have, within two. A source that finds nothing, or
finds something with the wrong number of tracks, hands over to the next one.

For one run you can ignore the list:

```bash
mmt --source discogs      # Discogs only
mmt --source musicbrainz  # MusicBrainz only
mmt --source auto         # back to the priority list (the default)
```

Leaving `existing_tags` out of the list is a deliberate choice with a real
consequence: an album that matches nothing then **fails** and stays where it
is, rather than being filed from its own tags. That is what you want while
checking how well matching works, because otherwise a failure looks like a
success. Put it back when you want everything filed regardless.

---

## Discogs

Discogs is usually the better answer for vinyl, for older releases, and for
anything where the pressing matters.

**Credentials** go in `credentials/discogs.yaml`, or in the environment as
`DISCOGS_USER_TOKEN`, which wins. A personal access token is the simple
option; OAuth is there if you need it.

```yaml
discogs:
  user_token: ""        # a personal access token — the easy way
  consumer_key: ""      # OAuth, only needed if you are not using a token
  consumer_secret: ""
  skip_auth: false      # no authentication at all: metadata only, no images
```

> Discogs issues **one personal token per account**. Generating a token for a
> second application invalidates the first, so every deployment sharing an
> account must use the same token. massMusicTagger checks the token when it
> starts and stops with an explanation if it has been refused — otherwise a
> warm cache can hide a dead token for a whole run.

### How it decides

1. **An ID you gave it** — from `--releaseid` or an `id.txt` beside the album.
   Used even if the track count disagrees, because you chose it; the mismatch
   is logged.
2. **A `discogs_id` already in the file tags.** Checked against the track
   count, and *abandoned* if it disagrees — the tag may be left over from a
   release that has since gained a bonus track.
3. **A search**, by artist and title, scored on track durations. When Discogs
   has no durations for a release it falls back to comparing track titles, and
   `batch.title_similarity_threshold` (default 60%) decides how close counts.

```yaml
batch:
  searchdiscogs: true          # allow searching at all
  tracklength_tolerance: 5.0   # seconds of average difference still accepted
  title_similarity_threshold: 60
```

---

## MusicBrainz

MusicBrainz is often better for CDs and digital releases, and it is the source
of the typed cover art described below.

**Credentials** go in `credentials/musicbrainz.yaml`. There is no API key, but
MusicBrainz requires a user agent that identifies you and gives them a contact:

```yaml
musicbrainz:
  user_agent: "YourApp/1.0 (you@example.com)"   # required
```

### How it decides

It works down these in order, stopping at the first answer.

| # | Method | Needs |
|---|---|---|
| 1 | `mbid=` in an `id.txt` beside the album | — |
| 2 | A `musicbrainz_releaseid` already in the file tags | — |
| 2.5 | Fingerprint first, before searching by name — only when `acoustid_early` is on | AcoustID, below |
| 3 | Search by artist, album title and track count | — |
| 4 | Barcode, from `barcode=` in an `id.txt` | — |
| 5 | Disc ID — the CD's own table of contents, worked out from track lengths | `libdiscid` |
| 6 | Fingerprint one track | AcoustID |
| 7 | Fingerprint every track and take the release most of them agree on | AcoustID |

Tier 3 is the one that needs care, because a title is not unique. Two things
guard it:

- The album title must score at least **70%** against the candidate's title.
- The artist must score at least **60%**.

The artist floor is not a tie-break, it is a refusal: a candidate credited to
a different artist is skipped, not ranked lower. Without it, *Pariah* by Anja
Huwe was tagged as *Pariah* by Red Dons — same title, same two tracks, and
fourteen years apart.

### Caching

MusicBrainz and the Cover Art Archive are free services, so answers are kept
on disk and reused.

```yaml
musicbrainz:
  cache_directory: ""      # empty: use the state directory
  cache_metadata: true     # release data and the cover art index
  cache_images:   true     # the image files themselves
  cache_search:   true     # which release a search chose
  caa_request_delay: 0.5   # seconds between cover art requests
```

`cache_search` stores the *decision*, not the reply — so if the matching rules
change, old answers would otherwise stand. They are stamped with a version and
retire themselves when the rules change.

### Fingerprinting

Tiers 5 to 7 need two system libraries and one extra install:

```bash
sudo apt install libdiscid0 libchromaprint-tools
pip install "massmusictagger[fingerprint]"
```

AcoustID also needs a free application key from
[acoustid.org](https://acoustid.org/login):

```yaml
musicbrainz:
  acoustid_api_key: ""
  acoustid_early: false    # fingerprint before searching by name
```

---

## existing_tags

The last resort, and the only source that asks nobody anything. It reads the
metadata already in your files and uses it to name and file them.

**It writes no new tags.** Only filenames and folder structure change; what is
in the files is left exactly as it is.

It earns its place for bootlegs and rarities in no database, for incomplete
rips whose track count will never match a real release, and for keeping a
consistent shelf out of files you have already tagged by hand.

One limitation worth knowing: the artist name is taken from the files
verbatim. If your tags say `Wumpscut` and the databases say `:wumpscut:`, this
source will not correct it, and that artist ends up in two folders.

---

## Pinning a release yourself

When the tagger picks the wrong release — or cannot pick one — you can name it.

### For one album

```bash
mmt --releaseid 14726546 ~/Music/incoming/album
mmt --releaseid musicbrainz:4b8a0e1b-249b-4d11-8e6e-42aa23466b96 ~/Music/album
```

A bare number means Discogs. Qualify it when it is not, because the two
databases number releases completely differently — a Discogs number handed to
MusicBrainz is not a near miss, it is a different namespace.

`--releaseid` names one release, so it is refused when the directory you point
it at contains more than one album.

### For a whole tree: id.txt

Put a file called `id.txt` inside an album folder. It travels with the album,
so one run over a large collection can pin a different release for each one.

Every form below works:

```ini
# A bare Discogs release number
4319687

# The same, named
discogs_id = 4319687

# A MusicBrainz release
musicbrainz_id = 4b8a0e1b-249b-4d11-8e6e-42aa23466b96

# The older discogstagger3 layout, still accepted
[source]
name = discogs
discogs_id = 4319687
```

Two further entries are read by the MusicBrainz search rather than as the
release ID, and can sit in the same file:

```ini
mbid=4b8a0e1b-249b-4d11-8e6e-42aa23466b96   # a MusicBrainz release
barcode=5099749939523                        # looked up at MusicBrainz
```

An ID you gave is used even when the track count disagrees — you chose it, and
the mismatch is only logged. That is the difference from a `discogs_id` found
in the file tags, which is abandoned on a mismatch because it may be stale.

### Finding the numbers

**Discogs.** Open the release page and take the number from the end of the
URL: `discogs.com/release/`**`4319687`**`-Artist-Album`. Prefer the specific
pressing you own over a general entry — the tracklist and labels will match.

**MusicBrainz.** Open the **Release** page, not the Release Group, and take the
UUID from the URL:
`musicbrainz.org/release/`**`4b8a0e1b-249b-4d11-8e6e-42aa23466b96`**. The
release page also shows whether the Cover Art Archive has artwork for it.

### Using both together

If a release is in both databases, name both and set
`artwork.image_source: musicbrainz`. Discogs supplies the metadata and the
Cover Art Archive supplies typed, usually larger, artwork:

```ini
4319687
mbid=4b8a0e1b-249b-4d11-8e6e-42aa23466b96
```

---

## Where the artwork comes from

Artwork can come from a different place than the metadata:

```yaml
artwork:
  image_source: auto         # whichever source supplied the metadata (default)
  # image_source: musicbrainz  # always the Cover Art Archive
  # image_source: discogs      # always Discogs
```

The Cover Art Archive labels its images — Front, Back, Medium, Booklet — so
they can be named and embedded correctly. Discogs only says which image is the
main one, so its main image is written as `cover.jpg` rather than `front.jpg`:
the name claims less, because Discogs told us less.

With `image_source: musicbrainz` and metadata from Discogs, massMusicTagger
looks the release up by barcode to find the MusicBrainz ID it needs.

### Telling the tagger what kind of rip it has

Folder names often say. `source_hints.yaml` lists the words that give it away,
and a match becomes a hint used to reject an obviously wrong pressing — a
vinyl release will not be matched to a download.

```yaml
source_hints:
  digital:
    - "24 Bit"
    - "24B-"        # matches "[FLAC] [24B-44.1kHz]"
    - "WEB"
  vinyl:
    - "Vinyl Rip"
    - "Needle Drop"
```

Your own `source_hints.yaml` beside `config.yaml` **adds to** this list rather
than replacing it, so a copy does not freeze at whatever shipped that day.

---

## What happens to the source folder afterwards

```yaml
archiving:
  source_action: done_file
```

| Value | What it does |
|---|---|
| `done_file` | Leaves the folder alone and drops a marker so it is skipped next time (default) |
| `move` | Moves the folder into an archive tree |
| `remove` | Deletes the folder |

`move` and `remove` both check that the tagged output actually contains audio
before touching the original, so a silent failure earlier cannot cost you the
files.

```yaml
archiving:
  source_action: move
  source_archive_dir: "~/Music/archive"
  source_move_template: "%source%/%albumartist%/%current_folder%"
```

The template accepts every format-string variable, plus `%current_folder%` for
the original folder's own name. It is sanitised with the same character
profile as the destination, so one artist does not end up under two spellings.
