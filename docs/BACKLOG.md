# Backlog

Work identified while running massMusicTagger over a real library, kept here
rather than in a commit message so it can be found again. Each entry says what
was observed, what is actually happening, and what would improve it.

---

## Canonicalise the artist name when falling back to existing tags

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

`use_anv` controls whether the sleeve credit (Discogs' Artist Name Variation)
is preferred over the canonical database name. It is currently `false`.

Even so, the distinction is worth making explicit rather than settled by one
switch: an ANV is the right name for a **track** artist, because it is what
the release actually credits, and the wrong name for the **album artist and
directory**, because it fragments a discography across folders. Two different
questions currently share one answer.

---

## Consider a wider check on artwork shape

`_local_front` compares aspect ratios to distinguish "the same picture,
scanned larger" from "a different picture that happens to be bigger" — which
is what stops a 2.4:1 sleeve spread being embedded as the front cover.

The same reasoning applies to what a *source* offers. Cover Art Archive typed
a 5033x1465 wraparound scan as `Front` for The Waterboys' Modern Blues, and
`image_policy: prefer_larger` compares pixel counts, so a spread always wins
on size. It is currently only avoided because the release also had a local
cover to prefer.

Not obviously right to impose: the source *said* it was the front, and some
releases genuinely have wide covers. Worth a decision rather than a default.

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

## An already-finished tree reports "No audio source directories found"

**Observed.** Two albums in a re-tag run logged:

```
WARN No audio source directories found
```

Both were fine. Each held a `.done` marker from an earlier run, so
`get_audio_dirs` skipped them, and with nothing left the caller reported the
empty result as a warning — the same message an empty or unreadable directory
produces.

The two cases deserve different words. Nothing to do is a success; nothing
*found* is a problem, and reading the first as the second sends you looking
for a fault that is not there. It cost real time during the bulk re-tag,
because the warning appears in exactly the same place as a genuine failure.

**What would improve it.** `scan()` already knows how many directories it
skipped for a done marker. Carry that count out and say so:

```
All 2 albums already tagged (.done present) — use --force to re-tag
```

reserving the existing warning for a tree that genuinely holds no audio. The
information is already in hand; only the message is missing.

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

---

## A MusicBrainz release with no date leaves the album with no year

**Observed.** *Station to Station (Ryko remaster) (RCD 10141)* was filed with
no year at all, while the LP beside it got `[1976-01-23]`:

```
David Bowie/Station to Station (Ryko remaster) (RCD 10141) [CD flac-lossless-44s]
David Bowie/[1976-01-23] Station to Station (APL1 1327) [LP flac-lossless-44s]
```

It matched MusicBrainz release `3abff816-a765-4aca-817d-030781b7979a`, whose
`date` is the empty string. `album.year` is taken straight from it:

```python
# sources/musicbrainz/album.py:83
album.year = date_str[:4] if len(date_str) >= 4 else None
```

This is the same defect that was fixed on the Discogs side, where a release
with no year now falls back to its master. MusicBrainz never got the
equivalent.

**Two separate problems, and the order matters.**

*The search does not prefer a dated candidate.* MusicBrainz holds three
releases with that catalogue number:

| date | country | label | id |
|---|---|---|---|
| *(none)* | US | Rykodisc | `3abff816` ← chosen |
| 1991 | US | Rykodisc | `a25dc82a` |
| 1991 | US | BMG Direct Marketing | `8393fe01` |

All three are the same pressing. Nothing breaks the tie on completeness, so
the one release lacking a date was as likely to win as either that has one.
A candidate carrying a date is strictly more useful than one that does not,
and this is the fix that yields the *right* answer: **1991**, the year of
this edition.

*There is no release-group fallback.* Even having chosen the undated release,
`release-group['first-release-date']` was `1976-01-23` and went unused. The
release group is already fetched — `release-groups` is in `_INCLUDES`
(connector.py:45) and `rg` is read at album.py:101 for the type fields — so
the fallback costs no extra request.

Worth being explicit about what it gives, though: the release group's date is
the date of the *original* release, so this fallback would file the 1991
remaster under 1976. That is the same trade-off already accepted for the
Discogs master-year fallback. It is the right safety net when no dated
candidate exists at all, and the wrong thing to reach for first — hence the
ordering above.
