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

## Bound CPU-heavy work with one global semaphore

**Observed.** Concurrent decode threads are `batch.workers x os.cpu_count()`,
because each worker's album spawns its own `r128gain` and `taggerutils.py`
passes no `-c`, so r128gain falls back to `OPTIMAL_THREAD_COUNT =
os.cpu_count()`. At `workers: 1` on an 8-core host that is 8 decodes. At
`workers: 4` on a 4-core mini-PC it is 32.

**Measured**, 12 FLAC / 345 MB, on local disk so the share could not mask it:

| `r128gain -c` | wall time |
|---|---|
| 1 | 35.1s |
| 2 | 19.1s |
| 4 | 20.1s |
| 8 | 20.6s |

It saturates at **two threads**. Four and eight buy nothing and eight is
marginally slower. Everything above 2 is pure contention.

For scale, the same album read from the NAS took 33.0s against 19.1s of
scanning — 1.7 : 1 I/O to CPU on the development machine. The deployment
hosts are second-hand mini-PCs sharing that same link with slower cores, so
the ratio there moves toward CPU and the oversubscription costs more, not
less.

**Why a semaphore rather than fewer workers.** Workers exist to overlap
*waiting*, and waiting is still the dominant cost. Cutting workers to protect
the CPU throws away the I/O overlap with it. One dial currently controls both
concerns, multiplicatively; they want separating, so a deployment can run
`workers: 4` for the link and `cpu_jobs: 1` for the processor.

**Why one semaphore rather than a queue per stage.** The contended resource is
the CPU itself, shared by four external programs: `r128gain`, `shntool` plus
`flac` for CUE splitting, `ffmpeg` for `.m4a` transcoding, and `fpcalc` for
fingerprinting. Per-stage queues would each run at their own cap
simultaneously and rebuild the problem a level up. A single counting
semaphore around every CPU-heavy subprocess is both smaller and correct.

Workers are threads in one process (`ThreadPoolExecutor`,
[processor.py:305]), so this is a module-level `BoundedSemaphore` rather than
any cross-process machinery.

**What to do:**

1. Pass `-c` to r128gain from a config key, defaulting to 2. One line, and it
   removes a 4x-8x oversubscription on its own.
2. Add `batch.cpu_jobs` (default 1) and a global semaphore held across every
   external CPU-heavy subprocess call.

Aim it at the weakest deployment: the same configuration then simply runs
faster on a stronger machine instead of needing different settings.
