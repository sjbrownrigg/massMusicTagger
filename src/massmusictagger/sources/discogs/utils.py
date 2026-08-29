"""Shared constants and small utilities used across the discogstagger package."""
import re

# Discogs role strings that map to the 'composer' tag.
# Matched case-insensitively after stripping parenthetical notes.
COMPOSER_ROLES = frozenset({
    'composed by', 'music by', 'written-by', 'written by',
    'composer', 'music, words by', 'music and lyrics by', 'music & lyrics by',
    'music by, words by',
})

# Discogs role strings that map to the 'lyricist' tag.
LYRICIST_ROLES = frozenset({
    'lyrics by', 'words by', 'lyricist', 'text by',
})

_ROLE_SUFFIX_RE = re.compile(r'\s*[\[\(].*?[\]\)]\s*')

# Position prefixes that indicate a non-audio disc type (DVD, Blu-ray, VHS …).
# Used by build_flat_tracklist() and is_non_audio_position().
_NON_AUDIO_PREFIXES = frozenset({
    'dvd', 'bd', 'blu-ray', 'bluray', 'vhs', 'umd', 'video',
})


def is_non_audio_position(pos: str) -> bool:
    """Return True when a Discogs track position indicates a non-audio disc.

    Matches positions like 'DVD-1', 'DVD1-3', 'BD-3', 'VHS-2', 'Video-1'
    against a known set of non-audio medium prefixes.  Bare labels ('DVD')
    and disc-numbered variants ('DVD1', 'DVD2-5') are all matched.
    Unknown or empty positions return False so they are always included
    rather than silently dropped.
    """
    if not pos:
        return False
    p = pos.lower()
    for prefix in _NON_AUDIO_PREFIXES:
        if p == prefix:
            return True
        if not p.startswith(prefix):
            continue
        # prefix must be followed by a separator or disc digit, not another letter
        rest = p[len(prefix):]
        if rest and (rest[0] in '-_ ' or rest[0].isdigit()):
            return True
    return False

def natural_sort_key(s: str) -> list:
    """Sort key treating numeric substrings numerically rather than lexicographically.

    Ensures multi-disc directories like 'Disc 2' sort before 'Disc 10'.
    Use as the ``key`` argument to ``list.sort()`` or ``sorted()``.
    """
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r'(\d+)', s)]


# All audio extensions recognised for directory discovery.
# A directory containing any of these triggers inclusion in the scan.
AUDIO_EXTENSIONS = ('.flac', '.mp3', '.ogg', '.ape', '.wav', '.wv', '.m4a')

# Subset of AUDIO_EXTENSIONS that can be tagged in place.
# Formats NOT in this set (currently .wav) must be converted to a taggable
# format first — writing tags to them is either unsupported or unreliable
# (e.g. WAV ID3 chunks are ignored by most media players).
TAGGABLE_EXTENSIONS = ('.flac', '.mp3', '.ogg', '.ape', '.wv', '.m4a')

# Artist name variants that indicate a Various-Artists compilation.
VARIOUS_ARTIST_NAMES = frozenset({'various', 'various artists', 'va'})


def ignored_source_dirs(cfg) -> frozenset:
    """Directory names that hold stashed originals and must never be treated
    as track sources, disc subdirectories, or copied to the tagged output.

    Currently: cue.cue_done_dir (stashed .cue/image files) and
    m4a.m4a_done_dir (stashed original .m4a files after conversion).
    """
    return frozenset({
        cfg.get('cue', 'cue_done_dir'),
        cfg.get('m4a', 'm4a_done_dir'),
    })

_DISCOGS_ID_SUFFIX_RE = re.compile(r'\s*\(\d+\)\s*$')

# Detects lettered sub-track positions: '13a', '13b', 'A1a', '1-13a'.
# Captures the numeric parent ('13', 'A1', '1-13') and the letter suffix ('a').
# Does NOT match bare positions like 'A1', '13', '1-02'.
_SUBTRACK_RE = re.compile(r'^(.*?\d+)([a-z])$')


def _sum_durations(durations: list) -> 'str | None':
    """Sum a list of Discogs 'mm:ss' / 'h:mm:ss' duration strings.

    Returns the total as 'mm:ss' or 'h:mm:ss', or None if any input is
    missing or unparseable (so callers can treat the merged duration as
    unknown rather than silently wrong).
    """
    total = 0
    for d in durations:
        if not d:
            return None
        try:
            parts = [int(x) for x in str(d).split(':')]
            while len(parts) < 3:
                parts.insert(0, 0)
            total += parts[0] * 3600 + parts[1] * 60 + parts[2]
        except (ValueError, AttributeError):
            return None
    m, s = divmod(total, 60)
    h, m = divmod(m, 60)
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'


