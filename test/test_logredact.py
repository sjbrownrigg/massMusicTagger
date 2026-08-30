"""Credentials must not reach a log handler.

The record we care about is emitted by urllib3, not by us, so these tests go
through the logging machinery rather than calling redact() alone -- a filter
attached to the wrong object would pass a unit test and leak in practice.
"""

import io
import logging
import unittest

from massmusictagger import logredact


class RedactTest(unittest.TestCase):

    def test_discogs_token_in_a_query_string(self):
        line = ('https://api.discogs.com:443 "GET '
                '/releases/4449888?token=abcd1234SECRET HTTP/1.1" 200 None')
        out = logredact.redact(line)
        self.assertNotIn('abcd1234SECRET', out)
        self.assertIn('token=<redacted>', out)
        # The useful part of the line survives.
        self.assertIn('/releases/4449888', out)
        self.assertIn('200 None', out)

    def test_identity_call_is_redacted_too(self):
        out = logredact.redact('GET /oauth/identity?token=zzzTOKENzzz HTTP/1.1')
        self.assertNotIn('zzzTOKENzzz', out)

    def test_authorization_header_shape(self):
        out = logredact.redact('Authorization: Discogs token=abcd1234SECRET')
        self.assertNotIn('abcd1234SECRET', out)

    def test_acoustid_client_key(self):
        out = logredact.redact('POST /v2/lookup?client=ACOUSTIDKEY&meta=recordings')
        self.assertNotIn('ACOUSTIDKEY', out)
        self.assertIn('meta=recordings', out)

    def test_oauth_parameters(self):
        line = ('oauth_consumer_key=CKEY&oauth_signature=SIG&'
                'oauth_token=OTOK&oauth_nonce=12345')
        out = logredact.redact(line)
        for secret in ('CKEY', 'SIG', 'OTOK'):
            self.assertNotIn(secret, out)
        # A nonce is not a credential and stays readable.
        self.assertIn('12345', out)

    def test_several_secrets_in_one_line(self):
        out = logredact.redact('?token=AAA&client_secret=BBB&other=keepme')
        self.assertNotIn('AAA', out)
        self.assertNotIn('BBB', out)
        self.assertIn('other=keepme', out)

    def test_url_encoded_separator(self):
        out = logredact.redact('token%3DabcdSECRET')
        self.assertNotIn('abcdSECRET', out)

    def test_ordinary_lines_are_untouched(self):
        for line in ('Fetching release 4449888 from Discogs',
                     'Matched release 1060982',
                     'avg track length diff: 1.5s over 27 track(s)'):
            with self.subTest(line=line):
                self.assertEqual(logredact.redact(line), line)

    def test_empty_and_none(self):
        self.assertEqual(logredact.redact(''), '')
        self.assertIsNone(logredact.redact(None))


class HandlerWiringTest(unittest.TestCase):
    """The filter must sit where third-party records actually pass."""

    def setUp(self):
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.setFormatter(logging.Formatter('%(message)s'))
        self.logger = logging.getLogger('test_logredact_root')
        self.logger.handlers = [self.handler]
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        self.addCleanup(setattr, self.logger, 'handlers', [])

    def _output(self):
        self.handler.flush()
        return self.stream.getvalue()

    def test_secret_leaks_without_the_filter(self):
        """Guard the guard: prove the test would catch a missing filter."""
        self.logger.debug('GET /releases/1?token=LEAKYVALUE HTTP/1.1')
        self.assertIn('LEAKYVALUE', self._output())

    def test_filter_on_the_handler_redacts(self):
        logredact.install(self.logger)
        self.logger.debug('GET /releases/1?token=LEAKYVALUE HTTP/1.1')
        out = self._output()
        self.assertNotIn('LEAKYVALUE', out)
        self.assertIn('token=<redacted>', out)

    def test_secret_arriving_via_args_is_redacted(self):
        """urllib3 logs with %s arguments, not a pre-formatted string."""
        logredact.install(self.logger)
        self.logger.debug('%s "GET %s" %s %s',
                          'https://api.discogs.com:443',
                          '/releases/1?token=LEAKYVALUE',
                          200, None)
        self.assertNotIn('LEAKYVALUE', self._output())

    def test_a_record_logged_by_a_child_logger_is_covered(self):
        """urllib3 propagates up to the root handlers -- that path must work."""
        logredact.install(self.logger)
        child = logging.getLogger('test_logredact_root.urllib3.connectionpool')
        child.debug('GET /releases/1?token=LEAKYVALUE HTTP/1.1')
        self.assertNotIn('LEAKYVALUE', self._output())

    def test_install_is_idempotent(self):
        logredact.install(self.logger)
        logredact.install(self.logger)
        self.assertEqual(
            sum(isinstance(f, logredact.RedactSecrets)
                for f in self.handler.filters), 1)

    def test_clean_records_pass_through_unchanged(self):
        logredact.install(self.logger)
        self.logger.info('Matched release 1060982')
        self.assertIn('Matched release 1060982', self._output())


if __name__ == '__main__':
    unittest.main()
