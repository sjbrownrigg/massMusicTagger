# Backlog

Work identified while running massMusicTagger over a real library, kept here
rather than in a commit message so it can be found again. Each entry says what
was observed, what is actually happening, and what would improve it.

---

## Canonicalise the artist name when falling back to existing tags

**Deferred deliberately.** `existing_tags` is currently commented out of
`source.priority`, so this fallback does not run at all and the fix would
have no effect. Revisit it together with turning that source back on, rather
than building against a path nothing takes.

**Observed.** One artist appears in the library under five names:

```
:wumpscut:                      matched on Discogs
-wumpscut-                      the same, after char_profile: windows
"wumpscut"                      a differently-credited Discogs release
Wumpscut                        no release matched — existing tags used
D.A.R.P.A. - Dive - -wumpscut-  a split-artist release
```

Two of those are correct and one is not worth chasing:

* `-wumpscut-` **is** `:wumpscut:`. The Windows character profile maps `:` to
  `-`, because a colon is illegal in an NTFS path. Working as intended, and
  worth knowing before anyone tries to "fix" it.
* `D.A.R.P.A. - Dive - -wumpscut-` is a genuine multi-artist credit.

`Wumpscut` is the problem. When every source fails to match a release, the
cascade falls back to `existing_tags` and takes the artist name from the files
verbatim. Discogs knows the canonical spelling is `:wumpscut:` — it has that
artist, with `Wumpscut` recorded as a name variation on two releases — but
nothing asks. The album lands in its own artist folder and the discography
splits.

**What would improve it.** Failing to match a *release* is not the same as
knowing nothing. When the fallback is used, look the artist up on its own
(Discogs artist search, or MusicBrainz) and take the canonical name. One
lookup per artist, cached for the run, and the library stops fragmenting for
want of a colon.

Worth guarding: only accept a confident match. Substituting a similarly-named
but different artist is worse than leaving the tag alone.

**Also seen:** `Depeche Mode` and `Depeche Mode_` as separate folders under
`archive/existing_tags/`, which is the same fault with a trailing underscore.

---

## Decide whether the album artist should ever use a name variation

**Partly settled in 3.6.2.** MusicBrainz was ignoring `use_anv` entirely and
always taking the credited form, so the setting only ever governed Discogs.
Both sources now honour it, and DHS/D.H.S. collapsed to one folder.

What is still open is the finer distinction below: `use_anv` remains one
answer to two questions, applying equally to the album artist (where a
variation fragments a discography) and the track artist (where it is the
right name, being what the release actually credits).

