# Tagging reference — massMusicTagger

> **Base reference:** the complete format string variable and function reference
> lives in discogstagger3:
>
> **[→ discogstagger3: tagging_reference.md](https://github.com/sjbrownrigg/discogstagger3/blob/master/docs/tagging_reference.md)**

This document covers what massMusicTagger **adds or changes** relative to
discogstagger3, with a complete combined tag mapping table for both sources.

---

## Contents

1. [Additional format string variables](#additional-format-string-variables)
2. [Changes to existing variables](#changes-to-existing-variables)
3. [Custom variables](#custom-variables-custom-variables)
4. [Complete tag mapping table](#complete-tag-mapping-table)
5. [Underlying tag names by format](#underlying-tag-names-by-format)
6. [Image handling](#image-handling)

---

## Additional format string variables

### massMusicTagger-only variables

| Variable | Description | Discogs | MB |
|---|---|---|---|
| `%releasetype%` | Primary release type: `Album`, `Single`, `EP`, `Compilation`, `Live`, `Remix`, … | Inferred from format descriptions via `release_type_map` in `format_codes.yaml` | Read directly from `release-group.primary-type` |
| `%format_base%` | Physical medium without quantity prefix: `CD`, `LP`, `12″`, `CDr`, `file`. Unlike `%format_code%`, never includes `D`/`3x`/… | Same as `%format_code%` when disctotal=1 | Same |
| `%digital%` | `'1'` for digital formats (`File`, `Web`, `Digital Media`); `''` for physical. Use in custom variables to add per-track counts without enumerating format names. | Based on `formats[0].name` | Based on `medium[0].format` |
| `%disambiguation%` | MusicBrainz disambiguation string — the edition statement distinguishing this pressing from others with the same title, e.g. `Beatport expanded version (US)`. Used as `%edition%` when `compute_edition()` finds no keyword match. | — | `release.disambiguation` |

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
| Limited 2×CD | `LDCD` | `DCD` | — (Album implicit) | `%edition%` = `Limited Edition` |

Quantity (`DCD`, `3xLP`) is retained as it describes the physical object.

---

## Custom variables (`[custom-variables]`)

massMusicTagger supports a `[custom-variables]` section in the formats INI
file. Reference variables as `%__varname__%` in any format string.

See [`conf/formats.ini`](https://github.com/sjbrownrigg/massMusicTagger/blob/master/conf/formats.ini)
for syntax, rules, and worked examples.

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
| **dt3** | Written by discogstagger3 (Discogs path) |
| **mmt/Discogs** | Written by massMusicTagger on the Discogs path |
| **mmt/MB** | Written by massMusicTagger on the MusicBrainz path |
| ✓ | Written |
| ✓† | Written with this change vs dt3 |
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
