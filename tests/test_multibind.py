"""Real local TCP checks plus parsing/configuration/URI regressions."""
import asyncio
import contextlib
import io
import json
import logging
import socket
from unittest.mock import patch

import pytest

from proxy.config import ProxyConfig, parse_dc_ip_list
from proxy.listeners import DEFAULT_HOSTS, format_link_host, parse_hosts, proxy_links
from proxy import tg_ws_proxy
import windows_service


def test_parse_hosts():
    assert parse_hosts(' 127.0.0.1, [::1],::1,127.0.0.1 ') == ['127.0.0.1', '::1']
    assert parse_hosts(['192.168.0.16', '2001:db8::16']) == ['192.168.0.16', '2001:db8::16']
    assert parse_hosts(DEFAULT_HOSTS) == ['0.0.0.0', '::']
    assert parse_hosts('PROXY.example') == ['proxy.example']


@pytest.mark.parametrize('value', ['', [], None, ',::', '127.0.0.1,', [''],
                                          ['::1', None], '::g', 'https://x', 'a&b', 'x:1443'])
def test_rejects_invalid_hosts(value):
    with pytest.raises(ValueError):
        parse_hosts(value)


def test_ipv6_and_nat_links():
    assert format_link_host('2001:db8::16') == '[2001:db8::16]'
    assert format_link_host('[::1]') == '[::1]'
    assert format_link_host('fe80::1%en0') == '[fe80::1%25en0]'
    links = proxy_links('192.168.0.16,2001:db8::16', 1443, '', 'proxy.example')
    assert len(links) == 3
    assert '?server=192.168.0.16&port=1443&secret=dd' in links[0]
    assert '?server=[2001:db8::16]&port=1443' in links[1]
    assert '?server=proxy.example&port=1443' in links[2]
    assert len(proxy_links('::1', 1443, '', '::1')) == 1
    assert proxy_links('::1', 1443, '', fake_tls_domain='example.com')[0].endswith(
        'secret=ee' + 'example.com'.encode().hex())


def test_outbound_ipv6_is_explicit():
    with pytest.raises(ValueError):
        parse_dc_ip_list(['2:2001:db8::2'])
    assert parse_dc_ip_list(['2:[2001:db8::2]'], ipv6=True) == {2: '2001:db8::2'}
    assert parse_dc_ip_list(['2:149.154.167.220'], ipv6=True) == {2: '149.154.167.220'}


def test_json_config_cli_precedence_and_print_links(tmp_path, capsys):
    path = tmp_path / 'config.json'
    # Synthetic test value, not a deployment credential; never printed by tests.
    path.write_text(json.dumps({'host': ['127.0.0.1', '::1'], 'port': 23456,
                                    'secret': 'ab' * 16, 'public_host': 'proxy.example',
                                    'dc_ip': ['2:1.2.3.4']}))
    config = ProxyConfig()
    with patch.object(tg_ws_proxy, 'proxy_config', config):
        args = tg_ws_proxy.configure(['--config', str(path), '--port', '23457',
                                     '--dc-ip', '4:1.2.3.5'])
        assert args.port == 23457
        assert config.host == '127.0.0.1,::1'
        assert config.dc_redirects == {4: '1.2.3.5'}
        tg_ws_proxy.main(['--config', str(path), '--print-links'])
    output = capsys.readouterr().out
    assert len(output.splitlines()) == 3
    assert 'server=[::1]' in output
    assert 'server=proxy.example' in output


@pytest.mark.parametrize('data', [{'host': '127.0.0.1,'}, {'port': 0},
                                  {'port': True}, {'port': 1.5}, {'ipv6': 'yes'},
                                  {'dc_ip': '2:1.2.3.4'}, {'unknown': 1}, []])
def test_bad_json_config(data, tmp_path, capsys):
    path = tmp_path / 'bad.json'
    path.write_text(json.dumps(data))
    with pytest.raises(SystemExit):
        tg_ws_proxy.configure(['--config', str(path)])
    capsys.readouterr()


def test_defaults():
    with patch.object(tg_ws_proxy, 'proxy_config', ProxyConfig()):
        args = tg_ws_proxy.configure([])
        assert args.host == DEFAULT_HOSTS
        assert not args.ipv6


