"""Local account authentication and database-backed sessions."""
import hashlib
import hmac
import secrets


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600000).hex()
    return salt + ':' + digest


def verify_password(password, stored):
    salt, digest = stored.split(':')
    candidate = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600000).hex()
    return hmac.compare_digest(candidate, digest)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()
