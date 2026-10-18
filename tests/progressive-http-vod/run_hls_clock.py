#!/usr/bin/env python3
"""One loopback MediaEngine clock/seek case with private null audio, no host graphics.

Inputs: hls_clock_probe.exe and a synthetic fixture.mp4 / playlist.m3u8 /
segNNN.ts set. The file case also accepts fixture.mkv, fixture.webm or fixture.asf, served
with their proper MIME types. This tests software frame consumption, not
VR/DXGI or a service. Existing MP4/HLS cases and frame/clock oracles are unchanged.
"""
import argparse
from collections import Counter
from contextlib import contextmanager, nullcontext
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import resource
import shutil
import socket
import subprocess
import sys
import threading
import time


@contextmanager
def rtsp_fixture():
    """One fixed synthetic stream in the already-isolated network namespace."""
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    source = Path('/srv/fixtures/fixture.mp4')
    assert hashlib.sha256(source.read_bytes()).hexdigest() == '6c2c44ae74b0c0fa862f7821a6d78d628be3633e7190a6083416ad1ec388248c'
    Path('/srv/lab/mediamtx.yml').write_text(
        'logLevel: info\nrtspAddress: 127.0.0.1:18555\nrtspTransports: [tcp]\n'
        'rtmp: no\nhls: no\nwebrtc: no\nsrt: no\nmoq: no\napi: no\nmetrics: no\npprof: no\n'
        'paths:\n  fixture:\n    source: publisher\n')
    children = []
    with Path('/srv/lab/mediamtx.log').open('wb') as server_log, \
            Path('/srv/lab/publisher.log').open('wb') as publisher_log:
        try:
            children.append(subprocess.Popen(['/srv/inputs/mediamtx', '/srv/lab/mediamtx.yml'],
                                             stdout=server_log, stderr=subprocess.STDOUT))
            deadline = time.monotonic() + 8
            while True:
                if children[0].poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('private RTSP server did not become ready')
                try:
                    with socket.create_connection(('127.0.0.1', 18555), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.05)
            children.append(subprocess.Popen(['/srv/inputs/ffmpeg', '-hide_banner', '-nostdin',
                '-nostats', '-loglevel', 'warning', '-re', '-stream_loop', '-1', '-i', str(source),
                '-map', '0:v:0', '-map', '0:a:0', '-c', 'copy', '-t', '90', '-f', 'rtsp',
                '-rtsp_transport', 'tcp', 'rtsp://127.0.0.1:18555/fixture'],
                stdout=publisher_log, stderr=subprocess.STDOUT))
            deadline = time.monotonic() + 8
            while 'is publishing to path' not in Path('/srv/lab/mediamtx.log').read_text():
                if children[-1].poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('private RTSP publisher did not become ready')
                time.sleep(0.05)
            yield
        finally:
            for child in reversed(children):
                child.terminate()
                try:
                    child.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


