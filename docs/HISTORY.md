## Changelog

---

## Version 3.19.2 (2026-09-03)

### Changed

**The title check is a veto, and it sits after the length match.** On a short
release a title mismatch now refuses a candidate outright on the Discogs path
too, once the track lengths have already agreed. Folding it into the score
would only move a wrong release down the ranking, and on a two-track single
there is often nothing else in the ranking to beat it.

### Fixed

**Titles that name nothing no longer veto.** An untagged or placeholder-tagged
rip carries titles like `Track 01` or `02`, which score near zero against real
ones — so a check meant to catch wrong matches would have refused right ones,
on exactly the material that most needs a database to tell it what it is. The
veto now stands down for placeholder titles, and for a rip that names only some
of its tracks: the evidence is absent, not contradictory.

---

## Version 3.19.1 (2026-09-03)

### Fixed

**A two-track single could be accepted as a different two-track single.** Their
track counts are equal by definition and their durations line up by chance
often enough to be worthless as evidence.

Red Cell's *Good Morning, Good Light* — Radio Edit 180s and *Only Night* 182s —
was accepted as the *Acoustic Version* release, whose two tracks are 176s and
180s. *Only Night* was retagged as a radio edit of a different song, destroying
the title it arrived with.

It came through MusicBrainz tier 3, which ranks on release title, artist and
track count: `Good Morning, Good Light` partial-matches `…(Acoustic Version)`,
the artist is identical and 2 == 2. Durations were never consulted on that
path. On the Discogs path they would have been, and would have agreed — every
pairing falls inside the 10-second tolerance — so neither source had anything
left to object with.

For a release of four tracks or fewer, every local track must now find a
counterpart title on the candidate. The wrong folder scores 33 on its weakest
track and the right folder 100 on both, so the two separate cleanly. Above that
size a stray track means a bonus track rather than a wrong release.

A veto only — durations and track counts still decide which release wins — and
it does not fire when either side has no titles, or when the local files cannot
be read.

---

## Version 3.19.0 (2026-09-03)

### Added

**A completeness guard.** `batch.completeness_guard`, off by default. When on,
a release holding fewer tracks than its own `tracktotal` says it should is not
tagged, and is not even looked up.

The number comes from the files themselves, so this is a statement about the
material rather than about any database. Refusing rather than tagging what is
there follows from a library that holds whole releases: tagging the fragment
files it away as though it were the album, and it stops being visible as a gap.

Refused releases carry an outcome of their own — distinct from `failed`, which
means the databases were asked and had no answer, and from `skipped`, which the
user asked for. The end-of-run report lists them separately with what they
hold, what was expected, and which track numbers are missing, so a run doubles
as a re-acquisition list.

Multi-disc sets are summed per disc, since `tracktotal` counts one disc, and a
gap names the disc it is on. CUE images are split before the check runs, so
they are counted as the tracks they become. A release whose files declare no
`tracktotal` cannot be judged and is allowed through.

Measured on this library when the guard was written: of 118 album folders in
`/incoming`, 90 were complete, 7 short, 8 held more files than expected, 10
were unsplit CUE images and 3 declared no `tracktotal` at all.

---

## Version 3.18.2 (2026-09-03)

### Fixed

