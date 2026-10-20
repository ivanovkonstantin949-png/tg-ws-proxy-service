"""macOS/Linux smoke: launch the real CLI process, connect to both families.

No upstream work: redirects, pools and CF refresh are explicitly disabled.
Connection links are consumed in memory and never printed or saved here.
"""
import asyncio
from pathlib import Path
import signal
import socket
import sys


async def main():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    process = await asyncio.create_subprocess_exec(
        sys.executable, '-m', 'proxy.tg_ws_proxy', '--host', '127.0.0.1,::1',
        '--port', str(port), '--dc-ip', '--pool-size', '0', '--no-cfproxy', '--no-h2',
        cwd=Path(__file__).resolve().parents[1],
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    try:
        count = 0
        while count < 2:
            line = await asyncio.wait_for(process.stderr.readline(), 10)
            if not line:
                raise RuntimeError('CLI exited before both listeners were ready')
            if b'Listening on' in line:
                count += 1
        for host in ('127.0.0.1', '::1'):
            _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), 2)
            writer.close()
            await writer.wait_closed()
            print(f'TCP connect {host}:{port}: OK')
        process.send_signal(signal.SIGINT)
        await asyncio.wait_for(process.communicate(), 10)
        if process.returncode != 0:
            raise RuntimeError('CLI failed to stop cleanly')
        print('CLI SIGINT shutdown: exit 0')
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()


if __name__ == '__main__':
    asyncio.run(main())
