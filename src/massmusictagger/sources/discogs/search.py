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
    AUDIO_EXTENSIONS, VARIOUS_ARTIST_NAMES, extract_catalog_hints,
    catalog_hint_from_tag, disc_distribution,
    normalize_catalog_number, strip_catalog_suffix, strip_discogs_id_suffix,
    build_flat_tracklist, ignored_source_dirs, is_non_audio_position,
    merge_indexed_subtracks, natural_sort_key,
)
from massmusictagger.core.mediafile import MediaFile
from massmusictagger.core.naming.pathutils import resolve_path

logger = logging.getLogger(__name__)

#: Media that carry 16-bit audio by definition, so a 24-bit source cannot be
#: a rip of one. SACD and DVD are deliberately absent: both carry hi-res.
_CD_ONLY_FMTS = frozenset(('cd', 'cdr', 'cd-r', 'hdcd', 'minidisc'))



class SearchState:
    """One album's working set for a single search.

    These four used to be attributes of DiscogsSearch, which the processor
    builds **once per session** because the object also holds caches. With
    batch.workers above 1 that meant every worker searched through one shared
    set of candidates: four albums overwriting each other's results mid-search.

    Measured on two albums, same cache, same code -- workers=1 accepted 10
    candidates and matched both; workers=4 accepted 0 and matched neither.
    Missed matches are the visible symptom; the worse one is invisible, an
    album selecting from another album's candidate pool.

    So the working set is created per search and passed down. The caches stay
    on the instance, which is what sharing the object was for.
    """

    __slots__ = ('params', 'candidates', 'no_duration', 'sifted_masters',
                 'rejections', 'artist_entity')

    def __init__(self):
        self.params = {}
        self.candidates = {}
        self.no_duration = {}
        self.sifted_masters = set()
        #: Why each compared release was refused, so a failed search can say
        #: what it saw instead of only that it saw nothing. One dict per
        #: rejection: kind, rid, detail, and distance (lower = closer).
        self.rejections = []
        #: The Discogs artist the browse tier settled on. Kept because its
        #: response already carries the artist's other names, and fetching it
        #: again to read them would be paying twice for one answer.
        self.artist_entity = None

    def diagnosis(self):
        """One line saying what the search saw, for a run that found nothing.

        "No match found" is the same three words whether Discogs holds nothing
        at all -- a white-label bootleg, a single-track remix release -- or
        holds the right album and refused it over one field. The first is
        nothing to be done; the second is usually an incomplete or mis-split
        rip, and is actionable. Reading the log to tell them apart means
        re-running the album with -v and reassembling wrapped lines, which is
        why a pile of failures stays a pile.

        Everything needed is already in hand when the search gives up: the
        closest release, the field that disqualified it, and the size of the
        gap.
        """
        if not self.rejections:
            return 'no candidates returned'

        # Rank by kind first: a track-count miss is what the user can act on,
        # and a medium veto says nothing useful about closeness.
        order = {'track_count': 0, 'duration': 1, 'artist': 2, 'titles': 3,
                 'medium': 4}
        closest = min(self.rejections,
                      key=lambda r: (order.get(r['kind'], 9), r['distance']))
        counts = {}
        for r in self.rejections:
            counts[r['kind']] = counts.get(r['kind'], 0) + 1
        tally = ', '.join('%d on %s' % (n, k.replace('_', ' '))
                          for k, n in sorted(counts.items(), key=lambda kv: -kv[1]))
        return 'closest %s — %s (%d compared: %s)' % (
            closest['rid'], closest['detail'], len(self.rejections), tally)


