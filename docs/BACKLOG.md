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

## Everything prepare() produces belongs in staging, not the source tree

`FileUtils.prepare()` has exactly two kinds of work -- `PrepTask.kind` is
`'cue' | 'm4a'` -- and both write derived audio into the source directory.

**CUE splitting:**

* `destination = cue.image_file_directory` (files.py) -- the split tracks land
  beside the disc image and stay there
* `tmp_wav = src_image + '_tmp_decode.wav'` -- a full WAV decode of the image,
  written next to it and then deleted

For a three-disc rip of ~500 MB images that is roughly 4.5 GB of transient
writes and 3.4 GB of lasting ones, all at the 9.8 MiB/s NAS-to-NAS rate that
`batch.staging_dir` exists to avoid. It is the heaviest filesystem operation
in the pipeline, and staging does not reach it: staging redirects the
*processor's destination*, while splitting happens earlier, in
`_get_source_dirs` -> `FileUtils.prepare()`.

**`.m4a` conversion does the same:** `out = os.path.splitext(path)[0] + '.'
+ target_ext` writes the transcode beside the original, and the original is
then `shutil.move`d into a done directory. A converted album therefore leaves
both the new files and a directory of originals behind, all on the share.

**The right framing is not "staging should cover more".** Nothing `prepare()`
produces is source material. The source is what the user put there -- a disc image
and its sheet, or a folder of `.m4a` -- and everything prepare() makes from
it is a decode artefact, produced to be tagged and then finished with.
Staging is where temporary files belong, and leaving them in the source tree
is pollution -- a CUE rip that has been through the tagger once is no longer
the thing the user put there.

**The complication, and it is the whole of the work.** `sourcedir` currently
means two things at once: where the audio is read from, and what
`source_action` archives or deletes. `_post_process_source` calls
`shutil.move(result.sourcedir, ...)` and `shutil.rmtree(result.sourcedir)`.
If splitting wrote to staging and the album's `sourcedir` became that path,
`move` would archive the temporary split and leave the disc images in
`incoming` for ever; `remove` would delete the split and leave them too.

So the two roles have to separate before anything else: an *origin* that
archiving acts on -- always the directory the user put there -- and an *audio
directory* the scan and processor read from, which for a CUE rip is the
staging copy and for everything else is the same as the origin.

With that separation the rest is small: `prepare()` splits into a staging
directory, returns it as the audio directory, and the existing staging
cleanup removes it afterwards -- emptied on the way out, swept on the way in,
exactly as the finished album already is.

**A second thing this buys.** With prepare() writing to staging, the source
tree becomes genuinely read-only during preparation. That is a stronger
guarantee than splitting `scan()` from `prepare()` achieved: that split
stopped a *dry run* from rewriting the files it was reporting on, but a real
run still mutates the source before deciding anything about it. It also makes
re-runs idempotent -- today a CUE album that has been split once presents a
different shape on the second pass than it did on the first, because the
tracks it produced are sitting next to the image.

**Do not deprecate `*_done_dir` awareness along with it.** The keys carry two
separate responsibilities that only look like one:

* `ignored_source_dirs()` prunes `.cue` and `.m4a` from the scan
  (files.py:285-290). **This must stay permanently.**
* `shutil.move(path, done_dir)` stashes originals there. This is the part
  staging replaces, and only for new work.

Measured on the live library: **54 `.cue` and 54 `.m4a` directories in the
archive, and 3 more `.cue` in incoming** -- 108 in all, holding the original
disc images and `.m4a` files, several hundred megabytes each. They are the
only copies of the pre-conversion originals.

Drop the pruning and a scan walks into every one of them, treats each as an
album, and either tags duplicates or re-converts originals. The three in
`incoming` would be hit on the very next run.

So the change is safe only while scoped to the write side: keys, defaults and
pruning all stay; only where preparation *puts* things moves. Nothing already
on disk changes meaning.

One shape to keep reading correctly: a legacy CUE rip already split in place
has its originals in `.cue/` and its split tracks beside them. The new scheme
would never produce that, but it exists and must still scan sensibly.

**And then the two keys can go from the configuration.** Once preparation
writes to staging there is nothing new to stash, so the only remaining job is
recognising the legacy directories -- and their names never needed to be a
user's decision. Nobody cares what a temporary directory inside the cache is
called.

Move `.cue` and `.m4a` into constants that `ignored_source_dirs()` reads, and
mark `cue.cue_done_dir` and `m4a.m4a_done_dir` **DEPRECATED rather than
REMOVED**, following `naming.char_substitutions`: the key still works and
warns, so anyone who customised the name keeps their directories pruned
instead of having them silently walked into. The live configuration uses the
defaults, so for this deployment it is simply two fewer keys.

That is the shape the config discipline already asks for -- defaults live in
code, and the configuration holds decisions the user actually has a stake in.
Where a scratch directory sits inside the cache is not one of them.
