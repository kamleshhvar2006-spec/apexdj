"""Where shipments and fleet records live.

CatalystStore  : the Catalyst Data Store (tables Shipments and Fleet), used on AppSail.
MemoryStore    : plain Python dicts with a few sample rows, for running locally (STORE_BACKEND=memory). Resets on restart.

Both expose the same methods and speak in API field names (status, mode, ...); CatalystStore maps them to
the column names used in the Data Store (shipStatus, transportMode, ...).
"""
import copy
import os
import re
import threading
from datetime import datetime, timedelta, timezone

from .errors import DuplicateKey

# ZCQL returns every value as a string and nests each row under its table name.
SHIP_COLS = ('ROWID, trackingId, shipStatus, customerName, email, origin, destination, currentLocation, '
             'transportMode, weightKg, estimatedCost, estimatedDelivery, createdAt, updatedAt')
FLEET_COLS = 'vehicleId, vehicleType, vehicleName, vehicleStatus, vehicleLocation'
CHANGE_COLUMNS = {'status': 'shipStatus', 'currentLocation': 'currentLocation', 'updatedAt': 'updatedAt'}
PAGE = 300          # ZCQL returns at most 300 rows per query
SCAN_CAP = 6000     # stop paging here so one dashboard request stays well inside the 30 s function limit


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    return int(number) if number.is_integer() else number


def _to_shipment(row):
    return {
        'rowId': row.get('ROWID'), 'trackingId': row.get('trackingId'), 'status': row.get('shipStatus'),
        'customerName': row.get('customerName'), 'email': row.get('email'), 'origin': row.get('origin'),
        'destination': row.get('destination'), 'currentLocation': row.get('currentLocation'),
        'mode': row.get('transportMode'), 'weightKg': _number(row.get('weightKg')),
        'estimatedCost': _number(row.get('estimatedCost')), 'estimatedDelivery': row.get('estimatedDelivery'),
        'createdAt': row.get('createdAt'), 'updatedAt': row.get('updatedAt'),
    }


def _to_vehicle(row):
    return {'vehicleId': row.get('vehicleId'), 'type': row.get('vehicleType'), 'name': row.get('vehicleName'),
            'status': row.get('vehicleStatus'), 'location': row.get('vehicleLocation')}


class CatalystStore:
    name = 'catalyst'

    def __init__(self, app):
        self.app = app  # a zcatalyst_sdk CatalystApp

    def find(self, tracking_id):
        # tracking_id is validated against ^APX-\d{8}-[A-Z0-9]{8}$ by the caller, so it cannot break out of the quotes
        rows = self.app.zcql().execute_query(
            f"SELECT {SHIP_COLS} FROM Shipments WHERE trackingId = '{tracking_id}'") or []
        return _to_shipment(rows[0]['Shipments']) if rows else None

    def insert(self, s):
        row = {
            'trackingId': s['trackingId'], 'shipStatus': s['status'], 'customerName': s['customerName'],
            'email': s['email'], 'origin': s['origin'], 'destination': s['destination'],
            'currentLocation': s['currentLocation'], 'transportMode': s['mode'], 'weightKg': s['weightKg'],
            'estimatedCost': s['estimatedCost'], 'estimatedDelivery': s['estimatedDelivery'],
            'createdAt': s['createdAt'], 'updatedAt': s['updatedAt'],
        }
        try:
            self.app.datastore().table('Shipments').insert_row(row)
        except Exception as exc:  # the SDK raises its own error types; only a unique-key clash is retried
            if re.search(r'duplicate|unique', str(exc), re.I):
                raise DuplicateKey(s['trackingId']) from exc
            raise

    def update(self, row_id, changes):
        row = {'ROWID': row_id}
        for field, value in changes.items():
            row[CHANGE_COLUMNS[field]] = value
        self.app.datastore().table('Shipments').update_row(row)

    def ping(self):
        """Selecting every column we use proves that both tables exist and the column names are spelled right."""
        self.app.zcql().execute_query(f'SELECT {SHIP_COLS} FROM Shipments LIMIT 0, 1')
        self.app.zcql().execute_query(f'SELECT {FLEET_COLS} FROM Fleet LIMIT 0, 1')

    def list_shipments(self):
        return self._scan('Shipments', SHIP_COLS, _to_shipment)

    def list_fleet(self):
        return self._scan('Fleet', FLEET_COLS, _to_vehicle)

    def _scan(self, table, cols, convert):
        out = []
        for offset in range(0, SCAN_CAP, PAGE):
            rows = self.app.zcql().execute_query(
                f'SELECT {cols} FROM {table} ORDER BY ROWID LIMIT {offset}, {PAGE}') or []
            out.extend(convert(r[table]) for r in rows)
            if len(rows) < PAGE:
                break
        return out


