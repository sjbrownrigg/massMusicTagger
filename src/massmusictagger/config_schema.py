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
    # Reserved: the second argument to acoustid.submit(). Nothing reads it yet
    # -- massMusicTagger only calls acoustid.match(), which takes the
    # application key alone. Registered so a key stored here is not reported
    # as a typo, and so the two are not confused for each other again.
    ('musicbrainz', 'acoustid_user_key'),
    ('musicbrainz', 'acoustid_early'),
    ('musicbrainz', 'caa_request_delay'),
    ('musicbrainz', 'cache_directory'),
    ('musicbrainz', 'user_agent'),
    ('source',      'priority'),
)


#: Sections holding free-form content rather than settings, so their keys are
#: not checked individually.
#:
#: extra_configs is a deprecated list of file paths -- its "keys" are paths,
#: and checking them as setting names reported every one as a typo.
FREEFORM_SECTIONS = (
    'extra_configs',
)


def register():
    """Declare these to discogstagger3's validator. Idempotent."""
    _dt3_schema.register_known_keys(KEYS)
    _dt3_schema.register_freeform_sections(FREEFORM_SECTIONS)
