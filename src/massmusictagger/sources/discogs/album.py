import logging
import re
import os

from datetime import timedelta, datetime

from massmusictagger.core.mediafile import MediaFile
from massmusictagger.core.album import Album, Disc, Track
from massmusictagger.sources.discogs.utils import strip_discogs_id_suffix, is_non_audio_position, parse_extraartists

# Connector classes live in discogs_connector; re-exported here for backward compat.
from massmusictagger.sources.discogs.connector import (  # noqa: F401
    DiscogsConnector, LocalDiscogsConnector, DummyResponse,
)

logger = logging.getLogger(__name__)


class AlbumError(Exception):
    """Raised when album mapping or processing fails."""
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


class DiscogsAlbum(object):
    """Wraps the Discogs API client, mapping release data to the Album/Track
    model used by the tagger."""

    def __init__(self, release, use_anv=True):
        self.release = release
        # When True, artist display uses the Discogs Artist Name Variation (ANV)
        # — the name as credited on the physical release sleeve.  Set False to
        # always use the canonical Discogs database name.
        self.use_anv = use_anv

    # Discogs container formats whose payload is described by the subsequent
    # entries in the formats list (e.g. Box Set → CD + Vinyl; All Media → 2×CD).
    _CONTAINER_FORMATS = frozenset({'Box Set', 'All Media'})
    _BOX_CONTAINED = frozenset({'CD', 'CDr', 'Vinyl', 'LP', 'Cassette',
                                 'SACD', 'Blu-ray', 'DVD', 'MiniDisc', 'DAT'})

    @staticmethod
    def _resolve_primary_format(fmts: list) -> str:
        """Return the physical format name from a Discogs formats list.

        Box Set and All Media are container formats; for these, return the
        first recognised physical media type from the subsequent entries, so
        %format_base%/%format_code% reflect what was actually ripped.
        """
        if not fmts:
            return ''
        primary = fmts[0].get('name', '')
        if primary in DiscogsAlbum._CONTAINER_FORMATS:
            for fmt in fmts[1:]:
                if fmt.get('name') in DiscogsAlbum._BOX_CONTAINED:
                    return fmt['name']
        return primary

    def map(self):
        """ map the retrieved information to the tagger specific objects """

        album = Album(self.release.id, self.release.title.strip(), self.album_artists(self.release.artists))
        album._artist_display = self.album_artist_display(self.release.artists)

        album.sort_artist = self.sort_artist(self.release.artists)
        album.url = self.url
        # Discogs returns "none" (lowercase) when no catalog number exists
        album.catnumbers = self.remove_duplicate_items([
            catno for name, catno in self.labels_and_numbers
            if catno and catno.lower() != 'none'
        ])
        album.labels = self.remove_duplicate_items([name for name, catno in self.labels_and_numbers])
        album.images = self.images
        album.year = self.year
        album.release_date = self.release_date
        # Collect all format names from the release (used for %format_names%)
        _all_fmts = self.release.data.get("formats", [])
        album.format_names = [f.get("name", "") for f in _all_fmts]
        album.format = self._resolve_primary_format(_all_fmts)

        album.format_description = self.format_description
        # Free-text notes from format.text (e.g. "30th Anniversary 2CD Edition").
        # Kept separate from format_description so they don't appear in
        # %format_description% / media-description display, but used by
        # TaggerUtils for edition detection via compute_edition().
        album.format_text_notes = self.format_text_notes
        album.genres = self.release.data["genres"]
        album.media = self.media


        try:
            album.styles = self.release.data["styles"]
        except KeyError:
            album.styles = [""]

        if "country" in self.release.data:
            album.country = self.release.data["country"]
        else:
            logger.warning("no country set for relid %s", self.release.id)
            album.country = ""

        if "notes" in self.release.data:
            album.notes = self.release.data["notes"]

        album.disctotal = self.disctotal
        album.is_compilation = self.is_compilation

        album.master_id = self.master_id

        # MusicBrainz-style release type classification, inferred from Discogs
        # format data.  Mapping is driven by format_codes.yaml release_type_map
        # so users can extend it without code changes.
        try:
            from massmusictagger.core.naming.formatcodes import load_format_codes, compute_release_types
            _fmt_data = self.release.data["formats"][0]
            album.release_type, album.release_types = compute_release_types(
                format_name=_fmt_data.get('name', ''),
                descriptions=list(_fmt_data.get('descriptions') or []),
                is_compilation=album.is_compilation,
                format_codes=load_format_codes(None),
            )
        except Exception as _exc:
            logger.debug('compute_release_types failed: %s', _exc)
            album.release_type = 'Album'
            album.release_types = ['Album']

        # Release status: Official, Promo, Bootleg, Pseudo-Release
        album.status = self.release.data.get('status', '')
        album.source = 'discogs'

        # Release-level identifiers: barcode, ISRC, ASIN, Matrix/Runout, etc.
        album.identifiers = self.release.data.get('identifiers', [])
        album.barcode = next(
            (i.get('value', '') for i in album.identifiers
             if i.get('type', '').lower() == 'barcode'),
            ''
        )

        # Release-level extra artist credits (composers, producers, engineers, …)
        album.extraartists = self.release.data.get('extraartists', [])

        album.discs = self.discs_and_tracks(album)

        # Reconcile disctotal against the parsed tracklist.
        #
        # The format-data estimate (self.disctotal) counts all physical media
        # qty entries.  For box sets this overstates the disc count: a
        # CD + Cassette + Box Set release has disctotal=2 from the format data
        # even though the user only holds one of those formats locally.
        #
        # The tracklist is the actual ground truth: it tells us how many
        # distinct disc/side numbers appear in the audio the user has ripped.
        # len(album.discs) is computed from the tracklist and matches exactly
        # what taggerutils writes to the disctotal file tag.  Keeping
        # album.disctotal in sync prevents the format code from overstating
        # the disc count (DCD instead of CD).
        #
        # Edge case — mismatched tracklist: if the user holds one format from a
        # multi-format box set whose tracklist covers all formats, len(album.discs)
        # may exceed the local file count.  Track-count validation in the cascade
        # catches this and falls through to other sources or existing_tags.
        if album.discs:
            album.disctotal = len(album.discs)

        return album

    @property
    def media(self):
        ''' the recording media the track came from.
            eg, CD, Cassette, Radio Broadcast, LP, CD Single
        '''
        fields = ['qty', 'name', 'descriptions', 'text']
        source = []

        for format in self.release.data["formats"]:
            f = ''
            for field in fields:
                if field in format:
                    if field == 'descriptions':
                        descriptions = format['descriptions'] or []
                        if descriptions:
                            f += ' ' + ', '.join(descriptions)
                    elif field == 'qty':
                        f += '{} x '.format(format['qty'])
                    elif field == 'name':
                        f += format['name']
                    else:
                        f += ', {}'.format(format[field])
            source.append(f)

        return '; '.join(source)



    @property
    def format_description(self):
        descriptions = []

        for format in self.release.data["formats"]:
            if 'descriptions' in format:
                descriptions.extend(format['descriptions'] or [])

        return descriptions

    @property
    def format_text_notes(self):
        """Return free-text format.text values (e.g. '30th Anniversary 2CD Edition').

        These are kept separate from format_description so they don't appear in
        the %format_description% media-description display.  TaggerUtils uses
        them for edition detection with loose (word-set) matching.
        """
        return [fmt['text'] for fmt in self.release.data.get('formats', [])
                if fmt.get('text')]


    @property
    def url(self):
        """ returns the discogs url of this release """

        return "http://www.discogs.com/release/{}".format(self.release.id)

    @property
    def labels_and_numbers(self):
        """ Returns all available catalog numbers"""
        for label in self.release.data["labels"]:
            yield self.clean_duplicate_handling(label["name"]), label["catno"]

    @property
    def images(self):
        """Return image metadata for the release.

        Each entry is a dict with at least 'uri' and 'type' keys.
        Discogs only distinguishes 'primary' (front cover) and 'secondary'
        (all other images — back, media, booklet, etc. are not differentiated).
        """
        try:
            return [
                {
                    'uri':    x['uri'],
                    'type':   x.get('type', 'secondary'),
                    'width':  x.get('width'),
                    'height': x.get('height'),
                }
                for x in self.release.data['images']
            ]
        except KeyError:
            return []

    @property
    def year(self):
        """ returns the album release year obtained from API 2.0 """

        good_year = re.compile(r"\d\d\d\d")
        try:
            return good_year.match(str(self.release.data["year"])).group(0)
        except IndexError:
            return "1900"
        except AttributeError:
            return "1900"

    @property
    def release_date(self):
        """Return the full release date from the Discogs 'released' field.

        Normalises the various formats Discogs uses:
          2004-06-21  → '2004-06-21'
          2004-06-00  → '2004-06'   (zero day = month precision only)
          2004-00-00  → '2004'      (zero month = year precision only)
          2004        → '2004'
          0 / ''      → None        (unknown)
        """
        raw = str(self.release.data.get('released', '') or '').strip()
        if not raw or raw == '0':
            return None
        parts = raw.split('-')
        # Drop trailing zero components (day=00, month=00)
        while parts and parts[-1] in ('00', '0'):
            parts.pop()
        result = '-'.join(parts)
        # Must at least be a 4-digit year
        if not re.match(r'^\d{4}', result):
            return None
        return result

    @property
    def disctotal(self):
        """ Obtain the number of discs for the given release. """

        discno = 0

        # allows tagging of digital releases.
        # sample format <format name="File" qty="2" text="320 kbps">
        # assumes all releases of name=File is 1 disc.
        if self.release.data["formats"][0]["name"] == "File":
            discno = 1
        else:
            _PHYSICAL_MEDIA = {
                'CD', 'CDr', 'Vinyl', 'LP',
                'SACD', 'Blu-ray', 'DVD-Audio', 'Cassette',
                'Minidisc', 'DAT', 'DCC', 'Laserdisc',
            }
            for format in self.release.data["formats"]:
                if format['name'] in _PHYSICAL_MEDIA:
                    discno += int(format['qty'])

        logger.info("determined %d no of discs total", discno)
        return discno

    @property
    def master_id(self):
        """ returns the master release id """

        try:
            return self.release.data["master_id"]
        except KeyError:
            return None

    def _gen_artist(self, artist_data):
        """ yields a list of artists name properties """
        for x in artist_data:
            # bugfix to avoid the following scenario, or ensure we're yielding
            # an artist object.
            # AttributeError: 'unicode' object has no attribute 'name'
            # [<Artist "A.D.N.Y*">, u'Presents', <Artist "Leiva">]
            try:
                yield x.name
            except AttributeError:
                pass

    def _artist_name(self, x):
        """Return the display name for an artist object, honouring use_anv.

        When use_anv=True and an ANV is present the ANV is used as-is, except
        that the "Artist, The" → "The Artist" display normalisation is applied
        (Discogs uses comma-The internally for both canonical and ANV forms).
        Disambiguation suffixes (e.g. '(65)') are NOT stripped from ANVs —
        they are part of the credited display name on that release.
        """
        anv = x.data.get('anv', '').strip() if hasattr(x, 'data') else ''
        if self.use_anv and anv:
            return self._THE_SUFFIX_RE.sub(r"The \g<1>", anv)
        return self.clean_name(x.name)

    def album_artists(self, artist_data):
        """Return individual artist names for the albumartists multi-value tag.

        When use_anv=True (default) prefers the Artist Name Variation — the
        name as credited on the physical release sleeve.
        """
        artists = []
        for x in artist_data:
            if isinstance(x, str):
                continue
            try:
                artists.append(self._artist_name(x))
            except AttributeError:
                pass
        return artists

    def album_artist_display(self, artist_data):
        """Build the full display string for the albumartist tag and format vars.

        Uses the Discogs join field ('Feat.', '&', 'vs.', …) when present.
        Returns empty string when Discogs provides no join between multiple
        artists — the caller (TaggerUtils) then applies the configured
        join_artists separator or falls back to the first artist name alone.

        Debug-level logs show the raw name/join/anv from Discogs so join
        field problems can be diagnosed.
        """
        parts = []  # list of (clean_name, join_after)

        for x in artist_data:
            if isinstance(x, str):
                # Legacy inline-string format: [Artist, "Feat.", Artist]
                if parts:
                    name, _ = parts[-1]
                    parts[-1] = (name, x.strip())
                continue
            try:
                name = self._artist_name(x)
            except AttributeError:
                continue
            raw_join = x.data.get('join', '').strip() if hasattr(x, 'data') else ''
            logger.debug("album-artist raw: name=%r join=%r anv=%r",
                         name, raw_join, x.data.get('anv', '') if hasattr(x, 'data') else '')
            parts.append((name, raw_join))

        if not parts:
            return ''
        if len(parts) == 1:
            return parts[0][0]

        # Combine only when at least one meaningful join is present between artists
        meaningful = any(j and j != ',' for _, j in parts[:-1])
        if not meaningful:
            logger.debug("album-artist: Discogs provides no join text — "
                         "TaggerUtils will apply join_artists or use first artist")
            return ''

        result = parts[0][0]
        for i in range(1, len(parts)):
            _, join_before = parts[i - 1]
            sep = f' {join_before} ' if join_before and join_before != ',' else ' '
            result = result + sep + parts[i][0]

        logger.debug("album-artist display: %r", result)
        return result

    def artists(self, artist_data):
        """ obtain the artists (normalized using clean_name). this is specific for tracks, since tracks are handled
            differently from the album artists.
            here the "join" is taken into account as well....

        """
        artists = []
        last_artist = None
        join = None

        for x in artist_data:
