import os
import re
import logging

from configparser import RawConfigParser, NoSectionError, NoOptionError

from massmusictagger import config_schema, roots

logger = logging.getLogger(__name__)

# Reference documentation only -- never loaded as a runtime baseline.
_SAMPLE_YAML     = os.path.join(roots.BUNDLED_CONF, "config_sample.yaml")
_DEFAULT_FORMATS = os.path.join(roots.BUNDLED_CONF, "formats_sample.ini")


class TaggerConfig(RawConfigParser):
    """Configuration for discogstagger3.

    Defaults come from config_schema.DEFAULTS -- a table in code -- not from
    a sample file loaded underneath the user's config.  conf/config_sample.yaml
    is reference documentation and is never read at runtime.

    Loading:
      1. config_file (YAML or INI) -- the sole source of user settings.
      2. formats_file from common.formats_file, resolved beside the config.
      3. Any key the config did not set takes its default from the schema.
      4. The result is validated: missing required keys raise ConfigError,
         unknown keys warn.

    A config_file that does not exist is an error.  It used to fall back to
    the bundled sample, which meant a typo in the path ran the tagger against
    settings the user had never seen.
    """

    # Preserve option key case so character_exceptions like 'Ö', 'Ä', 'Ü'
    # are stored distinctly from their lowercase equivalents.
    optionxform = str

    def __init__(self, config_file=None):
        # allow_no_value=True: suppress_tags entries can be bare keys
        # without a trailing '=', e.g. just "genres" instead of "genres ="
        RawConfigParser.__init__(self, strict=False, allow_no_value=True)

        # Base for paths this config file names (formats_file, templates_dir).
        # None when running off the bundled sample, in which case such paths
        # fall back to the working directory as they always did.
        self.config_root = roots.config_root(config_file) if config_file else None

        if not config_file:
            raise config_schema.ConfigError(
                "No configuration file given.\n"
                "  Pass one with -c <config.yaml>. Copy the annotated "
                f"reference at {_SAMPLE_YAML} and edit that copy.\n"
                "  Tagging renames and moves files, so it will not run "
                "against settings you have not reviewed."
            )

        if not os.path.exists(config_file):
            raise FileNotFoundError(
                f"Config file not found: {config_file!r}\n"
                f"  Check the path. Copy the annotated reference at "
                f"{_SAMPLE_YAML} if you do not have a config yet."
            )

        # Format strings always start from the bundled baseline: they are a
        # large body of defaults, and a user's formats file is expected to
        # override selectively rather than restate all of them.
        if os.path.exists(_DEFAULT_FORMATS):
            self.read(_DEFAULT_FORMATS)

        if _is_yaml(config_file):
            self._load_yaml(config_file)
            formats_file = self._resolve_formats_file(config_file)
            if formats_file:
                logger.debug('Loading formats file: %s', formats_file)
                self.read(formats_file)
        else:
            # INI config (legacy and test usage) -- a targeted override.
            self.read(config_file)

        defaulted = config_schema.apply_defaults(self)
        if defaulted:
            logger.debug('Defaults applied for %d unset keys: %s',
                         len(defaulted),
                         ', '.join(f'{s}.{k}' for s, k in defaulted))
        config_schema.validate(self, config_file)

    # ------------------------------------------------------------------

    def _resolve_formats_file(self, yaml_path: str) -> str | None:
        """Return the formats INI path to load after the user YAML.

        Reads common.formats_file from the loaded config.  Returns None when
        the key is absent or empty.  Raises FileNotFoundError if the key is
        set but the file does not exist.
        """
        resolved = self.resource('formats')
        if resolved and not os.path.exists(resolved):
            raise FileNotFoundError(
                f"formats file not found: {resolved!r}\n"
                f"  Put format strings in {roots.LAYOUT['formats']} beside "
                f"config.yaml, or leave it out to use the bundled defaults."
            )
        return resolved

    # Config keys that used to name these files. Discovery replaced them; they
    # still work so existing configs keep running, but they warn.
    _LEGACY_RESOURCE_KEYS = {
        'formats': ('common', 'formats_file'),
    }

    def resource(self, what):
        """Return the path to a configurable resource, or None for the default.

        Looked for at its fixed name inside the configuration directory -- see
        roots.LAYOUT. Nothing needs declaring in config.yaml; a file that is
        there is used, and one that is not falls through to the copy bundled
        in the package.

        The config key that used to name the file still wins if set, with a
        warning, so existing configurations keep working.
        """
        section_key = self._LEGACY_RESOURCE_KEYS.get(what)
        if section_key:
            section, key = section_key
            explicit = self.get(section, key)
            if explicit:
                resolved = self.resolve_path(explicit, f'{section}.{key}')
                logger.warning(
                    "%s.%s is deprecated and no longer needed: %s is found "
                    "automatically at %s inside the configuration directory. "
                    "Remove the setting, and move the file there if it is "
                    "somewhere else.",
                    section, key, what, roots.LAYOUT[what])
                return resolved

        return roots.discover(self.config_root, what)

    def resolve_path(self, value, key_name="path"):
        """Resolve a path read from this config file to an absolute path.

        Relative values resolve against the directory holding the config file,
        so a config and the files it names travel together. See
        massmusictagger.roots for the full rationale.
        """
        return roots.resolve_config_path(value, self.config_root, key_name)

    # ------------------------------------------------------------------

    def _load_yaml(self, yaml_path: str):
        """Load a YAML config file and inject its values into the parser.

        Each top-level YAML key becomes a section name.  Dict values become
        key=value pairs in that section.  List values (e.g. suppress_tags)
        become bare keys (allow_no_value).  Scalar top-level values are
        ignored (they have no INI equivalent).
        """
        if not yaml_path or not os.path.exists(yaml_path):
            return
        try:
            import yaml
        except ImportError:
            logger.warning(
                'pyyaml is not installed — YAML config files cannot be loaded. '
                'Run: pip install pyyaml'
            )
            return
        try:
            with open(yaml_path, encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning('Failed to load YAML config %s: %s', yaml_path, e)
            return

        for section, values in data.items():
            if not isinstance(values, (dict, list)):
                continue  # skip scalar top-level keys
            if not self.has_section(section):
                self.add_section(section)
            if isinstance(values, list):
                # suppress_tags: [genres, country, …]
                for item in values:
                    item_str = str(item).strip()
                    if item_str:
                        self.set(section, item_str, None)
            else:
                for key, val in values.items():
                    if val is None:
                        self.set(section, str(key), None)
                    else:
                        self.set(section, str(key), str(val))

    # ------------------------------------------------------------------

    def get(self, section, name, **kw):
        try:
            config_value = RawConfigParser.get(self, section, name.lower(), raw=True)
        except (NoSectionError, NoOptionError):
            return None
        if config_value is None or config_value == "":
            return None
        return config_value.strip()

    def items(self, section, **kw):
        return RawConfigParser.items(self, section, raw=True)

    @property
    def character_exceptions(self):
        """Character replacement map from [character_exceptions] section."""
        if "character_exceptions" not in self._sections:
            return {}
        exceptions = dict(self._sections["character_exceptions"])
        exceptions.pop("__name__", None)
        if "{space}" in exceptions:
            exceptions[" "] = exceptions.pop("{space}")
        return exceptions

    @property
    def configured_tags(self):
        """Tags explicitly set in the [tags] section."""
        if "tags" not in self._sections:
            return {}
        tags = dict(self._sections["tags"])
        tags.pop("__name__", None)
        return tags

    @property
    def suppressed_tags(self) -> set:
        """Set of MediaFile attribute names to suppress from file metadata.

        Keys listed under [suppress_tags] (bare keys, no value needed) are
        not written to file metadata during tagging.  The Discogs data for
        those fields is still available to format strings for naming.
        """
        if "suppress_tags" not in self._sections:
            return set()
        tags = dict(self._sections["suppress_tags"])
        tags.pop("__name__", None)
        return {k.strip().lower() for k in tags}


# -- Module helpers -----------------------------------------------------------

def _is_yaml(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in ('.yaml', '.yml')


def extract_sample_section(section: str, sample_path: str | None = None) -> str:
    """Return the raw text block for a top-level YAML section from the sample config.

    Includes comment lines so callers can print useful context in error messages
    when a required setting is absent.  Returns empty string if the section is
    not found or the file cannot be read.
    """
    import re
    path = sample_path or _SAMPLE_YAML
    if not os.path.exists(path):
        return ''
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            lines = fh.readlines()
    except OSError:
        return ''
    section_re = re.compile(r'^' + re.escape(section) + r'\s*:')
    toplevel_re = re.compile(r'^[a-z_][a-z_0-9]*\s*:')
    collecting = False
    result: list[str] = []
    for line in lines:
        if not collecting:
            if section_re.match(line):
                collecting = True
                result.append(line)
        else:
            if toplevel_re.match(line) and not section_re.match(line):
                break
            result.append(line)
            if len(result) >= 60:
                result.append('  ...\n')
                break
    return ''.join(result).rstrip()


# ── Scaffolding a fresh configuration ────────────────────────────────────────

# What --new-config writes. Rule tables and templates are deliberately not
# copied: leaving them unset means the bundled defaults are used, so they keep
# improving with each upgrade instead of freezing at the version that happened
# to be installed on the day the config was made. Copy them out by hand only
# when you actually want to change one -- write_new_config() says how.
_NEW_CONFIG_FILES = (
    ('config_sample.yaml', 'config.yaml'),
    ('formats_sample.ini', 'formats.ini'),
)


def write_new_config(dest_dir, force=False):
    """Write a fresh config.yaml and formats.ini into *dest_dir*.

    Returns (written, skipped) as lists of absolute paths. Existing files are
    never overwritten unless *force* is set -- a config holds credentials and
    hand-tuned format strings, so clobbering one silently is not acceptable.

    Nothing links the two: formats.ini is found because it sits beside
    config.yaml under the name roots.LAYOUT expects.
    """
    dest_dir = os.path.abspath(os.path.expanduser(dest_dir or '.'))
    os.makedirs(dest_dir, exist_ok=True)

    written, skipped = [], []

    for sample_name, out_name in _NEW_CONFIG_FILES:
        source = os.path.join(roots.BUNDLED_CONF, sample_name)
        target = os.path.join(dest_dir, out_name)

        if not os.path.exists(source):
            raise FileNotFoundError(
                f"Bundled sample missing: {source!r}\n"
                f"  The discogstagger3 installation appears incomplete."
            )

        if os.path.exists(target) and not force:
            skipped.append(target)
            continue

        with open(source, encoding='utf-8') as fh:
            text = fh.read()

        with open(target, 'w', encoding='utf-8') as fh:
            fh.write(text)
        written.append(target)

    return written, skipped
