FROM python:3.12-slim

# ── OS dependencies ────────────────────────────────────────────────────────────
# git        — required by pip to install massmusictagger from a git+https URL
# ffmpeg     — audio decoding, ReplayGain (r128gain wraps it), CUE splitting
# shntool    — CUE sheet splitting (fallback for non-FLAC)
# flac       — FLAC encoding/decoding
# libdiscid0 — DiscID computation (Tier 5 of MusicBrainz search; optional)
# libchromaprint-tools — fpcalc binary for AcoustID fingerprinting (Tier 6/7; optional)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ffmpeg \
    shntool \
    flac \
    libdiscid0 \
    libchromaprint-tools \
    && rm -rf /var/lib/apt/lists/*

# ── massMusicTagger ────────────────────────────────────────────────────────────
# Installing with [fingerprint] pulls pyacoustid and python-discid for the
# optional AcoustID and DiscID search tiers.
# discogstagger3 is installed automatically as a dependency.
RUN pip install --no-cache-dir \
    "massmusictagger[fingerprint] @ git+https://github.com/sjbrownrigg/massMusicTagger.git@master"

# ── Bundled application defaults ───────────────────────────────────────────────
# The massMusicTagger sample configs are copied into /app/conf/ so they are
# always available regardless of what the user mounts at /config.
# The user's config (at /config/config.yaml) references these via extra_configs
# using absolute /app/conf/ paths.
WORKDIR /app
COPY conf/config_sample.yaml      /app/conf/config_sample.yaml
COPY conf/discogs_sample.yaml     /app/conf/discogs_sample.yaml
COPY conf/musicbrainz_sample.yaml /app/conf/musicbrainz_sample.yaml
COPY conf/formats_sample.ini      /app/conf/formats_sample.ini
COPY conf/char_substitutions.yaml /app/conf/char_substitutions.yaml
COPY conf/format_codes.yaml       /app/conf/format_codes.yaml

# ── Runtime layout ─────────────────────────────────────────────────────────────
# /music/incoming  — source directory (bind-mounted from host)
# /music/sorted    — destination directory (bind-mounted from host)
# /config          — user-supplied config and credentials (bind-mounted)
# /cache           — Discogs + MusicBrainz API response cache (named volume)
#
# Pre-create /cache in the image so Docker initialises the named volume with
# correct ownership (root) and mode (777) on first use.
RUN mkdir -p /cache && chmod 777 /cache

ENTRYPOINT ["mmt"]
CMD ["-c", "/config/config.yaml", "-w"]
