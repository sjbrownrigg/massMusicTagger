# conf/ — configuration layout

This directory contains massMusicTagger's **shipped defaults** and **personal
overrides**. The two are kept separate so the defaults can be updated (via
`git pull` or a Docker image rebuild) without touching your credentials or
local path settings, and so credentials never end up in version control.

## Shipped defaults (tracked in git)

| File | Purpose |
|---|---|
| `config.yaml` | Baseline settings not specific to any metadata source (paths, batch, tags, logging, etc.) |
| `discogs.yaml` | Discogs API defaults |
| `musicbrainz.yaml` | MusicBrainz/AcoustID API defaults |
| `formats.ini` | Default tag/path formatting templates |
| `char_substitutions.yaml` | Default character substitution tables |
| `format_codes.yaml` | Default Discogs format-code mappings |
| `source_hints.yaml` | Default folder-name keyword hints (digital vs vinyl) |

These files contain no credentials and are safe to overwrite on update.

## Personal overrides (gitignored — never committed)

| File | Purpose |
|---|---|
| `config_personal.yaml` | Your `source_dir`/`dest_dir`, processing options, and `extra_configs` list — entry point passed via `mmt -c conf/config_personal.yaml` |
| `discogs_personal.yaml` | Your Discogs `user_token` (or `consumer_key`/`consumer_secret`) |
| `musicbrainz_personal.yaml` | Your MusicBrainz `user_agent` email and optional AcoustID key |
| `formats_personal.ini` | Your custom tag/path formatting overrides |

These are matched by `conf/*_personal.yaml` and `conf/*_personal.ini` in
`.gitignore`. Create them by copying the shipped defaults and editing as
needed — they are loaded **on top of** the defaults, so you only need to
specify the values you want to change.

## How loading works

`config_personal.yaml` lists the files to layer on top of the defaults:

```yaml
extra_configs:
  - conf/discogs.yaml
  - conf/musicbrainz.yaml
  - conf/discogs_personal.yaml
  - conf/musicbrainz_personal.yaml
  - conf/formats_personal.ini
```

Load order (later wins):
1. `config.yaml` (baseline, loaded automatically alongside `config_personal.yaml`)
2. Each entry in `extra_configs`, in order
3. `config_personal.yaml` itself again, so its own values always take final precedence

Paths in `extra_configs` are resolved relative to the config file's own
directory if not found relative to the current working directory — so the
`conf/...` paths above work regardless of where `mmt` is run from.

## Docker

The same default/override split exists in the container, under different
paths:

| Path | Equivalent to | Contents |
|---|---|---|
| `/app/conf/` | this `conf/` directory's shipped defaults | Baked into the image at build time (read-only) |
| `/config/` | your personal overrides | Bind-mounted from the host, persists across rebuilds |

See [`../docker/README.md`](../docker/README.md) for the Docker-specific
config template and setup instructions.
