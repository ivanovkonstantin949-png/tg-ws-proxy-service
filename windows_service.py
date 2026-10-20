"""Headless pywin32 service host and frozen EXE entry point.

No GUI imports. MSI owns installation; `service install/start/stop/remove` is
also available for administrators deploying the standalone executable.
"""
import asyncio
import json
import logging
import os
from pathlib import Path
import sys
import threading

from proxy.listeners import DEFAULT_HOSTS
from proxy import tg_ws_proxy

SERVICE_NAME = 'TgWsProxy'


def data_dir():
    return Path(os.environ.get('ProgramData', r'C:\ProgramData')) / 'tg-ws-proxy'


def secure_data_directory():
    import win32security
    directory = data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        'D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)', win32security.SDDL_REVISION_1)
    win32security.SetNamedSecurityInfo(
        str(directory), win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None, None, descriptor.GetSecurityDescriptorDacl(), None)


def ensure_service_config(port=1443):
    directory = data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'config.json'
    # Exclusive creation: repair, upgrade and restart preserve the existing secret.
    try:
        with path.open('x', encoding='utf-8') as stream:
            json.dump({'host': DEFAULT_HOSTS, 'port': port,
                       'secret': os.urandom(16).hex(), 'public_host': '',
                       'ipv6': False}, stream, indent=2)
            stream.write('\n')
    except FileExistsError:
        pass
    return path


def initial_port(argv):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--service', action='store_true')
    parser.add_argument('--initial-port', type=int, default=1443)
    args = parser.parse_args(argv)
    if not 1 <= args.initial_port <= 65535:
        parser.error('initial port must be between 1 and 65535')
    return args.initial_port


def service_class():
    import win32service
    import win32serviceutil

    class TgWsProxyService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = 'Telegram WebSocket Proxy (Flowseal)'
        _svc_description_ = 'MTProto WebSocket bridge with IPv4 and IPv6 listeners'
        _exe_name_ = sys.executable
        _exe_args_ = ('--service' if getattr(sys, 'frozen', False) else
                      '"' + str(Path(__file__).resolve()) + '" --service')

        def __init__(self, args):
            super().__init__(args)
            self.loop = None
            self.stop_event = None
            self.stop_requested = threading.Event()

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING, waitHint=30000)
            self.stop_requested.set()
            loop, stop_event = self.loop, self.stop_event
            if loop is not None and stop_event is not None:
                try:
                    loop.call_soon_threadsafe(stop_event.set)
                except RuntimeError:
                    # The event loop has already finished during service shutdown.
                    pass

        def SvcShutdown(self):
            self.SvcStop()

        def SvcRun(self):
            # Unlike ServiceFramework.SvcRun, report RUNNING only after bind.
            self.ReportServiceStatus(win32service.SERVICE_START_PENDING, waitHint=30000)
            try:
                directory = data_dir()
                secure_data_directory()
                # Configure logging before reading JSON, to retain startup errors.
                from types import SimpleNamespace
                tg_ws_proxy.setup_logging(SimpleNamespace(
                    verbose=False, log_file=str(directory / 'log.txt'),
                    log_max_mb=5, log_backups=2))
                # A service never writes secret-bearing connection links to a log.
                root = logging.getLogger()
                for handler in root.handlers[:]:
                    if type(handler) is logging.StreamHandler:
                        root.removeHandler(handler)
                        handler.close()
                path = ensure_service_config(initial_port(sys.argv[1:]))
                args = tg_ws_proxy.configure(['--config', str(path)])
                root.setLevel(logging.DEBUG if args.verbose else logging.INFO)
                asyncio.run(self.run_async())
                if not self.stop_requested.is_set():
                    raise RuntimeError('proxy stopped without a service stop request')
            except BaseException:
                logging.getLogger(SERVICE_NAME).exception('Service failed')
                logging.shutdown()
                # Exit the process abnormally so SCM restart actions apply even
                # to a config/bind failure; never report a successful STOPPED.
                os._exit(1)
            self.ReportServiceStatus(win32service.SERVICE_STOPPED)

        async def run_async(self):
            self.loop = asyncio.get_running_loop()
            self.stop_event = asyncio.Event()
            if self.stop_requested.is_set():
                self.stop_event.set()

            def ready():
                if not self.stop_requested.is_set():
                    self.ReportServiceStatus(win32service.SERVICE_RUNNING)

            try:
                await tg_ws_proxy._run(self.stop_event, on_ready=ready)
            finally:
                self.loop = None
                self.stop_event = None

    return TgWsProxyService


def main():
    argv = sys.argv[1:]
    if argv and argv[0] == 'service':
        if sys.platform != 'win32':
            raise SystemExit('Service management requires Windows')
        import win32service
        import win32serviceutil
        cls = service_class()
        command = argv[1:]
        if command == ['install']:
            command = ['--startup', 'auto', 'install']
        result = win32serviceutil.HandleCommandLine(cls, argv=[sys.argv[0]] + command)
        if result:
            raise SystemExit(result)
        if command and command[-1] == 'install':
            scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
            try:
                service = win32service.OpenService(scm, SERVICE_NAME, win32service.SERVICE_ALL_ACCESS)
                try:
                    win32service.ChangeServiceConfig2(
                        service, win32service.SERVICE_CONFIG_FAILURE_ACTIONS,
                        {'ResetPeriod': 86400,
                         'Actions': [(win32service.SC_ACTION_RESTART, 5000)] * 3})
                finally:
                    win32service.CloseServiceHandle(service)
            finally:
                win32service.CloseServiceHandle(scm)
        return
    if '--service' in argv:
        if sys.platform != 'win32':
            raise SystemExit('Service hosting requires Windows')
        import servicemanager
        initial_port(argv)
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(service_class())
        servicemanager.StartServiceCtrlDispatcher()
        return
    tg_ws_proxy.main(argv)


if __name__ == '__main__':
    main()
