# -*- coding: utf-8 -*-
"""Config keys massMusicTagger adds on top of discogstagger3's.

discogstagger3 validates a loaded config and reports keys it does not
recognise, so typos surface instead of being silently ignored. massMusicTagger
extends that config with its own settings — source priority, MusicBrainz,
concurrency — which discogstagger3 has no way to know about and would
otherwise report as typos.

Registering them here keeps unknown-key checking useful for both: a typo in a
massMusicTagger setting is still caught, because the combined set is what gets
checked.

A key added to conf/config_sample.yaml must be added here too, or it will be
reported as unknown at runtime.
"""

from discogstagger import config_schema as _dt3_schema

#: (section, key) pairs that belong to massMusicTagger rather than discogstagger3.
KEYS = (
    ('batch',       'audit_log'),
    ('batch',       'workers'),
    ('details',     'image_source'),
    ('details',     'source_action'),
    ('details',     'source_archive_dir'),
    ('details',     'source_hints_file'),
    ('details',     'source_move_template'),
    ('logging',     'log_file'),
    ('musicbrainz', 'acoustid_api_key'),
    ('musicbrainz', 'acoustid_early'),
    ('musicbrainz', 'caa_request_delay'),
    ('musicbrainz', 'cache_directory'),
    ('musicbrainz', 'user_agent'),
    ('source',      'priority'),
)


def register():
    """Declare these keys to discogstagger3's validator. Idempotent."""
    _dt3_schema.register_known_keys(KEYS)
