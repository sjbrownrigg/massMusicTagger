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
