"""Discogs API connector and local-JSON connector.

Moved here from discogsalbum.py so the connector concerns are clearly
separated from the album-mapping concerns.  discogsalbum.py re-exports these
classes for backward compatibility.
"""
import json
import logging
import os

import requests
import discogs_client as discogs

from massmusictagger.core.cache import ReleaseCache, ImageCache, MasterVersionsCache, SearchCache

from massmusictagger import roots
from massmusictagger.config_schema import ConfigError

logger = logging.getLogger(__name__)


def _is_auth_failure(exc) -> bool:
    """Is this exception Discogs refusing the credential, rather than a network
    problem? Checked by status code where there is one, because the client
    raises the same HTTPError type for 401 and for 503."""
    for attr in ('status_code', 'code'):
        code = getattr(exc, attr, None)
        if code in (401, 403):
            return True
    if isinstance(exc, discogs.exceptions.AuthorizationError):
        return True
    return '401' in str(exc) or 'Invalid consumer token' in str(exc)


class DiscogsConnector(object):
    """Connects to the Discogs API.

    Authentication priority:
      1. user_token in config / DISCOGS_USER_TOKEN env var (personal access token — simplest)
      2. consumer_key + consumer_secret (OAuth 1.0a PIN flow — stores token in .token file)
      3. No auth — metadata only, image downloads unavailable

    Rate limiting is handled automatically by the discogs_client library (backoff_enabled=True).
    """

    def __init__(self, tagger_config):
        self.config = tagger_config
        self.user_agent = self.config.get("common", "user_agent")
        self.discogs_auth = False
        self.release_cache = {}
        self.tracklength_tolerance = self.config.getfloat("batch", "tracklength_tolerance")
        self.title_similarity_threshold = self.config.getfloat("batch", "title_similarity_threshold")
        self._user_token = None
        self._release_cache = None
        self._image_cache = None
        self._master_versions_cache = None
        self._master_years = {}   # master_id -> year, per run
        self._search_cache = None

        cache_dir = self.config.get("cache", "directory")
        if cache_dir:
            cache_dir = os.path.expanduser(cache_dir)
            self._release_cache = ReleaseCache(cache_dir)
            self._image_cache = ImageCache(cache_dir)
            self._master_versions_cache = MasterVersionsCache(cache_dir)
            self._search_cache = SearchCache(cache_dir)
            logger.info('Disk cache enabled at %s', cache_dir)

        user_token = os.environ.get('DISCOGS_USER_TOKEN') or self.config.get("discogs", "user_token")
        skip_auth = self.config.get("discogs", "skip_auth")

        if user_token:
            self.discogs_client = discogs.Client(self.user_agent, user_token=user_token)
            self._user_token = user_token
            self.discogs_auth = True
            self._verify_token()
        elif skip_auth != "True":
            self.discogs_client = discogs.Client(self.user_agent)
            self._init_oauth()
        else:
            self.discogs_client = discogs.Client(self.user_agent)
            logger.warning('Authentication disabled — image downloads will not work')

    def _verify_token(self):
        """A token that is present is not a token that works.

        Discogs issues one personal access token at a time per account, so
        generating one for a second registered application silently
        invalidates the first. This used to log "Authenticated via personal
        access token" on the strength of the string being non-empty, and the
        only symptom of a dead token was that lookups quietly stopped finding
        anything -- which, with the disk cache warm, an entire run could hide.

        A rejected token is fatal and says which file to fix. A network
        failure is not: an offline run against a warm cache is legitimate.
        """
        try:
            identity = self.discogs_client.identity()
        except Exception as exc:
            if _is_auth_failure(exc):
                raise ConfigError(
                    'Discogs rejected the personal access token.\n'
                    '  Discogs issues one token at a time per account, so '
                    'generating a token for another\n'
                    '  application invalidates the previous one. Generate a '
                    'new token at\n'
                    '  https://www.discogs.com/settings/developers and set '
                    'DISCOGS_USER_TOKEN\n'
                    '  (or discogs.user_token in the configuration '
                    'directory).') from exc
            logger.warning('Could not reach Discogs to verify the token (%s) '
                           '— continuing; cached data will still be used', exc)
            return

        username = getattr(identity, 'username', None)
        logger.info('Authenticated with Discogs as %s',
                    username or 'an unnamed account')

    def _init_oauth(self):
        """Set up OAuth 1.0a using consumer key/secret from config or environment."""
        consumer_key = os.environ.get('DISCOGS_CONSUMER_KEY') or self.config.get("discogs", "consumer_key")
        consumer_secret = os.environ.get('DISCOGS_CONSUMER_SECRET') or self.config.get("discogs", "consumer_secret")

        if not (consumer_key and consumer_secret):
            logger.warning('No auth configured (no user_token, no consumer key/secret) — image downloads will not work')
            return

        self.discogs_client.set_consumer_key(consumer_key, consumer_secret)

        access_token, access_secret = self.read_token()
        if access_token and access_secret:
            self.discogs_client.set_token(access_token, access_secret)
            self.discogs_auth = True
            logger.info('Authenticated via cached OAuth token ({})'.format(self.construct_token_file()))
        else:
            self._run_oauth_pin_flow()

    def _run_oauth_pin_flow(self):
        """Interactive OAuth PIN flow — prompts user to visit a URL and enter a PIN."""
        try:
            request_token, request_token_secret, authorize_url = self.discogs_client.get_authorize_url()
            print('Visit this URL in your browser: ' + authorize_url)
            pin = input('Enter the PIN from the above URL: ').strip()
            access_token, access_secret = self.discogs_client.get_access_token(pin)
            token_file = self.construct_token_file()
            with open(token_file, 'w') as fh:
                fh.write('{},{}'.format(access_token, access_secret))
            self.discogs_auth = True
            logger.info('OAuth successful — token saved to {}'.format(token_file))
        except Exception as e:
            logger.error('OAuth flow failed: {}'.format(e))

    def read_token(self):
        """Read a cached OAuth token from the .token file."""
        token_file = self.construct_token_file()
        try:
            with open(token_file, 'r') as tf:
                parts = tf.read().split(',')
                if len(parts) == 2:
                    return parts[0].strip(), parts[1].strip()
        except (IOError, OSError):
            pass
        return None, None

    def construct_token_file(self):
        """Path to the cached OAuth token.

        Lives in the state root rather than the working directory, so the
        token survives being run from somewhere else and a container does not
        need a writable /app purely to hold it. Set DISCOGSTAGGER_STATE_DIR to
        place it on a mounted volume. An existing .token in the working
        directory is still honoured, with a warning.
        """
        return roots.state_path('.token')

    def fetch_release(self, release_id):
        rid = int(release_id)
        if self._release_cache:
            cached = self._release_cache.get(rid)
            if cached is not None:
                logger.info('Release %s loaded from cache', rid)
                return discogs.Release(self.discogs_client, cached)
        logger.info('Fetching release %s from Discogs', rid)
        return self.discogs_client.release(rid)

    def cache_release(self, release) -> None:
        """Write a fully-loaded release to the disk cache."""
        if self._release_cache and release is not None:
            self._release_cache.put(release.id, release.data)

    def fetch_master_year(self, master_id):
        """The original release year from a master, or None.

        A Discogs reissue often carries no year of its own -- 3,822 of the
        23,102 cached releases have none -- but 99.6% of those belong to a
        master that does. Without this the release is filed with no date at
        all, when Discogs plainly knows one.

        Fetching lives here rather than in the mapper so it is cached and so
        the mapper stays a pure transformation of data it was handed.
        """
        if not master_id:
            return None
        cached = self._master_years.get(master_id)
        if cached is not None:
            return cached or None
        try:
            master = self.discogs_client.master(int(master_id))
            # Read the attribute, not .data: the client is lazy, and .data on
            # an unfetched object is an empty stub that quietly yields None.
            # This is the same trap the release path hit in May.
            year = master.year
        except Exception as exc:
            logger.debug('Could not fetch master %s for its year: %s', master_id, exc)
            self._master_years[master_id] = ''
            return None
        year = str(year or '').strip()
        if not year.isdigit() or year in ('0', '0000'):
            year = ''
        self._master_years[master_id] = year
        logger.debug('Master %s year: %s', master_id, year or 'unknown')
        return year or None

    def fetch_image(self, image_dir, image_url):
        """Download a Discogs image, using the disk cache when available."""
        if not self.discogs_auth:
            logger.error('Not authenticated — cannot download image, skipping')
            return
        try:
            if self._image_cache:
                data = self._image_cache.get(image_url)
                if data is not None:
                    logger.info('Image loaded from cache: %s', image_url)
                    with open(image_dir, 'wb') as fh:
                        fh.write(data)
                    return

            headers = {'User-Agent': self.user_agent}
            params = {'token': self._user_token} if self._user_token else {}
            response = requests.get(image_url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.content
            with open(image_dir, 'wb') as fh:
                fh.write(data)
            if self._image_cache:
                self._image_cache.put(image_url, data)
        except Exception as e:
            logger.error("Unable to download image '%s': %s", image_url, e)


class DummyResponse(object):
    """Wraps a local release JSON file to stand in for a Discogs API response."""

    def __init__(self, release_id, json_path):
        self.releaseid = release_id
        json_file_name = f"{self.releaseid}.json"
        json_file_path = os.path.join(json_path, json_file_name)
        self.status_code = 200
        with open(json_file_path, 'r', encoding='utf-8') as json_file:
            self.content = json_file.read()


class LocalDiscogsConnector(object):
    """Serves release metadata from a local JSON file instead of the Discogs API.

    Delegates image downloads to a real DiscogsConnector so authentication
    is still used for artwork.
    """

    def __init__(self, delegate_discogs_connector):
        self.delegate = delegate_discogs_connector

    def fetch_release(self, release_id, source_dir):
        dummy_response = DummyResponse(release_id, source_dir)
        client = discogs.Client('Dummy Client - just for testing')
        self.content = self.convert(json.loads(dummy_response.content))
        logger.debug('content: %s', self.content)
        return discogs.Release(client, self.content)

    def authenticate(self):
        self.delegate.authenticate()

    def fetch_image(self, image_dir, image_url):
        self.delegate.fetch_image(image_dir, image_url)

    def updateRateLimits(self, request):
        self.delegate.updateRateLimits(request)

    def convert(self, input):
        if isinstance(input, dict):
            return {self.convert(key): self.convert(value) for key, value in input.items()}
        elif isinstance(input, list):
            return [self.convert(element) for element in input]
        else:
            return input