**Join words broke the single-track artist comparison.** A rip tagged
`Trentemøller, Marie Fisker` against MusicBrainz's `Trentemøller feat. Marie
Fisker` shares every name and still failed the containment test, because
`feat` sits in the middle of one and not the other. Two of seven realistic
collaboration credits from this library were refused that way.

Latent rather than observed — the track-count check rejects these before the
artist rule is reached — but modern singles are largely collaborations and the
two sides rarely agree on the join, so it would have bitten as soon as one
found a candidate with a matching track count.

The join words now come from `conf/artist_joins.yaml` rather than a second
hardwired list, so the same table decides how a credit is filed and how two
credits are compared.

---

## Version 3.18.1 (2026-09-02)

### Fixed

**The single-track artist rule did nothing for albums already searched.** The
MusicBrainz search cache stores the *decision*, not the API response, so a
cached answer bypasses ranking entirely — Thomas Feiner's *The Ship Song* kept
resolving to Thomas Anders from a stored decision, and 3.18.0 looked broken
when it was not.

`SEARCH_LOGIC_VERSION` is now 3, retiring every stored decision. The docstring
on that constant already described this failure from the previous time it
happened, with the minimum artist similarity.

---

## Version 3.18.0 (2026-09-02)

### Fixed

**A single-track release could be filed under anyone.** Thomas Feiner's *The
Ship Song* was filed as Thomas Anders' *The Christmas Song*, and had sat in the
library looking entirely normal. One track satisfies every other check
trivially — the count is 1 == 1, and duration agreement is a single comparison
— so the artist carries the whole match.

Raising the fuzzy thresholds could not fix it. Measured with rapidfuzz, the
wrong match scores **title 86, artist 76**, while a legitimate variation scores
as low as **62** (`Anja Huwe` against the collaboration credit `Anja Huwe &
Mona Mur`). Any floor high enough to reject 76 rejects 62 as well; the scores
genuinely overlap.

The discriminator is kind rather than degree. A real variation is one name
contained in the other, or the same name spelled with different punctuation or
diacritics; a wrong match is two different names that merely resemble each
other. A single-track candidate must now be credited to an artist *related* to
ours by containment after folding — including the letters NFKD leaves alone,
which is what `Trentemøller` against `Trentemoller` needs.

Applied on both sides. Of six albums an audit flagged as filed under an
unrelated artist, three are single-track covers filed under the artist of the
original, and two of those came from Discogs — so guarding MusicBrainz alone
would have left most of the pattern in place. It matters more since 3.13.0's
tier 3b, which deliberately searches under other names for an artist: widening
what is retrieved widens what can be wrongly accepted, unless the artist is
checked again at the point of acceptance.

---

## Version 3.17.0 (2026-09-02)

### Added

**A field search is retried with the edition qualifier trimmed off the title.**
*The Assassination Of Jesse James By The Coward Robert Ford* is the case. The
rip calls it "... Music From Original Motion Picture Soundtrack"; Discogs calls
it "... (Music From The Motion Picture)". Measured against the live API with
the artist held constant at `Nick Cave & Warren Ellis`:

```
full title       0 results
title trimmed   15 results, the right release first
```

The title is searched as given and then, only if that found nothing, once more
cut at the earliest edition marker. Earliest rather than latest because the
local title has already had stopwords stripped — it reads "Music From Original
Motion Picture Soundtrack", so cutting at "motion picture" would leave "Music
From Original" behind.

The artist anchor stays, which keeps this from behaving like a bare title
search: it narrows a query rather than abandoning one.

### Note

Three earlier releases blamed this album's failure on its artist credit and
changed the artist tiers accordingly. That was a real problem — the album is
credited to the duo while the rip says `Nick Cave` — but it was not the binding
one, and only replaying the album against 3.16.2 showed the tier trying the
right credit and still finding nothing.

---

## Version 3.16.2 (2026-09-02)

### Fixed

**The artist-variations tier spent its budget on implausible names.** Replaying
*The Assassination Of Jesse James* — credited on Discogs to `Nick Cave & Warren
Ellis` while the rip says `Nick Cave` — still returned no candidates. The tier
fired correctly but tried `Cave`, `A Drunk Cowboy Junkie`, `Nick Cave & The Bad
Seeds`, `Cave N`, `Her Dead Twin` and `The Birthday Party`. The credit that
holds the album is ninth in a groups list of ten and was never reached.

Names are now ranked by whether they share the credit being searched, in either
direction: `Nick Cave & Warren Ellis` extends `Nick Cave`, and `Nick Cave` is
contained by `Nick Cave & The Bad Seeds`. Both are the cases this tier exists
for, and both now rank above a name with nothing in common — a fellow band
member, or an unrelated alias. The sort is stable, so the round-robin across
name sources still decides within a rank.

---

## Version 3.16.1 (2026-09-02)

### Changed

**The medium weights are a rule table now, not constants.** They decide which
of two equally-matching releases wins, and the right answer depends on the
collection — a library of needle drops wants vinyl *preferred* at 16/44.1
rather than penalised, and only its owner knows that.

`conf/medium_preference.yaml` joins `format_codes`, `char_substitutions`,
`source_hints` and `artist_joins`: packaged by default so it keeps improving
with each upgrade, discoverable beside `config.yaml`, and merged over the
packaged table so changing one number neither discards the rest nor opts out of
later additions.

A weight beyond 5.0 is clamped with a warning rather than refused — against a
base score of 50 anything larger stops being a tie-breaker and starts deciding
matches by itself, and a typo should cost a warning rather than a run. A named
file that does not exist warns and falls back, rather than switching the
feature off in silence.

---

## Version 3.16.0 (2026-09-02)

### Fixed

**A cassette could outrank the CD it was issued alongside.** Track counts and
durations cannot separate the two — the tracklists are identical, so both
scored the same and either could win. Observed three times: a 16/44.1 FLAC rip
of *Dig, Lazarus, Dig!!!* matched an Indonesian cassette, a `Cass` folder
matched a CD, and the Music On Vinyl pressing of *Ultra* matched a CD carrying
a different catalogue number.

The audio is the evidence. 44.1kHz/16-bit is CD spec, so a CD is the likeliest
origin and a needle drop or tape rip at that resolution is unusual; above
16-bit or 48kHz cannot be a CD at all and is most likely a download. Sample
rate and codec are now collected alongside bit depth to support this.

Scored rather than vetoed: Discogs miscatalogues mediums — one entry in this
library is a `Cassette` carrying the CD catalogue number `CDSTUMM277` — so a
hard gate would make correct releases unmatchable. The adjustments stay small
against a base score of 50, breaking ties without outweighing agreement on
tracks and durations. Positive evidence for vinyl still wins outright, since
A1/B2 track numbers are a fact about the rip rather than an inference from it,
and a lossy file is left alone because a transcode says nothing about what it
was transcoded from.

**An artist's groups are searched too.** `members` finds a solo record filed
under the band; the reverse — a collaboration filed under the person — needs
`groups`, and it was missing. *The Assassination Of Jesse James* is credited on
Discogs to `Nick Cave & Warren Ellis` while the rip says `Nick Cave`, and the
search returned no candidates at all.

Names are now taken one from each source in turn rather than one list at a
time. Nick Cave the person carries ten-plus name variations, nearly all
initialisms — `Cave`, `N. Cave`, `N.E.Cave` — so draining that list first spent
the whole budget on noise and never reached `groups`.

---

## Version 3.15.0 (2026-09-02)

### Added

**Follow the Discogs link MusicBrainz already carries.** MusicBrainz editors
curate a URL relation to the equivalent Discogs release, and it was being
fetched and discarded.

Measured on this library: of 32 sampled albums that had fallen through to
MusicBrainz, **11 carried a Discogs link** — roughly a third, and not obscure
records. *Henry's Dream*, *Station to Station*, *Music For A Slaughtering
Tribe*. Every one is an album Discogs holds and our Discogs search failed to
find, so the fallback was returning second-choice metadata for a release the
preferred source had all along.

`url-rels` now joins the includes on the release fetch, so the relations
arrive on a call already being made and cost no extra request. When
`source.priority` puts Discogs first, the linked release is fetched and
validated against the local track count before it is used — a stale or wrong
link falls through to the MusicBrainz mapping rather than replacing it. A
configuration that asks for MusicBrainz first is left alone; it asked for
MusicBrainz metadata.

Note this treats the symptom. Each followed link is also a Discogs search that
should have succeeded, and those are worth diagnosing separately.

---

## Version 3.14.0 (2026-09-02)

### Added

**MusicBrainz tier 4.5 — ISRC agreement.** An ISRC identifies a recording, not
a release, so no single code answers the question: the same recording sits on
the album, the single, and every compilation that ever licensed it. Agreement
does answer it — the release carrying several of a directory's recordings is
the release that directory is.

Up to four codes are looked up, and at least two must name the same release
before it is accepted; one match is refused rather than guessed at, since a
lone shared recording names every compilation it ever reached. One API call
per code, and only for an album that text search and barcode have already
failed on.

### Fixed

**Tagging destroyed the ISRCs it found.** `tag_single_track` wipes the tag set
and rewrites it from the metadata source, and Discogs carries no ISRCs at all,
so every Discogs match stripped them. The scale of it: **55%** of a sample of
files in `/incoming` carry an ISRC, against **9%** of those already tagged.

Besides losing a genuine identifier the rip arrived with, this removed the
input to the new tier from every album the tagger had touched. The ISRC is now
read before the tag set is wiped and written back afterwards, preferring the
value the metadata source supplies — MusicBrainz models recordings and so
knows them — and otherwise keeping the file's own.

---

## Version 3.13.0 (2026-09-02)

### Fixed

**An album credited to a different artist than the files say was unreachable.**
Every Discogs tier is anchored on the artist string from the local tags, so
when that named the wrong artist the right release was never retrieved — not
ranked poorly, absent. Nick Cave's *Idiot Prayer* is credited on Discogs to
`Nick Cave`; the rip said `Nick Cave & The Bad Seeds`; 111 releases of the
wrong artist were compared and refused, while the two correct releases — which
agree on 22 of 22 track lengths — were never fetched.

**The artist browse matched only on the canonical name.** A rip carrying a
career variation resolved to no artist at all, so neither the browse nor
anything after it had somewhere to look. It now also matches the
`namevariations` Discogs records for exactly this reason, for the first few
search results only, since reading them forces the full artist fetch.

### Added

**Tier 3b — retry under the artist's other names.** After the artist browse
fails, the field search is repeated under the artist's `namevariations`,
`aliases` and `members`, in that order of confidence: the same act spelled
differently, then the same act renamed, then a member whose own catalogue is a
genuinely different artist — which is the point when a solo record has been
filed under the band.

Those names arrive in the artist response the browse tier already fetches, so
the tier costs **no extra artist lookups**: at most
`batch.artist_name_variations` field searches, and only for an album that has
otherwise failed. Broadening retrieval does not broaden acceptance — anything
found must still match on track count and agree on most track lengths — so the
setting is a cost control, not a safety one. Set it to 0 to switch the tier off.

`batch.artist_name_variations`, default `6`.

---

## Version 3.12.1 (2026-09-02)

### Fixed

**An index entry with no durations anywhere crashed the album.** Einstürzende
Neubauten's *Haus Der Luege* (release 23821019) holds "Fiat Lux" as an `index`
entry with sub_tracks 6a/6b/6c and no duration on the parent or on any sub.
Three branches could have claimed it and none did — Pattern A expands only when
every sub carries a duration, `_ambiguous` recognises the shape but expands
only when `expand_ambiguous_index` is set (off by default), and Pattern B
required a parent duration. The entry fell through to a branch referencing a
name that had never been defined:

```
NameError: name 'discsubtitle' is not defined
```

Pattern B no longer requires the parent duration, so an index whose sub_tracks
carry no durations collapses into a single track whether or not the parent is
timed. That is how the rip holds it — 11 files against 11 tracks. Skipping the
entry instead would have offered 10 and been refused on track count.

---

## Version 3.12.0 (2026-09-01)

### Changed

**A failed search now says what it compared.** `No match found` read exactly
the same whether Discogs held nothing at all — a white-label bootleg, a
single-track remix release — or held the right album and refused it over one
field. The first is nothing to be done; the second is usually an incomplete or
mis-split rip, and is actionable. Telling them apart meant re-running the album
with `-v` and reassembling wrapped log lines, so a batch of failures stayed one
undifferentiated pile.

Everything needed was already in hand when the search gave up: the closest
release, the field that disqualified it, and the size of the gap. All three
were discarded. Failures now read:

```
No match — closest 12530658 — 41 tracks, local has 36 (52 compared: 52 on track count)
No match — no candidates returned
```

The first is Jean-Michel Jarre's *Planet Jarre*: five tracks missing from the
rip, which no amount of matching work would fix and which the old message hid
behind a shrug. The second is a remix single nothing catalogues.

Rejections are ranked so the most actionable is named: track count first, then
duration, then titles, then a medium veto — which says nothing about how close
a release was and so should never be reported as the closest.

The diagnosis travels on a caller-owned list rather than an attribute of the
searcher, which is shared between worker threads.

---

## Version 3.11.0 (2026-09-01)

### Fixed

**One badly-timed track could reject the whole release.** Track lengths were
compared by averaging the absolute difference across the release and refusing
anything over `batch.tracklength_tolerance`. An average cannot separate "every
track is moderately wrong", which means a different release, from "one track is
very wrong", which usually means one mis-entered duration or one substituted
version — and those deserve opposite verdicts.

Nick Cave's *Fifteen Feet Of Pure White Snow* is the case that forced it.
Release 35448229 carries the same five titles in the same order, four of them
within a second, but Discogs lists a 4:07 single version where the rip holds
something 89s longer. The mean came to 18.2s, over tolerance, so the correct
release was refused and the run reported `No match found` — indistinguishable
from a release nobody had catalogued.

Agreement is now counted per track. A release is accepted when at least
`batch.tracklength_agreement` of its comparable tracks fall within
`batch.tracklength_tolerance` of the local files, and the median difference
becomes the score, so a release still ranks by how well it agrees rather than
merely passing. *Fifteen Feet* scores 4/5 with a median of 1s; a release whose
tracks are each 18s adrift scores 0/5 and is still refused.

### Added

`batch.tracklength_agreement`, default `0.75` — the share of tracks that must
agree. Raise it towards 1.0 to insist on near-exact agreement; lower it for a
collection whose durations are known to be patchy.

`batch.tracklength_tolerance` keeps its name, units and default, but now bounds
a single track rather than the average across a release.

### Changed

`SEARCH_LOGIC_VERSION` is now 3, retiring stored search decisions: releases
refused under the old rule are accepted under this one, and replaying the old
answers would hide the fix.

---

## Version 3.10.0 (2026-09-01)

### Fixed

**Concurrent searches shared one set of candidates, so albums in a batch
failed to match.** `MassProcessor` builds `DiscogsSearch` once per session
because the object holds caches — but it also held one album's working set as
instance attributes: `candidates`, `no_duration_candidates`, `search_params`
and `_sifted_masters`. With `batch.workers` above 1, every worker searched
through the same four containers and overwrote each other mid-search.

Measured on one directory of two albums, same cache, same code, with only
concurrency varying:

| run | comparisons | accepted | outcome |
|---|---|---|---|
| `workers: 4` (before) | 40 | 0 | both failed |
| `workers: 1` (before) | 38 | 10 | both matched |
| `workers: 4` (after) | 38 | 10 | both matched |

Concurrency now produces results identical to serial, down to the comparison
count and the release ids chosen.

A `SearchState` carries the four fields, is created in `search()`, and is
passed explicitly through the sixteen methods that touch them. The searcher
keeps its caches, which is what sharing the instance was for.

**Missed matches are only the visible symptom.** An album could also select
from another album's candidate pool, so wrong matches were possible and
nothing in the output would have said so. Anyone who has run batches with
`workers` above 1 should treat both their failures and their matches as
worth re-checking.

Raised as a minor rather than a patch release because matching results change
materially for any concurrent run.

---

## Version 3.9.1 (2026-08-30)

### Fixed

**A cue sheet naming audio that is not present stopped an album being split.**
An EAC rip commonly leaves two sheets per disc: the real one, and an ISRC
sheet pointing at the scratch file it ripped through — `FILE "Range.wav"` —
which was never kept. The test for a single-file rip is that sheets and audio
files are equal in number, so six sheets against three disc images failed it
and the set was never split. It reached the tagger as three untagged tracks,
matched nothing, and reported a plain no-match with nothing to suggest the
CUE handling was involved.

Filename grouping could not solve it: the two sheets per disc share no stem
at all, one carrying the artist prefix and the other an `ISRC` suffix. The
sheet itself is the reliable witness — one whose `FILE` is not in its own
directory cannot split anything. Nothing is dropped when no sheet resolves,
since that means the check does not apply rather than that every sheet is
junk.

Sheets are read tolerantly, since rippers rarely declare an encoding. UTF-16
is tried only behind a byte-order mark: it decodes almost any byte sequence
without complaint, which would otherwise turn a latin-1 sheet into mojibake
with no `FILE` line at all.

Verified on Nick Cave's *Lovely Creatures*: six sheets reduced to three, all
three discs split, 45 tracks tagged, and the source archived with its images
and all six sheets intact.

---

## Version 3.9.0 (2026-08-30)

### Changed

**Preparation writes to staging instead of the source tree.** Splitting a CUE
rip used to write its tracks beside the disc image, decode a full ~1.5 GB WAV
next to it first, and move the image and sheet into a `.cue` directory.
Converting `.m4a` wrote the transcode beside the original and moved the
original into `.m4a`. All of it on the share, at the 9.8 MiB/s NAS-to-NAS rate
`batch.staging_dir` exists to avoid.

Nothing preparation produces is source material. A disc image and its sheet
are the source; the split tracks are a decode artefact, made to be tagged and
then finished with. With `staging_dir` set they now go there, and the source
directory is left exactly as the user left it.

Two further things follow. The source tree is read-only during preparation —
stronger than splitting `scan()` from `prepare()` achieved, which only stopped
a *dry run* from rewriting what it reported on. And re-runs become idempotent:
a CUE album split once no longer presents a different shape on its second
pass.

The enabling change is that a source directory may now be two paths. `sourcedir`
meant both *where audio is read from* and *what `source_action` archives or
deletes*; pointing the latter at staging would archive a temporary decode and
leave the disc images in place for ever. So the origin and the audio directory
are now separate: the done marker, `id.txt` and the tag-in-place destination
all follow the origin, and only the reading follows the audio.

Staging holds a complete album — covers, rip logs and other sidecars are
carried across, since anything left in the origin would be dropped from the
tagged result. Preparation directories are swept at startup like assembly
ones, and removed per album so a batch of CUE rips does not accumulate
decodes.

`cue.cue_done_dir` and `m4a.m4a_done_dir` keep working unchanged. With staging
set there is nothing new to stash, but the directories they name are still
pruned from scans — 108 of them exist across this library, holding the only
copies of pre-conversion originals.

Without `staging_dir` set, preparation still works in place exactly as before.

---

## Version 3.8.0 (2026-08-30)

### Added

**`batch.staging_dir` — assemble albums on local disk.** Tagging read the
source from the share and wrote it back there, then ReplayGain read the
destination again and tagging rewrote it: every pass crossing the link.
Measured NAS-to-NAS **9.8 MiB/s**, against 1280 MiB/s local. With a staging
directory the album is copied in once, assembled at local speed, and copied
out once.

Empty by default, so nothing changes for anyone who does not set it.

The ordering matters more than the speed: the source is archived or deleted
only after the output is verified to hold audio, and that check reads
`result.target_dir`, so the move out of staging happens first and updates it.
A destination collision is suffixed rather than overwritten. Staging is
emptied as each album moves out, and anything left behind by a killed run —
`docker rm -f` is a SIGKILL and skips the cleanup — is swept at startup.

**`artwork.artist_image` — the artist's picture.** Written as `artist.jpg` in
the artist folder and embedded in every track as ID3/FLAC picture type 8,
"Artist/performer". Fetched from Discogs, the only source that has them —
MusicBrainz stores none — and cached per artist id, so a discography fetches
it once rather than once per album. Off by default, and most useful alongside
`%albumartist_primary%`: without that, a guest credit gets its own folder and
each collects a copy of the same picture.

### Fixed

**Disc layout was ignored when ranking candidates.** Matching compared the
flat track total, so a single-disc release of seventeen tracks scored exactly
as well as the correct 13 + 4, and the difference surfaced much later as a
per-disc count mismatch during tagging — an error that never mentioned
layout. Candidates whose per-disc distribution matches now score −5, and
those with a different number of discs +5. On the real *Spirit* candidates
against a local 12 + 5 that is a ten-point swing.

Compared as a distribution rather than a disc count, because
`format_quantity` is unreliable here: Spirit's correct 2-CD release reports
three format entries (CD, CD, All Media).

**A 24-bit source could match a CD pressing.** CD audio is 16-bit by
definition. The rule runs one way only — 16-bit rules nothing out, since it
may equally be a CD rip or a lossless download — and SACD and DVD are
excluded from the check because both carry hi-res.

**A finished album passed directly reported "No audio source directories
found".** `_count_ignored` skipped the root, so when the directory handed in
*was* the completed album — what a batch script passing one album per run
does — nothing was counted and a complete album read as an empty one.

**`info.txt` and `m3u.txt` always printed the track artist.** Both built
their own track lines and ignored the rule the `song` format string applies,
so the artist appeared even when it matched the album artist. The playlist's
file paths were already correct; only the human-readable labels diverged.

---

## Version 3.7.0 (2026-08-30)

### Added

**`%albumartist_primary%` — file an album under its primary artist.** A
release credited "David Bowie Featuring Al B. Sure!" gets its own artist
folder and fragments a discography. This variable reads the same as
`%albumartist%` except when a credit is one artist with guests, where it
gives the first artist alone. A split release — "D.A.R.P.A. / Dive /
:wumpscut:" — keeps its whole billing.

Two things decide it, and neither is hardwired. Credits resolving to a single
artist collapse first: 48 of 73 join tokens in a real Discogs cache are `=`,
which is transliteration (one artist id listed twice, once in another script),
not collaboration. After that, **`artist_joins.yaml`** says which join phrases
mark a guest — a new rule table beside `config.yaml`, merged over the packaged
one like `format_codes.yaml` and `source_hints.yaml`.

Unlisted joins keep the whole credit, so `and` and `,` ship unlisted rather
than guessed at: an uncollapsed featuring credit costs one surplus folder,
while a collapsed split hides artists with nothing to show it happened.

The variable is never written as a tag — `albumartist` always keeps the full
credit. Configurations whose format strings do not mention it are unaffected.

### Fixed

**A MusicBrainz release with no date left the album with no year.** *Station
to Station* (Ryko RCD 10141) has an empty `date`, and the album filed with no
year while the LP beside it showed `[1976-01-23]`. The release group's
`first-release-date` was already fetched and unused; the Discogs side has had
a master-year fallback for a long time.

Note this is the *original* release date, so a 1991 remaster now files under
1976 rather than under nothing — the same trade-off already accepted for
Discogs masters, and logged rather than silent.

---

## Version 3.6.2 (2026-08-30)

### Fixed

**MusicBrainz ignored `naming.use_anv`, splitting artists across folders.**
MusicBrainz's artist-credit `name` is its ANV equivalent — the form printed on
one particular release — while `artist.name` is the canonical name of the
artist entity. The mapper fetched both and always preferred the credit, so a
setting you had turned off went on applying.

DHS showed the cost: *House of God* is credited `DHS` on one release and
`D.H.S.` on another, both artist MBID `257180c1`, and the library grew two
folders for one act. Discogs has honoured `use_anv` all along; MusicBrainz was
never given it.

With `use_anv: false` both releases now file under `DHS`. With `use_anv: true`
the credited form is kept, as before.

No new setting: the existing one now means the same thing for both sources.
Note this changes naming for future runs only — folders already written stay
where they are.

---

## Version 3.6.1 (2026-08-30)

### Fixed

**Cached search decisions outlived the rules that produced them.** The Discogs
search cache stores which releases were worth comparing — a decision, not a
verbatim API response — and had no version stamp, so entries written before a
matching change were replayed forever.

Depeche Mode's *Spirit* showed the cost. A cached entry named a single
release; it was accepted, the search stopped at the first candidate, and the
correct Japanese pressing was never compared at all. Against a cold cache the
same album compared **40 releases**, found 14 candidates, and matched on
catalog number. The 3.6.0 fix was already in place and the cache concealed it.

`SearchCache.SEARCH_LOGIC_VERSION` is now part of the key, so bumping it
retires every stored decision at once. MusicBrainz's connector has carried the
same guard since its own rules changed; Discogs never had it.

---

## Version 3.6.0 (2026-08-30)

### Fixed

**Catalog-number hints were being lost, so the wrong pressing could win.**
The catalog number is worth -10 in candidate ranking and is often decisive --
regional and format reissues share track counts and near-identical durations,
leaving the number as the only thing that separates them.

It failed in two ways. Extraction required a single token containing both a
letter and a digit, so every space-separated number was missed: `ISLA 23`,
`MET 1010`, `CK 86656`, `88765 46063 2`. Over a 554-album library that lost
the signal on **372 of the 456** titles with a trailing parenthetical group.

And the hint was only ever parsed out of the album *title*, which is usually
not where the number lives. Delta Machine's album tag is just
`Delta Machine`, while its files carry `catalognum = 88765 46063 2`. The tag
is now used directly; **73%** of a 60-album sample had one.

Candidates are returned as a set, because a trailing group may hold a
descriptor as well as a number and nothing tells them apart reliably --
`Maxi XLCDBong24` must yield `xlcdbong24`, while `CK 86656` must be taken
whole. Every suffix is offered and any match counts.

False positives are guarded against, since they cost more than misses: a
candidate needs a digit, at least three characters, and must not be a bare
year, so a trailing `(2013)` stays a date.

---

## Version 3.5.1 (2026-08-30)

### Fixed

**The Discogs token was written into verbose logs.** The client authenticates
by putting the personal token in the query string, and urllib3 logs every
request line at DEBUG:

```
DEBUG https://api.discogs.com:443 "GET /releases/4449888?token=<token>"
```

A normal run never showed it — the root logger sits at INFO, so DEBUG records
are dropped before reaching a handler — but `-v` is exactly what someone
enables to capture a log for a bug report, which is when a log is most likely
to be shared.

It cannot be fixed at our call sites, because the record comes from a
third-party library. A `logging.Filter` on the handlers redacts credentials
wherever they originate, covering libraries added later as well. It catches
`token`, the OAuth parameters, `client_secret`, `api_key`, `password`,
`secret`, and AcoustID's `client` key, in query strings and in
`Authorization` headers.

This matters more than a leaked key usually would: Discogs issues **one
personal token per account**, so a token that reaches a shared log cannot be
rotated without breaking every other deployment using that account.

Rotate your token if you have previously shared a `-v` log.

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
