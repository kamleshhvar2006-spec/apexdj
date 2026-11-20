<<<<<<< HEAD
# APEX Logistics: Django on Zoho Catalyst AppSail

One AppSail service runs Django. It serves the website at `/` and the API under `/api`, so the browser and the API share one domain (no CORS). Data is stored in the Catalyst Data Store.

```
Browser ──► https://<service>-<ZAID>.development.catalystappsail.<tld>
                 /          → frontend/index.html
                 /api/...   → Django (gunicorn) ──► Catalyst Data Store (Shipments, Fleet)
```

## Files

| Path | Purpose |
|---|---|
| `frontend/index.html` | the website (`API_BASE` is `/api`) |
| `apex/` | Django project: settings, urls, wsgi |
| `logistics/views.py` | the API endpoints |
| `logistics/store.py` | Data Store access (`CatalystStore`) and an in-memory store for local runs |
| `logistics/pricing.py`, `auth.py` | freight pricing; admin password check and signed tokens |
| `logistics/tests.py` | 21 tests, no Catalyst account needed |
| `tools/make_admin_hash.py` | makes the admin password hash and session secret |
| `requirements.txt` | Django 5.2 LTS, gunicorn, zcatalyst-sdk |

API: `GET /api/track/<id>`, `POST /api/bookings`, `POST /api/admin/login`, `GET /api/admin/dashboard`, `PATCH /api/admin/shipments/<id>` (admin routes need the `X-Apex-Token` header), `GET /api/health` (add `?check=store` to test the Data Store tables).

## Run locally (no Catalyst needed)

```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python tools/make_admin_hash.py "YourStrongPassword"      # prints two values used below
export STORE_BACKEND=memory ADMIN_EMAIL=you@example.com ADMIN_PASSWORD_HASH=<printed> SESSION_SECRET=<printed>
python manage.py runserver                                # http://127.0.0.1:8000  (sample data, resets on restart)
STORE_BACKEND=memory python manage.py test                # run the tests
```

## Data Store tables (Catalyst console → Data Store; names and columns are case-sensitive)

**Shipments**: `trackingId` Var Char 40 (Is Unique, Is Mandatory), `shipStatus` Var Char 30, `customerName` Var Char 100, `email` Var Char 150, `origin` Var Char 40, `destination` Var Char 40, `currentLocation` Var Char 150, `transportMode` Var Char 10, `weightKg` Double, `estimatedCost` Double, `estimatedDelivery` Var Char 20, `createdAt` Var Char 30, `updatedAt` Var Char 30.

**Fleet**: `vehicleId` Var Char 20 (Is Unique), `vehicleType`, `vehicleName`, `vehicleStatus`, `vehicleLocation` (Var Char 100 each). Add a few rows by hand.

These are the same tables the Node.js Catalyst version uses.

## Environment variables (set in the AppSail service in the Catalyst console)

| Name | Value |
|---|---|
| `ADMIN_EMAIL` | the email you will type on the admin login form |
| `ADMIN_PASSWORD_HASH` | from `python tools/make_admin_hash.py "YourPassword"` |
| `SESSION_SECRET` | from the same command |
| `ALLOWED_HOSTS` | only if you get "Invalid HTTP_HOST header": your AppSail host name, comma-separated with any others |
| `CORS_ALLOWED_ORIGINS` | only if the website is hosted on another domain (see below) |

Development and production keep separate values for each variable.

## Deploy

```bash
npm install -g zcatalyst-cli
catalyst login
cd apex-django

# 1. Install dependencies into ./vendor for AppSail's Linux runtime.
#    Use the same Python version you pick in step 2 (3.11 or 3.12 recommended).
python3 -m pip install -r requirements.txt -t vendor --upgrade \
  --platform manylinux2014_x86_64 --python-version 3.12 --implementation cp --only-binary=:all:

# 2. Link this folder to your Catalyst project and create the AppSail service.
catalyst init
#    pick your project → AppSail → Catalyst-Managed Runtime → sample app: N → this is the source directory: Y
#    name: apex_django → build path: this folder → stack: Python 3.12 (or 3.11)

# 3. Open the generated app-config.json and set the startup command (keep the stack and build path the CLI wrote):
#    "command": "sh -c 'PYTHONPATH=./vendor python3 -m gunicorn apex.wsgi:application --bind 0.0.0.0:${X_ZOHO_CATALYST_LISTEN_PORT} --workers 1 --threads 8 --timeout 30 --access-logfile -'"
#    "memory": 256

# 4. Deploy.
catalyst deploy
```

Then set the environment variables in the console and open the URL the CLI printed. Check `<URL>/api/health?check=store` first: `{"status": "ok", ..., "tables": "ok"}` means the Data Store tables and columns are right.

If gunicorn will not start, the documented fallback command is `sh -c 'python3 -u manage.py runserver 0.0.0.0:${X_ZOHO_CATALYST_LISTEN_PORT} --noreload'`.

## Hosting the website separately (optional)

Deploy `frontend/index.html` with Catalyst Web Client Hosting (a `client` folder with `index.html` and `client-package.json`), change `API_BASE` in it to `https://<your AppSail URL>/api`, and set `CORS_ALLOWED_ORIGINS` on the AppSail service to the website's origin, for example `https://<project-domain>.development.catalystserverless.in`.

## Notes and limits

- The vendored dependencies are about 60 MB. AppSail restricts writing files in the app directory, which is why nothing is stored on disk.
- The login lockout (8 failures per 15 minutes) is held in the process's memory. For a hard limit use Catalyst API Gateway throttling on `/api/admin/login`.
- One admin account, no MFA. For several staff members, move to Catalyst Authentication.
- The dashboard reads up to 6,000 shipments per request (300 per Data Store query).
- Production needs a payment method in Catalyst; the development environment is free.
"# apexdynamo" 
=======
# vdart-project
>>>>>>> 251a51b27f06984682608b7ba18736aa40be8008
