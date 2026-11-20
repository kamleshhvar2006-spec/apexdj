"""Run with:  STORE_BACKEND=memory python manage.py test      (no Catalyst account or network needed)"""
import json
import os
import re
import sys
import types
from unittest import mock

from django.test import Client, SimpleTestCase, override_settings

from . import auth
from . import store as store_module
from .errors import DuplicateKey
from .store import CatalystStore

PASSWORD = 'Str0ng-Pass-123'
GOOD_BOOKING = {'customerName': 'Asha Rao', 'email': 'Asha@Example.com', 'origin': 'bhubaneswar',
                'destination': 'delhi', 'mode': 'road', 'weightKg': 1000, 'estimatedCost': 1}


class ApiTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password_hash = auth.hash_password(PASSWORD)

    def setUp(self):
        env = mock.patch.dict(os.environ, {
            'STORE_BACKEND': 'memory', 'ADMIN_EMAIL': 'Boss@Apex.in',
            'ADMIN_PASSWORD_HASH': self.password_hash, 'SESSION_SECRET': 'k' * 48})
        env.start()
        self.addCleanup(env.stop)
        sleep = mock.patch('logistics.views.time.sleep')  # the login failure delay
        sleep.start()
        self.addCleanup(sleep.stop)
        store_module.reset_memory_store()
        auth.reset_failures()
        self.client = Client()

    def post(self, path, data=None, token=None, raw=None):
        headers = {'X-Apex-Token': token} if token else {}
        body = raw if raw is not None else json.dumps(data or {})
        return self.client.post(path, data=body, content_type='application/json', headers=headers)

    def login(self):
        response = self.post('/api/admin/login', {'email': 'BOSS@apex.in', 'password': PASSWORD})
        self.assertEqual(response.status_code, 200)
        return response.json()['idToken']

    def book(self, **overrides):
        return self.post('/api/bookings', {**GOOD_BOOKING, **overrides})

    # ---- pages and health
    def test_index_serves_the_website(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'APEX', response.content)
        self.assertIn(b"API_BASE: '/api'", response.content)

    def test_health(self):
        self.assertEqual(self.client.get('/api/health').json(), {'status': 'ok', 'store': 'memory'})
        self.assertEqual(self.client.get('/api/health?check=store').json()['tables'], 'ok')

    def test_unknown_api_route_and_wrong_method_return_json(self):
        response = self.client.get('/api/nope')
        self.assertEqual((response.status_code, response.json()['message']), (404, 'Not found.'))
        response = self.post('/api/track/APX-20260101-AAAAAAAA')
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response['Allow'], 'GET')

    # ---- bookings
    def test_booking_rejects_bad_input(self):
        for overrides in ({'customerName': 'A'}, {'email': 'nope'}, {'origin': '__proto__'}, {'origin': 'delhi', 'destination': 'delhi'},
                          {'mode': 'ocean'}, {'mode': 'rail'}, {'weightKg': 'abc'}, {'weightKg': True}, {'weightKg': 0},
                          {'weightKg': 99999}, {'destination': 'london'}):
            with self.subTest(overrides=overrides):
                self.assertEqual(self.book(**overrides).status_code, 400)

    def test_booking_rejects_malformed_and_oversized_bodies(self):
        self.assertEqual(self.post('/api/bookings', raw='{bad').status_code, 400)
        self.assertEqual(self.post('/api/bookings', raw='[]').status_code, 400)
        self.assertEqual(self.post('/api/bookings', raw=json.dumps({'customerName': 'x' * 30000})).status_code, 413)

    def test_booking_is_saved_with_server_side_price_and_can_be_tracked(self):
        response = self.book()
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertRegex(body['trackingId'], r'^APX-\d{8}-[A-Z0-9]{8}$')
        self.assertEqual(body['estimatedCost'], 13543)  # the client sent 1; the server price wins
        self.assertEqual(body['status'], 'Pending')

        tracked = self.client.get('/api/track/' + body['trackingId'].lower()).json()
        self.assertEqual((tracked['status'], tracked['mode'], tracked['weightKg'], tracked['currentLocation']),
                         ('Pending', 'road', 1000, 'Bhubaneswar'))
        self.assertNotIn('email', tracked)
        self.assertNotIn('estimatedCost', tracked)

    def test_track_errors(self):
        self.assertEqual(self.client.get('/api/track/abc').status_code, 400)
        self.assertEqual(self.client.get("/api/track/APX-20260101-AAAA'--").status_code, 400)
        self.assertEqual(self.client.get('/api/track/APX-20260101-AAAAAAAA').status_code, 404)

    # ---- admin
    def test_login(self):
        self.assertEqual(self.post('/api/admin/login', {'email': 'boss@apex.in', 'password': 'wrong'}).status_code, 401)
        self.assertEqual(self.post('/api/admin/login', {'email': 'x@apex.in', 'password': PASSWORD}).status_code, 401)
        self.assertEqual(self.post('/api/admin/login', {'email': '', 'password': ''}).status_code, 400)
        ok = self.post('/api/admin/login', {'email': 'BOSS@apex.in', 'password': PASSWORD}).json()
        self.assertEqual(ok['expiresIn'], 3600)
        self.assertTrue(ok['idToken'])

    def test_login_needs_server_configuration(self):
        with mock.patch.dict(os.environ, {'ADMIN_EMAIL': ''}):
            response = self.post('/api/admin/login', {'email': 'a@b.co', 'password': 'whatever-pass'})
        self.assertEqual((response.status_code, response.json()['message']), (500, 'Admin login is not configured on the server.'))

    def test_login_lockout_after_repeated_failures(self):
        for i in range(auth.MAX_FAILURES):
            self.post('/api/admin/login', {'email': 'boss@apex.in', 'password': f'bad{i}'})
        self.assertEqual(self.post('/api/admin/login', {'email': 'boss@apex.in', 'password': PASSWORD}).status_code, 429)

    def test_admin_routes_need_a_valid_token(self):
        token = self.login()
        self.assertEqual(self.client.get('/api/admin/dashboard').status_code, 401)
        self.assertEqual(self.client.get('/api/admin/dashboard', headers={'X-Apex-Token': token[:-3] + 'abc'}).status_code, 401)
        self.assertEqual(self.client.get('/api/admin/dashboard', headers={'X-Apex-Token': 'a.b'}).status_code, 401)
        self.assertEqual(self.client.patch('/api/admin/shipments/APX-20260101-AAAAAAAA', data='{}',
                                           content_type='application/json').status_code, 401)
        with mock.patch('logistics.auth.time.time', return_value=10 ** 11):  # far in the future: token expired
            self.assertEqual(self.client.get('/api/admin/dashboard', headers={'X-Apex-Token': token}).status_code, 401)

    def test_dashboard_summary_and_shipment_update(self):
        token = self.login()
        tracking_id = self.book().json()['trackingId']
        header = {'X-Apex-Token': token}

        dash = self.client.get('/api/admin/dashboard', headers=header).json()
        self.assertEqual(len(dash['shipments']), 4)  # 3 demo rows + the new booking
        created = [s['createdAt'] for s in dash['shipments']]
        self.assertEqual(created, sorted(created, reverse=True))  # newest first
        booked = next(s for s in dash['shipments'] if s['trackingId'] == tracking_id)
        self.assertEqual((booked['email'], booked['estimatedCost']), ('asha@example.com', 13543))
        self.assertEqual(len(dash['fleet']), 3)
        self.assertEqual(len(dash['summary']['monthlyRevenue']), 6)
        self.assertEqual(dash['summary']['modeBreakdown'], {'road': 2, 'ocean': 1, 'air': 1})
        self.assertEqual((dash['summary']['pendingCount'], dash['summary']['activeCount']), (2, 2))
        self.assertEqual(dash['summary']['totalRevenue'], 91234 + 527574 + 35304 + 13543)

        url = '/api/admin/shipments/' + tracking_id
        patch = lambda data: self.client.patch(url, data=json.dumps(data), content_type='application/json', headers=header)
        self.assertEqual(patch({'status': 'Flying'}).status_code, 400)
        self.assertEqual(patch({}).status_code, 400)
        self.assertEqual(patch({'currentLocation': ''}).status_code, 400)
        response = patch({'status': 'In Transit', 'currentLocation': 'Nagpur Hub'})
        self.assertEqual((response.status_code, response.json()['status']), (200, 'In Transit'))
        tracked = self.client.get('/api/track/' + tracking_id).json()
        self.assertEqual((tracked['status'], tracked['currentLocation']), ('In Transit', 'Nagpur Hub'))
        missing = self.client.patch('/api/admin/shipments/APX-20260101-AAAAAAAA', data='{"status":"Delivered"}',
                                    content_type='application/json', headers=header)
        self.assertEqual(missing.status_code, 404)

        dash = self.client.get('/api/admin/dashboard', headers=header).json()
        self.assertEqual((dash['summary']['pendingCount'], dash['summary']['activeCount']), (1, 3))

    # ---- optional CORS (only when the website is hosted on another domain)
    def test_cors_is_off_by_default(self):
        response = self.client.get('/api/health', headers={'Origin': 'https://site.example'})
        self.assertNotIn('Access-Control-Allow-Origin', response)

    @override_settings(CORS_ALLOWED_ORIGINS=['https://site.example'])
    def test_cors_preflight_for_an_allowed_origin(self):
        response = self.client.options('/api/bookings', headers={'Origin': 'https://site.example'})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response['Access-Control-Allow-Origin'], 'https://site.example')
        self.assertIn('X-Apex-Token', response['Access-Control-Allow-Headers'])
        other = self.client.options('/api/bookings', headers={'Origin': 'https://evil.example'})
        self.assertNotIn('Access-Control-Allow-Origin', other)


