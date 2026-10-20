"""Portable contract checks. Real MSI/SCM acceptance is in Windows Actions."""
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import yaml

ROOT = Path(__file__).resolve().parents[1]
WXS = {'w': 'http://wixtoolset.org/schemas/v4/wxs',
       'f': 'http://wixtoolset.org/schemas/v4/wxs/firewall',
       'u': 'http://wixtoolset.org/schemas/v4/wxs/util'}


def test_wix_service_firewall_and_uninstall_contract():
    root = ET.parse(ROOT / 'packaging/msi/Package.wxs').getroot()
    package = root.find('w:Package', WXS)
    assert package.get('Version') == '1.11.3'
    assert package.get('Codepage') == '1251'  # Cyrillic firewall display names.
    assert package.get('UpgradeCode') == 'E83E6106-BDC7-47E2-9655-4249DDD7E664'
    folder = root.find(".//w:StandardDirectory[@Id='ProgramFiles64Folder']/"
                       "w:Directory[@Name='Flowseal']/w:Directory[@Id='INSTALLFOLDER']", WXS)
    assert folder is not None
    assert folder.get('Name') == 'TG Proxy'
    service = root.find('.//w:ServiceInstall', WXS)
    assert service.get('Name') == 'TgWsProxy'
    assert service.get('Start') == 'auto'
    assert service.get('Arguments') == '--service --initial-port [PROXYPORT]'
    assert service.get('Account') == 'LocalSystem'
    recovery = service.find('u:ServiceConfig', WXS)
    assert recovery.get('FirstFailureActionType') == 'restart'
    control = root.find('.//w:ServiceControl', WXS)
    assert control.get('Stop') == 'both'
    assert control.get('Remove') == 'uninstall'
    assert control.get('Wait') == 'yes'
    rules = root.findall('.//f:FirewallException', WXS)
    assert len(rules) == 2
    rules_by_name = {rule.get('Name'): rule for rule in rules}
    program = rules_by_name['TG Proxy (программа)']
    assert program.get('Program') == '[#ProxyExe]'
    assert program.get('Port') is None
    port = rules_by_name['TG Proxy TCP порт']
    assert port.get('Port') == '[PROXYPORT]'
    assert port.get('Protocol') == 'tcp'
    assert port.get('Program') is None
    component = folder.find("w:Component[@Id='ProxyService']", WXS)
    assert component is not None
    for rule in rules:
        assert rule in list(component)
        assert rule.get('Profile') == 'all'
        assert rule.get('Scope') == 'any'
        assert rule.get('IgnoreFailure') == 'no'
    assert root.find('.//w:PermissionEx', WXS).get('Sddl').startswith('D:P')
    assert root.find('.//w:MajorUpgrade', WXS) is not None


def test_workflow_yaml_and_build_commands():
    workflow = yaml.safe_load((ROOT / '.github/workflows/build-msi.yml').read_text())
    assert 'workflow_dispatch' in workflow['on']
    job = workflow['jobs']['build-msi']
    assert job['runs-on'] == 'windows-latest'
    setup = next(s for s in job['steps'] if s.get('uses', '').startswith('actions/setup-python@'))
    assert setup['with']['python-version'] == '3.11'
    assert setup['with']['architecture'] == 'x64'
    commands = '\n'.join(s.get('run', '') for s in job['steps'])
    test_step = next(s for s in job['steps'] if s.get('name') == 'Compile and test')
    assert 0 < test_step['timeout-minutes'] <= 5
    assert "python -m pytest tests -q '@tests/ci-pytest-args.txt'" in test_step['run']
    assert 'packaging/service.spec' in commands
    assert '-arch x64' in commands
    assert 'wix --version 4.0.6' in commands
    assert 'WixToolset.Firewall.wixext/4.0.6' in commands
    assert 'WixToolset.Util.wixext/4.0.6' in commands
    assert 'windows-msi-smoke.ps1' in commands
    upload = next(s for s in job['steps'] if s.get('name') == 'Upload MSI and executable')
    assert upload['with']['name'] == 'tg-ws-proxy-x64.msi'
    assert 'dist/tg-ws-proxy-x64.msi' in upload['with']['path']


def test_ci_exclusions_are_exact_upstream_cases_and_shared_with_verify():
    args = (ROOT / 'tests/ci-pytest-args.txt').read_text().splitlines()
    assert args[:2] == ['--timeout=30', '--timeout-method=thread']
    prefix = '--deselect=tests/test_h2_transport.py::H2WireTest::'
    names = {
        'test_body_tail_does_not_wait_for_unrelated_long_polls',
        'test_busy_channel_recovers_old_request_despite_newer_replies',
        'test_idle_poll_preserves_slot_for_new_overdue_request',
        'test_obfuscated_clients_preserve_packets_through_full_h2_fallback',
        'test_normal_long_poll_survives_six_seconds_and_delivers_late_reply',
    }
    assert set(args[2:]) == {prefix + name for name in names} | {
        '--deselect=tests/test_cf_h2.py::HttpMultiplexTest::'
        'test_unhelpful_replies_do_not_cause_unbounded_recovery',
    }
    for arg in args[2:]:
        file, _, name = arg.removeprefix('--deselect=').split('::')
        assert f'async def {name}(' in (ROOT / file).read_text()
    assert '@tests/ci-pytest-args.txt' in (ROOT / 'verify.sh').read_text()
    assert 'pytest-timeout==2.4.0' in (ROOT / 'packaging/requirements-test.txt').read_text()


def test_license_is_original_and_version_consistent():
    license_text = (ROOT / 'LICENSE').read_text()
    assert 'MIT License' in license_text
    assert 'Copyright (c) 2026 Flowseal' in license_text
    version_text = (ROOT / 'packaging/service_version.txt').read_text()
    assert re.search(r'filevers=\(1, 11, 3, 0\)', version_text)
