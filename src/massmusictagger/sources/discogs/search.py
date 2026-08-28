# -*- coding: utf-8 -*-
"""Discogs release search.

Separated from discogsalbum.py so the search logic can be developed and tested
independently from the connector and album-mapping code.

Search strategy — four tiers tried in order, each stopped early when a
tier-1 (duration-matched) candidate is found:

  Tier 1  artist + release_title + year   (structured fields, type=release)
  Tier 2  artist + release_title           (structured fields, no year filter)
  Tier 3  artist-browse                    (follow artist entity, scan releases)
  Tier 4  free-text search                 (safety net, first 5 results only)

Within Tier 1 and 2, every release returned by the API is compared directly.
Releases are no longer silently replaced by their master — the original bug
that caused specific reissues to be missed even when they appeared in search
results.
"""
import logging
import os
import re
from datetime import datetime, timedelta

from rapidfuzz import fuzz

from massmusictagger.core.cache import SearchCache
from massmusictagger.sources.discogs.connector import DiscogsConnector
from massmusictagger.sources.discogs.utils import (
    AUDIO_EXTENSIONS, VARIOUS_ARTIST_NAMES, extract_catalog_hint,
    normalize_catalog_number, strip_catalog_suffix, strip_discogs_id_suffix,
    build_flat_tracklist, ignored_source_dirs, is_non_audio_position,
    merge_indexed_subtracks, natural_sort_key,
)
from massmusictagger.core.mediafile import MediaFile
from massmusictagger.core.naming.pathutils import resolve_path

logger = logging.getLogger(__name__)


