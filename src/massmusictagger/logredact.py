"""Keep credentials out of log records.

The Discogs client authenticates by putting the personal token in the query
string, and urllib3 logs every request line at DEBUG:

    DEBUG https://api.discogs.com:443 "GET /releases/4449888?token=<token>"

Our own code never logs the token, so this cannot be fixed at the call site:
the record comes from a third-party library. A filter on the handlers catches
it wherever it originates, including libraries added later.

It matters more than a leaked key usually would. Discogs issues **one personal
token per account**, so a token that reaches a shared log cannot be rotated
without breaking every other deployment using that account. And DEBUG output
is exactly what someone captures to attach to a bug report.

The filter rewrites the formatted message, so it works whether the secret
arrives in the format string or in the arguments.
"""

import logging
import re

REDACTION = '<redacted>'

#: Query-string and header parameters whose value is a credential.
#: `client` is AcoustID's API key parameter. Over-redacting a log line is
#: cheap; under-redacting one is not, so borderline names are included.
_SECRET_NAMES = (
    'token',
    'oauth_token',
    'oauth_token_secret',
    'oauth_signature',
    'oauth_consumer_key',
    'consumer_secret',
    'client_secret',
    'api_key',
    'apikey',
    'password',
    'secret',
    'client',
)

# name=value, up to the next separator. Also catches "Authorization: Discogs
# token=..." because the header uses the same shape.
_QUERY = re.compile(
    r'\b(' + '|'.join(_SECRET_NAMES) + r')(=|%3D)([^&\s"\'<>]+)',
    re.IGNORECASE,
)


def redact(text):
    """Return *text* with any credential values replaced."""
    if not text:
        return text
    return _QUERY.sub(lambda m: f'{m.group(1)}{m.group(2)}{REDACTION}', text)


class RedactSecrets(logging.Filter):
    """Strip credentials from every record passing through a handler."""

    def filter(self, record):
        try:
            message = record.getMessage()
        except Exception:
            # A malformed record is the logging system's problem, not ours;
            # let it through rather than swallowing the failure here.
            return True

        cleaned = redact(message)
        if cleaned != message:
            # Collapse to a literal message: the secret may have arrived in
            # either msg or args, and re-formatting would reintroduce it.
            record.msg = cleaned
            record.args = ()
        return True


def install(logger=None):
    """Attach the filter to every handler on *logger* (root by default).

    Handlers, not the logger: a filter on a logger only sees records logged
    directly to it, and the records we care about come from urllib3 and
    propagate up.
    """
    target = logger if logger is not None else logging.getLogger()
    filt = RedactSecrets()
    for handler in target.handlers:
        if not any(isinstance(f, RedactSecrets) for f in handler.filters):
            handler.addFilter(filt)
    return filt
