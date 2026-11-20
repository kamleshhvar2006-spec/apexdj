"""Make the admin login secrets.

Usage:  python tools/make_admin_hash.py "YourStrongPassword"

Prints ADMIN_PASSWORD_HASH and SESSION_SECRET. Paste them (plus ADMIN_EMAIL) into the AppSail service's
environment variables in the Catalyst console. Never commit or share the output.
"""
import hashlib
import secrets
import sys

if len(sys.argv) != 2 or len(sys.argv[1]) < 10:
    sys.exit('Usage: python tools/make_admin_hash.py "<password with at least 10 characters>"')

salt = secrets.token_bytes(16)
digest = hashlib.scrypt(sys.argv[1].encode('utf-8'), salt=salt, n=16384, r=8, p=1, dklen=64, maxmem=64 * 1024 * 1024)
print(f'\nADMIN_PASSWORD_HASH=scrypt:{salt.hex()}:{digest.hex()}')
print(f'SESSION_SECRET={secrets.token_hex(48)}')
print('\nAlso set ADMIN_EMAIL to the email you will type on the login form.\n')
