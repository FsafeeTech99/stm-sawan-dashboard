"""Create a local runtime, then serve the dashboard only on this machine."""
import argparse
import hashlib
import os
from pathlib import Path
import socket
import subprocess
import sys
import venv
import webbrowser


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument('--python', help='Existing Python with app dependencies (optional)')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        raise SystemExit('Please install Python 3.11 or newer.')
    if args.python:
        runtime = Path(args.python).resolve()
        if not runtime.is_file():
            raise SystemExit('Python runtime not found')
    else:
        env_dir = root / '.venv'
        runtime = env_dir / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        if not runtime.exists():
            print('Creating local Python environment...')
            venv.create(env_dir, with_pip=True)
        requirements = root / 'requirements.txt'
        fingerprint = hashlib.sha256(requirements.read_bytes()).hexdigest()
        marker = env_dir / 'khamtech-requirements.sha256'
        if not marker.exists() or marker.read_text() != fingerprint:
            print('Installing app dependencies from PyPI...')
            subprocess.run([str(runtime), '-m', 'pip', 'install', '-r', str(requirements)], cwd=root, check=True)
            marker.write_text(fingerprint)
    port = args.port
    if not port:
        for candidate in range(8501, 8511):
            try:
                with socket.socket() as probe:
                    probe.bind(('127.0.0.1', candidate))
                port = candidate
                break
            except OSError:
                continue
    if not 1 <= port <= 65535:
        raise SystemExit('No available local port; pass --port NUMBER')
    env = os.environ.copy()
    env['KHAMTECH_LOCAL'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    url = f'http://127.0.0.1:{port}'
    print(f'KhamTechReCheck: {url}', flush=True)
    print('Local mode. Close this console / press Ctrl+C to stop.', flush=True)
    command = [str(runtime), '-m', 'streamlit', 'run', str(root / 'app.py'),
               '--server.address=127.0.0.1', f'--server.port={port}', '--server.headless=true',
               '--browser.gatherUsageStats=false']
    server = subprocess.Popen(command, cwd=root, env=env)
    try:
        if not args.no_browser:
            webbrowser.open(url)
        return server.wait()
    except KeyboardInterrupt:
        server.terminate()
        return server.wait()


if __name__ == '__main__':
    sys.exit(main())
