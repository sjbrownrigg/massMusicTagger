# massMusicTagger — Docker deployment

Runs massMusicTagger as a daemon, watching `incoming/` and tagging new albums
automatically using Discogs (primary) then MusicBrainz (fallback).

## Prerequisites

- Docker Engine 24+ and Docker Compose V2
- Your music library accessible from the Docker host (NFS mount, local drive, etc.)
- A Discogs personal access token (https://www.discogs.com/settings/developers)

## WSL2 / NAS setup

NFS Docker volumes are blocked by WSL2's mount syscall restriction.  Mount
your NAS shares in WSL2 first, then point `MUSIC_DIR` and `CONFIG_DIR` at
those mount points — bind mounts work correctly:

```bash
# Example WSL2 NFS mounts (add to /etc/fstab or mount manually)
sudo mount -t nfs 192.168.1.240:/volume1/Music        /mnt/music
sudo mount -t nfs 192.168.1.240:/volume1/Docker/mmt   /mnt/mmt
```

## Quick start

### 1. Prepare config

Copy `docker/config/` to your config directory on the NAS:

```bash
cp -r docker/config/ /mnt/mmt/config/
```

Edit the files you copied:
- `config_personal.yaml` — check `source_dir` / `dest_dir` paths
- `discogs_personal.yaml` — add your Discogs token
- `musicbrainz_personal.yaml` — add your email as user_agent; optionally add AcoustID key

### 2. Create a .env file

```bash
cd docker/
cp .env.example .env
# Edit .env: set MUSIC_DIR, CONFIG_DIR, TZ
```

### 3. Start the daemon

```bash
docker compose up -d
```

Check logs:
```bash
docker compose logs -f
```

### 4. Tag a single album (one-shot)

```bash
docker compose run --rm mmt \
  -c /config/config_personal.yaml \
  /music/incoming/Artist/Album
```

### 5. Dry-run the full incoming directory

```bash
docker compose run --rm mmt \
  -c /config/config_personal.yaml \
  --dry-run \
  /music/incoming
```

## Rebuild after updates

```bash
docker compose up -d --build
```

## Directory layout inside the container

| Path | Contents |
|---|---|
| `/music/incoming` | Source albums — mmt watches this |
| `/music/sorted` | Destination — tagged albums appear here |
| `/config/` | Your personal config + credentials (bind mount) |
| `/app/conf/` | massMusicTagger bundled defaults (read-only, in image) |
| `/cache/discogs/` | Discogs API response cache |
| `/cache/musicbrainz/` | MusicBrainz API response cache |
| `/cache/audit.json` | Structured log of every processed album |

## Optional: AcoustID fingerprinting

The image includes `fpcalc` (chromaprint) and `libdiscid0`.  To enable
audio fingerprinting for the MusicBrainz search path:

1. Register at https://acoustid.org/login
2. Add your key to `musicbrainz_personal.yaml`:
   ```yaml
   musicbrainz:
     acoustid_api_key: YOUR_KEY_HERE
   ```
