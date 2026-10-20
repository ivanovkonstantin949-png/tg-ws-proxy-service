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
    assert package.get('UpgradeCode') == 'E83E6106-BDC7-47E2-9655-4249DDD7E664'
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
    firewall = root.find('.//f:FirewallException', WXS)
    assert firewall.get('Port') == '[PROXYPORT]'
    assert firewall.get('Program') == '[#ProxyExe]'
    assert firewall.get('Protocol') == 'tcp'
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
    assert 'packaging/service.spec' in commands
    assert '-arch x64' in commands
    assert 'wix --version 4.0.6' in commands
    assert 'WixToolset.Firewall.wixext/4.0.6' in commands
    assert 'WixToolset.Util.wixext/4.0.6' in commands
    assert 'windows-msi-smoke.ps1' in commands
    upload = next(s for s in job['steps'] if s.get('name') == 'Upload MSI and executable')
    assert upload['with']['name'] == 'tg-ws-proxy-x64.msi'
    assert 'dist/tg-ws-proxy-x64.msi' in upload['with']['path']


def test_license_is_original_and_version_consistent():
    license_text = (ROOT / 'LICENSE').read_text()
    assert 'MIT License' in license_text
    assert 'Copyright (c) 2026 Flowseal' in license_text
    version_text = (ROOT / 'packaging/service_version.txt').read_text()
    assert re.search(r'filevers=\(1, 11, 3, 0\)', version_text)
