"""Explicit admin credentials for proxies; direct loopback remains a local demo mode."""
import os
import secrets
from ipaddress import ip_address
from urllib.parse import urlparse


def _local_host(host):
    if host == 'localhost':
        return True
    try:
        return ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False


def authorized(request):
    if os.getenv('WHYGRAPH_PUBLIC', 'false').lower() == 'true':
        return False
    expected = os.getenv('WHYGRAPH_ADMIN_TOKEN', '')
    if expected:
        supplied = request.headers.get('authorization', '')
        return secrets.compare_digest(supplied.encode(), ('Bearer ' + expected).encode())
    # A forwarded loopback connection is not a direct local administrative
    # session. Proxy deployments must configure the credential above.
    if any(key.lower() == 'forwarded' or key.lower().startswith('x-forwarded-') for key in request.headers):
        return False
    origin = request.headers.get('origin')
    return bool(request.client and _local_host(request.client.host) and
                _local_host(request.url.hostname) and
                (not origin or _local_host(urlparse(origin).hostname)))
