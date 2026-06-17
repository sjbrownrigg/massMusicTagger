# Docker configuration

This directory is mounted at `/config` inside the container.

Populate it before starting the container:

```bash
cp conf/config_sample.yaml          docker/config/config.yaml
cp conf/discogs_sample.yaml         docker/config/discogs.yaml
cp conf/musicbrainz_sample.yaml     docker/config/musicbrainz.yaml
cp conf/formats_sample.ini          docker/config/formats.ini
```

Then edit each file:
- `config.yaml` — main settings (source/dest paths, behaviour)
- `discogs.yaml` — Discogs API token
- `musicbrainz.yaml` — MusicBrainz user-agent
- `formats.ini` — file naming format strings (optional)

In `config.yaml` the `extra_configs` list must reference the absolute container paths:

```yaml
extra_configs:
  - /config/discogs.yaml
  - /config/musicbrainz.yaml
  - /config/formats.ini
```

See `conf/config_sample.yaml` for the full annotated reference.
