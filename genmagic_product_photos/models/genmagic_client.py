"""The only code that talks to the GenMagic API (https://genmagic.co/api/v1).

Errors carry GenMagic's own message, because that message says what to do. Nothing here reads
the database: the caller passes the API key in.
"""
import logging
import re
import time
from urllib.parse import urlsplit

import requests

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

BASE = 'https://genmagic.co/api/v1'
CLIENT_ID = 'odoo-product-photos/1.0.0'
DEFAULT_MODEL = 'google/gemini-nano-banana-2.1'
IMAGE_SIZE = '1024x1024'
# GenMagic takes an inline picture under 4,000,000 characters and base64 makes a file a third larger.
MAX_SOURCE_BYTES = 2900000
MAX_RESULT_BYTES = 15000000
MAX_REDIRECTS = 3
MODELS_TTL = 6 * 3600
MODELS_RETRY_AFTER = 60
# Hosts GenMagic serves generated files from. Files are only ever downloaded from these.
MEDIA_HOSTS = ('genmagic.co', 'axrsv1b9sa2ny4qv.public.blob.vercel-storage.com', 'tlwdqzfibvgektzgdfqa.supabase.co')

KEY_HELP = "Get a key at genmagic.co/get-api-key."
PRICING_TEXT = "genmagic.co/pricing"

# Process-wide cache of the model list: {'at': float, 'failed_at': float, 'models': list}
_MODELS_CACHE = {'at': 0.0, 'failed_at': 0.0, 'models': []}


def no_key_message():
    return _("Add your GenMagic API key under Settings > GenMagic before making photos. %s", KEY_HELP)


def low_balance_message():
    return _(
        "Your GenMagic balance is too low for this photo. Add credit at %s and try again.",
        PRICING_TEXT,
    )


def detect_mime(data):
    """The image type from the first bytes of a file, an empty string when it is not supported."""
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    return ''


def is_allowed_media_url(url):
    """Whether a URL points at a place GenMagic serves files from (https, no credentials, port 443)."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    if parts.scheme != 'https' or parts.username is not None or parts.password is not None:
        return False
    if port is not None and port != 443:
        return False
    return (parts.hostname or '').lower() in MEDIA_HOSTS


def _error_details(payload):
    """GenMagic's own error message and code from an error reply."""
    message, code = '', ''
    error = payload.get('error') if isinstance(payload, dict) else None
    if isinstance(error, dict):
        if isinstance(error.get('message'), str):
            message = error['message']
        raw_code = error.get('code') if isinstance(error.get('code'), str) else ''
        code = re.sub(r'[^A-Za-z0-9_-]', '', raw_code).lower()
    elif isinstance(error, str):
        message = error
    message = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', message).strip()
    return message[:600], code


def _number_header(headers, name):
    value = headers.get(name)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _request(method, path, api_key, body=None, timeout=20):
    headers = {'Accept': 'application/json', 'X-GenMagic-Client': CLIENT_ID}
    if api_key is not None:
        if not api_key:
            raise UserError(no_key_message())
        headers['Authorization'] = 'Bearer ' + api_key
    try:
        # No redirects: the key is only ever sent to the address built here.
        response = requests.request(
            method, BASE + path, headers=headers, json=body,
            timeout=(10, timeout), allow_redirects=False,
        )
    except requests.RequestException as exc:
        _logger.warning("GenMagic request failed: %s", exc)
        raise UserError(_("Could not reach GenMagic: %s", exc)) from None
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not 200 <= response.status_code < 300:
        message, code = _error_details(payload)
        if response.status_code == 402 or 'insufficient' in code:
            raise UserError(low_balance_message())
        if not message:
            message = _("GenMagic answered with HTTP %s.", response.status_code)
        raise UserError(message)
    headers_lc = {k.lower(): v for k, v in response.headers.items()}
    return payload if isinstance(payload, dict) else {}, {
        'cost_cents': _number_header(headers_lc, 'x-cost-cents'),
        'credits_cents': _number_header(headers_lc, 'x-credits-remaining'),
    }


