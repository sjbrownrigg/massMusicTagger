# conf/ — fixtures for the format-string preview

This directory holds one thing: the example albums that `format_preview.py`
renders your format strings against.

```
preview_cases.yaml    the albums, and which format strings to show
```

It used to describe a configuration layout of shipped defaults and personal
overrides — `config.yaml`, `discogs.yaml`, `formats.ini` and the rest, kept
here in the source tree. None of that is true any more, and none of those files
exist. A configuration is now a directory you own, found by name; the reference
copies live inside the package. See the [README](../README.md) for where it
goes and [docs/sources.md](../docs/sources.md) for what is in it.

## Previewing a format string

Format strings decide what your files and folders are called, and the cost of
getting one wrong is a library named badly. This renders them against fixture
albums so you can see the result first:

```bash
python format_preview.py                                  # the packaged reference config
python format_preview.py --conf ~/.config/massmusictagger # your own
python format_preview.py --conf ~/.config/massmusictagger --watch
```

`--watch` re-renders whenever you save, which makes editing a long format
string a matter of seconds rather than repeated runs.

## Adding a case

Each entry under `cases:` is one album. Only a few fields are required — name,
format, artist, title, year — and the rest have sensible defaults, so a case
for a specific awkwardness stays short:

```yaml
cases:
  - name: "Double LP with a catalogue number"
    format: Vinyl
    descriptions: ["LP", "Album"]
    artist: Test Artist
    title: Test Album
    year: 1985
    catno: TEST-001
    disctotal: 2
```

The `format_strings:` list at the top decides what is shown for every case.
It takes section names from `[file-formatting]` — `dir`, `song`, `va_song`,
`nfo`, `m3u` — a custom variable such as `%__format_desc__%`, or a raw format
string in quotes.

Worth adding a case whenever a release shape catches the tagger out: a box set,
a promo, a single-track digital release. The fixtures are cheap and they make
the next format-string change safe to reason about.
