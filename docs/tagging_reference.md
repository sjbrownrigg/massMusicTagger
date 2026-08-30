# Tagging reference — massMusicTagger

What massMusicTagger writes into your files, and the format strings that decide
what those files are called.

The tables below label one column **dt3**. That is the Discogs path as
massMusicTagger inherited it from discogstagger3, kept as a column because it
is a useful "this is the older behaviour" marker — not because discogstagger3
is involved at run time. It has not been since 3.0.0.

---

## Contents

1. [Format string functions](#format-string-functions)
2. [Additional format string variables](#additional-format-string-variables)
3. [Changes to existing variables](#changes-to-existing-variables)
4. [Custom variables](#custom-variables-custom-variables)
5. [Complete tag mapping table](#complete-tag-mapping-table)
6. [Underlying tag names by format](#underlying-tag-names-by-format)
7. [Image handling](#image-handling)

---

## Format string functions

Format strings are literal text with `%variables%` substituted in and
`$functions()` that can nest inside each other:

```ini
song = $num('%tracknumber%','2') $if1($neg($strcmp('%artist%','%albumartist%')),'%artist% - ')%title%%fileext%
```

Read that as: the track number padded to two digits, then — only if the track
artist differs from the album artist — that artist and a dash, then the title.

Every example below is taken from the test corpus that pins this behaviour, so
they are what the functions actually do rather than what they are meant to do.

### Text

| Function | Does | Example → result |
|---|---|---|
| `$upper(s)` | Uppercase | `$upper('abc')` → `ABC` |
| `$lower(s)` | Lowercase | `$lower('ABC')` → `abc` |
| `$num(s,places)` | Pad a number with leading zeros. Non-numeric values, such as vinyl positions like `A1`, pass through untouched | `$num('7','3')` → `007` |
| `$substr(s,start,end)` | A slice. Either end may be empty, and negatives count from the right | `$substr('abcdefgh','','-3')` → `abcde` |
| `$strchr(s,c)` | Position of the first `c`, counting from zero; `-1` when absent | `$strchr('hello','l')` → `2` |
| `$wrap(s,before,after)` | `before + s + after`, or **nothing at all** when `s` is empty | `$wrap('x','[',']')` → `[x]`, `$wrap('','[',']')` → *(empty)* |

`$wrap` is the one to reach for when a piece of punctuation should only appear
if its content does. `$wrap('%edition%',' (',')')` adds the brackets only when
there is an edition to put in them.

### Tests

These return true or false, and are meant to be used inside `$if1`.

| Function | True when |
|---|---|
| `$valid(s)` | `s` is non-empty |
| `$strcmp(a,b)` | `a` and `b` are identical |
| `$stricmp(a,b)` | …ignoring case |
| `$contains(s,part)` | `part` appears in `s` |
| `$icontains(s,part)` | …ignoring case |
| `$inarray(list,item)` | `item` is in a list variable such as `%format_description%` |
| `$neg(x)` | `x` is false |
| `$any(…)` | any argument is true |
| `$all(…)` | every argument is true |

```
$all($valid('x'),$valid('y'))   → True
$all($valid('x'),$valid(''))    → False
$any($valid(''),$valid('x'))    → True
```

### Choices

| Function | Does | Example → result |
|---|---|---|
| `$if1(test,then,else)` | `else` is optional and defaults to nothing | `$if1($valid(''),'yes','no')` → `no` |
| `$if2(a,b)` | `a` if it is non-empty, otherwise `b` | `$if2('','fallback')` → `fallback` |
| `$if3(a,b,c,…)` | The first non-empty argument | `$if3('','','third')` → `third` |
| `$ifeq(a,b,then,else)` | Compare as text | `$ifeq('a','b','same','diff')` → `diff` |
| `$ieq(a,b,then,else)` | …ignoring case | `$ieq('A','a','same','diff')` → `same` |
| `$ifequal(a,b,then,else)` | Compare as **numbers** | `$ifequal(2,2,'eq','ne')` → `eq` |
| `$ifgreater(a,b,then,else)` | Numeric greater-than | `$ifgreater(2,3,'gt','le')` → `le` |
| `$switch(v,k1,r1,k2,r2,…,default)` | Match `v` against each key | `$switch('9','1','one','2','two','other')` → `other` |
| `$iswitch(…)` | …ignoring case | `$iswitch('BOOTLEG','bootleg','B','promo','P','')` → `B` |

`$ifeq` compares text and `$ifequal` compares numbers — a distinction worth
remembering, because `$ifeq('2','02',…)` and `$ifequal(2,02,…)` disagree.

### Lists

Some variables hold a list rather than a single value — `%catnos%`,
`%format_description%`, `%format_names%`. `$flatten` turns part of one back
into text.

| Function | Does | Example → result |
|---|---|---|
| `$flatten(list,slice,join)` | Slice, then join with `join` | `$flatten('["A","B","C"]','0','')` → `A` |
| | The slice is Python's, so `:2` means the first two | `$flatten('["A","B","C"]',':2',' / ')` → `A / B` |
| | and `:` means all of them | `$flatten('["A","B","C"]',':',' + ')` → `A + B + C` |

### Two things worth knowing

**A `+` between two functions is not concatenation at the top level.** Inside
an argument it joins values; in ordinary text it is a plus sign. So
`$upper('a')+' '+$upper('b')` produces `A+' '+B`, while the same expression
*inside* an argument produces `A B`. Adjacent items concatenate on their own —
`$upper('a')$upper('b')` gives `AB` — so a `+` is rarely what you want outside
an argument.

**An unknown function name replaces the whole expression** with
`unknown command`, rather than being left as text. If a filename comes out
saying that, check the spelling of every function in the string, not just the
obvious one.

### Trying a change safely

`format_preview.py` renders your format strings against fixture albums, so you
can see the effect before running the tagger over anything:

```bash
python format_preview.py --conf ~/.config/massmusictagger
python format_preview.py --conf ~/.config/massmusictagger --watch   # re-run on save
```

---

## Additional format string variables

### massMusicTagger-only variables

| Variable | Description | Discogs | MB |
|---|---|---|---|
| `%releasetype%` | Primary release type: `Album`, `Single`, `EP`, `Compilation`, `Live`, `Remix`, … | Inferred from format descriptions via `release_type_map` in `format_codes.yaml` | Read directly from `release-group.primary-type` |
| `%format_base%` | Physical medium without quantity prefix: `CD`, `LP`, `12″`, `CDr`, `DM`. Unlike `%format_code%`, never includes `D`/`3x`/… | Same as `%format_code%` when disctotal=1 | Same |
| `%digital%` | `'1'` for digital formats (`File`, `Web`, `Digital Media`); `''` for physical. Use in custom variables to add per-track counts without enumerating format names. | Based on `formats[0].name` | Based on `medium[0].format` |
| `%disambiguation%` | MusicBrainz disambiguation string — the edition statement distinguishing this pressing from others with the same title, e.g. `Beatport expanded version (US)`. Used as `%edition%` when `compute_edition()` finds no keyword match. | — | `release.disambiguation` |
| `%status%` | Release status: `Official`, `Promo`, `Bootleg`, `Pseudo-Release`. MB `Promotional` is normalised to `Promo`. Empty string when absent. | `release.status` | `release.status` (normalised) |

---

## Changes to existing variables

### `%format_code%`

massMusicTagger **removes** the release-type suffix and edition prefix from
`%format_code%`. It now encodes only the **physical medium and quantity**:

| Example | discogstagger3 | massMusicTagger | Type now via | Edition now via |
|---|---|---|---|---|
| CD Single | `CDS` | `CD` | `%releasetype%` = `Single` | — |
| Limited CD Single | `LCDS` | `CD` | `%releasetype%` = `Single` | `%edition%` = `Limited Edition` |
| 7″ Single | `7″S` | `7″` | `%releasetype%` = `Single` | — |
| 12″ Single | `12″S` | `12″` | `%releasetype%` = `Single` | — |
| 12″ Album (LP) | `12″` | `LP` | — (Album implicit) | — |
| Limited 2×CD | `LDCD` | `DCD` | — (Album implicit) | `%edition%` = `Limited Edition` |
| Digital album | `file` | `DM` | — | — |

Quantity (`DCD`, `3xLP`) is retained as it describes the physical object.

---

## Custom variables (`[custom-variables]`)

massMusicTagger supports a `[custom-variables]` section in the formats INI
file. Reference variables as `%__varname__%` in any format string.

See [`conf/formats.ini`](https://github.com/sjbrownrigg/massMusicTagger/blob/master/conf/formats.ini)
for syntax, rules, and worked examples.

### Boolean logic helpers

Three functions make multi-condition tests inside custom variables readable
without deep nesting. See the [dt3 reference](https://github.com/sjbrownrigg/discogstagger3/blob/master/docs/tagging_reference.md#boolean-logic----any-all-neg) for full details.

| Function | Meaning |
|---|---|
| `$any(c1, c2, …)` | `True` if **any** argument is truthy — boolean OR |
| `$all(c1, c2, …)` | `True` if **all** arguments are truthy — boolean AND |
| `$neg(cond)` | Inverts truthiness — boolean NOT |

```ini
; Single OR Maxi-Single → show 'S' or 'M'
type_abbr = $if1($any($strcmp('%releasetype%','Single'),$strcmp('%releasetype%','Maxi-Single')),'S','')

; NOT an Album → show releasetype in the bracket
type_label = $if1($neg($strcmp('%releasetype%','Album')),'%releasetype%','')
```

The shipped `formats_personal.ini` includes a `status_abbr` building block:

```ini
; .B for Bootleg, .P for Promo, blank for Official
status_abbr = $if1($stricmp('%status%','bootleg'),'.B',$if1($stricmp('%status%','promo'),'.P',''))

; Append to format_desc:
format_desc = ...%__medium__%$if1(...)%__status_abbr__%
```

Results: `LP.B` (bootleg LP), `12″S.P` (promo 12" single), `CD` (official CD).

**Critical rule:** custom variables whose values contain `$function()` calls
must **not** be wrapped in single quotes when passed as arguments — single
quotes make the expansion a string literal that breaks `eval()`:

```ini
; BAD  — qty expands to $if1() but is quoted = SyntaxError:
format_desc = $if1('%digital%','2x','%__qty__%')

; GOOD — qty expands to $if1() and is treated as code:
format_desc = $if1('%digital%','2x',%__qty__%)
```

---

## Complete tag mapping table

This table shows every metadata tag written by discogstagger3 and/or
massMusicTagger, with the data source for both the Discogs and MusicBrainz
paths.

### Key

| Column | Meaning |
|---|---|
| **dt3** | The older Discogs-path behaviour, inherited from discogstagger3 |
| **mmt/Discogs** | Written by massMusicTagger on the Discogs path |
| **mmt/MB** | Written by massMusicTagger on the MusicBrainz path |
| ✓ | Written |
| ✓† | Written, but differently from that older behaviour |
| — | Not written |
| N | Native mediafile field |
| C | Custom field added via `MediaFile.add_field()` in `mediafile_ext.py` |

---

### Album-level tags

| MediaFile attr | dt3 | mmt/Discogs | mmt/MB | N/C | Discogs source | MB source |
|---|---|---|---|---|---|---|
| `album` | ✓ | ✓ | ✓ | N | `release.title` | `release.title` |
| `albumartist` | ✓ | ✓ | ✓ | N | `release.artists` combined with join text; ANV used when `use_anv: true` | `release.artist-credit` combined with joinphrase; credited name preferred |
| `albumartists` | ✓ | ✓ | ✓ | N | Individual artist names as array | Individual credited names as array |
| `albumartist_sort` | ✓ | ✓ | ✓† | N | First artist canonical name | First artist `sort-name` from MB (e.g. `deadmaus` for `deadmau5`) |

### Filing under the primary artist

`%albumartist_primary%` is a format-string variable only — it is never
written as a tag. It reads the same as `%albumartist%` except when a credit
is one artist with guests:

| credit | `%albumartist%` | `%albumartist_primary%` |
|---|---|---|
| David Bowie Featuring Al B. Sure! | *unchanged* | `David Bowie` |
| D.A.R.P.A. / Dive / :wumpscut: | *unchanged* | *unchanged* |
| DHS vs. DJ Slip | *unchanged* | *unchanged* |
| David Bowie = David Bowie | *unchanged* | `David Bowie` |

Use it in the `dir` format string to stop guest credits fragmenting an
artist's discography, while the `albumartist` tag keeps saying exactly what
the release says.

Two things decide the result, and both are yours. Credits resolving to one
artist are collapsed first — the last row above is Discogs' transliteration
form, the same artist id listed twice — and after that
[`artist_joins.yaml`](../src/massmusictagger/conf/artist_joins.yaml) says
which join phrases mark a guest. Unlisted joins keep the whole credit, so
`and` and `,` ship unlisted rather than guessed at; move them if your
collection wants them collapsed.
| `composer` | ✓ | ✓† | ✓† | N | dt3: album artist. mmt: actual composers from `release.extraartists` (Written-By, Composed By) when present; empty otherwise | Composers from MB release relations (future work) |
| `year` | ✓ | ✓ | ✓ | N | `release.year` | First 4 chars of `release.date`; skipped when absent |
| `date` | — | ✓† | ✓† | N | `release.released` normalised — strips zero components (`1998-01-00` → `1998-01`) | `release.date` normalised |
| `label` | ✓ | ✓ | ✓ | N | `release.labels[0].name` (first in Discogs order) | `release.label-info-list[0].label.name` |
| `catalognum` | ✓ | ✓ | ✓ | N | `release.labels[].catno` — first non-empty, non-`none` | `release.label-info-list[0].catalog-number` |
| `country` | ✓ | ✓ | ✓ | N | `release.country` | `release.country` |
| `genres` | ✓ | ✓ | ✓† | N | `release.genres` | `release-group.tag-list` — MB community genre tags, sorted by vote count |
| `grouping` | ✓ | ✓ | — | N | `release.styles` joined | MB has no styles equivalent |
| `media` | ✓ | ✓ | ✓ | N | `formats[].qty + name + descriptions` joined | Semicolon-joined medium formats |
| `disc` | ✓ | ✓ | ✓ | N | Parsed from tracklist position | Medium position |
| `disctotal` | ✓ | ✓ | ✓ | N | Count of distinct disc positions in tracklist | `len(medium-list)` |
| `disctitle` | ✓ | ✓ | ✓ | N | Tracklist heading classified by disc-boundary lookahead | `medium.title` |
| `comp` | ✓ | ✓ | ✓ | N | `release.artists[0].name == "Various"` or Compilation description | Various Artists in artist-credit or `Compilation` in secondary-type-list |
| `comments` | ✓ | ✓ | ✓ | N | `release.notes` | `release.annotation` |
| `barcode` | — | ✓† | ✓† | C | First `Barcode` identifier from `release.identifiers` | `release.barcode` field |
| `discogs_id` | ✓ | ✓ | — | C | `release.id` | — (use `musicbrainz_releaseid` instead) |
| `discogs_release_url` | ✓ | ✓ | ✓ | C | `https://www.discogs.com/release/{id}` | `https://musicbrainz.org/release/{mbid}` |
| `discogs_release_status` | — | ✓† | ✓† | C | `release.status` (`Official`, `Promo`, `Bootleg`, `Pseudo-Release`) | `release.status` |
| `musicbrainz_releaseid` | — | — | ✓† | C | — | `release.id` (UUID) |
| `musicbrainz_releasegroupid` | — | — | ✓† | C | — | `release-group.id` (UUID) |
| `releasetype` | — | ✓† | ✓† | C | Inferred from format descriptions via `release_type_map` in `format_codes.yaml` | `release-group.primary-type` |
| `tagger_source` | — | ✓† | ✓† | C | Which source wrote the tags: `discogs`, `musicbrainz`, or `existing_tags` | same |

---

### Track-level tags

| MediaFile attr | dt3 | mmt/Discogs | mmt/MB | N/C | Discogs source | MB source |
|---|---|---|---|---|---|---|
| `title` | ✓ | ✓ | ✓ | N | `tracklist[n].title` | `track.title` or `recording.title` |
| `artist` | ✓ | ✓ | ✓ | N | `tracklist[n].artists` combined; inherits album artist when no per-track credit | `track.artist-credit`; inherits album artist |
| `artists` | ✓ | ✓ | ✓ | N | Individual track artist names | Individual credited names |
| `artist_sort` | ✓ | ✓ | ✓† | N | First track artist canonical name | First track artist `sort-name` from MB |
| `track` | ✓ | ✓ | ✓ | N | Parsed from tracklist position | `track.number` |
| `tracktotal` | ✓ | ✓ | ✓ | N | Count of tracks on the disc | Count of `track-list` entries in the medium |
| `isrc` | — | — | ✓† | C | — | `recording.isrc-list[0]` |
| `musicbrainz_trackid` | — | — | ✓† | C | — | `recording.id` (Recording UUID) |

---

### ReplayGain tags (post-tagging, source-independent)

| MediaFile attr | Written | N/C | Source |
|---|---|---|---|
| `r128_album_gain` | ✓ | N | `r128gain` / `loudgain` |
| `r128_track_gain` | ✓ | N | `r128gain` / `loudgain` |
| `rg_album_gain` | ✓ | N | `metaflac` / `loudgain` |
| `rg_album_peak` | ✓ | N | `metaflac` / `loudgain` |
| `rg_track_gain` | ✓ | N | `metaflac` / `loudgain` |
| `rg_track_peak` | ✓ | N | `metaflac` / `loudgain` |

---

### User-configurable extras

| MediaFile attr | Written | N/C | Config key |
|---|---|---|---|
| `encoder` | ✓ (empty by default) | N | `tags.encoder` |
| `freedb_id` | ✓ (preserved) | C | `keep_tags: freedb_id` |

---

## Underlying tag names by format

Full combined table including all discogstagger3 fields plus massMusicTagger additions.

| MediaFile attribute | FLAC / Vorbis | MP3 / ID3v2 | MP4 / M4A | ASF / WMA |
|---|---|---|---|---|
| `album` | `ALBUM` | `TALB` | `©alb` | `WM/AlbumTitle` |
| `albumartist` | `ALBUMARTIST` | `TPE2` | `aART` | `WM/AlbumArtist` |
| `albumartists` | `ALBUMARTISTS` (multi) | `TXXX:Artists` | `----:com.apple.iTunes:ARTISTS` | `WM/AlbumArtists` |
| `albumartist_sort` | `ALBUMARTISTSORT` | `TSO2` | `soaa` | `WM/AlbumArtistSortOrder` |
| `artist` | `ARTIST` | `TPE1` | `©ART` | `Author` |
| `artists` | `ARTISTS` (multi) | `TXXX:Artists` | `----:com.apple.iTunes:ARTISTS` | `WM/Artists` |
| `artist_sort` | `ARTISTSORT` | `TSOP` | `soar` | `WM/ArtistSortOrder` |
| `composer` | `COMPOSER` | `TCOM` | `©wrt` | `WM/Composer` |
| `title` | `TITLE` | `TIT2` | `©nam` | `Title` |
| `year` | `DATE` | `TDRC` | `©day` | `WM/Year` |
| `date` | `DATE` | `TDRC` | `©day` | `WM/Year` |
| `label` | `LABEL` | `TPUB` | `----:com.apple.iTunes:LABEL` | `WM/Publisher` |
| `catalognum` | `CATALOGNUMBER` | `TXXX:CATALOGNUMBER` | `----:com.apple.iTunes:CATALOGNUMBER` | `WM/CatalogNo` |
| `country` | `RELEASECOUNTRY` | `TXXX:MusicBrainz Album Release Country` | `----:com.apple.iTunes:MusicBrainz Album Release Country` | `MusicBrainz/Album Release Country` |
| `genres` | `GENRE` (multi) | `TCON` | `©gen` | `WM/Genre` |
| `grouping` | `GROUPING` | `TIT1` | `©grp` | `WM/ContentGroupDescription` |
| `media` | `MEDIA` | `TMED` | `----:com.apple.iTunes:MEDIA` | `WM/Media` |
| `comments` | `COMMENT` | `COMM:eng` | `©cmt` | `WM/Description` |
| `disc` | `DISCNUMBER` | `TPOS` | `disk` | `WM/PartOfSet` |
| `disctotal` | `DISCTOTAL` | `TPOS` (as `n/total`) | `disk` (as `n/total`) | `WM/PartOfSet` |
| `disctitle` | `DISCSUBTITLE` | `TSST` | `----:com.apple.iTunes:DISCSUBTITLE` | `WM/SetSubTitle` |
| `track` | `TRACKNUMBER` | `TRCK` | `trkn` | `WM/TrackNumber` |
| `tracktotal` | `TRACKTOTAL` | `TRCK` (as `n/total`) | `trkn` (as `n/total`) | `WM/TrackNumber` |
| `comp` | `COMPILATION` | `TCMP` | `cpil` | `WM/IsCompilation` |
| `encoder` | `ENCODER` | `TENC` | `©too` | `WM/EncodedBy` |
| `r128_album_gain` | `R128_ALBUM_GAIN` | `TXXX:R128_ALBUM_GAIN` | `----:com.apple.iTunes:R128_ALBUM_GAIN` | `R128_ALBUM_GAIN` |
| `r128_track_gain` | `R128_TRACK_GAIN` | `TXXX:R128_TRACK_GAIN` | `----:com.apple.iTunes:R128_TRACK_GAIN` | `R128_TRACK_GAIN` |
| `rg_album_gain` | `REPLAYGAIN_ALBUM_GAIN` | `TXXX:REPLAYGAIN_ALBUM_GAIN` | `----:com.apple.iTunes:REPLAYGAIN_ALBUM_GAIN` | `REPLAYGAIN_ALBUM_GAIN` |
| `rg_track_gain` | `REPLAYGAIN_TRACK_GAIN` | `TXXX:REPLAYGAIN_TRACK_GAIN` | `----:com.apple.iTunes:REPLAYGAIN_TRACK_GAIN` | `REPLAYGAIN_TRACK_GAIN` |
| `discogs_id` | `DISCOGSID` | `TXXX:DiscogsReleaseId` | `----:com.apple.iTunes:DISCOGS_RELEASE_ID` | `DT/Release Id` |
| `discogs_release_url` | `URL_DISCOGS_RELEASE_SITE` | `TXXX:DISCOGS_RELEASE_URL` | `----:com.apple.iTunes:DISCOGS_RELEASE_URL` | `WM/DiscogsReleaseUrl` |
| `discogs_release_status` | `DISCOGS_RELEASE_STATUS` | `TXXX:DISCOGS_RELEASE_STATUS` | `----:com.apple.iTunes:DISCOGS_RELEASE_STATUS` | `WM/DiscogsReleaseStatus` |
| `barcode` | `BARCODE` | `TXXX:BARCODE` | `----:com.apple.iTunes:BARCODE` | `WM/Barcode` |
| `releasetype` | `RELEASETYPE` | `TXXX:MusicBrainz Release Group Type` | `----:com.apple.iTunes:MusicBrainz Release Group Type` | `MusicBrainz/Release Group Type` |
| `musicbrainz_releaseid` | `MUSICBRAINZ_ALBUMID` | `TXXX:MusicBrainz Release Id` | `----:com.apple.iTunes:MusicBrainz Release Id` | `MusicBrainz/Album Id` |
| `musicbrainz_trackid` | `MUSICBRAINZ_TRACKID` | `TXXX:MusicBrainz Recording Id` | `----:com.apple.iTunes:MusicBrainz Recording Id` | `MusicBrainz/Track Id` |
| `musicbrainz_releasegroupid` | `MUSICBRAINZ_RELEASEGROUPID` | `TXXX:MusicBrainz Release Group Id` | `----:com.apple.iTunes:MusicBrainz Release Group Id` | `MusicBrainz/Release Group Id` |
| `isrc` | `ISRC` | `TXXX:ISRC` | `----:com.apple.iTunes:ISRC` | `WM/ISRC` |
| `tagger_source` | `TAGGER_SOURCE` | `TXXX:TAGGER_SOURCE` | `----:com.apple.iTunes:TAGGER_SOURCE` | `WM/TaggerSource` |
| `freedb_id` | `DISCID` | `TXXX:DiscId` | `----:com.apple.iTunes:DISCID` | `DT/discid` |
| `amg_id` | `AMGID` | `TXXX:AMGID` | `----:com.apple.iTunes:AMG_ID` | `DT/AmgId` |

The `musicbrainz_*` field names follow [MusicBrainz Picard conventions](https://picard-docs.musicbrainz.org/en/appendices/tag_mapping.html)
so files tagged by massMusicTagger are recognised by Picard, beets, and other
MB-aware software.

---

## Image handling

massMusicTagger extends image handling with Cover Art Archive type metadata.

### File naming

| CAA type | File name | Discogs path | MB path |
|---|---|---|---|
| Front | `front.jpg` + `folder.jpg` | Primary image | ✓ |
| Back | `back.jpg` | Secondary image (as `image-01.jpg`) | ✓ |
| Medium (disc label) | `medium.jpg` | Secondary image | ✓ |
| Booklet | `booklet.jpg`, `booklet-01.jpg`, … | Secondary image | ✓ |
| Tray / Spine / etc. | `tray.jpg`, `spine.jpg`, … | Secondary image | ✓ |

### Embedded picture type

CAA images are embedded with the correct ID3 APIC picture-type code so media
players display each image in its designated slot:

| CAA type | `mediafile.ImageType` | ID3 code | Display slot |
|---|---|---|---|
| Front | `front` | 3 | Cover art |
| Back | `back` | 4 | Back cover |
| Booklet | `leaflet` | 5 | Leaflet / lyrics |
| Medium | `media` | 6 | Disc label |
| Others | `other` | 0 | General |

On the Discogs path, all images are embedded as `ImageType.front` (discogstagger3 behaviour).

### Image source preference

```yaml
details:
  image_source: auto          # same source as metadata (default)
  image_source: musicbrainz   # always use CAA (typed images, often higher resolution)
  image_source: discogs       # always use Discogs
```

When `image_source: musicbrainz` and metadata came from Discogs, massMusicTagger
performs a barcode-based MBID lookup before falling back to Discogs images.