class MemoryStore:
    name = 'memory'

    def __init__(self):
        self._lock = threading.Lock()
        self._shipments = {}
        self._fleet = []

    @classmethod
    def with_demo_data(cls):
        store = cls()
        now = datetime.now(timezone.utc)

        def demo(suffix, days_ago, status, origin, destination, mode, kg, cost, loc, name):
            created = now - timedelta(days=days_ago)
            tracking_id = f"APX-{created.strftime('%Y%m%d')}-{suffix}"
            store._shipments[tracking_id] = {
                'rowId': tracking_id, 'trackingId': tracking_id, 'status': status, 'customerName': name,
                'email': 'demo@example.com', 'origin': origin, 'destination': destination, 'currentLocation': loc,
                'mode': mode, 'weightKg': kg, 'estimatedCost': cost,
                'estimatedDelivery': (created + timedelta(days=6)).strftime('%Y-%m-%d'),
                'createdAt': created.strftime('%Y-%m-%dT%H:%M:%SZ'), 'updatedAt': created.strftime('%Y-%m-%dT%H:%M:%SZ'),
            }

        demo('DEMO0001', 3, 'In Transit', 'bhubaneswar', 'delhi', 'road', 8400, 91234, 'Nagpur Hub', 'Tata Steel Ltd')
        demo('DEMO0002', 9, 'In Transit', 'paradeep', 'rotterdam', 'ocean', 18000, 527574, 'Arabian Sea', 'Reliance Retail')
        demo('DEMO0003', 0, 'Pending', 'mumbai', 'london', 'air', 320, 35304, 'Mumbai', 'Kalinga Foods')
        store._fleet = [
            {'vehicleId': 'TRK-101', 'type': 'Truck', 'name': 'Tata Prima 5530', 'status': 'Active', 'location': 'Nagpur'},
            {'vehicleId': 'VSL-301', 'type': 'Vessel', 'name': 'MV Apex Utkal', 'status': 'Active', 'location': 'Arabian Sea'},
            {'vehicleId': 'AIR-401', 'type': 'Aircraft', 'name': 'Boeing 737-800BCF', 'status': 'Idle', 'location': 'Mumbai (BOM)'},
        ]
        return store

    def ping(self):
        return True

    def find(self, tracking_id):
        with self._lock:
            s = self._shipments.get(tracking_id)
            return copy.deepcopy(s) if s else None

    def insert(self, s):
        with self._lock:
            if s['trackingId'] in self._shipments:
                raise DuplicateKey(s['trackingId'])
            self._shipments[s['trackingId']] = {**copy.deepcopy(s), 'rowId': s['trackingId']}

    def update(self, row_id, changes):
        with self._lock:
            self._shipments[row_id].update(changes)

    def list_shipments(self):
        with self._lock:
            return [copy.deepcopy(s) for s in self._shipments.values()]

    def list_fleet(self):
        with self._lock:
            return copy.deepcopy(self._fleet)


_memory_store = None
_memory_lock = threading.Lock()


def reset_memory_store():
    global _memory_store
    with _memory_lock:
        _memory_store = None


def get_store(request):
    """Return the store for this request. On AppSail the Catalyst SDK is initialised from the request headers
    (Catalyst forwards the project credentials in x-zc-* headers)."""
    global _memory_store
    if os.environ.get('STORE_BACKEND', 'catalyst').lower() == 'memory':
        with _memory_lock:
            if _memory_store is None:
                _memory_store = MemoryStore.with_demo_data()
            return _memory_store
    import zcatalyst_sdk  # imported here so local development works without the SDK installed
    return CatalystStore(zcatalyst_sdk.initialize(req=request))
