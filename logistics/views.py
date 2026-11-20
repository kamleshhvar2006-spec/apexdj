"""HTTP endpoints. Same API as the AWS and Node.js versions, under /api:

  GET   /api/track/<id>                 public
  POST  /api/bookings                   public
  POST  /api/admin/login                public (checks ADMIN_EMAIL / ADMIN_PASSWORD_HASH)
  GET   /api/admin/dashboard            needs the X-Apex-Token header
  PATCH /api/admin/shipments/<id>       needs the X-Apex-Token header
  GET   /api/health[?check=store]       deployment check
"""
import functools
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_safe

from . import auth, pricing
from .errors import ApiError, DuplicateKey
from .store import get_store

log = logging.getLogger('apex')

STATUSES = ['Pending', 'Confirmed', 'In Transit', 'At Hub', 'Out for Delivery', 'Delivered', 'Delayed', 'Cancelled']
ACTIVE = {'Confirmed', 'In Transit', 'At Hub', 'Out for Delivery', 'Delayed'}
TRACKING_RE = re.compile(r'^APX-\d{8}-[A-Z0-9]{8}$')
EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]{2,}$')
ID_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


# --------------------------------------------------------------------------- helpers
def _json(data, status=200):
    response = JsonResponse(data, status=status, safe=False)
    response['Cache-Control'] = 'no-store'
    return response


def _iso(moment):
    return moment.strftime('%Y-%m-%dT%H:%M:%SZ')


def _text(value):
    return value if isinstance(value, str) else ''


def _body(request):
    try:
        raw = request.body
    except RequestDataTooBig:
        raise ApiError(413, 'Request body is too large.')
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise ApiError(400, 'Request body must be valid JSON.')
    if not isinstance(data, dict):
        raise ApiError(400, 'Request body must be a JSON object.')
    return data


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return (forwarded.split(',')[0].strip() or request.META.get('REMOTE_ADDR', 'unknown'))


def _require_admin(request):
    payload = auth.verify_token(request.headers.get('X-Apex-Token', ''))
    if not payload:
        raise ApiError(401, 'Your session has expired. Sign in again.')
    return payload.get('sub', 'admin')


def api(*methods, admin=False):
    """JSON error handling, method checking and (optionally) the admin token check for an API view."""
    def decorator(view):
        @functools.wraps(view)
        def wrapper(request, *args, **kwargs):
            try:
                if request.method not in methods:
                    raise ApiError(405, 'Method not allowed.')
                if admin:
                    request.admin_email = _require_admin(request)
                return view(request, *args, **kwargs)
            except ApiError as err:
                response = _json({'message': err.message}, err.status)
                if err.status == 405:
                    response['Allow'] = ', '.join(methods)
                return response
            except Exception:  # noqa: BLE001 - never leak internals; the traceback goes to the Catalyst logs
                log.exception('Unhandled error in %s', view.__name__)
                return _json({'message': 'Unexpected server error.'}, 500)
        return wrapper
    return decorator


def _shipment_public(s):
    return {k: s[k] for k in ('trackingId', 'status', 'customerName', 'origin', 'destination', 'currentLocation',
                              'mode', 'weightKg', 'estimatedDelivery', 'createdAt')}


def _shipment_admin(s):
    return {**_shipment_public(s), 'email': s['email'], 'estimatedCost': s['estimatedCost'], 'updatedAt': s['updatedAt']}


def summarise(shipments):
    now = datetime.now(timezone.utc)
    months, revenue = [], {}
    for i in range(5, -1, -1):
        y, m = now.year, now.month - i
        while m <= 0:
            m += 12
            y -= 1
        key = f'{y:04d}-{m:02d}'
        months.append((key, f'{MONTHS[m - 1]} {str(y)[2:]}'))
        revenue[key] = 0
    modes = {'road': 0, 'ocean': 0, 'air': 0}
    total = pending = active = 0
    for s in shipments:
        if s['mode'] in modes:
            modes[s['mode']] += 1
        if s['status'] == 'Cancelled':
            continue
        total += s['estimatedCost']
        key = str(s['createdAt'])[:7]
        if key in revenue:
            revenue[key] += s['estimatedCost']
        pending += s['status'] == 'Pending'
        active += s['status'] in ACTIVE
    return {
        'totalRevenue': total, 'monthRevenue': revenue[months[-1][0]], 'pendingCount': pending, 'activeCount': active,
        'modeBreakdown': modes, 'monthlyRevenue': [{'month': label, 'revenue': revenue[key]} for key, label in months],
    }


# --------------------------------------------------------------------------- pages
@require_safe
def index(request):
    try:
        html = settings.FRONTEND_FILE.read_text(encoding='utf-8')
    except OSError:
        log.exception('frontend/index.html is missing')
        return HttpResponse('The website file (frontend/index.html) is missing from this deployment.', status=500)
    response = HttpResponse(html, content_type='text/html; charset=utf-8')
    response['Cache-Control'] = 'no-cache'
    return response


@api('GET')
def health(request):
    backend = os.environ.get('STORE_BACKEND', 'catalyst').lower()
    result = {'status': 'ok', 'store': backend}
    if request.GET.get('check') == 'store':  # confirms the Data Store tables and columns are reachable
        try:
            get_store(request).ping()
            result['tables'] = 'ok'
        except Exception:  # noqa: BLE001
            log.exception('store check failed')
            result.update(status='error', tables='error: see the function logs')
            return _json(result, 503)
    return _json(result)


@api('GET', 'POST', 'PATCH', 'PUT', 'DELETE', 'HEAD')
def api_not_found(request):
    raise ApiError(404, 'Not found.')