class FakeCatalystApp:
    """Behaves like zcatalyst_sdk's CatalystApp for the few calls the store makes. Values come back as strings, like ZCQL."""

    def __init__(self):
        self.tables = {'Shipments': [], 'Fleet': []}
        self.queries, self.updates, self.fail_next_insert = [], [], None
        self._table = None

    def zcql(self):
        return self

    def execute_query(self, query):
        self.queries.append(query)
        table = re.search(r'FROM (\w+)', query).group(1)
        rows = self.tables[table]
        match = re.search(r"trackingId = '([^']+)'", query)
        if match:
            rows = [r for r in rows if r['trackingId'] == match.group(1)]
        page = re.search(r'LIMIT (\d+), (\d+)', query)
        if page:
            rows = rows[int(page.group(1)):int(page.group(1)) + int(page.group(2))]
        return [{table: dict(r)} for r in rows]

    def datastore(self):
        return self

    def table(self, name):
        self._table = name
        return self

    def insert_row(self, row):
        if self.fail_next_insert:
            raise Exception(self.fail_next_insert)
        stored = {k: str(v) for k, v in row.items()}
        stored['ROWID'] = str(1000 + len(self.tables[self._table]))
        self.tables[self._table].append(stored)
        return stored

    def update_row(self, row):
        self.updates.append(row)
        target = next(r for r in self.tables[self._table] if r['ROWID'] == row['ROWID'])
        target.update({k: str(v) for k, v in row.items() if k != 'ROWID'})
        return target