def _normalize_model(raw):
    """Keeps the fields this app uses from one model of GET /models, only when it takes a picture."""
    if not isinstance(raw, dict):
        return None
    model_id = raw.get('id') if isinstance(raw.get('id'), str) else ''
    if not re.fullmatch(r'[A-Za-z0-9._:/@+-]{1,120}', model_id):
        return None
    inputs = raw.get('input_modalities')
    if not isinstance(inputs, list) or 'image' not in inputs:
        return None
    pricing = raw.get('pricing') if isinstance(raw.get('pricing'), dict) else {}
    name = raw.get('name') if isinstance(raw.get('name'), str) and raw.get('name') else model_id
    estimate = pricing.get('est_per_generation_usd')
    try:
        est_usd = float(estimate) if estimate is not None and not isinstance(estimate, bool) else None
    except (TypeError, ValueError):
        est_usd = None
    return {
        'id': model_id,
        'name': re.sub(r'<[^>]*>', '', name).strip()[:120] or model_id,
        'est_usd': est_usd,
    }


def get_editing_models(timeout=20):
    """The image models that work from a photo. Cached for six hours. The list needs no key."""
    now = time.time()
    if _MODELS_CACHE['models'] and now - _MODELS_CACHE['at'] < MODELS_TTL:
        return _MODELS_CACHE['models']
    payload, _headers = _request('GET', '/models?category=image', None, timeout=timeout)
    listed = payload.get('data')
    models = []
    for raw in listed if isinstance(listed, list) else []:
        model = _normalize_model(raw)
        if model:
            models.append(model)
    if not models:
        raise UserError(_("GenMagic returned no models. Try again in a moment."))
    _MODELS_CACHE.update({'at': now, 'models': models})
    return models


def cached_models_or_empty():
    """The model list for a form's drop-down: never raises, and does not retry a failure for a minute."""
    now = time.time()
    if _MODELS_CACHE['models'] and now - _MODELS_CACHE['at'] < MODELS_TTL:
        return _MODELS_CACHE['models']
    if now - _MODELS_CACHE['failed_at'] < MODELS_RETRY_AFTER:
        return _MODELS_CACHE['models']
    try:
        return get_editing_models(timeout=5)
    except UserError:
        _MODELS_CACHE['failed_at'] = now
        return _MODELS_CACHE['models']


def pick_model(models, requested):
    """The requested model when it works from a photo, else the default, else the first that does."""
    if not models:
        raise UserError(_("No image model that works from a photo is available right now."))
    by_id = {m['id']: m for m in models}
    if requested:
        if requested not in by_id:
            # A model the merchant picked that cannot work from a photo is refused, never swapped silently.
            raise UserError(_("That model cannot make a photo from a photo. Pick another one."))
        return by_id[requested]
    return by_id.get(DEFAULT_MODEL, models[0])


def create_image(api_key, prompt, model_id, data_url):
    """Generates one image from a picture. GenMagic answers when the image is ready."""
    payload, headers = _request(
        'POST', '/images/generations', api_key,
        body={'prompt': prompt, 'model': model_id, 'size': IMAGE_SIZE, 'image': data_url},
        # Odoo workers stop a request after 120 seconds, so give up a little before that.
        timeout=100,
    )
    items = payload.get('data')
    first = items[0] if isinstance(items, list) and items else {}
    url = first.get('url') if isinstance(first, dict) else ''
    if not isinstance(url, str) or not is_allowed_media_url(url):
        raise UserError(_("GenMagic did not return a usable image address."))
    return {'url': url, **headers}


def download(url, max_bytes=MAX_RESULT_BYTES):
    """Downloads a generated file from a GenMagic media host (redirects included). The key is never sent."""
    hops = 0
    while True:
        if not is_allowed_media_url(url):
            raise UserError(_("The file is not on a GenMagic address, so it was not downloaded."))
        try:
            response = requests.get(
                url, headers={'X-GenMagic-Client': CLIENT_ID}, timeout=(10, 100),
                allow_redirects=False, stream=True,
            )
        except requests.RequestException as exc:
            _logger.warning("GenMagic download failed: %s", exc)
            raise UserError(_("Could not download the result from GenMagic: %s", exc)) from None
        with response:
            location = response.headers.get('Location', '')
            if response.status_code in (301, 302, 303, 307, 308) and location:
                hops += 1
                if hops > MAX_REDIRECTS:
                    raise UserError(_("Could not download the result from GenMagic (too many redirects)."))
                url = location
                continue
            if response.status_code != 200:
                raise UserError(_("Could not download the result from GenMagic (HTTP %s).", response.status_code))
            body = bytearray()
            try:
                for chunk in response.iter_content(chunk_size=65536):
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        break
            except requests.RequestException as exc:
                raise UserError(_("Could not download the result from GenMagic: %s", exc)) from None
        if not body or len(body) > max_bytes:
            raise UserError(_("The downloaded file is empty or larger than this app accepts."))
        return bytes(body)