`use_anv` controls whether the sleeve credit (Discogs' Artist Name Variation)
is preferred over the canonical database name. It is currently `false`.

Even so, the distinction is worth making explicit rather than settled by one
switch: an ANV is the right name for a **track** artist, because it is what
the release actually credits, and the wrong name for the **album artist and
directory**, because it fragments a discography across folders. Two different
questions currently share one answer.

---

## Artwork shape — decided: trust what the source typed

`_local_front` compares aspect ratios to tell "the same picture, scanned
larger" from "a different picture that happens to be bigger", which is what
stops a 2.4:1 sleeve spread being embedded as a front cover.

The open question was whether to apply the same reasoning to what a *source*
offers. Cover Art Archive typed a 5033x1465 wraparound scan as `Front` for
The Waterboys' Modern Blues, and `image_policy: prefer_larger` compares pixel
counts, so a spread always wins on size.

**Decided: no shape check on remote artwork.** When a source has typed an
image as the front cover, that typing is the best information available and
is taken at face value. Some releases genuinely have wide covers, and second
-guessing a deliberate label would trade a rare cosmetic problem for a
systematic one.

The local check stays, because there nothing has typed anything — the shape
comparison is standing in for the label that a source would have provided.

No further work; kept for the reasoning.

---

## Bit depth can rule out a CD match

A 24-bit source cannot be a CD rip — CD audio is 16-bit by definition. The
same album matched both `Codes (SBR331) [9xDM]` and `Codes (SBR331CD) [CD]`
across two runs of a 24-bit/44.1 download, and only the first is possible.

`format_hint` already rejects a vinyl release for a digital source, and a
non-vinyl release for a vinyl source. It does not use bit depth, so a
hi-res download can still match a CD pressing — which is both wrong and
cheap to exclude, since `%bitdepth%` is already gathered.

Worth care in one direction only: 24-bit rules *out* CD, but 16-bit rules
nothing out, since a 16-bit file may be a CD rip or a lossless download.

---

## Tagging is bound by the share, not the CPU

Measured on the WSL2 host, tagging a 313 MiB album takes about 139 seconds,
and raising `batch.workers` from 1 to 4 changed that to 145 → 139 — nothing.
The container sits at **1.5% CPU** throughout.

| path | throughput |
|---|---|
| NAS → local disk (read) | 31 MiB/s |
| local disk → NAS (write) | 21 MiB/s |
| **NAS → NAS (what tagging does)** | **9.8 MiB/s** |
| local → local | 1280 MiB/s |

A NAS-to-NAS copy is mediated by the client, so it pays both directions on
one link and lands well below either. More workers cannot help: the link is
already saturated, and they would only contend for it.

Where the time goes, per album: the source is read from the share and written
back to it, then ReplayGain reads the destination again, then tagging
rewrites it. Most of that traffic exists only because the working directory
*is* the share.

**Since addressed in part.** 3.5.0 added `batch.cpu_jobs` and
`replaygain.thread_count`, which stop the two concerns multiplying: workers
can now be raised for the link without also multiplying decode threads. That
removes the contention, but not the traffic — the measurements above still
stand, and the staging idea below is still the change that would move them.

**Worth considering:** stage each album on local disk — copy in once, tag and
ReplayGain there at 1280 MiB/s, copy the finished album out once. That trades
two slow passes for two fast ones and one fewer round trip. It is a real
change to how the processor handles files, not a setting, so it wants
deciding rather than assuming.

Running on a host that mounts the share natively, rather than through WSL2's
drvfs to the Windows SMB client, may be a bigger win for less work.

---

## "No audio source directories found" when the album itself is complete

**Mostly already fixed; the remaining gap is narrower than first recorded.**

An earlier version of this entry said the tagger reports a finished tree as
though it found nothing. It does not: `_get_source_dirs` returns
`n_ignored`, and `__main__` logs *"All N album(s) already tagged — nothing to
do"*. That has been in place since 2026-05-31, three months before the
observation was written down. Reading the log was not enough; the code said
otherwise.

What actually produced the misleading line is narrower. The batch script
passes each album directory individually, and when the directory handed in
**is itself** the completed album -- rather than a tree containing one --
nothing is counted as ignored, `n_ignored` is 0, and the generic warning is
used:

```
WARN No audio source directories found
```

Reproduced with two albums whose folders carry `.done` and hold the audio
directly.

**What would improve it.** Count the root itself when it is excluded for a
done marker, so a single completed album reports like a completed tree. Small
and contained, and the message it should print already exists.

**The lesson, which is the same one twice today.** Both this and the
multi-disc entry were written from a truncated batch log without checking the
code or running the case. Both were wrong. The log is the cheapest evidence
and the least reliable.

---

## A downstream failure is reported as if the album did not match

**Observed.** During the bulk re-tag, one album logged:

```
ERR Failed to process /incoming/David Bowie/[2004] Hours... [LDCD ...]
Summary: 7 processed — 6 tagged  0 skipped  1 failed  0 dry-run
```

The natural reading is that nothing matched. It is wrong. Re-running the
search against both a cold and a warm cache finds four acceptable candidates
— 1060982 and 4449888 at 1.7s and 1.5s average track-length difference — and
picks one. The *matching* worked; something after it raised.

The batch's log filter compounded it, cutting the message at the album name
so the exception never reached the operator, but the underlying problem is
that one line covers two very different situations: no release was found, and
a release was found but processing then failed. Only the first is a matching
problem, and only the second is a bug.

**What would improve it.** Say which. When the failure comes after a match,
name the release that was matched and the exception, so the log distinguishes
"nothing fits this album" from "this album matched 1060982 and then failed
writing". The information is in hand at the point the message is written.

**Resolved, and it confirms the point.** The exception was
`mutagen.flac.error: file said N bytes, read fewer`, wrapped in
`UnreadableFileError` -- a truncated read over SMB. All 27 source files parse
cleanly, and the album tagged without incident on a retry, so the fault was
transient I/O rather than damaged audio.

That is exactly the distinction the message failed to draw. "Failed to
process" sent two people hunting for a matching problem for the better part
of an hour when the correct reading was "retry it". Naming the matched
release and the exception would have cost nothing and saved all of it.

---

## A MusicBrainz release with no date leaves the album with no year

**Fixed in 3.7.0**, and the diagnosis needed correcting on the way.

*Station to Station (Ryko remaster, RCD 10141)* filed with no year at all,
while the LP beside it showed `[1976-01-23]`. It matched MusicBrainz release
`3abff816`, whose `date` is the empty string, and `album.year` was taken
straight from it with no fallback.

**What was wrong in the first write-up.** It claimed the search does not
prefer a dated candidate. It does: tier 3 ranks on
`(title_score, artist_score, has_date)`, and `has_date` is exactly that
tie-break (search.py). MusicBrainz holds three releases with that catalogue
number, two dated 1991 and one undated, and had the search run it would have
preferred a dated one.

The album never reached tier 3. It already carried a `musicbrainz_releaseid`
tag from an earlier run, and tier 2 reuses that identifier directly -- by
design, and reasonable. Ranking was never consulted.

**What was genuinely missing**, and is now fixed: no release-group fallback.
`release-group['first-release-date']` was `1976-01-23`, already fetched
(`release-groups` is in `_INCLUDES`) and unused. The Discogs side gained a
master-year fallback long ago; MusicBrainz never got the equivalent.

Worth being explicit that this yields the *original* release date, so the
1991 remaster now files under 1976 rather than under nothing. That is the
same trade-off already accepted for Discogs masters, and it is logged rather
than silent. Getting 1991 instead would mean re-searching rather than
reusing the stored identifier, which is a different and larger decision.

---

## Disc layout is not compared when ranking candidates

**Corrected entry.** An earlier version of this claimed a wrong-layout
release winning was the common cause of three failed Depeche Mode deluxe
sets. That was asserted from a truncated, interleaved batch log before the
albums were examined individually, and it was wrong for two of the three.
What follows is what was actually established by running them.

The three shared a *symptom* — the extra disc directory skipped at
`taggerutils.py:1130`, then `taggerutils.py:1231` raising on the per-disc
count — but not a cause:

| album | what was really wrong |
|---|---|
| Delta Machine | Not layout. The release the matcher chose (4399837) already had the correct 2-disc 13 + 4 shape. Re-run, it tagged cleanly. The original failure is unexplained. |
| Spirit | Genuinely layout: it matched a release with all 17 tracks on one disc against a local 12 + 5. But the reason it saw only that release was a stale cached decision, fixed in 3.6.1. |
| Sounds Of The Universe | Not a tagger fault at all. The rip holds two files numbered 13 — the same track at two compression levels — so no release can match it. |

**What the fixes actually were.** 3.6.0 took catalog hints from the
`catalognum` tag and stopped losing space-separated numbers; 3.6.1 versioned
the Discogs search cache so decisions made under older rules retire. Together
those got Delta Machine and Spirit matched and tagged correctly, both landing
on releases whose catalog number and disc layout match the source exactly.

**What remains true, and is still worth doing.** Disc layout is not a factor
in ranking. `local_count = len(searchParams['tracks'])` (search.py) compares
flat totals, and `disc` appears nowhere in `_compareRelease`. The only disc
signal in `_candidate_score` is a -0.5 nudge comparing `format_quantity`
against the highest local disc number, which is both weak and easily wrong —
Spirit's correct release reports three format entries (CD, CD, All Media) for
a two-disc set.

Both sides already carry what is needed: `_fetchSubdirectories` knows the
local disc directories, and Discogs positions carry the disc (`CD1-1`,
`2-4`). Comparing the per-disc distribution would have rejected Spirit's
single-disc candidate on its own merits, without depending on the cache fix
to widen the candidate list.

So this is worth implementing — as a genuine improvement to ranking, not as
the explanation for those three failures.

**The lesson worth keeping.** The batch log truncates each line and
interleaves albums, so attributing a warning to a particular album by reading
nearby lines is guesswork. Two diagnoses were published from it and both were
wrong. Running one album on its own settled each in minutes.

---

## Filing multi-artist releases under the primary artist

**The question.** A release credited "David Bowie Featuring Al B. Sure!" gets
its own artist folder, fragmenting Bowie's discography. Filing it under the
primary artist is obviously right. Doing the same to a split release --
"D.A.R.P.A. / Dive / :wumpscut:" -- would be obviously wrong, because it
hides two artists entirely. Is the distinction reliable enough to act on?

**Yes, in two steps, and the second is where the care is needed.**

### Step 1 -- collapse credits that are the same artist

Measured over the cached Discogs releases, **48 of 73** join tokens are `=`.
That is not a collaboration marker at all; it is Discogs' transliteration
form, the same artist listed twice:

```
name='David Bowie' anv=''                join='=' id=10263
name='David Bowie' anv='デビッド・ボウイー'  join=''  id=10263
```

So the first test is not the join phrase but the **artist identity**: if
every credit resolves to one entity -- Discogs `id`, MusicBrainz artist MBID
-- there is one artist and nothing to decide. That covers the majority case
here and needs no heuristics. It is the same principle that collapsed
DHS/D.H.S. in 3.6.2.

### Step 2 -- classify the join, for genuinely different artists

The join phrase is already parsed by both mappers to build the display
string. What occurs in this library:

| join | example | reading |
|---|---|---|
| `/` | D.A.R.P.A. / Dive / :wumpscut: | split -- keep all |
| `vs.` | DHS vs. DJ Slip | equal billing -- keep all |
| `With` | David Bowie With Tina Turner | Bowie is primary |
| `Remixed by` | Depeche Mode Remixed by Symbion Project | DM is primary |
| `,` | David Bowie, John Hiatt | ambiguous |
| `And` | Depeche Mode And Richard Morel | ambiguous |

Clear at both ends, ambiguous in the middle -- and the middle is exactly
where one person's judgement should not be baked into everyone's tagger.

**So the classification belongs in a rule table the user owns**, not in a
list in the source. The project already has this shape three times over:
`format_codes.yaml`, `source_hints.yaml` and `char_substitutions.yaml` all
ship a packaged default that a file beside `config.yaml` merges over, so a
user can override one line without freezing the rest at whatever shipped
that day.

```yaml
# artist_joins.yaml
subordinating:      # the first artist is the primary; the rest are guests
  - "featuring"
  - "feat."
  - "ft."
  - "presents"
  - "introducing"
  - "remixed by"
coordinating:       # equal billing; keep the whole credit
  - "/"
  - "vs."
  - "versus"
  - "meets"
  - "&"
  - "+"
```

Anything unlisted stays coordinating, which is the safe default: **a
featuring credit left uncollapsed costs one surplus folder, visible and
trivially fixed, while a split collapsed under its first artist hides the
other artists entirely and leaves no trace that it happened.** So `and` and
`,` ship unlisted, and anyone who wants them subordinating can say so.

Worth noting `&` is listed coordinating but rarely matters: a band name like
"Nick Cave & The Bad Seeds" is a single entity in both databases, one credit
rather than two, so it never reaches this logic.

### Where to apply it

**Not to the `albumartist` tag.** The tag should keep saying what the release
says. Only the *directory* wants simplifying, which is the same album-versus-
track distinction `use_anv` already embodies.

That points at a format-string variable rather than a config setting --
say `%albumartist_primary%`, resolving to the primary artist when the credit
is subordinating and to the full credit otherwise. Filing is already
controlled through `formats.ini`, so using it at all stays the user's choice,
per format string, and adds no setting to think about.

Together that leaves two decisions with the user and none hardwired: the
table says which joins subordinate, and the format string says whether
filing uses that at all. The packaged table is a starting point, not a
ruling.

One prerequisite: `Album` currently keeps `artists` (the names) and a
flattened `_artist_display`, but discards the join phrases. They would need
retaining at map time, where both mappers already have them. Parsing them
back out of the display string would work but is the fragile way round.

---

## The MusicBrainz cache path lives in a credentials file

`credentials/musicbrainz.yaml` carries `cache_directory: /cache/mb`, while
Discogs takes its cache path from `config.yaml`:

| source | where the path lives |
|---|---|
| Discogs | `config.yaml` -> `cache: directory: /cache/discogs` |
| MusicBrainz | `credentials/musicbrainz.yaml` -> `cache_directory: /cache/mb` |

A cache directory is not a credential, and nothing signposts the difference.
It cost four failed runs to find while setting up a test configuration: the
obvious file was edited repeatedly and the real setting was somewhere else.

Credentials files are merged into the configuration under their section name,
so `cfg.get('musicbrainz', 'cache_directory')` reads whichever file supplies
it -- which is what makes the split invisible.

**What would improve it.** Treat `cache.directory` as the root and derive
both, which is already the de facto layout: `<root>/discogs` and `<root>/mb`
are exactly what the two settings point at today. Keep the per-source keys
working as deprecated overrides, and warn when one is found in a credentials
file, since that is the case nobody will think to look for.

---

## Artist images in the artist folder

**Feasible from Discogs only.** `api.discogs.com/artists/<id>` returns an
`images` list -- 54 for David Bowie, with one `type=primary` and the rest
secondary. MusicBrainz stores no artist images at all; only release cover art
through the Cover Art Archive. So an album matched on MusicBrainz would need
a separate Discogs artist lookup to get one.

**This pairs with `%albumartist_primary%`.** An artist folder is only a
stable place to put a picture once guest credits stop creating folders of
their own -- otherwise "David Bowie Featuring Al B. Sure!" gets its own
folder and its own copy of the image.

**Open questions, none of them technical:**

* *Filename.* Media servers disagree: Plex looks for `artist.jpg` or
  `poster.jpg`, Jellyfin and Kodi for `folder.jpg`. Guessing wrong means the
  file is ignored.
* *Embed as well?* ID3 and FLAC both have picture type 8, "Artist/performer".
  But an artist image embedded in every track adds its weight to every file
  for something the player normally reads from the folder once -- and this
  library already skips 24 MB booklets rather than embed them.
* *Fetch once per artist.* One folder serves many albums, so the lookup and
  download want caching per artist id, not per album.
* *What happens on a MusicBrainz match* -- accept no image, or look the
  artist up on Discogs anyway.

---

## Preparation should write to staging, not the source tree

### The problem

`FileUtils.prepare()` has exactly two kinds of work -- `PrepTask.kind` is
`'cue' | 'm4a'` -- and both write derived audio into the source directory:

* **CUE splitting** writes tracks to `cue.image_file_directory`, and decodes
  the image to `src_image + '_tmp_decode.wav'` beside it first.
* **`.m4a` conversion** writes the transcode to
  `os.path.splitext(path)[0] + '.' + target_ext`, then moves the original
  into a done directory.

For a three-disc CUE rip of ~500 MB images that is roughly 4.5 GB of
transient writes and 3.4 GB of lasting ones, all at the 9.8 MiB/s NAS-to-NAS
rate `batch.staging_dir` exists to avoid. It is the heaviest filesystem
operation in the pipeline, and staging does not reach it: staging redirects
the *processor's destination*, while preparation runs earlier, in
`_get_source_dirs` -> `prepare()`.

### The insight

Nothing `prepare()` produces is source material. The source is what the user
put there -- a disc image and its sheet, or a folder of `.m4a` -- and
everything made from it is a decode artefact, produced to be tagged and then
finished with. Staging is where temporary files belong. Leaving them in the
source tree means a rip that has been through the tagger once is no longer
the thing the user put there.

### What blocks it

`sourcedir` currently means two things at once: **where audio is read from**,
and **what `source_action` archives or deletes** --
`_post_process_source` calls `shutil.move(result.sourcedir, ...)` and
`shutil.rmtree(result.sourcedir)`.

Write preparation to staging without separating those, and `move` archives
the temporary split while leaving the disc images in `incoming` for ever;
`remove` deletes the split and leaves them too.

**So the whole of the work is one distinction**: an *origin*, always the
directory the user put there and the only thing archiving acts on, and an
*audio directory* the scan and processor read from -- staging for a prepared
album, the same as the origin for everything else. `PrepTask` already carries
`dirpath`; what it needs to return is where the prepared audio ended up.

### What follows once that exists

**Staging becomes a run-level facility rather than a processor-private one.**
Today it is allocated per album inside `_process_one`, after matching.
Preparation needs it earlier, so the per-album directory must be allocatable
at prepare time and handed forward. The startup sweep already runs early
enough: `MassProcessor` is built at `__main__.py:1086` and `_get_source_dirs`
at 1099. Watch mode calls the same `_get_source_dirs`, so it inherits this
without separate work.

**Preparation and copying stay consecutive, not alternative.**
`copy_files()` is not a directory copy -- it maps each track individually,
`shutil.copyfile(source/track.orig_file, target/track.new_file)`, renaming to
whatever the `song` format string produced. That name exists only after
matching, and preparation runs before it, so splitting cannot write final
filenames. Both steps end in staging:

| album | into staging | then |
|---|---|---|
| ordinary | `copy_files()` copies and renames from the share | -- |
| CUE | `shntool` splits the image into staging as `01.flac`... | `copy_files()` becomes a local rename |
| `.m4a` | `ffmpeg` transcodes into staging | `copy_files()` becomes a local rename |

For a prepared album the copy degenerates into a rename within one
filesystem -- effectively free, against the cross-link copy it is today. A
CUE rip would then cross the share only to read the image once and write the
finished album once. `copy_files()` already guards with
`if not source_folder == target_folder`, which is the branch a rename in
place would take.

**The source tree becomes read-only during preparation.** Stronger than
splitting `scan()` from `prepare()` achieved: that stopped a *dry run* from
rewriting the files it reported on, but a real run still mutates the source
before deciding anything about it.

**Re-runs become idempotent.** Today a CUE album split once presents a
different shape on its second pass, because the tracks it produced sit beside
the image.

**Two config keys can go.** With nothing new to stash, the only remaining job
is recognising the legacy directories, and their names were never a decision
the user has a stake in. Move `.cue` and `.m4a` into constants that
`ignored_source_dirs()` reads.

### The hazard, which is not optional

`cue.cue_done_dir` and `m4a.m4a_done_dir` carry two responsibilities that
look like one:

* `ignored_source_dirs()` prunes those directories from the scan
  (files.py:285-290). **This must stay permanently.**
* `shutil.move(path, done_dir)` stashes originals there. Only this is
  replaced, and only for new work.

Measured on the live library: **54 `.cue` and 54 `.m4a` directories in the
archive, and 3 more `.cue` in incoming** -- 108 in all, holding the only
copies of pre-conversion originals, several hundred megabytes each. Drop the
pruning and a scan walks into every one, treats each as an album, and either
tags duplicates or re-converts originals. The three in `incoming` would be
hit on the very next run.

So mark the keys **DEPRECATED, not REMOVED**, following
`naming.char_substitutions`: still honoured, still warning, so anyone who
customised a name keeps their directories pruned rather than silently walked
into.

One shape must keep scanning sensibly even though the new code would never
produce it: a legacy CUE rip split in place, originals in `.cue/` and tracks
beside them.

---

## A search that will match nothing has no budget

**Observed.** During a bulk run one album held a worker for over 25 minutes:

```
candidate comparisons in 25 min : 2374
no-match outcomes               : 0
successful matches              : 0
```

A 16-track album whose candidates all report 9, 11 or 2 tracks. Every one is
rejected on count, and the search keeps going: each search result has its
master sifted, and for a prolific artist that enumerates thousands of
releases before the tiers are exhausted.

It is not a hang -- the work is real and it does finish -- but the effort is
unbounded and produces nothing. It also makes monitoring harder: "no files
written for 25 minutes" is the signature of a wedged container, and here it
was a perfectly healthy one. The container log is the only reliable
discriminator, and even that misleads unless you know its clock runs an hour
behind the host.

**What would improve it.** A cap on comparisons per album, or an early exit
when a run of candidates all miss the track count by a wide margin. A 16-track
album against a 2-track release is not a near miss worth pursuing, and
nothing about the next thousand candidates will change that.

Worth measuring first: how often a match arrives *late* in the candidate list.
If matches essentially always land early, the cap can be tight and the saving
is large. That is a cheap thing to count from a cached corpus and would settle
the number rather than guessing it.

---

## An unsplit disc image counted as a track

**Rare, but it produced the worst pathology of a 107-unit run.** One album
held a worker for **50 minutes** and 2374 candidate comparisons before giving
up. David Bowie's *Hours*, in a directory that looks like this:

```
01 Thursday's Child.flac                    39 MB
...  (15 genuine tracks, 11-49 MB each)
15 We All Go Through ....flac               32 MB
16 David Bowie - Hours.flac.flac           494 MB   <- the whole album
   David Bowie - Hours.cue
   David Bowie - Hours.log
```

Some tool renamed the disc image as though it were track 16, doubling the
extension into `.flac.flac`. The album therefore presents as 16 tracks when
it is 15 plus a copy of the whole thing, and no release can match that: the
candidates it kept rejecting had 9, 11 and 2 tracks. It searched exhaustively
for something that was never there.

**The cue fix does not help, and should not.** The sheet names
`David Bowie - Hours.flac`, which no longer exists, so it is correctly judged
unusable and dropped. The problem is not the sheet; it is the file the sheet
points at masquerading as a track.

**Two signals, both already to hand:**

*Size.* A 494 MB file among 30 MB neighbours is not a track. A file several
times the median in a directory of otherwise-consistent audio is a
whole-album image whatever it is called. That alone would catch this.

*The orphaned sheet's stem.* `David Bowie - Hours.cue` and
`16 David Bowie - Hours.flac.flac` share a stem once a track-number prefix
and the doubled extension are stripped. Weaker than size, but it confirms it
-- and a doubled `.flac.flac` is itself a tell that something renamed a file
without understanding it.

Excluding such a file from the track count would let this album match as 15
tracks, and would have saved 50 minutes on one album. Worth pairing with the
search budget entry above: this is the case that motivates both.

## "No match found" hides the difference between absent and rejected

**The report is the defect, not the matching.** Jean-Michel Jarre's *Planet
Jarre* failed a batch with `No match found`, which reads as "Discogs does not
hold this release". Discogs holds it eight times over. The search compared 52
releases and rejected every one for a single reason:

```
[12530658] rejected — local has 36 tracks, Discogs has 41 (41 audio, 0 non-audio)
[12522642] rejected — local has 36 tracks, Discogs has 41 (41 audio, 0 non-audio)
[12523403] rejected — local has 36 tracks, Discogs has 136 (136 audio, 0 non-audio)
```

Every version on master 1423126 is 41 tracks, bar the 136-track box set. The
local copy is 36, split 6/9/9/12 across four disc folders, against a released
layout of 20/21 across two. **Five tracks are missing**, and the four-way split
matches no edition anyone has catalogued. That is a defect in the rip, and by
the standing rule that the library holds whole releases it is exactly the kind
of thing a run should be telling us.

Instead the run said the same three words it says for a white-label bootleg
that genuinely is not in any database. One is source material to re-acquire;
the other is nothing to be done. The log cannot tell them apart, so neither can
the person reading it, and a real gap in the library stays invisible behind a
message that sounds like a shrug.

**What the run already knows.** By the time it gives up it is holding the
closest release, the field that disqualified it, and the size of the gap. All
three are discarded. The information cost of reporting them is zero -- it is a
formatting change, not new work:

```
✗  Planet Jarre   No match — closest 12530658 (41 tracks, local 36); 5 short
✗  Copy Steal     No match — no candidates returned
```

**Three outcomes, not one.** Worth separating in the summary as well as the
line:

*No candidates.* Nothing came back from either source. Genuinely absent --
bootlegs, promos, single-track remix releases. Nothing to do.

*Rejected on track count.* Candidates found, all disqualified on length.
Almost always an incomplete or mis-split rip, and actionable: re-rip, or pin
the right release with `id.txt` once the files are right.

*Rejected on everything else.* Duration, catalog number, artist. Worth reading
individually; this is where genuine matching defects will surface.

**Why this outranks a matching fix.** The rejections above are correct -- a
36-track directory is not a 41-track release and should not be tagged as one.
The failure is that a run over 57 albums produces one undifferentiated pile of
`No match found`, and the only way to learn which kind each is, is to re-run it
by hand with `-v` and reassemble the wrapped log lines. That is the loop this
entry exists to close: every no-match should arrive already classified.

## A multi-disc set with one CUE sheet per disc folder loses its disc identity

Nick Cave & The Bad Seeds' *B-Sides & Rarities* -- an EAC rip of the physical
3xCD, three disc images with three sheets -- was filed as three albums:

```
/sorted/…/[2005] B-Sides & Rarities (Disc 1) [CDr …]              19 tracks  → 13855891
/sorted/…/[2005] B-Sides & Rarities (Disc 2) (CDMUTEL11) [CDr …]  18 tracks  → 11397434
/sorted/…/[2005] B-Sides & Rarities (Disc 3) (CDMUTEL11) [CDr …]  19 tracks  → 11397681
```

**The disc grouping is decided per directory.** `_processCueFiles` sets disc
identity only when a single directory holds more than one sheet:

```python
if len(files) > 1:
    cue.discnumber = str(idx + 1)
    cue.disctotal  = str(len(files))
```

and `_splitCueFile` groups the output only when that ran:

```python
if cue.disctotal is not None and int(cue.disctotal) > 1:
    destination = os.path.join(destination, 'cd' + str(cue.discnumber))
```

Three sheets side by side in one folder are handled correctly -- they become
`cd1`, `cd2`, `cd3`, which the scan's `^(cd|disc|disk)\s*\d+` test then reads
back as one multi-disc album. The same three discs in folders `1/`, `2/`, `3/`,
one sheet each, are three separate single-sheet directories. `len(files) > 1`
is false in each, so no disc number is assigned, the tracks split in place, and
the images are stashed to `1/.cue/`, `2/.cue/`, `3/.cue/`.

**The scan then has nothing left to group by.** `1` does not match the disc
pattern -- it wants a `cd`/`disc`/`disk` word -- so the walker descends and
treats each as its own album. The sheets knew: each `TITLE` reads
`B-Sides & Rarities (Disc N)`, and `_processCueFiles` strips exactly that
suffix before splitting. The disc number is read, used to clean the title, and
discarded.

**Nothing looked wrong, which is the part worth dwelling on.** Discogs
catalogues the Mute promo CDrs as three separate single-disc releases under
master 323438, at 19, 18 and 19 tracks. Each orphaned folder therefore found a
real release whose track count fitted exactly, was accepted at full confidence,
and passed without a warning. The near-miss reporting proposed above would not
have caught this: there was no near miss. Three correct matches to the wrong
three releases.

**The right release was there.** 429074 -- 3xCD, 56 tracks, 19/18/19 -- fits
the rip exactly, as do 1390744 and 12899192.

**The cost is a duplicate.** `sorted` already held
`[2017-01-03] B-Sides & Rarities [56xDM …]` at 56 tracks, so the library
carried the compilation twice, once whole and once in pieces.

**Two fixes, and the first is the real one.**

*Decide disc identity for the album, not the directory.* Gather the sheets
across an album's subdirectories before assigning numbers, so three folders
holding one sheet each are the same case as one folder holding three. The disc
number is already parsed out of each `TITLE`; use it instead of throwing it
away, and fall back to sorted order as now.

*Recognise bare numeric disc folders in the scan.* Narrower, and worth having
anyway for rips that arrive already split. Safe when the parent has no audio of
its own, every audio-bearing subdirectory is digits only, and there are at
least two numbered consecutively from 1. A folder called `1` alone means
nothing; three of them, sibling and consecutive under an empty parent, is a
disc layout and nothing else.

## An id.txt beside a disc image suppresses CUE splitting

Pinning *B-Sides & Rarities* to release 429074 with an `id.txt` stopped the
three CUE sheets from being split at all. The album reached the tagger as three
audio files -- the disc images themselves -- and died:

```
TaggerError: 'Flat multi-disc layout: 3 audio files found but Discogs lists
56 tracks across 3 discs. Check the release or arrange files into per-disc
subdirectories.'
```

**One early return does it.** `__main__.py`:

```python
if has_audio_here and has_id_here:
    return [source_dir], 0, {}
```

`has_audio_here` is true for any CUE album whose image sits in the album root,
which is the normal shape. The return happens before `scan()` and `prepare()`,
so the sheets are never seen, never split, and never reported as skipped. The
same album without the `id.txt` splits correctly.

**The two features are worth most together.** An `id.txt` is what a user
reaches for when the search picked the wrong release -- and a multi-disc CUE
set, whose disc layout the ranking does not compare, is exactly the case where
the search is most likely to pick the wrong release. The pin is unavailable
precisely where it is most needed.

**The early return is right for what it was written for**: a single-album run
on an already-split directory, where walking is pointless. It just tests the
wrong thing. Audio in the root does not mean the album is ready; a disc image
is audio, and it needs splitting before anything can be tagged. The condition
should exclude a directory that also holds usable CUE sheets, or -- cleaner --
should run `scan()`/`prepare()` first and take the early exit afterwards, when
"has audio here" has a settled meaning.

Worth pairing with the multi-disc grouping entry above: both come from the same
album, and both are about a decision made before the sheets have been read.

## Design: grouping CUE sheets into one multi-disc release

Requirements, from the B-Sides case and the ones around it:

* sheets may sit together in the album root **or** one per subfolder;
* the disc number may be absent from the sheet and have to come from the folder
  or file name;
* and the whole thing must not sweep unrelated releases into one set.

The third is the hard one, and it sets the bias: **over-grouping is much worse
than under-grouping.** Under-grouping is today's behaviour -- correct albums at
the wrong granularity, visible as duplicates, recoverable by re-running.
Over-grouping merges unrelated audio into one release, tags it from a tracklist
that does not describe it, and looks fine afterwards. Every rule below is
therefore written to refuse when uncertain.

### Stage 1 -- collect

Walk the album subtree for CUE sheets, skipping `cue_done_dir`, `m4a_done_dir`
and `ignored_source_dirs`. Keep only sheets whose `FILE` resolves against
their own directory -- the existing usability test, which already drops the
scratch sheets EAC leaves behind.

### Stage 2 -- decide whether they are one release

Group only when **every** one of these holds:

*Shape is uniform.* Either all sheets are in the album root, or every sheet is
alone in its own sibling subdirectory. A mixture is not a layout anyone
produces on purpose, and is the shape most likely to be two releases sharing a
folder.

*Depth is one.* No sheet more than one directory below the album root. This is
what stops an artist folder of separate CUE albums being read as a box set --
the failure this whole entry exists to prevent.

*The credit agrees.* `PERFORMER` matches across sheets once normalised. A
differing performer means separate releases, or a various-artists set that
should not be assembled this way regardless.

*The title agrees once the disc marker is stripped.* `B-Sides & Rarities
(Disc 1)`, `(Disc 2)`, `(Disc 3)` reduce to the same stem; `Heathen` and
`Reality` do not. This is the single strongest signal available and the one
that most reliably separates a box set from a folder of albums.

*The date agrees*, where present. Differing `REM DATE` is a strong negative.

*The numbers come out clean.* Derived disc numbers must be exactly 1..N, no
duplicates, no gaps.

Any failure: treat each sheet as its own album, as today. Log which test
failed.

### Stage 3 -- derive the disc number

First hit wins:

1. `REM DISCNUMBER` in the sheet.
2. A trailing disc marker in the sheet's `TITLE` -- `(Disc 2)`, `CD2`,
   `- Disc 2`. `_processCueFiles` already strips exactly this to clean the
   title; read it before discarding it.
3. The containing folder name: bare `2`, `CD 2`, `Disc 2`, or a trailing
   `… CD 2` -- note the current scan regex is anchored at the start and so
   misses the trailing form.
4. The sheet's filename, same patterns.
5. Sorted order.

**All or nothing.** Either every sheet gets its number from evidence (1-4), or
they all fall back to order (5). Mixing a derived `3` with a positional `1`
produces collisions, and a collision here means one disc silently overwriting
another.

### The volume trap

Only `cd`/`disc`/`disk` count as disc markers. `Vol. 1` and `Vol. 2` are as
often two releases as two discs of one -- and this very album proves the
ambiguity runs both ways: Discogs labels 429074's three discs
`Volume I`, `Volume II`, `Volume III` in their `discsubtitle`, while the sheets
call them `Disc 1..3`. Read volumes on the release side, never as a grouping
signal on the source side.

### Make the decision visible

One line per album: the shape detected, where each disc number came from, and
the failing test when grouping is refused. The B-Sides set ran five times over
two days without anything in the log suggesting the discs had been separated --
which is why it took a manual read of the audit trail to find. A rule this
conservative will refuse sometimes; refusing silently is how it becomes the
next invisible defect.

## A cassette can win a match against a CD rip

*Dig, Lazarus, Dig!!!*, a FLAC 16bit-44.1kHz rip, matched release 13741187 --
`1 x Cassette / Album | Mute CDSTUMM277 | Indonesia 2008`. Nothing in the
ranking weighs the release medium against the provenance the rip declares.

**16/44.1 is CD provenance.** Not proof -- a needle-drop or a tape transfer can
be resampled to it -- but it is what a CD rip always is, and the existing bit
depth gate already reasons this way in the other direction: `_CD_ONLY_FMTS`
rules out a CD when the audio is 24-bit, because no CD carries 24-bit audio. The
converse deserves the same treatment as a preference rather than a veto: at
16/44.1, prefer CD over Cassette, Vinyl and File, and let a strong signal such
as a catalogue number override it.

**Discogs data quality is part of it and cannot be relied on.** This very entry
is a "Cassette" carrying `CDSTUMM277`, a CD catalogue number. So the format
field alone should tilt the score rather than decide it -- a mis-catalogued
release must not be able to win outright, nor be excluded outright.

**The user had already found the better answer.** 3270382 -- `1 x CD / Album |
Mute LCD STUMM 277 | Russia 2008` -- is an 11-track CD, the obvious fit. The
matcher had it in reach and preferred a cassette.

Related to the disc layout entry above: both are cases where the ranking
compares tracklists but ignores what the release physically is.

## An averaged duration lets one wrong track reject the whole release

*Fifteen Feet Of Pure White Snow* failed to match. The correct release was
found, compared, and thrown out:

```
[35448229] rejected — avg track length diff 18.0s exceeds tolerance 10.0
```

Five local tracks against a five-track release, same titles, same order:

```
  #  track                              local  discogs   diff
  1  Fifteen Feet Of Pure White Snow      336      247    +89
  2  God Is in the House                  353      353      0
  3  We Came Along This Road              337      337      0
  4  And No More Shall We Part            254      255     -1
  5  Fifteen Feet of Pure White Snow      345      346     -1
                            mean absolute difference: 18.2s
```

**Four of five agree to within a second.** One track is 89s out -- Discogs
lists a 4:07 "Single Version" where the rip holds something longer. The mean
carries that one disagreement across the other four and the release is refused
at 18.2s against a 10.0s tolerance.

**The average is the wrong statistic.** It cannot tell "every track is
moderately wrong", which means a different release, from "one track is very
wrong", which usually means one mis-entered duration or one substituted
version. Those need opposite verdicts and the mean gives them the same one.
The median here is 1s.

**What to use instead.** Count agreement rather than averaging error: the
fraction of tracks within tolerance, needing most of them to agree. 4/5 accepts
this release; five tracks each 18s adrift scores 0/5 and is still refused. It
also degrades sensibly when Discogs lists no duration for some tracks, which
the mean currently handles by quietly shrinking its own sample. Keep a bound on
the worst single outlier if one is wanted, but do not let one track veto four.

**It is invisible, too.** The rejection is logged at debug; the run reports
`No match found`, indistinguishable from a release nobody catalogued. That is
the classification entry above, and this is its best worked example: an exact
title-and-order match on the right release, discarded on an averaged number,
reported as if nothing had been found.

## Every Discogs tier is anchored on the artist, so a mis-credited album is unreachable

*Idiot Prayer (Nick Cave Alone At Alexandra Palace)* failed with:

```
No match — closest 9043299 — 19 tracks, local has 22 (111 compared: 111 on track count)
```

111 releases compared, none of them the album. The correct releases were never
fetched at all:

```
16854426  File FLAC, Album, Stereo   22 tracks  -> 22/22 tracks agree on length
16236210  CD Album                   22 tracks  -> 22/22 tracks agree on length
```

Both would pass every acceptance check untouched. Discogs' own
`release_title=Idiot Prayer` returns seven results, all correct, first try.

**The folder says one artist and Discogs says another.** It is a solo Nick Cave
live album, credited on Discogs to `Nick Cave`. The local tags and folder call
it `Nick Cave & The Bad Seeds`. The search resolved that to artist 36665,
enumerated their releases, and compared 111 of the wrong artist's records.

**No tier can recover from it.** Tier 1 and 2 are `artist`+`title` field
searches; tier 3 browses the artist entity; and tier 4, the "safety net",
queries `artistRelease` -- artist and title concatenated. Four tiers, one
assumption: that the local artist string names the right Discogs artist. When
it does not, the right release is not merely ranked poorly, it is never
retrieved.

**A title-only tier would close it.** Search `release_title` alone, capped at a
handful of results, run only when every other tier has failed. The existing
acceptance rules are the safety net that makes this safe to try: an unrelated
album that happens to share a title fails on track count, and anything that
survives that must still agree on most durations. *Idiot Prayer* scores 22/22.

**A caution for the near-miss report.** This failure reads as "your rip has 22
tracks and the closest release has 19" -- which invites trimming the rip, the
opposite of the truth. When every comparison in a search was rejected on track
count and the closest is still several tracks out, the likelier reading is that
the pool is wrong, not the rip. Worth saying so: *"111 compared, none within 3
tracks -- the artist may be credited differently on Discogs"*.

The compilations already carry a related warning (`Compilation credited to
"Nick Cave & The Bad Seeds" rather than to a various-artist entry`), which is
the same disagreement seen from the other end.

## A single-track release has almost no evidence, and can be filed under anyone

The first confirmed wrong match in the library:

```
source : /incoming/Nick Cave/Thomas Feiner - The Ship Song (2022) [24B-48kHz]
matched: musicbrainz b7e6e4c9-701a-4e1d-b6f2-9bed3e9c2e51
filed as: Thomas Anders / [2010-12-10] The Christmas Song
```

One track, filed under a different artist's different song. It has sat in
`sorted` looking entirely normal ever since.

**Every check we have is satisfied trivially by one track.** Track count is
1 == 1. Duration agreement is a single comparison, so the 75% threshold is met
by one number falling within tolerance. What is left is fuzzy text: `Thomas
Feiner` against `Thomas Anders` scores well above threshold, and `The Ship
Song` against `The Christmas Song` shares two words of three. Nothing in the
pipeline was in a position to object.

**This is the largest category in the library.** The Trentemøller, Red Cell and
Snog singles are almost all one track, and every one of them is matched on this
evidence.

**What would help, in rough order of value.** Require more of a single-track
match than of an album: a tighter duration tolerance, since one track either is
or is not the same recording; a higher artist-similarity floor, since there is
no tracklist to corroborate it; and preference for an ISRC or DiscID match,
which identify a recording outright — tier 4.5 already does this and would have
refused here.

**Finding the rest is a separate job.** A first pass comparing the folder
artist against the artist we filed under turned up 15 disagreements, of which
roughly half look real -- `FabrikC` filed as `j:dead`, `Nick Cave` as `Gary
Lucas`, `Lunar Paths` as `Marianne Faithfull`. It did **not** catch the
Thomas Feiner case, because `thomasfeiner` and `thomasanders` are similar
enough to pass a 0.55 similarity floor. The near-name collisions are both the
most dangerous and the hardest to detect this way, so the true count is higher
than fifteen.

## Two sources that map to one target directory corrupt each other

`High Time (Chinese Takeaway)` exists twice in `sorted`: one folder holding the
sidecars and no audio, and a `(2)` folder holding the audio. The audit explains
it:

```
2026-09-01T16:28:44  failed  discogs 28525462   → …High Time…[1xDMS…]
     error: source_action remove/move: no audio files found in target
2026-09-01T16:28:44  ok      musicbrainz cf5cb13e → …High Time…[1xDMS…]
2026-09-02T11:08:07  ok      discogs 28525462   → …High Time…[1xDMS…] (2)
```

**The same second, two workers, one destination.** `/incoming` holds the album
twice -- the `[FLAC]` duplicate pair -- and both copies compute the same target
directory because they are the same release. With `batch.workers` above 1 they
were tagged concurrently: one wrote its audio there, the other found the
directory already populated, and the archive guard refused to move its source
because the target held no audio it recognised. A retry the next day collided
with the surviving folder and took the `(2)` suffix.

**The collision suffix is not the bug.** It did its job: nothing was
overwritten. The bug is that two albums were allowed to assemble into one
directory at the same time, which the suffix only helps with once one of them
has finished.

**Staging does not cover this.** Each album stages separately and moves at the
end, so the *contents* are safe -- but `_move_staged` resolves the collision at
move time, and two moves racing for the same destination can both see it free.

**What would fix it.** A destination claimed for the duration of a run: a
per-target lock taken before the move and released after, so the second album
waits and then takes the suffix deliberately rather than by accident. Cheaper
still, and worth doing anyway: detect at scan time that two source directories
resolve to the same release and process them in sequence, or refuse the second
with a message naming the first -- the user knows the duplicates are there and
would rather be told than have them silently interleave.

Related: the concurrency fix in 3.10.0 was the same shape one level up --
per-album state shared between workers. This is per-destination state shared
between workers.

## The backlog is singles, and a folder is not always a release

Measured on the 105 albums that failed in both of the last two runs:

```
  1 track    48   ################################################
  2-4        26   ##########################
  5+         30   ##############################
```

**70% hold four tracks or fewer, and nearly half are a single track.** This is
not a tail of odd cases; it is the shape of the remaining work.

Among the small ones:

```
  catalogued release larger than local   47
  nothing catalogued at all              23
  local bundle larger than the release   10
```

**Modern release practice is the cause, and it breaks an assumption the tagger
was built on: that a folder is a release.** Three patterns, all now common:

*The bundle.* A single is released as the new track plus two or three from the
back catalogue. ALT BLK ERA's three 2024 singles hold overlapping subsets of
the same three tracks, one of them with a remix. MusicBrainz catalogues each as
a **1-track Single**; the folders hold 3, 3 and 2. No release in either
database matches the folder, because the folder is a bundle rather than an
edition.

*The repackage.* The same tracks reappear in a different order under a
different title track. Each pressing is a distinct release, and the local copy
may correspond to none of them.

*The per-service edition.* The same album is issued in different shapes across
streaming services -- different bonus tracks, different masters, so different
durations. Discogs catalogues some of these as separate `File` releases and
most not at all, so exact track count and duration agreement are both weaker
evidence for digital than they are for a CD rip.

**What follows from this.**

Exact track count is the wrong gate for a small digital release. It is a good
gate for a CD rip, where the medium fixes the contents. Treating a candidate as
plausible when the local tracks are a **subset** of its tracklist would cover
the 47 in the largest group -- a 1-track folder whose track appears on a
catalogued single or album -- provided the matched track's title and duration
agree closely. The risk is filing a single under an album, so the release
chosen should prefer a Single release-group over an album when one exists.

A single track is a recording, not a release, and should be identified as one.
Tier 4.5 already looks up ISRCs and would answer many of these outright; it
currently requires two agreeing codes, which a 1-track folder can never supply.
Worth revisiting that floor specifically for the single-track case, where the
alternative is not a weaker match but no match at all.

And the reporting should say which of these it is. "Rejected on track count,
local has 1, closest has 15" reads as a defective rip when it usually means a
single whose track the database only catalogues as part of an album.