class CatalystStoreTests(SimpleTestCase):
    SHIPMENT = {'trackingId': 'APX-20261012-AB12CD34', 'status': 'Pending', 'customerName': 'Asha', 'email': 'a@b.co',
                'origin': 'mumbai', 'destination': 'delhi', 'currentLocation': 'Mumbai', 'mode': 'road', 'weightKg': 250.5,
                'estimatedCost': 9100, 'estimatedDelivery': '2026-10-18', 'createdAt': '2026-10-12T05:00:00Z',
                'updatedAt': '2026-10-12T05:00:00Z'}

    def test_insert_maps_api_fields_to_data_store_columns(self):
        app = FakeCatalystApp()
        CatalystStore(app).insert(self.SHIPMENT)
        row = app.tables['Shipments'][0]
        self.assertEqual((row['shipStatus'], row['transportMode'], row['weightKg']), ('Pending', 'road', '250.5'))
        self.assertNotIn('status', row)
        self.assertNotIn('mode', row)

    def test_find_converts_strings_back_to_numbers(self):
        app = FakeCatalystApp()
        store = CatalystStore(app)
        store.insert(self.SHIPMENT)
        found = store.find('APX-20261012-AB12CD34')
        self.assertEqual((found['status'], found['mode'], found['weightKg'], found['estimatedCost']), ('Pending', 'road', 250.5, 9100))
        self.assertIsNone(store.find('APX-20261012-ZZZZZZZZ'))

    def test_duplicate_tracking_id_is_reported(self):
        app = FakeCatalystApp()
        app.fail_next_insert = 'DUPLICATE_VALUE: trackingId must be unique'
        with self.assertRaises(DuplicateKey):
            CatalystStore(app).insert(self.SHIPMENT)
        app.fail_next_insert = 'INVALID_TABLE: Shipments'
        with self.assertRaises(Exception) as ctx:
            CatalystStore(app).insert(self.SHIPMENT)
        self.assertNotIsInstance(ctx.exception, DuplicateKey)

    def test_update_uses_column_names_and_rowid(self):
        app = FakeCatalystApp()
        store = CatalystStore(app)
        store.insert(self.SHIPMENT)
        rowid = store.find('APX-20261012-AB12CD34')['rowId']
        store.update(rowid, {'status': 'Delivered', 'currentLocation': 'Delhi', 'updatedAt': '2026-10-15T00:00:00Z'})
        self.assertEqual(app.updates[0], {'ROWID': rowid, 'shipStatus': 'Delivered', 'currentLocation': 'Delhi',
                                          'updatedAt': '2026-10-15T00:00:00Z'})

    def test_list_pages_through_more_than_300_rows(self):
        app = FakeCatalystApp()
        app.tables['Shipments'] = [{'ROWID': str(i), 'trackingId': f'T{i}', 'shipStatus': 'Pending', 'weightKg': '1',
                                    'estimatedCost': '10'} for i in range(650)]
        self.assertEqual(len(CatalystStore(app).list_shipments()), 650)
        self.assertEqual(len([q for q in app.queries if 'LIMIT' in q]), 3)  # 300 + 300 + 50

    def test_ping_queries_both_tables(self):
        app = FakeCatalystApp()
        CatalystStore(app).ping()
        self.assertEqual([re.search(r'FROM (\w+)', q).group(1) for q in app.queries], ['Shipments', 'Fleet'])

    def test_views_initialise_the_sdk_from_the_django_request(self):
        app = FakeCatalystApp()
        CatalystStore(app).insert(self.SHIPMENT)
        fake_sdk = types.SimpleNamespace(initialize=mock.Mock(return_value=app))
        with mock.patch.dict(os.environ, {'STORE_BACKEND': 'catalyst'}), \
                mock.patch.dict(sys.modules, {'zcatalyst_sdk': fake_sdk}):
            response = Client().get('/api/track/APX-20261012-AB12CD34')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['customerName'], 'Asha')
        request = fake_sdk.initialize.call_args.kwargs['req']
        self.assertTrue(hasattr(request, 'headers'))  # the SDK reads the x-zc-* project headers from request.headers
