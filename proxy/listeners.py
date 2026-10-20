"""Shared address parsing and Telegram links (no socket or network activity)."""
import ipaddress
import re
from urllib.parse import quote


DEFAULT_HOSTS = '0.0.0.0,::'


def parse_hosts(value):
    """Accept comma-separated hosts or a JSON list; preserve order, deduplicate."""
    if isinstance(value, str):
        value = value.split(',')
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError('host must be a nonempty comma-separated string or list')
    hosts = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError('host contains an empty or non-string entry')
        host = entry.strip()
        if host.startswith('[') and host.endswith(']'):
            host = host[1:-1]
        try:
            host = str(ipaddress.ip_address(host))
        except ValueError:
            if (len(host) > 253 or not re.fullmatch(
                    r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?', host)
                    or any(not label or len(label) > 63 or label.startswith('-')
                           or label.endswith('-') for label in host.split('.'))):
                raise ValueError('invalid host: use an IP address or DNS name') from None
            host = host.lower()
        if host not in hosts:
            hosts.append(host)
    return hosts


def format_link_host(host):
    host = parse_hosts([host])[0]
    # IPv6 literals are bracketed; zone identifiers are escaped for a URI.
    return '[' + quote(host, safe=':') + ']' if ':' in host else host


def proxy_links(hosts, port, secret, public_host='', fake_tls_domain=''):
    addresses = parse_hosts(hosts)
    if public_host:
        addresses += parse_hosts(public_host)
    prefix = 'ee' if fake_tls_domain else 'dd'
    suffix = fake_tls_domain.encode('ascii').hex() if fake_tls_domain else ''
    return [f'tg://proxy?server={format_link_host(host)}&port={port}'
            f'&secret={prefix}{secret}{suffix}' for host in dict.fromkeys(addresses)]