# --------------------------------------------------------------------------- public API
@api('GET')
def track(request, tracking_id):
    tracking_id = tracking_id.strip().upper()
    if not TRACKING_RE.match(tracking_id):
        raise ApiError(400, 'Tracking IDs look like APX-20261012-AB12CD34.')
    shipment = get_store(request).find(tracking_id)
    if not shipment:
        raise ApiError(404, 'No shipment found for that tracking ID.')
    return _json(_shipment_public(shipment))


@api('POST')
def bookings(request):
    data = _body(request)
    name, email = _text(data.get('customerName')).strip(), _text(data.get('email')).strip().lower()
    origin, destination, mode = _text(data.get('origin')), _text(data.get('destination')), _text(data.get('mode'))
    raw_weight = data.get('weightKg')
    try:
        if isinstance(raw_weight, bool) or not isinstance(raw_weight, (int, float, str)) or not str(raw_weight).strip():
            raise ValueError
        weight = float(raw_weight)
        if weight != weight or weight in (float('inf'), float('-inf')):
            raise ValueError
    except ValueError:
        raise ApiError(400, 'Weight must be a number.')
    if not 2 <= len(name) <= 80:
        raise ApiError(400, 'Customer name must be 2-80 characters.')
    if len(email) > 120 or not EMAIL_RE.match(email):
        raise ApiError(400, 'Enter a valid email address.')
    quote = pricing.estimate(origin, destination, mode, weight)  # the browser's cost is ignored on purpose
    weight = int(weight) if weight.is_integer() else weight

    now = datetime.now(timezone.utc)
    store = get_store(request)
    for _ in range(3):  # retry only if a generated ID collides with an existing one
        shipment = {
            'trackingId': 'APX-{}-{}'.format(now.strftime('%Y%m%d'), ''.join(secrets.choice(ID_ALPHABET) for _ in range(8))),
            'status': 'Pending', 'customerName': name, 'email': email, 'origin': origin, 'destination': destination,
            'currentLocation': pricing.hub_name(origin), 'mode': mode, 'weightKg': weight,
            'estimatedCost': quote['total'],
            'estimatedDelivery': (now + timedelta(days=quote['transitDays'])).strftime('%Y-%m-%d'),
            'createdAt': _iso(now), 'updatedAt': _iso(now),
        }
        try:
            store.insert(shipment)
        except DuplicateKey:
            continue
        log.info(json.dumps({'event': 'booking_created', 'trackingId': shipment['trackingId'], 'mode': mode,
                             'total': quote['total']}))
        return _json({'trackingId': shipment['trackingId'], 'status': 'Pending', 'estimatedCost': quote['total'],
                      'estimatedDelivery': shipment['estimatedDelivery'], 'createdAt': shipment['createdAt']}, 201)
    raise ApiError(503, 'Could not allocate a tracking reference. Please retry.')


@api('POST')
def admin_login(request):
    ip = _client_ip(request)
    if auth.locked_out(ip):
        raise ApiError(429, 'Too many attempts. Wait 15 minutes and try again.')
    data = _body(request)
    email, password = _text(data.get('email')).strip().lower(), _text(data.get('password'))
    if not email or not password:
        raise ApiError(400, 'Enter your email and password.')
    admin_email = os.environ.get('ADMIN_EMAIL', '').strip().lower()
    stored_hash = os.environ.get('ADMIN_PASSWORD_HASH', '')
    if not admin_email or not stored_hash or not auth.session_secret():
        log.error('admin login is not configured (ADMIN_EMAIL, ADMIN_PASSWORD_HASH, SESSION_SECRET)')
        raise ApiError(500, 'Admin login is not configured on the server.')
    email_ok, password_ok = auth.same_text(email, admin_email), auth.verify_password(password, stored_hash)  # both always run
    if not (email_ok and password_ok):
        auth.note_failure(ip)
        log.warning('admin login failed')
        time.sleep(0.4)
        raise ApiError(401, 'Invalid email or password.')
    issued = int(time.time())
    token = auth.sign_token({'sub': admin_email, 'iat': issued, 'exp': issued + auth.SESSION_SECONDS})
    return _json({'idToken': token, 'expiresIn': auth.SESSION_SECONDS})


# --------------------------------------------------------------------------- admin API
@api('GET', admin=True)
def admin_dashboard(request):
    store = get_store(request)
    shipments = sorted(store.list_shipments(), key=lambda s: str(s['createdAt']), reverse=True)
    return _json({'summary': summarise(shipments), 'shipments': [_shipment_admin(s) for s in shipments],
                  'fleet': store.list_fleet()})


@api('PATCH', admin=True)
def admin_update(request, tracking_id):
    tracking_id = tracking_id.strip().upper()
    if not TRACKING_RE.match(tracking_id):
        raise ApiError(400, 'Invalid tracking ID.')
    data = _body(request)
    changes = {}
    if 'status' in data:
        if data['status'] not in STATUSES:
            raise ApiError(400, 'Unknown status.')
        changes['status'] = data['status']
    if 'currentLocation' in data:
        location = _text(data['currentLocation']).strip()
        if not 1 <= len(location) <= 120:
            raise ApiError(400, 'Location must be 1-120 characters.')
        changes['currentLocation'] = location
    if not changes:
        raise ApiError(400, 'Provide a status and/or currentLocation.')

    store = get_store(request)
    current = store.find(tracking_id)
    if not current:
        raise ApiError(404, 'Shipment not found.')
    changes['updatedAt'] = _iso(datetime.now(timezone.utc))
    store.update(current['rowId'], changes)
    log.info(json.dumps({'event': 'shipment_updated', 'trackingId': tracking_id, 'by': request.admin_email,
                         'status': changes.get('status'), 'location': changes.get('currentLocation')}))
    return _json(_shipment_admin({**current, **changes}))