def test_log_does_not_contain_links_and_console_dns_is_intact(tmp_path):
    previous_handlers = logging.root.handlers[:]
    previous_level = logging.root.level
    output = io.StringIO()
    path = tmp_path / 'proxy.log'
    try:
        with patch.object(tg_ws_proxy, 'proxy_config', ProxyConfig()):
            args = tg_ws_proxy.configure(['--log-file', str(path)])
        with contextlib.redirect_stderr(output):
            tg_ws_proxy.setup_logging(args)
        logging.getLogger('tg-mtproto-proxy').info(
            'tg://proxy?server=proxy.example&port=1443', extra={'proxy_link': True})
        logging.getLogger('tg-mtproto-proxy').info('listener ready')
        assert 'proxy.example' in output.getvalue()
        assert 'tg://' not in path.read_text()
        assert 'listener ready' in path.read_text()
    finally:
        for handler in logging.root.handlers[:]:
            if handler not in previous_handlers:
                logging.root.removeHandler(handler)
                handler.close()
        logging.root.setLevel(previous_level)


def test_service_paths_and_config_preservation(tmp_path):
    with patch.dict('os.environ', {'ProgramData': str(tmp_path)}):
        path = windows_service.ensure_service_config(23456)
        original = path.read_bytes()
        assert path == tmp_path / 'tg-ws-proxy' / 'config.json'
        assert json.loads(original)['host'] == DEFAULT_HOSTS
        assert json.loads(original)['port'] == 23456
        assert len(json.loads(original)['secret']) == 32
        windows_service.ensure_service_config(34567)
        assert path.read_bytes() == original


def test_ipv4_and_ipv6_accept_real_clients():
    """Exercise the full proxy, handshake reader and graceful stop; no upstream."""
    async def run():
        config = ProxyConfig(host='127.0.0.1,::1', port=0, dc_redirects={},
                             pool_size=0, fallback_cfproxy=False,
                             cfproxy_h2_media=False)
        stop = asyncio.Event()
        ready = asyncio.Event()
        with patch.object(tg_ws_proxy, 'proxy_config', config), \
                patch('proxy.pool.proxy_config', config):
            task = asyncio.create_task(tg_ws_proxy._run(stop, on_ready=ready.set))
            try:
                await asyncio.wait_for(ready.wait(), 3)
                server = tg_ws_proxy._server_instance
                addresses = {s.getsockname()[0] for s in server.sockets}
                assert addresses == {'127.0.0.1', '::1'}
                ports = {s.getsockname()[1] for s in server.sockets}
                assert len(ports) == 1
                port = ports.pop()
                for host in ('127.0.0.1', '::1'):
                    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), 2)
                    writer.close()
                    await writer.wait_closed()
                    assert await asyncio.wait_for(reader.read(), 2) == b''
                stop.set()
                await asyncio.wait_for(task, 3)
                assert tg_ws_proxy._server_instance is None
                assert not tg_ws_proxy._client_tasks
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


def test_wildcards_do_not_conflict():
    async def run():
        async def client(reader, writer):
            writer.close()
            await writer.wait_closed()
        server = await tg_ws_proxy.start_listener(client, DEFAULT_HOSTS, 0)
        try:
            assert {s.family for s in server.sockets} == {socket.AF_INET, socket.AF_INET6}
            for host in ('127.0.0.1', '::1'):
                _, writer = await asyncio.wait_for(asyncio.open_connection(
                    host, server.sockets[0].getsockname()[1]), 2)
                writer.close()
                await writer.wait_closed()
        finally:
            server.close()
            await server.wait_closed()
    asyncio.run(run())


def test_failed_bind_releases_other_listener():
    async def run():
        occupied = await asyncio.start_server(lambda r, w: w.close(), '::1', 0)
        port = occupied.sockets[0].getsockname()[1]
        try:
            with pytest.raises(OSError):
                await tg_ws_proxy.start_listener(lambda r, w: w.close(), '127.0.0.1,::1', port)
            server = await asyncio.start_server(lambda r, w: w.close(), '127.0.0.1', port)
            server.close()
            await server.wait_closed()
        finally:
            occupied.close()
            await occupied.wait_closed()
    asyncio.run(run())


def test_unavailable_address_is_not_silently_skipped():
    async def run():
        with pytest.raises(OSError):
            await tg_ws_proxy.start_listener(lambda r, w: w.close(),
                                              '127.0.0.1,192.0.2.1', 0)
    asyncio.run(run())