class DiscogsSearch(DiscogsConnector):
    """Search for a Discogs release using metadata extracted from local files."""

    def __init__(self, tagger_config):
        DiscogsConnector.__init__(self, tagger_config)
        self.candidates = {}
        self.no_duration_candidates = {}
        self.search_params = {}
        self._artist_name_cache = {}
        self._sifted_masters = set()

    # ------------------------------------------------------------------
    # Metadata extraction
    # ------------------------------------------------------------------

    def getSearchParams(self, source_dir):
        """Read file metadata from source_dir and populate self.search_params."""
        logger.info('Retrieving original metadata for search purposes')
        self.search_params = {}
        self.candidates = {}
        self.no_duration_candidates = {}
        self._sifted_masters = set()

        files = self._getMusicFiles(source_dir)
        files.sort(key=natural_sort_key)
        subdirectories = self._fetchSubdirectories(source_dir, files)
        searchParams = self.search_params
        searchParams['sourcedir'] = source_dir

        trackcount = 0
        discnumber = 0
        searchParams['artists'] = []
        searchParams['tracks'] = []

        for i, file in enumerate(files):
            trackcount += 1
            try:
                metadata = MediaFile(file)
            except Exception as e:
                logger.warning('Cannot read metadata from %s: %s', repr(file), e)
                searchParams['tracks'].append({
                    'position': str(trackcount),
                    'duration': '',
                    'title': '',
                    'artist': '',
                })
                continue

            track_artists = metadata.artists or ([metadata.artist] if metadata.artist else [])
            for a in track_artists:
                if a:
                    searchParams['artists'].append(a)
            searchParams['albumartist'] = metadata.albumartist or ''
            _raw_album = re.sub(r'\[.*?\]', '', metadata.album or '')
            catalog_hint = extract_catalog_hint(_raw_album)
            if catalog_hint:
                searchParams['catalog_hint'] = catalog_hint
            searchParams['album'] = strip_catalog_suffix(_raw_album)
            searchParams['year'] = metadata.year
            searchParams['date'] = metadata.date

            disc = metadata.disc
            if disc is not None and int(disc) > 1:
                searchParams['disc'] = disc
            elif disc is None and len(set(subdirectories)) > 1 and i < len(subdirectories):
                # Strip leading path separator so "^disc" matches "/Disc 1 (..." paths
                subdir_name = subdirectories[i].lstrip('/\\')
                m = re.search(r'(?i)^(cd|disc)\s?(?P<n>[0-9]{1,2})', subdir_name)
                if m:
                    searchParams['disc'] = int(m.group('n'))

            if 'disc' in searchParams and searchParams['disc'] != discnumber:
                trackcount = 1
                discnumber = searchParams['disc']

            tracknumber = str(searchParams['disc']) + '-' if 'disc' in searchParams else ''
            tracknumber += str(metadata.track) if metadata.track is not None else str(trackcount)

            trackInfo = {}
            if re.search(r'(?i)^[a-z]', str(metadata.track or '')):
                trackInfo['real_tracknumber'] = metadata.track
            trackInfo['position'] = tracknumber
            trackInfo['duration'] = str(timedelta(seconds=round(metadata.length or 0, 0)))
            trackInfo['title'] = metadata.title or ''
            trackInfo['artist'] = metadata.artist or ''
            searchParams['tracks'].append(trackInfo)

        searchParams['artists'] = [a for a in dict.fromkeys(searchParams['artists']) if a]

        va_names = VARIOUS_ARTIST_NAMES
        albumartist = searchParams.get('albumartist', '')

        # Albumartist is authoritative for the whole release; individual track
        # artists are preserved in searchParams['artists'] for VA compilations.
        if albumartist and albumartist.lower() not in va_names:
            searchParams['artist'] = albumartist
        elif searchParams['artists']:
            searchParams['artist'] = ', '.join(searchParams['artists'])
        else:
            searchParams['artist'] = albumartist  # VA or empty — kept as-is

        # Resolve to the Discogs canonical name while we still have the raw
        # metadata.  This runs once per album so every search tier and every log
        # entry sees the correct name from the outset.
        if searchParams['artist'] and searchParams['artist'].lower() not in va_names:
            canonical = self._resolve_artist_name(searchParams['artist'])
            if canonical != searchParams['artist']:
                logger.info('Canonical artist resolved: "%s" → "%s"',
                            searchParams['artist'], canonical)
            searchParams['artist'] = canonical
            if albumartist and albumartist.lower() not in va_names:
                searchParams['albumartist'] = canonical

        if (not searchParams['artists']
                and not searchParams.get('albumartist')
                and not searchParams.get('album')):
            logger.warning('No metadata available in the audio files')
            self.metadataFromFileNaming(source_dir, files)
            return None

    def metadataFromFileNaming(self, source_dir, files):
        """Fall back: derive artist/album/track info from directory and file names."""
        logger.info('Fetching metadata from file & directory naming')
        searchParams = self.search_params
        try:
            base_dir = self.config.get('details', 'source_dir') or ''
        except Exception:
            base_dir = self.config.get('common', 'source_dir') or ''
        if re.search(r'(?i)(vinyl)', source_dir):
            searchParams['media'] = 'vinyl'
        release_dir = re.sub(base_dir, '', source_dir)
        year = re.search(r'(\d{4})', release_dir)
        if year:
            searchParams['year'] = year.group(0)
            release_dir = re.sub(year.group(0), '', release_dir)
        dirs = release_dir.split(os.sep)
        dirs = [self.u2s(d) for d in dirs if d and d.lower() not in ('albums', 'singles')]
        if len(dirs) == 3:
            dirs.pop(1)
        if len(dirs) == 2:
            dirs[1] = re.sub(dirs[0].lower(), '', dirs[1].lower())
        elif len(dirs) == 1:
            dirs = re.split(r'\s*[-]\s*', dirs[0])
        if len(dirs) == 2:
            searchParams['artist'] = dirs[0].strip()
            searchParams['album'] = strip_catalog_suffix(dirs[1].strip())
        else:
            searchParams['album'] = strip_catalog_suffix(dirs[0])
        for idx, track in enumerate(searchParams['tracks']):
            filename = os.path.basename(files[idx])
            name, _ = os.path.splitext(self.u2s(filename))
            namesplit = name.split(' ', 1)
            track['real_tracknumber'] = namesplit[0]
            rest = namesplit[1].split(' - ')
            if len(rest) > 1:
                track['artist'] = rest[0]
                searchParams['artists'].append(rest[0])
                track['title'] = rest[1]
            else:
                track['title'] = rest[0]
                track['artist'] = searchParams.get('artist', '')
        searchParams['artists'] = list(dict.fromkeys(searchParams['artists']))
        if not searchParams.get('artist'):
            searchParams['artist'] = ' '.join(searchParams['artists'])
            if searchParams['artists']:
                searchParams['albumartist'] = searchParams['artists'][0]

    def u2s(self, string):
        return re.sub(r'[_]', ' ', string)

    def _getMusicFiles(self, source_dir):
        ignored = ignored_source_dirs(self.config)
        found = []
        for dirpath, dirs, files in os.walk(source_dir):
            dirs[:] = [d for d in dirs if d not in ignored]
            for file in files:
                if file.endswith(AUDIO_EXTENSIONS):
                    found.append(resolve_path(os.path.join(dirpath, file)))
        return found

    def _fetchSubdirectories(self, source_dir, filepaths):
        paths = [os.path.split(fp)[0] for fp in filepaths]
        if len(set(paths)) > 1:
            subdirs = [p.replace(source_dir, '') for p in paths]
            subdirs.sort()
            return subdirs
        return []

    # ------------------------------------------------------------------
    # Search orchestration
    # ------------------------------------------------------------------

    def search_strings(self):
        """Build normalised search strings from self.search_params.

        searchParams['artist'] is already the Discogs canonical name and has
        albumartist priority — both resolved in getSearchParams.  This method
        only normalises the strings and handles the VA compilation special case.
        """
        searchParams = self.search_params
        searchParams['search'] = {}
        s = searchParams['search']
        va = VARIOUS_ARTIST_NAMES

        albumartist = (searchParams.get('albumartist') or '').lower()
        if albumartist in va:
            # VA compilation: use first individual track artist for the query
            artists = searchParams.get('artists', [])
            s['artist'] = artists[0] if artists else ''
        else:
            # Already canonical and albumartist-preferred from getSearchParams
            s['artist'] = searchParams.get('artist', '')

        if not s['artist']:
            logger.warning('No artist found in file metadata — search will use album title only')

        s['artist'] = self.normalize(s['artist'])
        s['release'] = self.normalize(searchParams.get('album', ''))

        if s['artist'].lower() in va:
            tracks = searchParams.get('tracks', [])
            s['title'] = tracks[0]['title'] if tracks else ''
            s['artistRelease'] = self.normalize(' '.join((s['title'], s['release'])))
        else:
            s['artistRelease'] = self.normalize(' '.join((s['artist'], s['release'])).strip())

    def search(self, sourcedir: str) -> 'str | None':
        """Return a Discogs release ID for *sourcedir*, or None.

        The SourceSearch entry point, matching MBSearch.search(). Everything
        Discogs needs to run a search now happens in here.

        The caller used to have to do this itself: call getSearchParams, work
        out the folder hints, reach into self.search_params to inject them,
        conditionally pop the year, call search_discogs() -- a differently
        named method returning a release object rather than an ID -- and then
        know to touch .tracklist to force a lazy fetch that could 404. None of
        that is the cascade's business, and none of it applied to MusicBrainz,
        which is why the two branches looked nothing alike.
        """
        from massmusictagger.sources.hints import (
            _load_source_hints, _folder_format_hint, _folder_descriptor_hints)

        self.getSearchParams(sourcedir)

        # Folder-name signals. The format hint gates candidates whose medium
        # conflicts with the folder (a vinyl LP for a 24-bit remaster), and the
        # descriptor hints boost candidates whose descriptions agree.
        hints = _load_source_hints(self.config)
        fmt_hint = _folder_format_hint(sourcedir, hints)
        if fmt_hint:
            self.search_params['format_hint'] = fmt_hint
            if fmt_hint == 'digital':
                # The original album year would restrict results to that year's
                # pressings -- all vinyl -- and hide the digital remaster.
                year = self.search_params.pop('year', None)
                if year:
                    logger.debug(
                        'Format hint "digital": suppressed year %s from the '
                        'Discogs search so remasters can surface (folder: %s)',
                        year, os.path.basename(sourcedir))
        desc_hints = _folder_descriptor_hints(sourcedir, hints)
        if desc_hints:
            self.search_params['descriptor_hints'] = desc_hints

        release = self.search_discogs()
        if release is None:
            return None

        try:
            # A search result is lazy; touching the tracklist forces the fetch
            # and surfaces a release that has since been deleted.
            _ = release.tracklist
            return str(release.id)
        except Exception as exc:
            logger.warning(
                'Discogs release %s could not be fetched (%s) — treating as no '
                'match', getattr(release, 'id', '?'), exc)
            return None

    def search_discogs(self):
        """Search Discogs for a matching release — four-tier strategy."""
        searchParams = self.search_params

        self.candidates = {}
        self.no_duration_candidates = {}
        self._sifted_masters = set()

        self.search_strings()
        s = searchParams.get('search', {})
        logger.info('Searching Discogs for: artist="%s" album="%s"',
                    s.get('artist', '?'), searchParams.get('album', '?'))

        # Tier 1 — structured fields with year (most precise)
        if searchParams.get('year'):
            self._search_release_fields(include_year=True)
            if self.candidates or self.no_duration_candidates:
                logger.info('Tier 1 (artist+title+year) found candidates')

        # Tier 2 — structured fields without year
        if not self.candidates and not self.no_duration_candidates:
            self._search_release_fields(include_year=False)
            if self.candidates or self.no_duration_candidates:
                logger.info('Tier 2 (artist+title) found candidates')

        # Tier 3 — artist-browse: follow the artist entity → scan their releases
        # More targeted than a free-text search when structured fields have failed.
        if not self.candidates and not self.no_duration_candidates:
            self.search_artist()
            if self.candidates or self.no_duration_candidates:
                logger.info('Tier 3 (artist browse) found candidates')

        # Tier 4 — free-text search, first 5 results only.
        # Anything beyond this is unlikely to surface a better match than the
        # structured tiers already tried; it exists purely as a safety net.
        if not self.candidates and not self.no_duration_candidates:
            self._search_text(['all', 'master'], max_results=5)
            if self.candidates or self.no_duration_candidates:
                logger.info('Tier 4 (text search, first 5 results) found candidates')

        return self._pick_best()

    def _pick_best(self):
        """Select and return the best candidate, or None."""
        if not self.candidates and not self.no_duration_candidates:
            logger.warning('No matching release found on Discogs')
            return None

        if not self.candidates:
            logger.info('No duration-matched candidates; falling back to %d no-duration candidate(s)',
                        len(self.no_duration_candidates))
            return self._select_by_metadata(self.no_duration_candidates)

        if len(self.candidates) == 1:
            result = list(self.candidates.values())[0]
            logger.info('Found 1 tier-1 candidate: [%s] — %s',
                        result.id, getattr(result, 'title', '?'))
            return result

        logger.info('Found %d tier-1 candidates, selecting best match', len(self.candidates))
        scored = [
            (self._candidate_score(release, base_score=diff), release)
            for diff, release in self.candidates.items()
        ]
        scored.sort(key=lambda x: x[0])
        best_score, best = scored[0]
        logger.info('Selected [%s] composite score %.2f', best.id, best_score)
        return best

    # ------------------------------------------------------------------
    # Tier 1 / 2 — structured field search
    # ------------------------------------------------------------------

    def _search_release_fields(self, include_year=True):
        """Search using Discogs structured fields: artist, release_title[, year].

        Every release returned by the API is compared directly.  Its master's
        versions are also sifted (once per master) to catch related editions.
        This avoids the bug where a release returned by the search API was
        silently replaced by its parent master and never directly compared.
        """
        s = self.search_params.get('search', {})
        artist = s.get('artist', '')
        release_title = s.get('release', '')
        year = str(self.search_params.get('year') or '') if include_year else ''

        if not artist and not release_title:
            return

        cache_key = '|'.join(filter(None, [artist, release_title, year]))
        cache_type = 'fields_year' if include_year else 'fields'
        label = 'artist+title+year' if include_year else 'artist+title'

        cached = self._search_cache.get(cache_key, cache_type) if self._search_cache else None
        if cached is not None:
            logger.info('Field search cache hit (%s): %s', label, cache_key)
            self._replay_search_results(cached)
            return

        kwargs = {}
        if artist:
            kwargs['artist'] = artist
        if release_title:
            kwargs['release_title'] = release_title
        if year:
            kwargs['year'] = year

        logger.info('Field search (%s): %s', label, kwargs)
        try:
            results = self.discogs_client.search(**kwargs, type='release')
        except Exception as e:
            logger.warning('Field search failed: %s', e)
            return

        collected = []
        for idx, result in enumerate(results):
            if self.candidates:
                break
            if idx >= 25:
                break
            if 'Artist' in type(result).__name__:
                continue

            # Compare this release directly — key fix for the "swallowed release" bug
            self._siftReleases([result])
            collected.append({'id': result.id, 'is_master': False})
            logger.debug('  Field search direct compare: [%s]', result.id)

            # Also sift master versions (once per master)
            master = self.get_master_release(result)
            if hasattr(master, 'versions') and master.id not in self._sifted_masters:
                self._sift_master_versions(master)
                self._sifted_masters.add(master.id)
                collected.append({'id': master.id, 'is_master': True})

        if self._search_cache and collected:
            self._search_cache.put(cache_key, cache_type, collected)

    # ------------------------------------------------------------------
    # Text search — used as Tier 4 fallback
    # ------------------------------------------------------------------

    def _search_text(self, types, max_results=25):
        """Run the combined-text search for each type in the list."""
        for type_ in types:
            if self.candidates:
                break
            try:
                self._search_artist_title(type_, max_results=max_results)
            except Exception as e:
                logger.warning('Text search error (%s): %s', type_, e)

    def _search_artist_title(self, type_, max_results=25):
        """Combined text search using artistRelease string.

        max_results caps how many API results are examined before giving up.
        Set low (e.g. 5) when used as a last-resort tier to avoid scanning
        hundreds of pages for a match that structured tiers already missed.

        Fixes the 'swallowed release' bug: when the API returns a Release
        (not a Master) as a search result, compare it directly *and* sift
        its master's versions.  Previously only the master was sifted.
        """
        s = self.search_params['search']
        query = s['artistRelease']

        cached = self._search_cache.get(query, type_) if self._search_cache else None
        if cached is not None:
            logger.info('Search cache hit: "%s" (%s)', query, type_)
            self._replay_search_results(cached)
            return

        logger.info('Searching by artist and title (%s, max %d): %s', type_, max_results, query)
        results = self.discogs_client.search(query, type=type_)

        collected = []
        for idx, result in enumerate(results):
            if self.candidates:
                break
            if idx >= max_results:
                break
            if 'Artist' in type(result).__name__:
                continue

            result_is_release = not hasattr(result, 'versions')

            # If the API returned a Release directly, compare it immediately.
            # Its master is not a reliable proxy — it may include hundreds of
            # versions, none of which are this exact reissue if the cache is stale.
            if result_is_release:
                self._siftReleases([result])
                collected.append({'id': result.id, 'is_master': False})

            # Sift master versions — once per master across all tiers
            master = self.get_master_release(result)
            if hasattr(master, 'versions') and master.id not in self._sifted_masters:
                self._sift_master_versions(master)
                self._sifted_masters.add(master.id)
                collected.append({'id': master.id, 'is_master': True})
            elif not result_is_release:
                # result is a master itself and was already sifted (or IS the master)
                if master.id not in self._sifted_masters:
                    self._sift_master_versions(master)
                    self._sifted_masters.add(master.id)
                    collected.append({'id': master.id, 'is_master': True})

        if self._search_cache and collected:
            self._search_cache.put(query, type_, collected)

    # ------------------------------------------------------------------
    # Artist browse — Tier 3
    # ------------------------------------------------------------------

    def search_artist(self):
        searchParams = self.search_params
        artist = self.search_params['search']['artist']

        logger.info('Searching by artist: %s', artist)
        results = self.discogs_client.search(artist, type='artist')

        if results.count == 0:
            return

        releases = None
        for result in results:
            if self.candidates:
                break
            canonical = strip_discogs_id_suffix(result.name)
            if self.normalize(artist).lower() == self.normalize(canonical).lower():
                releases = result.releases
            if releases is None:
                continue
            for i, release in enumerate(releases):
                if self.candidates or i > 25:
                    return
                if searchParams['album'].lower() in release.title.lower() or \
                        release.title.lower() in searchParams['album'].lower():
                    if hasattr(release, 'versions'):
                        self._siftReleases(list(release.versions))
                    else:
                        self._siftReleases([release])

    def search_album_title(self):
        searchParams = self.search_params
        release_title = self.search_params['search']['release']
        logger.info('Searching by title: %s', release_title)
        results = self.discogs_client.search(release_title, type='release')
        for i, result in enumerate(results):
            if self.candidates or i > 25:
                break
            master = self.get_master_release(result)
            if hasattr(master, 'versions'):
                self._siftReleases(list(master.versions))
            else:
                self._siftReleases([result])

    # ------------------------------------------------------------------
    # Candidate management
    # ------------------------------------------------------------------

    def _siftReleases(self, releases):
        """Evaluate each release into tier-1 or tier-2 candidate buckets.

        Evaluates every release in the batch (even once a candidate exists)
        so _pick_best() can later choose the best among several tier-1
        matches — callers that want to stop after the first hit already
        check self.candidates between batches themselves.

        Comparing a release can trigger a lazy API fetch of its tracklist
        (master.versions returns lightweight stubs); a single deleted/404
        release in that list is caught and skipped rather than aborting the
        whole search and losing every candidate found earlier in the same
        call (regression: a 404 on one of 98 master versions discarded an
        already-accepted 0.0s-diff match for Depeche Mode "Never Let Me
        Down Again", release 8620985).
        """
        for release in releases:
            try:
                difference = self._compareRelease(release)
            except Exception as e:
                logger.warning('Skipping release %s — fetch/compare failed: %s',
                                getattr(release, 'id', '?'), e)
                continue
            if difference is False:
                continue
            elif difference < 0:
                self.no_duration_candidates[release.id] = (release, abs(difference) * 100)
            else:
                while difference in self.candidates:
                    difference += 0.001
                self.candidates[difference] = release

    def _sift_master_versions(self, master):
        """Sift all versions of a master, using the master-versions cache."""
        cached_ids = (self._master_versions_cache.get(master.id)
                      if self._master_versions_cache else None)
        if cached_ids is not None:
            logger.info('Master %s: %d version(s) from cache', master.id, len(cached_ids))
            versions = [self._release_obj_from_cache(vid) for vid in cached_ids]
        else:
            versions = list(master.versions)
            version_ids = [v.id for v in versions]
            if self._master_versions_cache and version_ids:
                self._master_versions_cache.put(master.id, version_ids)
            logger.info('Master %s: %d version(s) fetched from API', master.id, len(versions))
        self._siftReleases(versions)

    def _replay_search_results(self, cached_results):
        """Replay a cached search result list without hitting the search API."""
        for item in cached_results:
            if self.candidates:
                break
            rid = item['id']
            if item.get('is_master'):
                if rid not in self._sifted_masters:
                    master = self.discogs_client.master(rid)
                    self._sift_master_versions(master)
                    self._sifted_masters.add(rid)
            else:
                release = self._release_obj_from_cache(rid)
                diff = self._compareRelease(release)
                if diff is False:
                    continue
                elif diff < 0:
                    self.no_duration_candidates[release.id] = (release, abs(diff) * 100)
                else:
                    while diff in self.candidates:
                        diff += 0.001
                    self.candidates[diff] = release

    def _compareRelease(self, release):
        """Compare local files against a single Discogs release.

        Return convention (lower is always better for the caller):
          float >= 0  — tier-1: avg track-length diff in seconds
          float < 0   — tier-2: -(similarity/100)
          False       — rejected
        """
        searchParams = self.search_params
        rid = release.id

        # Fetch the full tracklist first (including non-audio like DVD/Blu-ray).
        # Two-pass count matching:
        #   Pass 1 — full list: for users who have all content inc. video discs.
        #   Pass 2 — audio only: for users who only ripped the audio CDs from a
        #            set that also includes a DVD/Blu-ray bonus disc.
        trackInfo = self._getTrackInfo(release, skip_non_audio=False)

        if not trackInfo:
            logger.info('  [%s] rejected — no track info on Discogs', rid)
            return False

        local_count = len(searchParams['tracks'])
        if local_count != len(trackInfo):
            # Pass 2: strip non-audio positions and retry the count check.
            trackInfo_audio = [t for t in trackInfo
                               if not is_non_audio_position(t['position'])]
            non_audio_count = len(trackInfo) - len(trackInfo_audio)
            if non_audio_count > 0 and local_count == len(trackInfo_audio):
                trackInfo = trackInfo_audio
                logger.info('  [%s] matched %d audio tracks (%d non-audio '
                            'disc track(s) excluded)',
                            rid, local_count, non_audio_count)
            else:
                # Pass 3: merge lettered sub-tracks (e.g. 13a+13b+13c → 13).
                # Handles Discogs data errors where a single-file track was
                # entered as separate lettered positions with no parent index.
                trackInfo_merged = merge_indexed_subtracks(trackInfo_audio)
                if trackInfo_merged is not None and local_count == len(trackInfo_merged):
                    logger.info(
                        '  [%s] sub-track merge: %d position(s) collapsed → '
                        'retrying with %d tracks',
                        rid,
                        len(trackInfo_audio) - len(trackInfo_merged),
                        len(trackInfo_merged),
                    )
                    trackInfo = trackInfo_merged
                else:
                    logger.info(
                        '  [%s] rejected — local has %d tracks, Discogs '
                        'has %d (%d audio, %d non-audio)',
                        rid, local_count, len(trackInfo),
                        len(trackInfo_audio), non_audio_count,
                    )
                    return False

        # Format hint: reject releases whose medium type conflicts with the
        # source-folder signal injected from massMusicTagger.  Catches the
        # common case of a 24-bit remaster folder matching a vinyl pressing
        # because both have identical track durations from the same master.
        fmt_hint = searchParams.get('format_hint', '')
        if fmt_hint:
            try:
                rel_fmt = (release.data.get('formats', [{}])[0]
                           .get('name', '').lower())
                _VINYL_FMTS = frozenset(('lp', 'vinyl', '12"', '7"', '10"',
                                         'shellac', 'flexi-disc', 'acetate'))
                _NON_VINYL_FMTS = frozenset(('cd', 'cdr', 'sacd', 'dvd', 'dvd-video',
                                              'file', 'digital media', 'web',
                                              'cassette', 'dat', 'minidisc'))
                if fmt_hint == 'digital' and rel_fmt in _VINYL_FMTS:
                    logger.info('  [%s] rejected — format hint "digital" conflicts '
                                'with vinyl medium (%s)', rid, rel_fmt)
                    return False
                if fmt_hint == 'vinyl' and rel_fmt in _NON_VINYL_FMTS:
                    logger.info('  [%s] rejected — format hint "vinyl" conflicts '
                                'with non-vinyl medium (%s)', rid, rel_fmt)
                    return False
            except Exception:
                pass

        has_duration = any(t['duration'] is not None for t in trackInfo)
        if not has_duration:
            similarity = self._compareTitleSimilarity(searchParams['tracks'], trackInfo)
            if similarity > 0 and similarity < self.title_similarity_threshold:
                logger.info('  [%s] rejected — title similarity %.0f%% below threshold %.0f%%',
                            rid, similarity, self.title_similarity_threshold)
                return False
            logger.info('  [%s] tier-2 candidate — track count %d, title similarity %.0f%%',
                        rid, local_count, similarity)
            return -(similarity / 100.0)

        difference = self._compareTrackLengths(searchParams['tracks'], trackInfo)
        if difference < self.tracklength_tolerance:
            logger.info('  [%s] accepted — avg track length diff %.1fs', rid, difference)
            return difference

        logger.info('  [%s] rejected — avg track length diff %.1fs exceeds tolerance %s',
                    rid, difference, self.tracklength_tolerance)
        return False

    def _compareTrackLengths(self, current, imported):
        """Average absolute track-length difference in seconds (duration-having tracks only)."""
        total = 0.0
        count = 0
        for i, track in enumerate(current):
            local_dur = track.get('duration') or ''
            discogs_dur = imported[i]['duration']
            if not local_dur or discogs_dur is None:
                continue
            diff = self._compareTimeDifference(local_dur, discogs_dur)
            total += diff.total_seconds()
            count += 1
        if count == 0:
            return float('inf')
        avg = total / count
        logger.info('avg track length diff: %.1fs over %d track(s)', avg, count)
        return avg

    def _compareTimeDifference(self, current, imported):
        if current and imported:
            try:
                return abs(
                    datetime.strptime(self._paddedHMS(current), '%H:%M:%S') -
                    datetime.strptime(self._paddedHMS(imported), '%H:%M:%S')
                )
            except Exception as e:
                logger.debug('Track length comparison failed: %s', e)
                return timedelta(seconds=999)
        return timedelta(seconds=999)

    def _paddedHMS(self, string):
        """Normalise a Discogs duration string to hh:mm:ss."""
        parts = [int(s) for s in string.split(':')]
        while len(parts) < 3:
            parts.insert(0, 0)
        total_s = parts[0] * 3600 + parts[1] * 60 + parts[2]
        return str(timedelta(seconds=total_s)).zfill(8)

    def _compareTitleSimilarity(self, local_tracks, discogs_tracks):
        """Average fuzzy title similarity (0–100) across tracks with titles on both sides."""
        total = 0.0
        count = 0
        for local, discogs_track in zip(local_tracks, discogs_tracks):
            lt = (local.get('title') or '').strip()
            dt = (discogs_track.get('title') or '').strip()
            if lt and dt:
                total += fuzz.token_sort_ratio(lt, dt)
                count += 1
        return total / count if count > 0 else 0.0

    def _getTrackInfo(self, version, skip_non_audio: bool = True):
        """Get track data from a Discogs release version, with disk-cache support.

        Version objects from master.versions are lightweight — they may not
        have their full data populated.  We check the release cache before
        accessing tracklist (which would trigger an API call) and save the
        data back afterwards.  This is distinct from fetch_release(), which
        works on full Release objects by numeric ID.

        Track extraction delegates to build_flat_tracklist() so that Pattern A
        (index entries whose sub_tracks are individually ripped files) and
        Pattern B (index entries that are a single file containing named
        sub-movements) are handled the same way as in DiscogsAlbum.
        This prevents false rejections when the local track count matches the
        expanded sub_track count rather than the top-level tracklist count.

        skip_non_audio:
            When True (default), DVD/Blu-ray/VHS etc. tracks are excluded.
            Pass False to get the complete tracklist for two-pass count matching.
        """
        if self._release_cache:
            cached = self._release_cache.get(version.id)
            if cached is not None:
                version.data.update(cached)

        trackinfo = build_flat_tracklist(version.tracklist,
                                         skip_non_audio=skip_non_audio)

        if self._release_cache:
            self._release_cache.put(version.id, version.data)

        return trackinfo

    def _candidate_score(self, release, base_score=50.0):
        """Composite score for ranking candidates (lower is better)."""
        score = float(base_score)
        searchParams = self.search_params
        try:
            data = release.data
            fmt_name = data.get('formats', [{}])[0].get('name', '').lower()
            qty = int(data.get('format_quantity', 1))
            year = release.year
        except Exception:
            return score

        local_year = searchParams.get('year')
        if local_year and str(year) == str(local_year):
            score -= 2.0

        is_vinyl = fmt_name in ('lp', 'vinyl', '12"', '7"', '10"')
        local_vinyl = (
            searchParams.get('media') == 'vinyl' or
            any('real_tracknumber' in t for t in searchParams.get('tracks', []))
        )
        if is_vinyl and local_vinyl:
            score -= 1.5
        elif fmt_name == 'cd' and not local_vinyl:
            score -= 1.0

        local_disc = searchParams.get('disc')
        if local_disc and qty == int(local_disc):
            score -= 0.5

        # Catalog number match: a strong, decisive signal that overrides
        # everything else here. Common when several regional/format
        # reissues of the same release share identical track counts and
        # near-identical durations (e.g. "In Your Room" maxi-singles) — the
        # catalog number is the only thing that tells them apart.
        catalog_hint = searchParams.get('catalog_hint')
        if catalog_hint:
            catnos = {normalize_catalog_number(l.get('catno', ''))
                      for l in data.get('labels', [])}
            if catalog_hint in catnos:
                score -= 10.0

        # Descriptor boost: soft scoring signal from folder-name keywords
        # (e.g. "Remastered", "Live").  Candidates whose Discogs descriptions
        # contain a matched keyword rank higher; non-matching candidates are
        # not rejected — this is a hint, not a gate.
        desc_hints = searchParams.get('descriptor_hints', [])
        if desc_hints:
            release_descs = [
                d.lower()
                for fmt in data.get('formats', [])
                for d in fmt.get('descriptions', [])
            ]
            if any(hint.lower() in desc
                   for hint in desc_hints
                   for desc in release_descs):
                score -= 1.0

        return score

    def _select_by_metadata(self, no_duration_candidates):
        """Rank tier-2 candidates: primary by title similarity, secondary by metadata."""
        scored = []
        for release, similarity in no_duration_candidates.values():
            metadata_bonus = self._candidate_score(release, base_score=0.0)
            scored.append((-similarity, metadata_bonus, release))
        scored.sort(key=lambda x: (x[0], x[1]))
        best_similarity, _, best = scored[0]
        logger.info('Tier-2 selection: [%s] title similarity %.0f%%', best.id, -best_similarity)
        return best

    # ------------------------------------------------------------------
    # Artist name resolution
    # ------------------------------------------------------------------

    def _resolve_artist_name(self, artist_name):
        """Return the Discogs canonical name for an artist.

        Phase 1: exact + space-insensitive match (free, no extra API calls).
        Phase 2: check namevariations on the top result (one extra API call).
        """
        if not artist_name or not artist_name.strip():
            return artist_name

        cached = self._artist_name_cache.get(artist_name)
        if cached is not None:
            return cached

        local = artist_name.strip()
        local_lower = local.lower()
        local_nospace = local_lower.replace(' ', '')
        top_result = None

        try:
            results = self.discogs_client.search(local, type='artist')
            for i, result in enumerate(results):
                if i >= 5:
                    break
                if top_result is None:
                    top_result = result
                canonical = strip_discogs_id_suffix(result.name)
                c_lower = canonical.lower()
                if c_lower == local_lower:
                    self._artist_name_cache[artist_name] = canonical
                    return canonical
                if c_lower.replace(' ', '') == local_nospace:
                    logger.info('Resolved artist "%s" → "%s" (space-normalised)', local, canonical)
                    self._artist_name_cache[artist_name] = canonical
                    return canonical
        except Exception as e:
            logger.debug('Artist name resolution (phase 1) failed for "%s": %s', local, e)

        if top_result is not None:
            try:
                canonical = strip_discogs_id_suffix(top_result.name)
                for v in (top_result.namevariations or []):
                    if v.lower() == local_lower or v.lower().replace(' ', '') == local_nospace:
                        logger.info('Resolved artist "%s" → "%s" (name variation)', local, canonical)
                        self._artist_name_cache[artist_name] = canonical
                        return canonical
            except Exception as e:
                logger.debug('Artist name resolution (phase 2) failed for "%s": %s', local, e)

        self._artist_name_cache[artist_name] = artist_name
        return artist_name

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def normalize(self, string):
        """Remove stop words and special characters from a search string."""
        if not string:
            return ''
        stop_words = ['lp', 'ep', 'bonus', 'tracks', 'mcd', 'cd', 'cdm', 'cds', 'none',
                      'vs.', 'vs', 'inch', 'various', 'artists', 'boxset', 'limited',
                      'edition', 'the']
        string = re.sub(r'[,"\-_\\]', ' ', string)
        string = re.sub(r'[\[\]()|:;]', '', string)
        string = re.sub(r'\s\d{1}\s', ' ', string)
        tokens = list(dict.fromkeys(string.split(' ')))
        return ' '.join(w for w in tokens if w.lower() not in stop_words)

    def get_master_release(self, release):
        if hasattr(release, 'master') and release.master is not None:
            return release.master
        return release

    def _release_obj_from_cache(self, release_id):
        release = self.discogs_client.release(release_id)
        if self._release_cache:
            cached = self._release_cache.get(release_id)
            if cached:
                release.data.update(cached)
        return release