def combine_subtrack_titles(titles: list, max_length: int = 100) -> 'tuple[str, str | None]':
    """Combine sub-track titles collapsed by a merge into one title string.

    Joins non-empty titles with ' / ' (e.g. 'Corrupt / (silence) / Untitled').
    If the combined string would exceed max_length, falls back to the first
    title alone and returns the rest joined as a second string, for the
    caller to store separately (e.g. appended to track notes/comments)
    rather than bloating the title tag or generated filename.

    Returns (title, extra_or_None).
    """
    cleaned = [t.strip() for t in titles if t and t.strip()]
    if not cleaned:
        return '', None
    combined = ' / '.join(cleaned)
    if len(cleaned) == 1 or len(combined) <= max_length:
        return combined, None
    return cleaned[0], ' / '.join(cleaned[1:])


def group_by_subtrack_position(items: list, position_of) -> 'list[tuple[str, list]] | None':
    """Group items into runs sharing a lettered sub-track parent position.

    position_of(item) -> str extracts the Discogs position string from each
    item (a flat-tracklist dict, a Track object, or any other shape callers
    use). Items whose position matches a {parent}{letter} pattern (e.g.
    '13a', 'CD1-13b', 'A1c') are grouped by their shared parent; everything
    else is its own singleton group. Order is preserved.

    Shared by merge_indexed_subtracks() (flat dicts, for search matching) and
    taggerutils._merge_indexed_disc_sub_tracks() (Track objects, for tagging)
    so the grouping rule only needs to be defined once.

    Returns None if no group has more than one member (nothing to merge),
    otherwise the list of (group_key, [items]) pairs — group_key is
    'sub:{parent}' for mergeable groups, 'trk:{position}' for singletons.
    """
    groups: list[tuple[str, list]] = []
    key_map: dict[str, int] = {}

    for item in items:
        pos = position_of(item)
        m = _SUBTRACK_RE.match(pos)
        parent = m.group(1) if m else None
        group_key = f'sub:{parent}' if parent else f'trk:{pos}'

        if group_key not in key_map:
            key_map[group_key] = len(groups)
            groups.append((group_key, []))
        groups[key_map[group_key]][1].append(item)

    if not any(key.startswith('sub:') and len(entries) > 1
               for key, entries in groups):
        return None
    return groups


def merge_indexed_subtracks(flat_list: list) -> 'list | None':
    """Merge consecutive lettered sub-track positions into single entries.

    Detects runs of tracks like ('13a', '13b', '13c') — positions that share
    a numeric base with only a single lowercase-letter suffix — and collapses
    each group into one entry by summing durations and joining titles with
    ' / ' (e.g. 'Corrupt / (silence) / Untitled').

    This handles Discogs user-data errors where a single-file track has been
    entered as separate lettered type='track' positions without any parent
    index entry.  It is intentionally a fallback: only called when the normal
    track-count check has already failed.

    Returns a new list if any groups were merged, or None if no mergeable
    groups were found (so callers can detect the no-op case cheaply).
    """
    groups = group_by_subtrack_position(flat_list, lambda e: e.get('position', ''))
    if groups is None:
        return None

    result = []
    for key, entries in groups:
        if key.startswith('sub:') and len(entries) > 1:
            title, _extra = combine_subtrack_titles([e.get('title', '') for e in entries])
            result.append({
                'position': key[4:],  # strip 'sub:'
                'title':    title,
                'duration': _sum_durations([e.get('duration') for e in entries]),
            })
        else:
            result.extend(entries)
    return result