class DiscogsSearch(DiscogsConnector):
    """Search for a Discogs release using metadata extracted from local files."""

    def __init__(self, tagger_config):
        DiscogsConnector.__init__(self, tagger_config)
        # Caches only. Anything belonging to one album's search lives in a
        # SearchState created per search -- this object is built once per
        # session and shared by every worker thread.
        self._artist_name_cache = {}

    # ------------------------------------------------------------------
    # Metadata extraction
    # ------------------------------------------------------------------

    def getSearchParams(self, source_dir, state):
        """Read file metadata from source_dir and populate state.params."""
        logger.info('Retrieving original metadata for search purposes')
        state.params = {}
        state.candidates = {}
        state.no_duration = {}
        state.sifted_masters = set()

        files = self._getMusicFiles(source_dir)
        files.sort(key=natural_sort_key)
        subdirectories = self._fetchSubdirectories(source_dir, files)
        searchParams = state.params
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
            catalog_hints = set(extract_catalog_hints(_raw_album))
            # A rip carrying `catalognum` names its pressing outright, which
            # beats parsing a number out of a title -- and the two disagree
            # often: Delta Machine tags '88765 46063 2' while its album tag
            # is just 'Delta Machine', so the title yielded nothing at all.
            tag_hint = catalog_hint_from_tag(getattr(metadata, 'catalognum', None))
            if tag_hint:
                catalog_hints.add(tag_hint)
            if catalog_hints:
                searchParams['catalog_hints'] = frozenset(catalog_hints)
            searchParams['album'] = strip_catalog_suffix(_raw_album)
            searchParams['year'] = metadata.year
            # Highest bit depth seen. A 24-bit file cannot have come off a CD,
            # which is 16-bit by definition, so it rules that medium out.
            depth = getattr(metadata, 'bitdepth', None)
            if depth:
                searchParams['bitdepth'] = max(
                    int(depth), int(searchParams.get('bitdepth') or 0))
            # Sample rate for the same reason: 44.1kHz is CD spec, and
            # anything above 48kHz did not come off one.
            rate = getattr(metadata, 'samplerate', None)
            if rate:
                searchParams['samplerate'] = max(
                    int(rate), int(searchParams.get('samplerate') or 0))
            codec = getattr(metadata, 'type', None)
            if codec:
                searchParams['codec'] = str(codec).lower()
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
            self.metadataFromFileNaming(source_dir, files, state)
            return None

    def metadataFromFileNaming(self, source_dir, files, state):
        """Fall back: derive artist/album/track info from directory and file names."""
        logger.info('Fetching metadata from file & directory naming')
        searchParams = state.params
        # source_dir lives in [common]. Reading it from [details] returned
        # None rather than raising -- TaggerConfig.get swallows a missing
        # section -- so base_dir was always '', the except never fired, and
        # re.sub('', '', ...) left the full path in place. The search then
        # matched against "/incoming/Artist/..." instead of the release
        # directory, including any year it found in the path.
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

    def search_strings(self, state):
        """Build normalised search strings from state.params.

        searchParams['artist'] is already the Discogs canonical name and has
        albumartist priority — both resolved in getSearchParams.  This method
        only normalises the strings and handles the VA compilation special case.
        """
        searchParams = state.params
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

    def search(self, sourcedir: str, notes: 'list | None' = None) -> 'str | None':
        """Return a Discogs release ID for *sourcedir*, or None.

        The SourceSearch entry point, matching MBSearch.search(). Everything
        Discogs needs to run a search now happens in here.

        The caller used to have to do this itself: call getSearchParams, work
        out the folder hints, reach into state.params to inject them,
        conditionally pop the year, call search_discogs() -- a differently
        named method returning a release object rather than an ID -- and then
        know to touch .tracklist to force a lazy fetch that could 404. None of
        that is the cascade's business, and none of it applied to MusicBrainz,
        which is why the two branches looked nothing alike.

        *notes* is an optional caller-owned list. On a failed search one line
        describing what was compared is appended to it, so the run can say
        whether nothing was found or the right release was refused. It is a
        parameter rather than an attribute because the searcher is shared
        between worker threads and per-album state on the instance is exactly
        the bug SearchState exists to prevent.
        """
        from massmusictagger.sources.hints import (
            _load_source_hints, _folder_format_hint, _folder_descriptor_hints)

        state = SearchState()
        self.getSearchParams(sourcedir, state)

        # Folder-name signals. The format hint gates candidates whose medium
        # conflicts with the folder (a vinyl LP for a 24-bit remaster), and the
        # descriptor hints boost candidates whose descriptions agree.
        hints = _load_source_hints(self.config)
        fmt_hint = _folder_format_hint(sourcedir, hints)
        if fmt_hint:
            state.params['format_hint'] = fmt_hint
            if fmt_hint == 'digital':
                # The original album year would restrict results to that year's
                # pressings -- all vinyl -- and hide the digital remaster.
                year = state.params.pop('year', None)
                if year:
                    logger.debug(
                        'Format hint "digital": suppressed year %s from the '
                        'Discogs search so remasters can surface (folder: %s)',
                        year, os.path.basename(sourcedir))
        desc_hints = _folder_descriptor_hints(sourcedir, hints)
        if desc_hints:
            state.params['descriptor_hints'] = desc_hints

        release = self.search_discogs(state)
        if release is None:
            if notes is not None:
                notes.append(state.diagnosis())
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

    def search_discogs(self, state):
        """Search Discogs for a matching release — four-tier strategy."""
        searchParams = state.params

        state.candidates = {}
        state.no_duration = {}
        state.sifted_masters = set()

        self.search_strings(state)
        s = searchParams.get('search', {})
        logger.info('Searching Discogs for: artist="%s" album="%s"',
                    s.get('artist', '?'), searchParams.get('album', '?'))

        # Tier 1 — structured fields with year (most precise)
        if searchParams.get('year'):
            self._search_release_fields(state, include_year=True)
            if state.candidates or state.no_duration:
                logger.info('Tier 1 (artist+title+year) found candidates')

        # Tier 2 — structured fields without year
        if not state.candidates and not state.no_duration:
            self._search_release_fields(state, include_year=False)
            if state.candidates or state.no_duration:
                logger.info('Tier 2 (artist+title) found candidates')

        # Tier 3 — artist-browse: follow the artist entity → scan their releases
        # More targeted than a free-text search when structured fields have failed.
        if not state.candidates and not state.no_duration:
            self.search_artist(state)
            if state.candidates or state.no_duration:
                logger.info('Tier 3 (artist browse) found candidates')

        # Tier 3b — the same artist under another name. Free of extra artist
        # lookups: the names come from the entity tier 3 already fetched.
        if not state.candidates and not state.no_duration:
            self.search_artist_variations(state)
            if state.candidates or state.no_duration:
                logger.info('Tier 3b (artist name variations) found candidates')

        # Tier 4 — free-text search, first 5 results only.
        # Anything beyond this is unlikely to surface a better match than the
        # structured tiers already tried; it exists purely as a safety net.
        if not state.candidates and not state.no_duration:
            self._search_text(state, ['all', 'master'], max_results=5)
            if state.candidates or state.no_duration:
                logger.info('Tier 4 (text search, first 5 results) found candidates')

        return self._pick_best(state)

    def _pick_best(self, state):
        """Select and return the best candidate, or None."""
        if not state.candidates and not state.no_duration:
            logger.warning('No matching release found on Discogs')
            return None

        if not state.candidates:
            logger.info('No duration-matched candidates; falling back to %d no-duration candidate(s)',
                        len(state.no_duration))
            return self._select_by_metadata(state.no_duration, state)

        if len(state.candidates) == 1:
            result = list(state.candidates.values())[0]
            logger.info('Found 1 tier-1 candidate: [%s] — %s',
                        result.id, getattr(result, 'title', '?'))
            return result

        logger.info('Found %d tier-1 candidates, selecting best match', len(state.candidates))
        scored = [
            (self._candidate_score(release, state, base_score=diff), release)
            for diff, release in state.candidates.items()
        ]
        scored.sort(key=lambda x: x[0])
        best_score, best = scored[0]
        logger.info('Selected [%s] composite score %.2f', best.id, best_score)
        return best

    # ------------------------------------------------------------------
    # Tier 1 / 2 — structured field search
    # ------------------------------------------------------------------

    #: Where an edition qualifier starts. Cutting at the *earliest* of these
    #: removes the whole tail, including the words leading into it: the local
    #: title has already had stopwords stripped, so it reads "Music From
    #: Original Motion Picture Soundtrack" and cutting at "motion picture"
    #: would leave "Music From Original" behind.
    _TITLE_TAIL_MARKERS = (
        'music from', 'original motion picture', 'motion picture',
        'original soundtrack', 'soundtrack',
        'deluxe edition', 'special edition', 'expanded edition',
        'anniversary edition', 'remastered', 'remaster',
        'bonus tracks', 'bonus track',
    )

    def _title_variants(self, release_title):
        """The title as given, then with an edition qualifier trimmed off.

        *The Assassination Of Jesse James* is the case. The rip calls it
        "... (Music From The Original Motion Picture Soundtrack)"; Discogs
        calls it "... (Music From The Motion Picture)". Searched in full the
        field search returns nothing at all. Cut at the qualifier it returns
        fifteen results with the right release first.

        Only a trailing qualifier is removed, and only when enough of the title
        survives to still identify it, so this narrows the query rather than
        abandoning it -- the artist anchor stays, which is what keeps it from
        behaving like a bare title search.
        """
        variants = [release_title]
        low = (release_title or '').lower()
        cut = min((low.find(m) for m in self._TITLE_TAIL_MARKERS
                   if low.find(m) > 0), default=-1)
        if cut > 0:
            trimmed = release_title[:cut].strip(' -(),:[]')
            # No length floor beyond "not empty": Low, Pop and IV are real
            # albums, and the artist anchor keeps even a short title a
            # constrained query rather than a fishing trip.
            if trimmed and trimmed.lower() != low:
                variants.append(trimmed)
        return variants

    def _search_release_fields(self, state, include_year=True):
        """Search using Discogs structured fields: artist, release_title[, year].

        Every release returned by the API is compared directly.  Its master's
        versions are also sifted (once per master) to catch related editions.
        This avoids the bug where a release returned by the search API was
        silently replaced by its parent master and never directly compared.
        """
        s = state.params.get('search', {})
        artist = s.get('artist', '')
        release_title = s.get('release', '')
        year = str(state.params.get('year') or '') if include_year else ''

        if not artist and not release_title:
            return

        # An edition qualifier the rip carries and Discogs does not makes the
        # whole query miss. Try the title as given first, then once more with
        # the qualifier cut off.
        variants = self._title_variants(release_title)
        if len(variants) > 1:
            for variant in variants:
                if state.candidates or state.no_duration:
                    return
                if variant != release_title:
                    logger.info('Retrying without the edition qualifier: %r',
                                variant)
                s['release'] = variant
                try:
                    self._search_release_fields_once(state, include_year)
                finally:
                    s['release'] = release_title
            return

        return self._search_release_fields_once(state, include_year)

    def _search_release_fields_once(self, state, include_year=True):
        """One field search, for exactly the title currently in the params."""
        s = state.params.get('search', {})
        artist = s.get('artist', '')
        release_title = s.get('release', '')
        year = str(state.params.get('year') or '') if include_year else ''

        cache_key = '|'.join(filter(None, [artist, release_title, year]))
        cache_type = 'fields_year' if include_year else 'fields'
        label = 'artist+title+year' if include_year else 'artist+title'

        cached = self._search_cache.get(cache_key, cache_type) if self._search_cache else None
        if cached is not None:
            logger.info('Field search cache hit (%s): %s', label, cache_key)
            self._replay_search_results(cached, state)
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
            if state.candidates:
                break
            if idx >= 25:
                break
            if 'Artist' in type(result).__name__:
                continue

            # Compare this release directly — key fix for the "swallowed release" bug
            self._siftReleases([result], state)
            collected.append({'id': result.id, 'is_master': False})
            logger.debug('  Field search direct compare: [%s]', result.id)

            # Also sift master versions (once per master)
            master = self.get_master_release(result)
            if hasattr(master, 'versions') and master.id not in state.sifted_masters:
                self._sift_master_versions(master, state)
                state.sifted_masters.add(master.id)
                collected.append({'id': master.id, 'is_master': True})

        if self._search_cache and collected:
            self._search_cache.put(cache_key, cache_type, collected)

    # ------------------------------------------------------------------
    # Text search — used as Tier 4 fallback
    # ------------------------------------------------------------------

    def _search_text(self, state, types, max_results=25):
        """Run the combined-text search for each type in the list."""
        for type_ in types:
            if state.candidates:
                break
            try:
                self._search_artist_title(state, type_, max_results=max_results)
            except Exception as e:
                logger.warning('Text search error (%s): %s', type_, e)

    def _search_artist_title(self, state, type_, max_results=25):
        """Combined text search using artistRelease string.

        max_results caps how many API results are examined before giving up.
        Set low (e.g. 5) when used as a last-resort tier to avoid scanning
        hundreds of pages for a match that structured tiers already missed.

        Fixes the 'swallowed release' bug: when the API returns a Release
        (not a Master) as a search result, compare it directly *and* sift
        its master's versions.  Previously only the master was sifted.
        """
        s = state.params['search']
        query = s['artistRelease']

        cached = self._search_cache.get(query, type_) if self._search_cache else None
        if cached is not None:
            logger.info('Search cache hit: "%s" (%s)', query, type_)
            self._replay_search_results(cached, state)
            return

        logger.info('Searching by artist and title (%s, max %d): %s', type_, max_results, query)
        results = self.discogs_client.search(query, type=type_)

        collected = []
        for idx, result in enumerate(results):
            if state.candidates:
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
                self._siftReleases([result], state)
                collected.append({'id': result.id, 'is_master': False})

            # Sift master versions — once per master across all tiers
            master = self.get_master_release(result)
            if hasattr(master, 'versions') and master.id not in state.sifted_masters:
                self._sift_master_versions(master, state)
                state.sifted_masters.add(master.id)
                collected.append({'id': master.id, 'is_master': True})
            elif not result_is_release:
                # result is a master itself and was already sifted (or IS the master)
                if master.id not in state.sifted_masters:
                    self._sift_master_versions(master, state)
                    state.sifted_masters.add(master.id)
                    collected.append({'id': master.id, 'is_master': True})

        if self._search_cache and collected:
            self._search_cache.put(query, type_, collected)

    # ------------------------------------------------------------------
    # Artist browse — Tier 3
    # ------------------------------------------------------------------

    #: How many artist search results to inspect for name variations before
    #: giving up. Reading them forces the full artist fetch, so this is a cost
    #: bound; the canonical-name comparison above it is free.
    _ANV_RESULTS_TO_INSPECT = 3

    def _artist_result_matches(self, artist, result, inspect_variations):
        """Does this Discogs artist go by the name the files use?

        The canonical name is checked first and costs nothing. Failing that,
        the artist's recorded name variations are checked -- Discogs keeps them
        precisely because acts are credited differently across a career, so
        "Nick Cave And The Bad Seeds" and "Einsturzende Neubauten" name real
        artists whose canonical spellings differ. Matching on the canonical
        name alone left those unresolvable.
        """
        wanted = self.normalize(artist).lower()
        if wanted == self.normalize(strip_discogs_id_suffix(result.name)).lower():
            return True
        if not inspect_variations:
            return False
        try:
            variations = (getattr(result, 'data', None) or {}).get('namevariations') or []
        except Exception:
            return False
        for v in variations:
            if wanted == self.normalize(strip_discogs_id_suffix(v or '')).lower():
                logger.info('Artist %r matched %r on a name variation',
                            artist, result.name)
                return True
        return False

    def search_artist(self, state):
        searchParams = state.params
        artist = state.params['search']['artist']

        logger.info('Searching by artist: %s', artist)
        results = self.discogs_client.search(artist, type='artist')

        if results.count == 0:
            return

        releases = None
        fallback = None
        for idx, result in enumerate(results):
            if state.candidates:
                break
            if fallback is None:
                fallback = result
            if self._artist_result_matches(
                    artist, result, idx < self._ANV_RESULTS_TO_INSPECT):
                releases = result.releases
                state.artist_entity = result
            if releases is None:
                continue
            for i, release in enumerate(releases):
                if state.candidates or i > 25:
                    return
                if searchParams['album'].lower() in release.title.lower() or \
                        release.title.lower() in searchParams['album'].lower():
                    if hasattr(release, 'versions'):
                        self._siftReleases(list(release.versions), state)
                    else:
                        self._siftReleases([release], state)

        # Nothing matched by name, but the closest artist Discogs offered is
        # still the best source of alternate names for the tier that follows.
        # Without this a mis-credited album has nothing at all to retry under.
        if state.artist_entity is None and fallback is not None:
            state.artist_entity = fallback

    #: Where an artist's other names come from, in descending confidence.
    #: Both directions of the same relationship are needed: `members` finds a
    #: solo record filed under the band, `groups` finds a collaboration filed
    #: under the person.
    _NAME_SOURCES = ('namevariations', 'aliases', 'groups', 'members')

    def artist_alternate_names(self, state):
        """The artist's other names, from the entity the browse tier fetched.

        Discogs models an artist as one entity with several names attached::

            namevariations  Cave, N. Cave, Nicholas Cave, …
            aliases         A Drunk Cowboy Junkie, Her Dead Twin
            groups          Nick Cave & The Bad Seeds, Nick Cave & Warren
                            Ellis, The Birthday Party, Grinderman
            members         (for a group) Mick Harvey, Blixa Bargeld, …

        All of it arrives in the `/artists/<id>` response the browse tier
        already fetches, and was being discarded.

        Taken **one from each list in turn** rather than one list at a time.
        Nick Cave the person carries more than ten namevariations, nearly all
        of them initialisms -- `Cave`, `N. Cave`, `N.E.Cave` -- so draining
        that list first would spend the whole budget on noise and never reach
        `groups`, which is where the answer actually is: *The Assassination Of
        Jesse James* is credited to `Nick Cave & Warren Ellis` and the rip says
        `Nick Cave`.

        Names that normalise to the artist already searched are dropped: they
        would repeat a search that has just failed.
        """
        entity = state.artist_entity
        if entity is None:
            return []
        data = getattr(entity, 'data', None) or {}
        searched = self.normalize(state.params['search']['artist']).lower()
        seen = {searched}

        buckets = []
        for key in self._NAME_SOURCES:
            bucket = []
            for item in (data.get(key) or []):
                name = item.get('name') if isinstance(item, dict) else item
                name = strip_discogs_id_suffix((name or '').strip())
                if not name:
                    continue
                norm = self.normalize(name).lower()
                if norm in seen:
                    continue
                seen.add(norm)
                bucket.append(name)
            buckets.append(bucket)

        names = []
        for i in range(max((len(b) for b in buckets), default=0)):
            for bucket in buckets:
                if i < len(bucket):
                    names.append(bucket[i])

        # Rank by how the name relates to the one searched, because list order
        # is not relevance. Nick Cave's groups list runs ten deep and
        # "Nick Cave & Warren Ellis" is ninth, so a budget of six spent in list
        # order went on "Cave", "Cave N", "Her Dead Twin" and "The Birthday
        # Party" and never reached the one that holds The Assassination Of
        # Jesse James.
        #
        # A name that shares the searched one, in either direction, is where an
        # album credited slightly differently will be: "Nick Cave & Warren
        # Ellis" extends "Nick Cave", and "Nick Cave" is contained by "Nick
        # Cave & The Bad Seeds". Both are the cases this tier exists for, so
        # both rank above a name with nothing in common -- another member of
        # the band, or an unrelated alias.
        #
        # The sort is stable, so within a rank the round-robin above still
        # decides, and a namevariation still precedes a member.
        def shares_the_credit(name):
            other = self.normalize(name).lower()
            if not other or not searched:
                return 1
            return 0 if (searched in other or other in searched) else 1
        return sorted(names, key=shares_the_credit)

    def search_artist_variations(self, state):
        """Retry the field search under the artist's other names.

        The case this exists for: every tier is anchored on the artist string
        from the local tags, so when that names the wrong Discogs artist the
        right release is never retrieved -- not ranked poorly, absent. Nick
        Cave's *Idiot Prayer* is credited to `Nick Cave`; the rip said
        `Nick Cave & The Bad Seeds`; 111 releases of the wrong artist were
        compared and refused, and the two correct releases -- which agree on
        22 of 22 track lengths -- were never fetched.

        Broadening retrieval does not broaden acceptance: whatever this finds
        must still match on track count and agree on most track lengths, so
        the risk here is wasted calls rather than wrong matches. The limit is
        therefore a cost control, not a safety one, and setting it to 0 turns
        the tier off.
        """
        limit = self.artist_name_variations
        if limit <= 0:
            return
        names = self.artist_alternate_names(state)[:limit]
        if not names:
            return
        logger.info('Retrying under %d other name(s) for this artist: %s',
                    len(names), ', '.join(names))
        original = state.params['search']['artist']
        try:
            for name in names:
                if state.candidates or state.no_duration:
                    break
                state.params['search']['artist'] = name
                self._search_release_fields(state, include_year=False)
        finally:
            state.params['search']['artist'] = original

    def search_album_title(self, state):
        searchParams = state.params
        release_title = state.params['search']['release']
        logger.info('Searching by title: %s', release_title)
        results = self.discogs_client.search(release_title, type='release')
        for i, result in enumerate(results):
            if state.candidates or i > 25:
                break
            master = self.get_master_release(result)
            if hasattr(master, 'versions'):
                self._siftReleases(list(master.versions), state)
            else:
                self._siftReleases([result], state)

    # ------------------------------------------------------------------
    # Candidate management
    # ------------------------------------------------------------------

    def _siftReleases(self, releases, state):
        """Evaluate each release into tier-1 or tier-2 candidate buckets.

        Evaluates every release in the batch (even once a candidate exists)
        so _pick_best() can later choose the best among several tier-1
        matches — callers that want to stop after the first hit already
        check state.candidates between batches themselves.

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
                difference = self._compareRelease(release, state)
            except Exception as e:
                logger.warning('Skipping release %s — fetch/compare failed: %s',
                                getattr(release, 'id', '?'), e)
                continue
            if difference is False:
                continue
            elif difference < 0:
                state.no_duration[release.id] = (release, abs(difference) * 100)
            else:
                while difference in state.candidates:
                    difference += 0.001
                state.candidates[difference] = release

    def _sift_master_versions(self, master, state):
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
        self._siftReleases(versions, state)

    def _replay_search_results(self, cached_results, state):
        """Replay a cached search result list without hitting the search API."""
        for item in cached_results:
            if state.candidates:
                break
            rid = item['id']
            if item.get('is_master'):
                if rid not in state.sifted_masters:
                    master = self.discogs_client.master(rid)
                    self._sift_master_versions(master, state)
                    state.sifted_masters.add(rid)
            else:
                release = self._release_obj_from_cache(rid)
                diff = self._compareRelease(release, state)
                if diff is False:
                    continue
                elif diff < 0:
                    state.no_duration[release.id] = (release, abs(diff) * 100)
                else:
                    while diff in state.candidates:
                        diff += 0.001
                    state.candidates[diff] = release

    def _compareRelease(self, release, state):
        """Compare local files against a single Discogs release.

        Return convention (lower is always better for the caller):
          float >= 0  — tier-1: avg track-length diff in seconds
          float < 0   — tier-2: -(similarity/100)
          False       — rejected
        """
        searchParams = state.params
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
                    # Pass 4: an index entry carrying a parent duration and
                    # timed sub_tracks -- or neither -- reads equally as one
                    # file or several, and nothing in the Discogs data
                    # settles it. Collapsing is the default; try expanding
                    # before rejecting the release outright.
                    trackInfo_expanded = self._expanded_track_info(release, local_count)
                    if (trackInfo_expanded is not None
                            and local_count == len(trackInfo_expanded)):
                        logger.info(
                            '  [%s] sub-track expansion: %d index entr%s '
                            'read as separate files → retrying with %d '
                            'tracks', rid,
                            len(trackInfo_expanded) - len(trackInfo_audio),
                            'y' if len(trackInfo_expanded) - len(trackInfo_audio) == 1
                            else 'ies',
                            len(trackInfo_expanded))
                        trackInfo = trackInfo_expanded
                    else:
                        logger.info(
                            '  [%s] rejected — local has %d tracks, Discogs '
                            'has %d (%d audio, %d non-audio)',
                            rid, local_count, len(trackInfo),
                            len(trackInfo_audio), non_audio_count,
                        )
                        state.rejections.append({
                            'kind': 'track_count', 'rid': rid,
                            'distance': abs(local_count - len(trackInfo)),
                            'detail': '%d tracks, local has %d' % (
                                len(trackInfo), local_count),
                        })
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

        # Bit depth rules a medium out, one way only. CD audio is 16-bit by
        # definition, so a 24-bit source cannot be a CD rip -- the same album
        # matched both 'Codes (SBR331) [9xDM]' and 'Codes (SBR331CD) [CD]'
        # across two runs of a 24-bit/44.1 download, and only the first is
        # possible. 16-bit rules nothing out, since a 16-bit file may equally
        # be a CD rip or a lossless download.
        local_depth = int(searchParams.get('bitdepth') or 0)
        if local_depth > 16:
            try:
                rel_fmt = (release.data.get('formats', [{}])[0]
                           .get('name', '') or '').lower()
            except Exception:
                rel_fmt = ''
            if rel_fmt in _CD_ONLY_FMTS:
                logger.info('  [%s] rejected — %d-bit source cannot be a %s '
                            '(CD audio is 16-bit)', rid, local_depth, rel_fmt)
                state.rejections.append({
                    'kind': 'medium', 'rid': rid, 'distance': 1000.0,
                    'detail': '%d-bit source cannot be a %s' % (local_depth, rel_fmt),
                })
                return False

        has_duration = any(t['duration'] is not None for t in trackInfo)
        if not has_duration:
            similarity = self._compareTitleSimilarity(searchParams['tracks'], trackInfo)
            if similarity > 0 and similarity < self.title_similarity_threshold:
                logger.info('  [%s] rejected — title similarity %.0f%% below threshold %.0f%%',
                            rid, similarity, self.title_similarity_threshold)
                state.rejections.append({
                    'kind': 'titles', 'rid': rid,
                    'distance': 100.0 - similarity,
                    'detail': 'titles %.0f%% similar' % similarity,
                })
                return False
            logger.info('  [%s] tier-2 candidate — track count %d, title similarity %.0f%%',
                        rid, local_count, similarity)
            return -(similarity / 100.0)

        # A single track corroborates nothing: the count matches trivially and
        # duration agreement is one comparison. The artist has to carry the
        # whole match, and a resemblance is not enough -- three albums in this
        # library are single-track covers filed under the artist of the
        # original, including Lunar Paths' reading of "The Ship Song" filed as
        # Marianne Faithfull.
        #
        # This matters more since tier 3b, which deliberately searches under
        # other names for the artist: widening retrieval widens what can be
        # wrongly accepted unless the artist is checked at the point of
        # acceptance too.
        if local_count == 1:
            from massmusictagger.sources.musicbrainz.search import artists_are_related
            ours = searchParams.get('albumartist') or searchParams.get('artist') or ''
            try:
                theirs = ', '.join(a.get('name', '') for a in
                                   (release.data.get('artists') or []))
            except Exception:
                theirs = ''
            if ours and theirs and not artists_are_related(ours, theirs):
                logger.info('  [%s] rejected — single track, and %r is not a '
                            'variation of %r', rid, theirs, ours)
                state.rejections.append({
                    'kind': 'artist', 'rid': rid, 'distance': 500.0,
                    'detail': 'single track credited to %s, not %s' % (theirs, ours),
                })
                return False

        agreed, compared, median = self._compareTrackLengths(
            searchParams['tracks'], trackInfo)
        if compared == 0:
            logger.info('  [%s] rejected — no track pair had both durations', rid)
            return False

        share = agreed / compared
        if share >= self.tracklength_agreement:
            logger.info('  [%s] accepted — %d/%d tracks within %ss, median diff %.1fs',
                        rid, agreed, compared, self.tracklength_tolerance, median)
            return median

        logger.info('  [%s] rejected — only %d/%d tracks within %ss '
                    '(need %.0f%%), median diff %.1fs',
                    rid, agreed, compared, self.tracklength_tolerance,
                    self.tracklength_agreement * 100, median)
        state.rejections.append({
            'kind': 'duration', 'rid': rid, 'distance': median,
            'detail': 'only %d of %d tracks agree on length' % (agreed, compared),
        })
        return False

    def _compareTrackLengths(self, current, imported):
        """How many tracks agree on length, and by how much they typically differ.

        Returns ``(agreed, compared, median_difference)`` over the track pairs
        where both sides state a duration.

        This counts agreement rather than averaging error, because the two
        answer different questions and only the first one is useful here. An
        average cannot separate "every track is moderately wrong", which means
        a different release, from "one track is very wrong", which usually
        means one mis-entered duration or one substituted version -- and those
        deserve opposite verdicts.

        Nick Cave's *Fifteen Feet Of Pure White Snow* is the case that forced
        it. Release 35448229 has the same five titles in the same order, four
        of them within a second; track 1 is 89s out because Discogs lists a
        4:07 single version. The mean was 18.2s, over a 10s tolerance, so the
        right release was refused and the run reported "No match found".

        The median is returned as the score because it is the robust summary of
        the same numbers: 1s here rather than 18.2s, so a release that agrees
        on most tracks still ranks by how well it agrees.
        """
        diffs = []
        for i, track in enumerate(current):
            local_dur = track.get('duration') or ''
            discogs_dur = imported[i]['duration']
            if not local_dur or discogs_dur is None:
                continue
            diffs.append(
                self._compareTimeDifference(local_dur, discogs_dur).total_seconds())
        if not diffs:
            return 0, 0, float('inf')
        agreed = sum(1 for d in diffs if d <= self.tracklength_tolerance)
        ordered = sorted(diffs)
        mid = len(ordered) // 2
        median = (ordered[mid] if len(ordered) % 2
                  else (ordered[mid - 1] + ordered[mid]) / 2)
        logger.info('track lengths: %d/%d within %ss, median diff %.1fs',
                    agreed, len(diffs), self.tracklength_tolerance, median)
        return agreed, len(diffs), median

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

    def _expanded_track_info(self, version, local_count):
        """The other reading of an ambiguous index entry, or None.

        Returns None when the release has no ambiguous index entry, so the
        common case costs one cheap check rather than a second flatten.
        """
        from massmusictagger.sources.discogs.utils import prefers_expanded_index
        try:
            tracklist = version.tracklist
            if not prefers_expanded_index(tracklist, local_count):
                return None
            return build_flat_tracklist(tracklist, skip_non_audio=True,
                                        expand_ambiguous_index=True)
        except Exception as exc:
            logger.debug('Could not build the expanded tracklist: %s', exc)
            return None

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

    _VINYL_FMTS = ('lp', 'vinyl', '12"', '7"', '10"')

    @property
    def medium_preference(self):
        """The medium weights, from conf/medium_preference.yaml.

        Read once per searcher rather than per candidate: this is consulted for
        every release compared, and a search can compare hundreds.
        """
        table = getattr(self, '_medium_preference', None)
        if table is None:
            from massmusictagger.sources.medium import load_medium_preference
            from massmusictagger import roots
            path = None
            try:
                path = roots.discover(
                    roots.config_root(getattr(self.config, 'config_file', '')),
                    'medium_preference')
            except Exception:
                path = None
            table = load_medium_preference(path)
            self._medium_preference = table
        return table

    def _medium_adjustment(self, fmt_name, searchParams):
        """Prefer the medium the rip could plausibly have come from.

        Track counts and durations cannot separate a CD from the cassette
        issued alongside it: the tracklists are identical, so the two score the
        same and either can win. Observed doing exactly that -- a 16/44.1 FLAC
        rip matched an Indonesian cassette, a `Cass` folder matched a CD, and
        an LP folder matched a CD with a different catalogue number.

        The audio is the evidence. 44.1kHz/16-bit is CD spec, so a CD is the
        likeliest origin and a needle drop or tape rip at that resolution is
        unusual. Above 16-bit or 48kHz cannot be a CD at all -- ruled out
        outright elsewhere -- and is most likely a download.

        Positive evidence for vinyl still wins: side-and-position track
        numbers (A1, B2) are a fact about the rip, not an inference from it.
        """
        tracks = searchParams.get('tracks', [])
        local_vinyl = (searchParams.get('media') == 'vinyl'
                       or any('real_tracknumber' in t for t in tracks))
        if local_vinyl:
            return -1.5 if fmt_name in self._VINYL_FMTS else 0.0

        depth = int(searchParams.get('bitdepth') or 0)
        rate = int(searchParams.get('samplerate') or 0)

        # A lossy file has been through a transcode and says nothing about
        # what it was transcoded from.
        if (searchParams.get('codec') or '') in ('mp3', 'aac', 'ogg', 'opus'):
            return 0.0

        table = self.medium_preference
        if depth > 16 or rate > 48000:
            return table.get('hi_res', {}).get(fmt_name, 0.0)
        if depth == 16 and rate == 44100:
            return table.get('cd_spec', {}).get(fmt_name, 0.0)
        return 0.0

    def _candidate_score(self, release, state, base_score=50.0):
        """Composite score for ranking candidates (lower is better)."""
        score = float(base_score)
        searchParams = state.params
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

        score += self._medium_adjustment(fmt_name, searchParams)

        # Disc layout. The flat track count cannot tell a 2-disc 13 + 4 album
        # from a single-disc release of seventeen, so both score identically
        # and the wrong one can win -- surfacing much later as a per-disc count
        # mismatch during tagging, with an error that never mentions layout.
        #
        # Compared as a distribution rather than a disc count, because Discogs
        # format_quantity is unreliable for this: Spirit's correct 2-CD release
        # reports three format entries (CD, CD, All Media).
        local_disc_hint = searchParams.get('disc')
        local_dist = disc_distribution(
            t.get('position') for t in searchParams.get('tracks', []))
        if len(local_dist) > 1:
            try:
                cand_dist = disc_distribution(
                    t.get('position') for t in (data.get('tracklist') or [])
                    if t.get('type_') == 'track')
            except Exception:
                cand_dist = ()
            if cand_dist:
                if cand_dist == local_dist:
                    logger.info('  [%s] disc layout matches %s', release.id,
                                list(local_dist))
                    score -= 5.0
                elif len(cand_dist) != len(local_dist):
                    logger.info('  [%s] disc layout %s does not match local %s',
                                release.id, list(cand_dist), list(local_dist))
                    score += 5.0
        elif local_disc_hint and qty == int(local_disc_hint):
            # Single-disc local album: keep the old, weaker nudge.
            score -= 0.5

        # Catalog number match: a strong, decisive signal that overrides
        # everything else here. Common when several regional/format
        # reissues of the same release share identical track counts and
        # near-identical durations (e.g. "In Your Room" maxi-singles) — the
        # catalog number is the only thing that tells them apart.
        catalog_hints = searchParams.get('catalog_hints')
        if catalog_hints:
            catnos = {normalize_catalog_number(l.get('catno', ''))
                      for l in data.get('labels', [])}
            matched = catnos & catalog_hints
            if matched:
                logger.info('  [%s] catalog number %s matches the folder name',
                            release.id, sorted(matched)[0])
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

    def _select_by_metadata(self, no_duration_candidates, state):
        """Rank tier-2 candidates: primary by title similarity, secondary by metadata."""
        scored = []
        for release, similarity in no_duration_candidates.values():
            metadata_bonus = self._candidate_score(release, state, base_score=0.0)
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