def inner(case):
    media_file = os.environ.get('PROBE_MEDIA_FILE', 'fixture.mp4')
    budget_mib = int(os.environ.get('PROBE_HTTP_BYTE_BUDGET_MIB', '32'))
    if budget_mib not in (32, 64, 128, 256) or (case != 'file' and budget_mib != 32):
        raise ValueError('HTTP budget must be 32 MiB, or an explicit 64/128/256 MiB file case')
    http_byte_budget = budget_mib * 1024 * 1024
    http11 = os.environ.get('PROBE_HTTP11') == '1'
    tailseek = os.environ.get('PROBE_HTTP_TAIL_SEEK') == '1'
    stress = os.environ.get('PROBE_SEEK_STRESS') == '1'
    filter_error = os.environ.get('PROBE_FILTER_ERROR') == '1'
    control = os.environ.get('PROBE_CONTROL_STRESS') == '1'
    recovery = os.environ.get('PROBE_FILTER_RECOVERY') == '1'
    # libpulse allocates a 64 MiB memfd even with the private server's SHM
    # transport disabled. A 32 MiB cap killed Wine with SIGXFSZ before playback.
    # This per-file/IPC cap is independent of the HTTP transfer budget.
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    bodies = {} if case == 'rtsp' else {p.name: p.read_bytes() for p in Path('/srv/fixtures').iterdir()
              if p.name in {media_file, 'playlist.m3u8', 'key.bin', 'video.mp4'} or re.fullmatch(r'seg\d{3}\.ts', p.name)
              or (filter_error and p.name == 'clean.mp4')}
    opaque = case in ('hls-opaque', 'hls-opaque-no-range')
    mime_only = opaque or case in ('hls-mime', 'hls-mime-no-range')
    encrypted = b'#EXT-X-KEY:METHOD=AES-128,' in bodies.get('playlist.m3u8', b'')
    if os.environ.get('PROBE_ENCRYPTED_HLS') == '1' and not encrypted:
        raise RuntimeError('AES-128 case requires the encrypted synthetic playlist')
    if case == 'web' or opaque:
        bodies['playlist.m3u8'] = bodies['playlist.m3u8'].replace(b'.ts', b'.js')
        bodies.update({k[:-3] + '.js': v for k, v in list(bodies.items()) if k.endswith('.ts')})
    requests = Counter()
    served = 0
    exhausted = False

    class Handler(BaseHTTPRequestHandler):
        # Co-test fixture behavior: honor the client's Connection:close but
        # do not echo it in the response. Historical controls remain HTTP/1.0.
        protocol_version = 'HTTP/1.1' if http11 else 'HTTP/1.0'

        def log_message(self, *_):
            pass

        def do_GET(self):
            nonlocal served, exhausted
            self.connection.settimeout(3)
            key = self.path.lstrip('/')
            requests[key] += 1
            if sum(requests.values()) > 128:
                exhausted = True
                self.close_connection = True
                return
            if stress and key == 'media':
                key = media_file
            if case == 'hls-hint-wrong-mime':
                key = key.removeprefix('hls_playlist/')
            if (mime_only or case == 'hls-hint-wrong-mime') and key == 'media':
                key = 'playlist.m3u8'
            if key not in bodies:
                self.send_error(404)
                return
            body = bodies[key]
            status, offset, end = 200, 0, len(body)
            range_supported = not (case in ('hls-opaque-no-range', 'hls-mime-no-range')
                                   and key == 'playlist.m3u8')
            if range_supported and self.headers.get('Range'):
                match = re.fullmatch(r'bytes=(\d+)-(\d*)', self.headers['Range'])
                if not match or int(match[1]) >= len(body):
                    self.send_error(416)
                    return
                offset = int(match[1])
                if match[2]:
                    end = min(end, int(match[2]) + 1)
                status, body = 206, body[offset:end]
            if served + len(body) > http_byte_budget:
                exhausted = True
                self.close_connection = True
                return
            self.send_response(status)
            self.send_header('Content-Type', 'application/octet-stream' if case == 'hls-hint-wrong-mime' or key == 'key.bin'
                             else 'application/vnd.apple.mpegurl' if key.endswith('.m3u8')
                             else 'video/mp4' if key.endswith('.mp4')
                             else 'video/webm' if key.endswith('.webm')
                             else 'video/x-ms-asf' if key.endswith('.asf')
                             else 'video/x-msvideo' if key.endswith('.avi')
                             else 'video/x-matroska' if key.endswith('.mkv') else 'video/mp2t')
            self.send_header('Content-Length', str(len(body)))
            if range_supported:
                self.send_header('Accept-Ranges', 'bytes')
            if status == 206:
                self.send_header('Content-Range', f'bytes {offset}-{end - 1}/{len(bodies[key])}')
            self.end_headers()
            served += len(body)
            try:
                if stress:
                    # Same 64 KiB chunks / 4 MiB/s cap as the co-test server.
                    start = time.monotonic()
                    for pos in range(0, len(body), 65536):
                        self.wfile.write(body[pos:pos + 65536])
                        delay = (min(pos + 65536, len(body)) / (4096 * 1024)
                                 - (time.monotonic() - start))
                        if delay > 0:
                            time.sleep(delay)
                else:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass

    server = None
    if case != 'rtsp':
        server = HTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
    for name in ('home', 'run'):
        Path('/srv/lab', name).mkdir(mode=0o700)
    env = dict(os.environ, HOME='/srv/lab/home', XDG_RUNTIME_DIR='/srv/lab/run',
               WINEPREFIX='/srv/lab/prefix',
               WINEDEBUG='-all,err+all,warn+dmo,warn+mfplat' if os.environ.get('PROBE_DIAGNOSTIC') == '1' else '-all',
               WINEDLLOVERRIDES='winemenubuilder.exe=d', WINEESYNC='0', WINEFSYNC='0',
               WINEDLLPATH='/srv/tool/files/lib/vkd3d:/srv/tool/files/lib/wine',
               LD_LIBRARY_PATH='/srv/tool/files/lib/x86_64-linux-gnu:/srv/tool/files/lib:' + os.environ['PROBE_RUNTIME_LIB'],
               PULSE_SERVER='unix:/srv/lab/pulse.sock', PULSE_SINK='probe',
               SteamGameId=os.environ['PROBE_APP_ID'], SteamAppId=os.environ['PROBE_APP_ID'])
    # The outer namespace masks every host service socket; this server has only
    # a null sink and no module-udev-detect or physical audio devices.
    with Path('/srv/lab/pulse.log').open('wb') as pulse_log:
        pulse = subprocess.Popen([os.environ['PROBE_PULSE'], '-n', '--daemonize=no',
                                  '--exit-idle-time=-1', '--disable-shm=true', '--use-pid-file=no',
                                  '--load=module-native-protocol-unix socket=/srv/lab/pulse.sock auth-anonymous=1',
                                  '--load=module-null-sink sink_name=probe rate=48000 channels=2'],
                                 env=env, stdout=pulse_log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 5
            while not Path('/srv/lab/pulse.sock').exists() and time.monotonic() < deadline:
                if pulse.poll() is not None:
                    raise RuntimeError('private audio server failed; inspect pulse.log')
                time.sleep(0.05)
            if not Path('/srv/lab/pulse.sock').exists():
                raise RuntimeError('private audio server readiness timed out')
            path = media_file if case in ('mp4', 'file') else 'playlist.m3u8'
            if stress or mime_only:
                path = 'media'
            if case == 'hls-hint-wrong-mime':
                path = 'hls_playlist/media'
            command = ['/srv/tool/files/bin/wine', r'Z:\srv\inputs\probe.exe',
                       'rtspt://127.0.0.1:18555/fixture' if case == 'rtsp' else
                       f'http://127.0.0.1:{server.server_port}/{path}']
            if case == 'rtsp':
                command.append('--rtsp-live')
            if os.environ.get('PROBE_SEEK_STRESS') == '1':
                command.append('--seek-scrub' if os.environ.get('PROBE_SEEK_SCRUB') == '1' else '--seek-stress')
            if tailseek:
                command.append('--http-tail-seek')
            if filter_error:
                command.append('--expect-filter-error')
            if control:
                command.append('--control-stress')
            if recovery:
                command.append('--filter-recovery-seek')
            try:
                result = subprocess.run(command, env=env, capture_output=True, timeout=75)
            except subprocess.TimeoutExpired as error:
                result = subprocess.CompletedProcess(command, 124, error.stdout or b'', error.stderr or b'')
        finally:
            pulse.terminate()
            try:
                pulse.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pulse.kill()
                pulse.wait()
            if server:
                server.shutdown()
                server.server_close()
    Path('/srv/lab/probe.stdout').write_bytes(result.stdout)
    Path('/srv/lab/probe.stderr').write_bytes(result.stderr)
    phases = [(int(n), bool(int(ok))) for n, ok in re.findall(rb'phase=(\d+) pass=([01])', result.stdout)]
    expected = [(i, True) for i in range(2 if filter_error or control or recovery else 4 if stress or tailseek else 3)]
    key_read = any(path == 'key.bin' or path.endswith('/key.bin') for path in requests)
    passed = (result.returncode == 0 and phases == expected and not exhausted
              and (not encrypted or key_read))
    summary = dict(passed=passed, case=case, exit=result.returncode, phases=phases,
                   http_version=Handler.protocol_version if server else None,
                   http_tail_seek=tailseek,
                   encrypted_hls=encrypted, encryption_key_requested=key_read,
                   seek_stress=stress,
                   seek_scrub=os.environ.get('PROBE_SEEK_SCRUB') == '1',
                   filter_error_case=filter_error,
                   control_stress=control, filter_recovery_seek=recovery,
                   requests=dict(requests), served_bytes=served, budget_exhausted=exhausted,
                   http_byte_budget_bytes=http_byte_budget,
                   scope='MediaEngine clock and software frame transfer; null audio; not endpoint/audio-sync/VR proof')
    Path('/srv/lab/result.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary), flush=True)
    return 0 if passed else 1


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--inner':
        if os.environ.get('PROBE_CONTAINED') != '1':
            raise SystemExit('use outer runner')
        with rtsp_fixture() if sys.argv[2] == 'rtsp' else nullcontext():
            return inner(sys.argv[2])
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('tool', 'probe', 'fixtures', 'output', 'runtime-lib', 'pulseaudio'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--app-id', type=int, required=True)
    parser.add_argument('--case', choices=('mp4', 'hls', 'web', 'file', 'rtsp',
                                         'hls-opaque', 'hls-opaque-no-range',
                                         'hls-mime', 'hls-mime-no-range', 'hls-hint-wrong-mime'), required=True)
    parser.add_argument('--mediamtx', type=Path, help='existing MediaMTX executable for --case rtsp')
    parser.add_argument('--ffmpeg', type=Path, help='existing native publisher for --case rtsp')
    parser.add_argument('--media-file', choices=('fixture.mp4', 'fixture.mkv', 'fixture.webm', 'fixture.asf', 'fixture.avi'),
                        default='fixture.mp4', help='synthetic finite file for --case file only')
    parser.add_argument('--diagnostic', action='store_true', help='bounded warnings/errors on synthetic media only; no trace')
    parser.add_argument('--http11', action='store_true',
                        help='file-only co-test HTTP/1.1 implicit-close response; default remains HTTP/1.0')
    parser.add_argument('--http-tail-seek', action='store_true',
                        help='three tail-to-natural-end/backward-seek cycles; software frames and clock required')
    parser.add_argument('--http-byte-budget-mib', type=int, choices=(32, 64, 128, 256), default=32,
                        help='bounded file-case response allowance for larger seek fixtures; default 32 MiB')
    parser.add_argument('--encrypted-hls', action='store_true',
                        help='require AES-128 fixture and an actual key request, not a mislabeled clear control')
    parser.add_argument('--seek-stress', action='store_true',
                        help='three 10-seek waves replaying co-test positions/cadence, consuming frames')
    parser.add_argument('--seek-scrub', action='store_true',
                        help='stress mode plus Pause/position/Play; caller behavior, not claimed AVPro equivalence')
    parser.add_argument('--filter-error', action='store_true',
                        help='single-corruption fixture: require decode error then manual reopen of clean.mp4')
    parser.add_argument('--filter-recovery-seek', action='store_true',
                        help='investigate explicit same-source seek after single damaged NAL; no auto retry')
    parser.add_argument('--control-stress', action='store_true',
                        help='160 volume/mute/time operations concurrent with frame consumption; no VR emulation')
    args = parser.parse_args()
    if args.http11 and args.case != 'file':
        parser.error('--http11 currently qualifies --case file only')
    if args.http_tail_seek and args.case != 'file':
        parser.error('--http-tail-seek requires --case file')
    if args.http_byte_budget_mib != 32 and args.case != 'file':
        parser.error('--http-byte-budget-mib above 32 requires --case file')
    if args.encrypted_hls and (args.case in ('mp4', 'file', 'rtsp')
            or not (args.fixtures / 'key.bin').is_file()
            or not (args.fixtures / 'playlist.m3u8').is_file()
            or b'#EXT-X-KEY:METHOD=AES-128,' not in (args.fixtures / 'playlist.m3u8').read_bytes()):
        parser.error('--encrypted-hls requires the prepared AES-128 HLS fixture')
    args.seek_stress = args.seek_stress or args.seek_scrub
    if sum((args.filter_error, args.filter_recovery_seek, args.control_stress, args.seek_stress, args.http_tail_seek)) > 1:
        parser.error('select only one probe mode')
    if args.filter_recovery_seek and (args.case != 'file' or args.media_file != 'fixture.mp4'):
        parser.error('--filter-recovery-seek requires --case file --media-file fixture.mp4')
    if args.control_stress and args.case == 'rtsp':
        parser.error('--control-stress currently covers HTTP files/HLS only')
    if args.filter_error and (args.case != 'file' or args.seek_stress or args.media_file != 'fixture.mp4'):
        parser.error('--filter-error requires --case file --media-file fixture.mp4 without seek stress')
    if args.filter_error and not (args.fixtures / 'clean.mp4').is_file():
        parser.error('--filter-error needs the matching clean.mp4 control')
    if args.seek_stress and args.case != 'file':
        parser.error('--seek-stress requires --case file')
    if args.case != 'file' and args.media_file != 'fixture.mp4':
        parser.error('--media-file requires --case file')
    if not 990000 <= args.app_id <= 999999:
        parser.error('synthetic AppID 990000..999999 required; 438100 refused')
    if args.output.exists() or args.output.is_symlink():
        parser.error('output must be a new directory')
    required = [args.tool / 'files/bin/wine', args.probe, args.fixtures / args.media_file,
                args.pulseaudio]
    if args.case not in ('file', 'rtsp'):
        required.append(args.fixtures / 'playlist.m3u8')
    if args.case == 'rtsp':
        if not args.mediamtx or not args.ffmpeg:
            parser.error('--case rtsp requires --mediamtx and --ffmpeg')
        required.extend((args.mediamtx, args.ffmpeg))
    for path in required:
        if not path.is_file():
            parser.error(f'missing input: {path}')
    os.umask(0o077)
    args.output.mkdir(mode=0o700, parents=True)
    command = [shutil.which('bwrap'), '--unshare-all', '--die-with-parent', '--new-session',
               '--ro-bind', '/', '/', '--tmpfs', '/home', '--tmpfs', '/root', '--tmpfs', '/mnt',
               '--tmpfs', '/srv', '--tmpfs', '/run', '--tmpfs', '/tmp', '--tmpfs', '/var/tmp',
               '--proc', '/proc', '--dev', '/dev',
               '--ro-bind', str(args.tool.resolve()), '/srv/tool',
               '--ro-bind', str(args.probe.resolve()), '/srv/inputs/probe.exe',
               '--ro-bind', str(args.fixtures.resolve()), '/srv/fixtures',
               '--ro-bind', str(Path(__file__).resolve()), '/srv/inputs/runner.py',
               '--bind', str(args.output.resolve()), '/srv/lab', '--chdir', '/srv/lab', '--clearenv',
               '--setenv', 'PATH', os.environ['PATH'], '--setenv', 'HOME', '/srv/lab/home',
               '--setenv', 'PROBE_CONTAINED', '1', '--setenv', 'PROBE_APP_ID', str(args.app_id),
               '--setenv', 'PROBE_MEDIA_FILE', args.media_file,
               '--setenv', 'PROBE_HTTP_BYTE_BUDGET_MIB', str(args.http_byte_budget_mib),
               '--setenv', 'PROBE_HTTP11', '1' if args.http11 else '0',
               '--setenv', 'PROBE_HTTP_TAIL_SEEK', '1' if args.http_tail_seek else '0',
               '--setenv', 'PROBE_DIAGNOSTIC', '1' if args.diagnostic else '0',
               '--setenv', 'PROBE_ENCRYPTED_HLS', '1' if args.encrypted_hls else '0',
               '--setenv', 'PROBE_SEEK_STRESS', '1' if args.seek_stress else '0',
               '--setenv', 'PROBE_SEEK_SCRUB', '1' if args.seek_scrub else '0',
               '--setenv', 'PROBE_FILTER_ERROR', '1' if args.filter_error else '0',
               '--setenv', 'PROBE_CONTROL_STRESS', '1' if args.control_stress else '0',
               '--setenv', 'PROBE_FILTER_RECOVERY', '1' if args.filter_recovery_seek else '0',
               '--setenv', 'PROBE_RUNTIME_LIB', str(args.runtime_lib.resolve()),
               '--setenv', 'PROBE_PULSE', str(args.pulseaudio.resolve()),
               str(Path(shutil.which('steam-run')).resolve()), str(Path(sys.executable).resolve()),
               '/srv/inputs/runner.py', '--inner', args.case]
    if args.case == 'rtsp':
        position = command.index('--bind')
        command[position:position] = ['--ro-bind', str(args.mediamtx.resolve()), '/srv/inputs/mediamtx',
                                     '--ro-bind', str(args.ffmpeg.resolve()), '/srv/inputs/ffmpeg']
    return subprocess.run(command, timeout=110).returncode


if __name__ == '__main__':
    raise SystemExit(main())