def build_flat_tracklist(tracklist, skip_non_audio: bool = True,
                         expand_ambiguous_index: bool = False) -> list:
    """Flatten a Discogs tracklist into one dict per physical file.

    Applies the same Pattern A / Pattern B logic used by DiscogsAlbum when
    building the disc/track model for tagging, so that search matching sees
    exactly the same track count and durations as the tagger expects.

    Pattern A — index entry whose sub_tracks each have an individual duration
        (e.g. a continuous-mix section whose songs were ripped separately).
        Expanded: each sub_track becomes its own entry.

    Pattern B — index entry with a parent duration whose sub_tracks lack
        individual durations (e.g. "Mighty Mix (Part 1)" covering four
        named movements in a single file).
        Collapsed: one entry using the parent title and duration.

    Anything else -- a parent duration *and* timed sub_tracks, or neither --
    is genuinely ambiguous. Across 23,102 cached releases those are 12% of
    index entries (85 of 711), and nothing in the Discogs data settles them:
    the parent position is empty for every index entry, so it cannot be used
    as a signal, and where both durations exist the sub-tracks usually sum to
    the parent exactly, which is true of one file or several.

    So this does not guess. By default an ambiguous entry collapses, as it
    always has; with expand_ambiguous_index=True it becomes one entry per
    sub_track. Callers that know the local file count try the second reading
    when the first does not match, the same way merge_indexed_subtracks() is
    used. All 85 carry a position and a title on every sub_track, so the
    expansion is always well-formed.

    All other headings, bare structural labels and Video/DVD entries are
    skipped.

    Args:
        tracklist: iterable of track objects from python3-discogs-client.
                   Each item exposes .position, .title, .duration and a
                   .data dict containing 'type_' and 'sub_tracks'.

    Returns:
        List of dicts: {'position': str, 'title': str, 'duration': str|None}
    """
    result = []

    for t in tracklist:
        _type = (t.data.get('type_', 'track')
                 if hasattr(t, 'data') else getattr(t, 'type_', 'track'))
        pos   = (t.position or '') if hasattr(t, 'position') else ''
        dur   = (t.duration or '') if hasattr(t, 'duration') else ''
        title = (t.title   or '') if hasattr(t, 'title')    else ''
        subs  = (t.data.get('sub_tracks', [])
                 if hasattr(t, 'data') else [])
        real_subs = [s for s in subs if s.get('type_', '') == 'track']

        # ── Skip structural entries ───────────────────────────────────────
        if _type == 'heading':
            continue
        if skip_non_audio and is_non_audio_position(pos):
            continue

        # ── Pattern A: index container → expand sub_tracks ───────────────
        # Each sub_track is a separately ripped file (they have individual
        # durations).  Only applied when sub_track data is present (full
        # release).  When sub_tracks are absent (lightweight version from
        # master.versions), the entry falls through to single-entry fallback.
        if (_type == 'index' and real_subs and not dur
                and all(s.get('duration', '') for s in real_subs)):
            for sub in real_subs:
                sub_dur = sub.get('duration', '')
                result.append({
                    'position': sub.get('position', ''),
                    'title':    sub.get('title', ''),
                    'duration': sub_dur if sub_dur else None,
                })
            continue

        # ── Pattern B: index with parent duration → single file ───────────
        # The sub_tracks are movements within one file (no individual
        # durations).  Only applied when sub_track data is present.
        if (_type == 'index' and real_subs and dur
                and not any(s.get('duration', '') for s in real_subs)):
            result.append({
                'position': pos,
                'title':    title,
                'duration': dur,
            })
            continue

        # ── Ambiguous index: neither pattern fits ─────────────────────────
        # Collapsing is what has always happened here, by falling through to
        # the normal-track branch below. It is now explicit, so the other
        # reading can be asked for.
        if _type == 'index' and real_subs and expand_ambiguous_index:
            for sub in real_subs:
                sub_dur = (sub.get('duration', '') or '').strip()
                result.append({
                    'position': sub.get('position', ''),
                    'title':    sub.get('title', ''),
                    'duration': sub_dur if sub_dur else None,
                })
            continue

        # ── Normal track ──────────────────────────────────────────────────
        result.append({
            'position': pos,
            'title':    title,
            'duration': dur if dur else None,
        })

    return result


def prefers_expanded_index(tracklist, local_count, skip_non_audio: bool = True) -> bool:
    """Is "separate files" the reading that matches what is on disk?

    The one place this decision is made. The search uses it to accept a
    release it would otherwise reject, the ID validation uses it to avoid a
    spurious mismatch warning, and the mapper uses it to build the same
    tracks the search was scored on -- three places that must agree, because
    a release accepted under one reading and tagged under the other produces
    a track list that does not match the files.

    False whenever the collapsed reading already matches, so the default is
    never overturned by a coincidence.
    """
    if local_count is None:
        return False
    if not has_ambiguous_index(tracklist):
        return False
    collapsed = build_flat_tracklist(tracklist, skip_non_audio)
    if len(collapsed) == local_count:
        return False
    expanded = build_flat_tracklist(tracklist, skip_non_audio,
                                    expand_ambiguous_index=True)
    return len(expanded) == local_count


def has_ambiguous_index(tracklist) -> bool:
    """Would expand_ambiguous_index change anything for this tracklist?

    Lets callers skip the second flatten when there is nothing to reinterpret,
    which is the overwhelming majority of releases.
    """
    for t in tracklist:
        _type = (t.data.get('type_', 'track')
                 if hasattr(t, 'data') else getattr(t, 'type_', 'track'))
        if _type != 'index':
            continue
        subs = (t.data.get('sub_tracks', []) if hasattr(t, 'data') else [])
        real_subs = [s for s in subs if s.get('type_', '') == 'track']
        if not real_subs:
            continue
        dur = (t.duration or '') if hasattr(t, 'duration') else ''
        timed = sum(1 for s in real_subs if (s.get('duration', '') or '').strip())
        if (dur and timed == len(real_subs)) or (not dur and timed == 0):
            return True
    return False


