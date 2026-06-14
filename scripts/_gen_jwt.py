#!/usr/bin/env python3
"""Generate a JWT for a given username (works around the broken login endpoint).

Usage:
  python3 _gen_jwt.py <username>
"""
import os
import sys
import time
import jwt

if len(sys.argv) != 2:
    print("usage: _gen_jwt.py <username>", file=sys.stderr)
    sys.exit(2)

username = sys.argv[1]

# Map username -> user_id from the seed/dev data.
user_ids = {
    "demo": "user_f156a6ac55c2",
    "leader": "user_f29cff535b4d",
}
if username not in user_ids:
    print(f"unknown user: {username}; known: {list(user_ids)}", file=sys.stderr)
    sys.exit(2)

secret = os.environ.get("JWT_SECRET", "devflow-jwt-secret-change-in-production")
algorithm = os.environ.get("JWT_ALGORITHM", "HS256")

now = int(time.time())
payload = {
    "sub": user_ids[username],
    "username": username,
    "iat": now,
    "exp": now + 24 * 3600,
}
token = jwt.encode(payload, secret, algorithm=algorithm)
print(token)
