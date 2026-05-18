## Changelog

---

## Version 1.0.0 (2026-05-18)

Initial release of massMusicTagger.

Built on discogstagger3 (v3.0.3) as a shared-core dependency.

### Features

- **Configurable source priority** — `source.priority` list controls which
  metadata sources are tried and in what order.  Sources: `discogs`,
  `musicbrainz`, `existing_tags` (fallback organiser).
- **MusicBrainz adapter** — full Release → Album/Disc/Track mapping;
  Cover Art Archive image download; MBID and ISRC tags.
- **MusicBrainz search** — tier 1 (MBID from id.txt), tier 2 (text search
  with fuzzy title matching + track count), tier 3 (AcoustID fingerprinting,
  optional dependency).
- **existing_tags fallback** — when no API match is found, organises files
  using metadata already embedded in the audio files.  No API calls; no
  tag overwrites.
- **Concurrent processing** — `batch.workers` controls the thread pool size.
- **Rich progress display** — per-album status in the terminal.
- **Structured audit log** — JSON log of every processed directory.
- **Dry-run mode** (`--dry-run`) — compute proposed changes without writing.
- **Interactive review mode** (`--review`) — confirm each album match
  interactively before tagging.
- **Rollback** (`--undo DIR`) — remove tagged output and done marker using
  the audit log.
- **Watch / daemon mode** (`--watch`) — PollingObserver for CIFS/NFS mounts.
