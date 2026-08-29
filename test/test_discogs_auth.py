# -*- coding: utf-8 -*-
"""A token that is present is not a token that works.

Discogs issues one personal access token at a time per account, so generating
one for a second registered application invalidates the first. The connector
logged "Authenticated via personal access token" on the strength of the string
being non-empty; the only symptom of a dead token was that lookups quietly
stopped finding anything, and with the disk cache warm a whole run looked fine.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(parentdir, 'src'))

from massmusictagger.config_schema import ConfigError
from massmusictagger.sources.discogs import connector as conn_mod


def _connector(identity):
    """A DiscogsConnector with just enough state to verify its token."""
    c = conn_mod.DiscogsConnector.__new__(conn_mod.DiscogsConnector)
    c.discogs_client = MagicMock()
    c.discogs_client.identity = identity
    return c


class _HTTPError(Exception):
    def __init__(self, msg, status_code):
        super().__init__(msg)
        self.status_code = status_code


class TokenVerification(unittest.TestCase):

    def test_a_rejected_token_is_fatal(self):
        def identity():
            raise _HTTPError('401: You must authenticate to access this resource.', 401)
        with self.assertRaises(ConfigError) as exc:
            _connector(identity)._verify_token()
        self.assertIn('one token at a time', str(exc.exception))

    def test_the_error_says_where_to_fix_it(self):
        def identity():
            raise _HTTPError('401', 401)
        with self.assertRaises(ConfigError) as exc:
            _connector(identity)._verify_token()
        msg = str(exc.exception)
        self.assertIn('DISCOGS_USER_TOKEN', msg)
        self.assertIn('discogs.com/settings/developers', msg)

    def test_a_403_is_also_a_credential_problem(self):
        def identity():
            raise _HTTPError('403 Forbidden', 403)
        with self.assertRaises(ConfigError):
            _connector(identity)._verify_token()

    def test_a_network_failure_is_not_fatal(self):
        """An offline run against a warm cache is legitimate."""
        def identity():
            raise OSError('Name or service not known')
        _connector(identity)._verify_token()   # must not raise

    def test_a_server_error_is_not_a_credential_problem(self):
        """The client raises the same type for 401 and 503."""
        def identity():
            raise _HTTPError('503 Service Unavailable', 503)
        _connector(identity)._verify_token()   # must not raise

    def test_a_good_token_passes_quietly(self):
        identity = MagicMock(return_value=MagicMock(username='ghostdanser'))
        _connector(identity)._verify_token()
        identity.assert_called_once()

    def test_an_identity_without_a_username_still_passes(self):
        identity = MagicMock(return_value=object())
        _connector(identity)._verify_token()


class AuthFailureDetection(unittest.TestCase):

    def test_status_code_decides(self):
        self.assertTrue(conn_mod._is_auth_failure(_HTTPError('nope', 401)))
        self.assertFalse(conn_mod._is_auth_failure(_HTTPError('oops', 500)))

    def test_a_bare_network_error_is_not_an_auth_failure(self):
        self.assertFalse(conn_mod._is_auth_failure(OSError('unreachable')))

    def test_the_clients_own_authorization_error_counts(self):
        import discogs_client.exceptions as dce
        self.assertTrue(
            conn_mod._is_auth_failure(dce.AuthorizationError('no', 401, None)))


class ConfigErrorsReachTheUser(unittest.TestCase):
    """A config problem is a message and an exit code, not a stack trace.

    _validate_config's problems already printed cleanly and exited 78. A
    rejected token cannot be found that way -- it takes asking Discogs -- so
    it surfaced later, as a traceback, burying an actionable message under a
    call stack.
    """

    def test_a_config_error_becomes_a_message_and_exit_78(self):
        from unittest.mock import patch
        import io
        from massmusictagger import __main__ as mmt_main

        with patch.object(mmt_main, '_main',
                          side_effect=ConfigError('Discogs rejected the token.')):
            err = io.StringIO()
            with patch('sys.stderr', err):
                with self.assertRaises(SystemExit) as exit_:
                    mmt_main.main([])
        self.assertEqual(exit_.exception.code, 78)
        self.assertIn('Discogs rejected the token.', err.getvalue())
        self.assertNotIn('Traceback', err.getvalue())

    def test_other_exceptions_are_not_swallowed(self):
        from unittest.mock import patch
        from massmusictagger import __main__ as mmt_main

        with patch.object(mmt_main, '_main', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                mmt_main.main([])