#            logger.debug("x: %s" % vars(x))
#            logger.debug("join: %s" % x.data['join'])

            if isinstance(x, str):
                logger.debug("x: %s", x)
                if last_artist:
                    last_artist = last_artist + " " + x
                else:
                    last_artist = x
            else:
                display_name = self._artist_name(x)
                if last_artist is not None:
                    logger.debug("name: %s", x.name)
                    concatString = " "
                    if join is not None:
                        concatString = " " + join + " "

                    last_artist = last_artist + concatString + display_name
                    artists.append(last_artist)
                    last_artist = None
                else:
                    join = x.data['join'] if hasattr(x, 'data') else ''
                    last_artist = display_name

            logger.debug("last_artist: %s", last_artist)

        if last_artist is not None:
            artists.append(last_artist)

        return artists

    def sort_artist(self, artist_data):
        """ Obtain a clean sort artist """
        return self.clean_duplicate_handling(artist_data[0].name)

    def disc_and_track_no(self, position):
        """Obtain the disc and track number from a Discogs track position string.

        Handles several numbering schemes:
          CD01-12 / 1-02    — hyphen-separated numeric (multi-disc CDs)
          CD1-13a / 1-13a   — hyphen-separated with a lettered sub-track suffix
                              (preserved so callers can merge 13a+13b+13c → 13)
          CD-12             — single CD with sequence number
          USB-Stick-n       — USB stick releases
          A1 / B3           — vinyl side-based (A=disc 1, B=disc 2, …)
          1.1 / 2.3         — dot-separated numeric (classical multi-disc)
          7                 — bare number (single disc, track 7)
        """
        if position.find("-") > -1:
            # Hyphen-separated schemes for multi-disc CDs and similar.
            NUMBERING_SCHEMES = (
                r"^CD(?P<discnumber>\d+)-(?P<tracknumber>\d+[a-z]?)$",    # CD01-12, CD1-13a
                r"^(?P<discnumber>\d+)-(?P<tracknumber>\d+[a-z]?)$",       # 1-02, 1-13a
                r"^(?P<discnumber>CD)-(?P<tracknumber>\d+[a-z]?)$",        # CD-12, CD-13a
                r"^(?P<discnumber>USB-Stick)-(?P<tracknumber>\d+[a-z]?)$", # USB-Stick-1
            )
            for scheme in NUMBERING_SCHEMES:
                m = re.search(scheme, position)
                if m:
                    return {'tracknumber': m.group('tracknumber'),
                            'discnumber': m.group('discnumber')}

        else:
            # Vinyl side-based: A1, B3, C2, … (each letter side = one disc slot).
            # Discogs uses A–H for up to 4-record sets; uppercase and lowercase
            # are both found in real data.
            # \d* (not \d+) so that letter-only positions like 'A' also match —
            # some releases have a single track per side with no track number.
            m = re.match(r'^(?P<side>[A-Ha-h])(?P<tracknumber>\d*)$', position)
            if m:
                side_letter = m.group('side').upper()
                track_digits = m.group('tracknumber')
                # Pair sides onto physical records: A+B = record 1, C+D = record 2, …
                # This means a single LP (sides A+B) gets disctotal=1, a double LP
                # (sides A+B+C+D) gets disctotal=2 — matching the physical disc count.
                discnumber = (ord(side_letter) - ord('A')) // 2 + 1
                # Return the full position string ('A', 'A1', 'B3', …) as the track
                # number so that %tracknumber% in format strings produces the original
                # vinyl label rather than a bare integer.
                return {'tracknumber': side_letter + track_digits,
                        'discnumber': discnumber}

            # Dot-separated numeric: 1.1, 2.3 (classical / some box sets).
            # Caveat: hidden-track notation (9.1 mixed with bare 1–8) would
            # assign those tracks to disc 9; prefer per-disc subdirectories
            # for releases that mix bare and dot-notation positions.
            m = re.match(r'^(?P<discnumber>\d+)\.(?P<tracknumber>\d+)$', position)
            if m:
                return {'tracknumber': m.group('tracknumber'),
                        'discnumber': m.group('discnumber')}

            # Default: single-disc, bare track number or position string.
            return {'tracknumber': position, 'discnumber': 1}

        logger.error("Unable to match multi-disc track/position for %r", position)
        return False

    @property
    def is_compilation(self):
        if self.release.data["artists"][0]["name"] == "Various":
            return True

        for format in self.release.data["formats"]:
            if "descriptions" in format:
                for description in (format["descriptions"] or []):
                    if description == "Compilation":
                        return True

        return False

    def _classify_headings(self):
        """Pre-scan the tracklist and return a list of (entry_type, title, role) tuples.

        Each heading is classified as either:
          'boundary' — the heading precedes the first track of a new disc; it
                       is the title for that disc
          'section'  — the heading precedes tracks on the *same* disc as the
                       preceding tracks; it is a sub-section label (e.g.
                       "Bonus Tracks") and should be concatenated with the
                       enclosing boundary heading

        Classification is exact: compare the disc number of the last track
        before the heading with the disc number of the first track after it.
        No hard-coded label lists are required.
        """
        exclude = ('Video', 'video', 'DVD')

        def _disc_of(pos, subs):
            """Return the disc number for a track given its position or sub_tracks."""
            if pos and not pos.startswith(exclude):
                for scheme in (
                    r'^CD(?P<d>\d+)-',
                    r'^(?P<d>\d+)-',
                ):
                    m = re.match(scheme, pos)
                    if m:
                        return int(m.group('d'))
            # Pattern A index: use first sub_track position
            for s in subs:
                if s.get('type_') == 'track' and s.get('position', ''):
                    return _disc_of(s['position'], [])
            return None

        # Build a flat list of (is_heading, title, disc_num)
        flat = []
        for t in self.release.tracklist:
            _type = t.data.get('type_', 'track') if hasattr(t, 'data') else getattr(t, 'type_', 'track')
            subs = t.data.get('sub_tracks', []) if hasattr(t, 'data') else []
            real_subs = [s for s in subs if s.get('type_') == 'track']
            pos = t.position or ''
            dur = t.duration or ''

            if _type == 'heading' or (not pos and not dur and not real_subs):
                flat.append(('heading', t.title.strip(), None))
            else:
                dn = _disc_of(pos, real_subs)
                if dn is not None and not pos.startswith(exclude):
                    flat.append(('track', t.title.strip(), dn))

        # Classify each heading by comparing disc numbers on either side
        classified = []  # (title, role)  role = 'boundary' | 'section'
        last_track_disc = None
        for i, (typ, title, dn) in enumerate(flat):
            if typ == 'track':
                last_track_disc = dn
                continue
            next_disc = next((e[2] for e in flat[i + 1:] if e[0] == 'track'), None)
            role = 'boundary' if (next_disc is not None and next_disc != last_track_disc) else 'section'
            classified.append((title, role))

        return classified

    def discs_and_tracks(self, album):
        """ provides the tracklist of the given release id
        """
        disc_list = []
        track_list = []

        # Pre-classify headings so we know which are disc boundaries and which
        # are section labels — determined exactly by lookahead, no heuristics.
        heading_roles = iter(self._classify_headings())

        last_boundary_heading = None  # most recent disc-boundary heading
        current_combined = None       # effective subtitle for the current section
        disccount= 1
        disc = Disc(1)
        running_num = 0

        for i, t in enumerate(x for x in self.release.tracklist):

            if t.position is None:
                logger.error("position is null, shouldn't be...")

            if is_non_audio_position(t.position):
                continue

            _type = t.data.get('type_', 'track') if hasattr(t, 'data') else getattr(t, 'type_', 'track')
            sub_tracks_data = t.data.get('sub_tracks', []) if hasattr(t, 'data') else []
            real_subs = [s for s in sub_tracks_data if s.get('type_', '') == 'track']

            # ── Structural / heading entries ──────────────────────────────────
            def _record_heading(title):
                nonlocal last_boundary_heading, current_combined
                role_title, role = next(heading_roles, (title, 'section'))
                if role == 'boundary':
                    last_boundary_heading = title
                    current_combined = title
                else:
                    # Section label: concatenate with the enclosing boundary
                    # heading so the subtitle reads "Album: Bonus Tracks".
                    current_combined = (
                        f'{last_boundary_heading}: {title}'
                        if last_boundary_heading else title
                    )

            if _type == 'heading':
                _record_heading(t.title.strip())
                continue

            # Entries with no position, no duration, and no useful sub_tracks
            # are disc-section labels (e.g. "Bonus Tracks").
            if not t.position and not t.duration and not real_subs:
                _record_heading(t.title.strip())
                continue

            # ── Pattern A: index entry whose sub_tracks are separate files ────
            # Identified by: type=index, no parent duration, sub_tracks each
            # have their own duration and explicit positions.
            # Example: "Continuous Mix" → 8 individual songs, each ripped separately.
            if _type == 'index' and real_subs and not t.duration and \
                    all(s.get('duration', '') for s in real_subs):
                logger.debug('Pattern A: expanding %d sub_tracks of %r as separate files',
                             len(real_subs), t.title)
                for sub in real_subs:
                    sub_pos = sub.get('position', '')
                    running_num += 1
                    track = Track(i + 1, sub.get('title', '').strip(), album.artists)
                    track._artist_display = album.artist
                    track.position = i
                    pos = self.disc_and_track_no(sub_pos) if sub_pos else False
                    self._assign_disc_and_track(track, pos, disc, disc_list,
                                                disccount, running_num)
                    if track.discnumber != disc.discnumber:
                        disc_list.append(disc)
                        disc = Disc(track.discnumber)
                        running_num = 1
                        disccount += 1
                    track.tracknumber = running_num
                    track.real_tracknumber = (pos['tracknumber'] if pos and pos.get('tracknumber') else str(running_num))
                    if current_combined:
                        track.discsubtitle = current_combined
                    if not disc.discsubtitle and current_combined:
                        disc.discsubtitle = current_combined
                    track.sort_artist = album.sort_artist
                    disc.tracks.append(track)
                continue

            # ── Pattern B: index entry that is one file containing sub-movements ─
            # Identified by: type=index, has a parent duration, sub_tracks lack
            # individual durations (they are CD index markers, not separate files).
            # Example: "Mighty Mix (Part 1)" with 4 named movements 9a–9d.
            # Treated as a single track; movements stored in the comments tag.
            if _type == 'index' and real_subs and t.duration and \
                    not any(s.get('duration', '') for s in real_subs):
                logger.debug('Pattern B: collapsing %d sub-movements of %r into one track',
                             len(real_subs), t.title)
                # Fall through to normal track creation; sub_track notes handled below.

            # ── Bare entries with no position (older Discogs style) ───────────
            # Entries with title+no-position+no-duration and no sub_tracks were
            # already caught above.  Those with sub_tracks reach here as Pattern B.
            # Any remaining no-position entry with no duration: skip.
            elif not t.position and not t.duration:
                discsubtitle.append(t.title.strip())
                continue

            # ── Normal track / Pattern B: create one Track object ─────────────
            running_num += 1
            if t.artists:
                artists = self.artists(t.artists)
                sort_artist = self.sort_artist(t.artists)
                track = Track(i + 1, t.title.strip(), artists)
            else:
                artists = album.artists
                sort_artist = album.sort_artist
                track = Track(i + 1, t.title.strip(), artists)
                track._artist_display = album.artist

            # Sub-track movements → notes/comments (Pattern B and any normal
            # tracks that Discogs stores with sub_track detail).
            if sub_tracks_data:
                comments = []
                for subtrack in sub_tracks_data:
                    if subtrack.get('type_') == 'track':
                        comment = subtrack['position'].strip() + '. ' + subtrack['title'].strip()
                        if subtrack.get('duration', ''):
                            comment += ' (' + subtrack['duration'].strip() + ')'
                        comments.append(comment)
                if comments:
                    setattr(track, 'notes', '\r\n'.join(comments))

            # Track-level extra artist credits (composer, conductor, etc.)
            track.extraartists = (t.data.get('extraartists', [])
                                  if hasattr(t, 'data') else [])

            track.position = i

            # For Pattern B (empty position), stay on the current disc.
            if not t.position and _type == 'index':
                pos = {'discnumber': str(disc.discnumber), 'tracknumber': str(running_num)}
            else:
                pos = self.disc_and_track_no(t.position)

            try:
                if re.match(r'^\d+$', str(pos["discnumber"])):
                    track.discnumber = int(pos["discnumber"])
                elif disc.mediatype != pos["discnumber"]:
                    track.discnumber = disccount if len(disc_list) == 0 else disccount + 1
                    track.mediatype = pos["discnumber"]
                else:
                    track.discnumber = disccount
                    track.mediatype = disc.mediatype
            except (ValueError, TypeError):
                if pos is False:
                    track.discnumber = disc.discnumber
                else:
                    msg = "cannot convert {0} to a valid track-/discnumber".format(t.position)
                    logger.error(msg)
                    raise AlbumError(msg)

            if track.discnumber != disc.discnumber:
                disc_list.append(disc)
                disc = Disc(track.discnumber)
                running_num = 1
                disccount += 1
                if track.mediatype is not None:
                    disc.mediatype = track.mediatype

            track.real_tracknumber = pos["tracknumber"] if pos and pos.get("tracknumber") else str(running_num)
            track.tracknumber = running_num

            # track.discsubtitle reflects the current section (changes mid-disc).
            # e.g. tracks 1-10 get "Sophisticated Boom Boom",
            #      tracks 11-15 get "Sophisticated Boom Boom: Bonus Tracks".
            if current_combined:
                track.discsubtitle = current_combined

            # disc.discsubtitle is set once per disc (used for folder naming).
            # It captures the combined heading at the moment the disc's first
            # track is encountered, so bonus discs read "Album: Bonus Tracks"
            # rather than just "Bonus Tracks".
            if not disc.discsubtitle and current_combined:
                disc.discsubtitle = current_combined
                logger.debug("discsubtitle: %s", disc.discsubtitle)

            track.sort_artist = sort_artist
            disc.tracks.append(track)
        disc_list.append(disc)
        return disc_list

    def _assign_disc_and_track(self, track, pos, disc, disc_list, disccount, running_num):
        """Set track.discnumber from a parsed position dict (or False)."""
        try:
            if pos and re.match(r'^\d+$', str(pos.get('discnumber', ''))):
                track.discnumber = int(pos['discnumber'])
            elif pos and disc.mediatype != pos.get('discnumber'):
                track.discnumber = disccount if len(disc_list) == 0 else disccount + 1
                track.mediatype = pos.get('discnumber')
            else:
                track.discnumber = disc.discnumber
        except (ValueError, TypeError):
            track.discnumber = disc.discnumber

    def remove_duplicate_items(self, duplicates_list):
        """Remove duplicates while preserving insertion order."""
        return list(dict.fromkeys(duplicates_list))

    def clean_duplicate_handling(self, clean_target):
        """Remove Discogs disambiguation suffix, e.g. 'Goldie (12)' → 'Goldie'."""
        return strip_discogs_id_suffix(clean_target)

    _THE_SUFFIX_RE = re.compile(r"(.*),\sThe$")

    def clean_name(self, clean_target):
        """Clean a Discogs artist or label name.

        Strips disambiguation suffixes ('Goldie (12)' → 'Goldie') and
        normalises 'Artist, The' → 'The Artist'.
        """
        clean_target = self.clean_duplicate_handling(clean_target)
        return self._THE_SUFFIX_RE.sub(r"The \g<1>", clean_target)

