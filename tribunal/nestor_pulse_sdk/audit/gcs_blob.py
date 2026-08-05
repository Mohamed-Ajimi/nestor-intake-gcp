"""
nestor_pulse_sdk.audit.gcs_blob -- GCS audit body storage with per-object retention.

Design:
  - Every LLM call's full request + response body is uploaded to GCS as JSON.
  - Key pattern: runs/{run_id}/{audit_id}_{provider}_{model}.json
    audit_id is a UUID4 unique to every individual LLM call (assigned before upload),
    so keys are globally unique and never collide even when multiple calls share the
    same run_id + provider + model (e.g. three deep-research providers in parallel).
    NOTE: audit_seq was previously used in the key but was always 0 at upload time,
    causing same-provider/model writes in the same run to collide on the GCS object
    name. Under Object Retention that collision returns HTTP 403 ("Object is subject
    to bucket's retention"). audit_id replaces it as the key's unique component.
  - Per-object retention: 7 years, mode="Unlocked" (NOT Bucket Lock -- Pitfall 7).
    Bucket Lock is irreversible at the bucket level and FORBIDDEN for this project.
    Per-object retention is set on each blob individually via blob.retention + blob.patch().
  - Credentials are REDACTED before upload (Security Domain T-07-04) by TWO
    INDEPENDENT MECHANISMS, applied to BOTH the request and the response half:
      1. `_redact_dict` -- KEY-NAME redaction. Replaces the value of any dict key
         named like a credential header (`authorization`, `x-api-key`, ...). This
         catches auth HEADERS, which is the shape most provider SDKs use.
      2. `_scrub_urls_in_value` -- VALUE-LEVEL redaction. Replaces the value of any
         URL QUERY PARAMETER named like a credential, anywhere in any string.
    BOTH ARE REQUIRED AND NEITHER SUBSUMES THE OTHER. Mechanism 1 inspects key
    names only and never looks at a value, so a credential riding INSIDE a URL --
    `https://serpapi.com/search.json?q=x&api_key=LIVE` -- is invisible to it. The
    SerpApi key travels exactly that way. Because objects here are written under
    SEVEN-YEAR retention, an unredacted body freezes a live credential for seven
    years, so the response half is redacted too and is NOT a bare deepcopy.
    (Plan 15.8-08. Before that plan the response half had NO redaction at all,
    and `AuditedLLMClient.write_failure` writes `{"error": str(error)}` there --
    a provider exception whose text renders a request URL landed verbatim.)
  - Bucket name: from env var AUDIT_GCS_BUCKET (default: "nestor-audit-prod").

Pitfall 7 -- Object Retention, NOT Bucket Lock:
  Do NOT call bucket.configure_default_object_acl() or enable bucket-level retention policy.
  Use blob.retention.mode = "Unlocked" + blob.retention.retain_until_time = now + 7y.
  This is reversible (can be shortened) unlike Bucket Lock which is permanent.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Iterable

_logger = logging.getLogger(__name__)

# Per-object retention duration: 7 years (Plan 01 + D-12).
_RETENTION_YEARS = 7

# Default GCS bucket name; overridable via AUDIT_GCS_BUCKET env var.
_DEFAULT_BUCKET = "nestor-audit-prod"

# Headers / keys that contain provider credentials -- must be redacted before upload.
_DEFAULT_REDACT_KEYS: frozenset[str] = frozenset({
    "authorization",
    "x-api-key",
    "anthropic-api-key",
    "openai-api-key",
    "google-api-key",
    "x-goog-api-key",
    "api_key",
    "apikey",
})


# URL QUERY PARAMETER names whose VALUE is a credential. The sibling of
# _DEFAULT_REDACT_KEYS above, and deliberately placed next to it so a reader sees
# the two mechanisms together:
#
#   _DEFAULT_REDACT_KEYS  -> matches a DICT KEY NAME  (auth headers)
#   _CREDENTIAL_QUERY_PARAMS -> matches a QUERY PARAM NAME inside a STRING (URLs)
#
# Neither one covers the other's case. SerpApi authenticates by query parameter
# (`?api_key=...`), so without the second mechanism a live key reaches a
# 7-year-retention object. Separator-insensitive: each entry below also matches
# its `-`, `_` and run-together spellings (api_key / api-key / apikey).
_CREDENTIAL_QUERY_PARAMS: frozenset[str] = frozenset({
    "api_key",
    "apikey",
    "key",
    "token",
    "access_token",
    "auth_token",
    "serpapi_key",
    "x_api_key",
    "secret",
    "password",
})


def _build_credential_query_pattern(param_names: frozenset[str]) -> "re.Pattern[str]":
    """Compile the query-parameter credential pattern FROM the constant above.

    Derived rather than hand-written so the frozenset stays the single source of
    truth -- a hand-maintained second copy of the vocabulary is the
    two-authorities trap this phase is explicitly guarding against.

    Each name's `_` becomes `[-_]?`, so one entry covers the `-`, `_` and
    run-together spellings. Alternatives are sorted LONGEST-FIRST because Python
    regex alternation is leftmost-first: without it, `key` could shadow
    `serpapi_key` on a pattern that did not anchor the delimiter.
    """
    alternatives = sorted(
        (re.escape(name).replace("_", "[-_]?") for name in param_names),
        key=len,
        reverse=True,
    )
    # ([?&] or start-of-param) NAME = VALUE
    # The value runs to the next &, whitespace, quote or bracket -- these URLs are
    # frequently embedded in JSON blobs and provider exception strings, so the
    # terminator set must include the characters that end a string literal.
    return re.compile(
        r"([?&])(" + "|".join(alternatives) + r")(=)([^&\s\"'<>\\]*)",
        re.IGNORECASE,
    )


_CREDENTIAL_QUERY_RE = _build_credential_query_pattern(_CREDENTIAL_QUERY_PARAMS)


def _scrub_urls_in_value(value, _depth: int = 0):
    """Replace credential VALUES inside URL query strings, anywhere in `value`.

    Walks strings, dicts and lists; returns anything else untouched. Only the
    credential parameter's VALUE is replaced -- the scheme, host, path, the
    parameter NAME and every non-credential parameter survive byte-identical,
    because the audit record exists to be READ and a scrubber that mangles every
    URL destroys the evidence it was added to protect.

    Deliberately regex-based rather than urlsplit + parse_qs + urlencode: a
    round trip through the parser REWRITES the URL (re-orders and re-encodes
    parameters), which changes evidence, and a malformed URL out of a provider
    exception string is not guaranteed to survive it at all.

    NEVER RAISES. This sits in the live audit-write path, and a failure to redact
    must not become a failure to RECORD -- the same discipline as
    `serpapi._safe_excerpt`. On an unexpected error the value is returned as-is
    with a WARNING.
    """
    # Guard against a self-referential structure; audit bodies are provider JSON
    # and should never be deep, so a generous cap costs nothing.
    if _depth > 20:
        return value
    try:
        if isinstance(value, str):
            return _CREDENTIAL_QUERY_RE.sub(r"\1\2\3[REDACTED]", value)
        if isinstance(value, (bytes, bytearray)):
            # Bytes are NOT inert here: upload_audit_body serialises with
            # `default=str`, so a bytes value is stringified INTO the stored blob
            # and a credential inside it would reach 7-year retention unscrubbed.
            # Scrub in place and keep the type; only re-encode when something
            # actually changed, and leave undecodable binary strictly untouched
            # rather than corrupting evidence with a lossy decode.
            try:
                decoded = bytes(value).decode("utf-8")
            except UnicodeDecodeError:
                return value
            scrubbed = _CREDENTIAL_QUERY_RE.sub(r"\1\2\3[REDACTED]", decoded)
            return value if scrubbed == decoded else scrubbed.encode("utf-8")
        if isinstance(value, dict):
            return {k: _scrub_urls_in_value(v, _depth + 1) for k, v in value.items()}
        if isinstance(value, list):
            return [_scrub_urls_in_value(item, _depth + 1) for item in value]
        if isinstance(value, tuple):
            return [_scrub_urls_in_value(item, _depth + 1) for item in value]
        return value
    except Exception as exc:  # noqa: BLE001 -- redaction must never break the audit write
        _logger.warning(
            "URL credential scrub failed (%s: %s) -- value passed through unscrubbed",
            type(exc).__name__,
            exc,
        )
        return value


def _redact_dict(d: dict, redact_keys: frozenset[str]) -> dict:
    """
    Recursively redact sensitive keys from a dict, case-insensitively.
    Replaces values with "[REDACTED]".

    KEY-NAME MECHANISM ONLY -- it never inspects a value. A credential inside a
    URL query parameter is invisible here BY DESIGN; `_scrub_urls_in_value` is
    the mechanism that covers that case. Do not "improve" this function to look
    at values: `test_own_researcher.py` pins this behaviour and it is the correct
    control for auth headers.
    """
    result = {}
    for k, v in d.items():
        if k.lower() in redact_keys:
            result[k] = "[REDACTED]"
        elif isinstance(v, dict):
            result[k] = _redact_dict(v, redact_keys)
        elif isinstance(v, list):
            result[k] = [
                _redact_dict(item, redact_keys) if isinstance(item, dict) else item
                for item in v
            ]
        else:
            result[k] = v
    return result


async def upload_audit_body(
    run_id: uuid.UUID,
    audit_id: uuid.UUID,
    provider: str,
    model: str,
    request_dict: dict,
    response_dict: dict,
    audit_seq: int = 0,
    redact_keys: Iterable[str] = _DEFAULT_REDACT_KEYS,
) -> str:
    """
    Upload one LLM call's full request + response body to GCS with per-object retention.

    Steps:
      1. Redact provider API keys + auth headers from request_dict (T-07-04).
      2. Build GCS key: runs/{run_id}/{audit_id}_{provider}_{model}.json
         audit_id is a per-call UUID4 that makes the key unique even when the same
         run_id + provider + model combination is uploaded multiple times in parallel
         (e.g. three deep-research providers). audit_seq is kept in the JSON payload
         metadata only (may be 0 at upload time; it is assigned under the per-run lock
         after the upload).
      3. Upload via google.cloud.storage blob.upload_from_string (content_type=application/json).
      4. Set per-object retention: blob.retention.mode = "Unlocked",
         blob.retention.retain_until_time = now + 7y, blob.patch() (Pitfall 7 -- NOT Bucket Lock).
      5. Return gs://{bucket}/{key}.

    Args:
      run_id:        Run UUID (for GCS key + payload tagging).
      audit_id:      Per-call UUID4 (unique key component; replaces audit_seq in the key).
      provider:      "anthropic", "google", or "openai".
      model:         Model identifier (sanitized in key; "/" replaced by "-").
      request_dict:  Raw request body dict (will be deep-copied + redacted).
      response_dict: Raw response body dict (will be deep-copied; no sensitive keys expected).
      audit_seq:     Sequence number stored in the JSON payload only (NOT used in the key).
                     May be 0 at upload time; the real value is assigned under the per-run lock
                     after upload and stored in the DB row.
      redact_keys:   Additional keys to redact (case-insensitive).

    Returns:
      gs:// URI of the uploaded blob.

    Raises:
      google.cloud.exceptions.GoogleCloudError: on upload failure.
      ImportError: if google-cloud-storage is not installed (caught by caller).
    """
    # BOTH halves get BOTH mechanisms (plan 15.8-08).
    #
    # Key-name redaction catches auth HEADERS; the URL scrub catches credentials
    # riding in a query parameter, which the key-name pass cannot see because it
    # never inspects a value. SerpApi authenticates by query parameter.
    #
    # The RESPONSE half was a bare `deepcopy` before 15.8-08 -- i.e. no redaction
    # at all -- while `AuditedLLMClient.write_failure` routes
    # `{"error": str(error), "type": ...}` through it. `serpapi.search` does not
    # wrap its httpx `.get()`, so a transport-layer exception carrying the full
    # request URL propagated raw into a 7-YEAR-RETENTION object. Do not revert
    # this to a deepcopy.
    redact_set = frozenset(k.lower() for k in redact_keys)
    safe_request = _scrub_urls_in_value(_redact_dict(deepcopy(request_dict), redact_set))
    safe_response = _scrub_urls_in_value(_redact_dict(deepcopy(response_dict), redact_set))

    # Sanitize model name for use in the key (replace "/" and spaces with "-")
    safe_model = model.replace("/", "-").replace(" ", "-")[:64]
    safe_provider = provider.replace("/", "-")[:32]

    key = f"runs/{run_id}/{audit_id}_{safe_provider}_{safe_model}.json"

    body = json.dumps(
        {
            "run_id": str(run_id),
            "audit_id": str(audit_id),
            "seq": audit_seq,
            "provider": provider,
            "model": model,
            "request": safe_request,
            "response": safe_response,
        },
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")

    # Local-dev fallback: when NESTOR_AUDIT_LOCAL_DIR is set, persist the audit
    # body to disk and return a file:// URI instead of GCS. This keeps the audit
    # chain functional (a body is stored + a URI pointer recorded) on a machine
    # with no GCP project/bucket. Gated on the env var alone -- deployed
    # environments never set it, so the real GCS path below is untouched.
    local_dir = os.environ.get("NESTOR_AUDIT_LOCAL_DIR")
    if local_dir:
        from pathlib import Path

        path = Path(local_dir) / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        uri = path.resolve().as_uri()
        _logger.info("Wrote audit body locally: %s", uri)
        return uri

    try:
        from google.cloud import storage  # type: ignore
    except ImportError as exc:
        _logger.error(
            "google-cloud-storage not installed; cannot upload audit body: %s", exc
        )
        raise

    bucket_name = os.environ.get("AUDIT_GCS_BUCKET", _DEFAULT_BUCKET)
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(key)

    blob.upload_from_string(body, content_type="application/json")

    # Per-object retention (Pitfall 7 -- NOT Bucket Lock).
    # Object Retention API: set retain_until_time per blob after upload.
    retain_until = datetime.now(tz=timezone.utc) + timedelta(days=_RETENTION_YEARS * 365)
    blob.retention.mode = "Unlocked"
    blob.retention.retain_until_time = retain_until
    blob.patch()

    _logger.info(
        "Uploaded audit body: gs://%s/%s (retention until %s)",
        bucket_name,
        key,
        retain_until.date(),
    )

    return f"gs://{bucket_name}/{key}"


async def download_audit_body(gcs_uri: str) -> dict | None:
    """Read one stored audit body back from GCS (the 15-04 drill-down reader).

    Fetches the JSON object at `gcs_uri` and returns it AS-STORED. The stored body
    was ALREADY redacted at upload time (upload_audit_body redacts request keys
    before writing), so this reader NEVER re-exposes provider keys and NEVER
    re-fetches anything from a live source URL -- it reads GCS (or the local-dev
    file:// fallback) ONLY.

    Returns:
      * the parsed body dict `{run_id, audit_id, seq, provider, model, request,
        response}` as stored, OR
      * None for an `error://` uri, a missing/unreadable object, or any GCS error
        (logged at warning). None is the caller's cue to 404 the drill-down.

    Design mirrors upload_audit_body's bucket resolution (AUDIT_GCS_BUCKET env) and
    the NESTOR_AUDIT_LOCAL_DIR file:// fallback so it works on a box with no GCP
    project. No new secret exposure, no live-URL fetch (Plan 15-03 T-15-08c).
    """
    if not gcs_uri or gcs_uri.startswith("error://"):
        _logger.warning("download_audit_body: unusable uri %r -> None", gcs_uri)
        return None

    # Local-dev fallback: a file:// uri written by upload_audit_body's local path.
    if gcs_uri.startswith("file://"):
        from urllib.parse import urlparse
        from urllib.request import url2pathname

        try:
            path = url2pathname(urlparse(gcs_uri).path)
            with open(path, "rb") as fh:
                return json.loads(fh.read().decode("utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            _logger.warning("download_audit_body: local read failed for %s: %s", gcs_uri, exc)
            return None

    if not gcs_uri.startswith("gs://"):
        _logger.warning("download_audit_body: not a gs:// uri %r -> None", gcs_uri)
        return None

    # Parse gs://<bucket>/<key>. The bucket is taken from the uri itself (it was
    # recorded at upload); AUDIT_GCS_BUCKET remains the default for consistency.
    without_scheme = gcs_uri[len("gs://"):]
    bucket_name, _, key = without_scheme.partition("/")
    if not bucket_name or not key:
        _logger.warning("download_audit_body: malformed gs uri %r -> None", gcs_uri)
        return None

    try:
        from google.cloud import storage  # type: ignore
    except ImportError as exc:
        _logger.error(
            "google-cloud-storage not installed; cannot download audit body: %s", exc
        )
        return None

    try:
        client = storage.Client()
        blob = client.bucket(bucket_name).blob(key)
        raw = blob.download_as_bytes()
    except Exception as exc:  # noqa: BLE001 -- a missing object / GCS error -> 404 upstream
        _logger.warning("download_audit_body: GCS read failed for %s: %s", gcs_uri, exc)
        return None

    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        _logger.warning("download_audit_body: body at %s is unreadable JSON: %s", gcs_uri, exc)
        return None
