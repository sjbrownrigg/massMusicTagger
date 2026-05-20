# Tagging reference — massMusicTagger

> **Base reference:** the complete format string variable, function, and metadata
> mapping reference lives in discogstagger3, which massMusicTagger uses as its
> tagging engine.
>
> **[→ discogstagger3: tagging_reference.md](https://github.com/sjbrownrigg/discogstagger3/blob/master/docs/tagging_reference.md)**

This document covers only what massMusicTagger **adds or changes** relative to
discogstagger3.

---

## Additional variables

### Source and release classification

| Variable | Description | Source |
|---|---|---|
| `%releasetype%` | Primary release type: `Album`, `Single`, `EP`, `Compilation`, `Live`, `Remix`, … | Both — inferred from Discogs descriptions; read directly from MB release-group |
| `%format_base%` | Physical medium abbreviation without quantity prefix (`CD`, `LP`, `12″`, `CDr`, `file`). Unlike `%format_code%`, never includes `D`/`3x`/… | Both |
| `%digital%` | `'1'` for digital formats (`File`, `Web`, `Digital Media`); `''` for physical media. Use in custom variables to add per-track counts without enumerating format names. | Both |
| `%disambiguation%` | MusicBrainz disambiguation string — the edition statement that distinguishes a specific pressing from others with the same title, e.g. `Beatport expanded version (US)`. Falls back to nothing for Discogs releases. | MB only |

### Discogs-sourced (unchanged)

All variables from discogstagger3 work identically in massMusicTagger on the
Discogs path. See the base reference for the full list.

---

## Changes to existing variables

### `%format_code%`

massMusicTagger **removes** the release-type suffix and edition prefix from
`%format_code%` that discogstagger3 formerly encoded:

| discogstagger3 | massMusicTagger | Now use instead |
|---|---|---|
| `CDS` | `CD` | `%releasetype%` = `Single` |
| `LCDS` | `CD` | `%edition%` + `%releasetype%` |
| `7″S` | `7″` | `%releasetype%` = `Single` |
| `LDCD` | `DCD` | `%edition%` + quantity |

`%format_code%` now encodes only the **physical medium + quantity** (e.g. `CD`,
`DCD`, `3xLP`, `file`). This harmonises Discogs and MusicBrainz, which keep
these dimensions separate.

---

## Custom variables (`[custom-variables]`)

massMusicTagger supports a `[custom-variables]` section in the formats INI file
that lets you define named format string fragments and reference them as
`%__varname__%` in any other format string.

See `conf/formats.ini` for the full syntax and worked examples, including the
built-in `prefix`, `medium`, `qty`, and `type_abbr` building blocks.

> **[→ formats.ini custom-variables section](https://github.com/sjbrownrigg/massMusicTagger/blob/master/conf/formats.ini)**

**Key rule:** if a custom variable's value contains `$function()` calls, do
**not** wrap `%__varname__%` in single quotes when passing it to another
`$function()`. Single quotes make the expansion a string literal (not code)
and break `eval()`.

```ini
; BAD  — qty expands to $if1() but is treated as a string:
format_desc = $if1('%digital%','2x','%__qty__%')

; GOOD — qty expands to $if1() and is treated as code:
format_desc = $if1('%digital%','2x',%__qty__%)
```

---

## Additional tags written

massMusicTagger writes several tags beyond what discogstagger3 produces.

### MusicBrainz identifiers (MB path only)

| Tag | Field | Description |
|---|---|---|
| `RELEASETYPE` | `releasetype` | Primary release type (`Album`, `Single`, `EP`, …) |
| `MUSICBRAINZ_RELEASEID` | `musicbrainz_releaseid` | Release MBID (UUID) |
| `MUSICBRAINZ_RELEASETRACKID` / `MUSICBRAINZ_TRACKID` | `musicbrainz_trackid` | Recording MBID per track |
| `MUSICBRAINZ_RELEASEGROUPID` | `musicbrainz_releasegroupid` | Release group MBID |
| `ISRC` | `isrc` | International Standard Recording Code per track |

### Available on both paths

| Tag | Field | Description |
|---|---|---|
| `RELEASETYPE` | `releasetype` | Inferred from Discogs descriptions on the Discogs path |
| `BARCODE` | `barcode` | EAN/UPC barcode |
| `DISCOGS_RELEASE_STATUS` | `discogs_release_status` | Official / Promo / Bootleg / Pseudo-Release |

---

## Image handling

massMusicTagger extends image handling beyond the Discogs primary/secondary
distinction. Cover Art Archive images carry explicit type metadata:

| CAA type | File name | Embedded picture type |
|---|---|---|
| Front | `front.jpg` | `ImageType.front` (3) |
| Back | `back.jpg` | `ImageType.back` (4) |
| Booklet | `booklet.jpg`, `booklet-01.jpg`, … | `ImageType.leaflet` (5) |
| Medium | `medium.jpg` | `ImageType.media` (6) |
| Others | `tray.jpg`, `spine.jpg`, … | `ImageType.other` (0) |

All downloaded images are embedded into audio files with their correct picture
type so that media players display front cover, back cover, disc label, etc.
in their designated slots.

The `details.image_source` config key controls which source provides images,
independently of where the metadata came from:

```yaml
details:
  image_source: auto         # same source as metadata (default)
  # image_source: musicbrainz  # always use CAA (preferred for MB quality + types)
  # image_source: discogs      # always use Discogs
```