def strip_discogs_id_suffix(name: str) -> str:
    """Remove a Discogs disambiguation suffix from an artist or label name.

    Discogs appends a parenthesised integer to distinguish artists who share
    a name, e.g. 'Goldie (12)' or 'Various (1)'.  This strips that suffix so
    the bare name can be used for matching and display.
    """
    return _DISCOGS_ID_SUFFIX_RE.sub('', name).strip()


# A token mixing letters and digits is the signature of a catalogue/format
# code (e.g. 'XLCDBong24', 'CDBong14X') — genuine title suffixes like
# 'Deluxe Edition' or '2009 Remaster' never have one.
_CATALOG_TOKEN_RE = re.compile(r'^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9\-]{4,}$')
_TRAILING_PAREN_RE = re.compile(r'\s*\(([^()]*)\)\s*$')


def strip_catalog_suffix(title: str) -> str:
    """Strip a trailing parenthetical catalog/format suffix from a title.

    Some embedded tags fold the catalog number into the album title itself
    (e.g. 'In Your Room (Maxi XLCDBong24)') — almost certainly written there
    by whatever tool originally tagged the file, since Discogs release
    titles never include this. Searching Discogs for the literal title then
    returns zero results.  A trailing '(...)' group is removed only when it
    contains a token mixing letters and digits — the catalog-number
    signature — so legitimate suffixes ('Deluxe Edition', '2009 Remaster')
    are left untouched. This only affects the search query, never the
    tagged output (which is built from the matched Discogs release data).
    """
    result = title
    while True:
        m = _TRAILING_PAREN_RE.search(result)
        if not m:
            break
        tokens = m.group(1).split()
        if not any(_CATALOG_TOKEN_RE.match(t) for t in tokens):
            break
        result = result[:m.start()].rstrip()
    return result


def normalize_catalog_number(catno: str) -> str:
    """Normalise a catalog number for comparison across formatting styles.

    A given catalog number shows up differently depending on where it's
    written: Discogs lists 'XLCD BONG 24' (spaced) while an embedded tag
    might fold it into 'XLCDBong24' (no spaces, mixed case). Stripping
    whitespace/hyphens and lowercasing makes both 'xlcdbong24' so they can
    be compared with a plain equality check.
    """
    return re.sub(r'[\s\-]', '', catno or '').lower()


def extract_catalog_hint(title: str) -> 'str | None':
    """Extract a normalised catalog-number hint from a title's trailing
    parenthetical group — the same group strip_catalog_suffix() removes.

    Used to disambiguate between several Discogs releases that otherwise
    match equally well (identical track count and near-identical durations
    are common across regional/format reissues of the same single/album).
    When the embedded tag happens to fold the catalog number into the title,
    that's a strong, free signal for picking the exact pressing — e.g.
    'In Your Room (Maxi XLCDBong24)' should prefer the Discogs release whose
    catalog number normalises to 'xlcdbong24' over others with identical
    durations but unrelated catalog numbers.

    Returns None if no catalog-like token is found in the trailing group.
    """
    m = _TRAILING_PAREN_RE.search(title)
    if not m:
        return None
    catalog_tokens = [t for t in m.group(1).split() if _CATALOG_TOKEN_RE.match(t)]
    if not catalog_tokens:
        return None
    return normalize_catalog_number(catalog_tokens[-1])


def parse_extraartists(extraartists_data: list) -> dict:
    """Extract role-grouped names from a Discogs extraartists list.

    Each item in extraartists_data is expected to be a dict with at least
    'name', 'anv', and 'role' keys (as returned by the Discogs API).

    Returns a dict:
        {
          'composers': [str, ...],   # 'Composed By', 'Written-By', etc.
          'lyricists': [str, ...],   # 'Lyrics By', 'Words By', etc.
        }

    The ANV (Artist Name Variation) is preferred over the canonical name when
    present.  Role strings are matched case-insensitively after stripping any
    parenthetical or bracketed qualifier (e.g. 'Composed By [Tracks 1-3]'
    → 'composed by').
    """
    result: dict = {'composers': [], 'lyricists': []}
    for ea in (extraartists_data or []):
        anv = (ea.get('anv') or '').strip()
        name = anv or (ea.get('name') or '').strip()
        if not name:
            continue
        role_raw = ea.get('role') or ''
        # Strip bracketed/parenthetical qualifiers: "Composed By [Tracks 1-3]" → "Composed By"
        role = _ROLE_SUFFIX_RE.sub('', role_raw).strip().rstrip(',').strip().lower()
        if role in COMPOSER_ROLES:
            result['composers'].append(name)
        elif role in LYRICIST_ROLES:
            result['lyricists'].append(name)
    return result
