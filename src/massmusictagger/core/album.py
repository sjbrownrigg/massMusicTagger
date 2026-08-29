def first_of(lst, default=None):
    """Return lst[0] if the list is non-empty, otherwise default."""
    return lst[0] if lst else default


class BaseObject(object):
    pass


class Track(BaseObject):
    """ A disc contains several tracks, each track has a tracknumber,
        a title, an artist """

    def __init__(self, tracknumber, title, artists):
        self.tracknumber = tracknumber
        self.title = title
        self.artists = artists      # individual names, for artists multi-value tag
        self._artist_display = None # combined display string (e.g. 'A Feat. B')
        self.discsubtitle = None
        self.mediatype = None

    @property
    def artist(self):
        return self._artist_display or first_of(self.artists, '')

    def __getattr__(self, name):
        return None


class Disc(BaseObject):
    """ An album has one or more discs, each disc has a number and
        could have also a disctitle, furthermore several tracks
        are on each disc """

    def __init__(self, discnumber):
        self.discnumber = discnumber
        self.discsubtitle = None
        self.mediatype = None
        self.tracks = []
        self.filetype = None
        self.sourcedir = None   # set by TaggerUtils._get_target_list()
        self.target_dir = None  # set by TaggerUtils._set_target_discs_and_tracks()
        self.copy_files = []    # set by TaggerUtils._get_target_list()

    def track(self, trackno):
        return self.tracks[trackno - 1]


class Album(BaseObject):
    """ An album contains one or more discs and has a title, an artist
        (special case: Various), a source identifier (eg. discogs_id)
        and a catno """

    def __init__(self, identifier, title, artists):
        self.id = identifier
        self.artists = artists      # individual names, for albumartists tag
        self._artist_display = None # combined display string, set by DiscogsAlbum
        self.title = title
        self.discs = []
        self.fileformat = "flac"
        self.genres = []
        self.styles = []

    @property
    def has_multi_disc(self):
        return len(self.discs) > 1

    def disc(self, discno):
        return self.discs[discno - 1]

    @property
    def artist(self):
        return self._artist_display or first_of(self.artists, '')

    @property
    def genre(self):
        return first_of(self.genres, '')

    @property
    def style(self):
        return first_of(self.styles, '')

    def __getattr__(self, name):
        return None
