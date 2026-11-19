"""Shared helpers for the dual-DXVK (dxvk-legacy) tooling tests.

Everything is driven from the SE4-P7 pin, so a re-derived pin needs no edits
here. Tests that need the pinned GE sources use a local checkout that already
holds them (read-only; clones are --shared or --local into a temp directory).
"""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PIN = ROOT / 'config/ge-proton11-12-se4-p7.env'
COMMON = ROOT / 'scripts/pinned-ge-common.sh'
EXPORT = ROOT / 'scripts/export-dxvk-legacy-source.sh'
LAUNCHER_PATCH = ROOT / 'patches/proton/0002-launcher-add-dxvk-legacy-selection.patch'
MAKEFILE_PATCH = ROOT / 'patches/proposed/dxvk-legacy-build-module.patch'
CANDIDATES = ('ge-proton11-12-se4-p6-rtsp', 'ge-proton11-12-se4-p4-rtsp',
              'ge-proton11-12-se4-p3-rtsp', 'ge-proton11-12-se4-p2-rtsp')

GIT_ENV = {**os.environ, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_NO_LAZY_FETCH': '1',
           'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t.invalid',
           'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t.invalid'}


def pin_values(path=PIN):
    return dict(line.split('=', 1) for line in Path(path).read_text().splitlines()
                if line.startswith('PIN_'))


def run(*args, cwd=None, env=None, check=False, **kw):
    result = subprocess.run([str(a) for a in args], cwd=cwd, env=env or GIT_ENV,
                            text=True, capture_output=True, timeout=300, **kw)
    if check and result.returncode:
        raise AssertionError('%s failed (%d): %s' % (args, result.returncode, result.stderr))
    return result


def git(repo, *args, check=True, env=None):
    return run('git', '-C', repo, *args, check=check, env=env)


def shell(config, script, *args, env=None):
    """Run bash with the common helpers loaded for the given pin."""
    return run('bash', '-eu', '-c',
               'source "$1"; PINNED_GE_CONFIG="$2"; pinned_ge_load_config; ' + script,
               'dxvk-legacy-test', COMMON, config, *args, cwd=ROOT, env=env)


def local_ge_source():
    """A local checkout whose DXVK stores hold every pinned legacy commit, or None."""
    pin = pin_values()
    rows = [('dxvk', pin['PIN_DXVK_LEGACY_COMMIT'])]
    rows += [('dxvk/' + e.split(':')[0], e.split(':')[1])
             for e in pin['PIN_DXVK_LEGACY_NESTED'].split(',')]
    for name in CANDIDATES:
        source = ROOT / 'worktrees' / name
        if all((source / path / '.git').exists() and
               git(source / path, 'cat-file', '-e', commit + '^{commit}', check=False).returncode == 0
               for path, commit in rows):
            return source
    return None


def make_fixture(parent, reference, *, shallow=(), omit=(), local=False):
    """A source root whose dxvk stores are clones of REFERENCE's stores.

    shallow: nested paths replaced by a --depth 1 file:// clone (no legacy commit).
    omit: nested paths left absent. local: full non-shared copies, as the
    submodule materializer makes (clone --local --no-hardlinks --no-checkout).
    """
    pin = pin_values()
    root = Path(parent) / 'source'
    root.mkdir()
    git(root, 'init', '-q')
    paths = ['dxvk'] + ['dxvk/' + e.split(':')[0] for e in pin['PIN_DXVK_LEGACY_NESTED'].split(',')]
    for path in paths:
        if path in omit:
            continue
        dest = root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = reference / path
        if path in shallow:
            run('git', 'clone', '--depth', '1', '--no-checkout', '--quiet', 'file://' + str(src), dest, check=True)
        elif local:
            run('git', 'clone', '--local', '--no-hardlinks', '--no-checkout', '--quiet', src, dest, check=True)
        else:
            run('git', 'clone', '--shared', '--no-checkout', '--quiet', src, dest, check=True)
    # dxvk is a registered gitlink of the root checkout, as in GE.
    head = git(reference / 'dxvk', 'rev-parse', 'HEAD').stdout.strip()
    (root / 'README').write_text('fixture root\n')
    git(root, 'add', 'README')
    git(root, 'update-index', '--add', '--cacheinfo', '160000,%s,dxvk' % head)
    git(root, 'commit', '-q', '-m', 'fixture')
    return root


def pin_with(tmp, name, replacements=(), drop=()):
    """A modified copy of the P7 pin (exact-line replacements and dropped keys)."""
    lines = []
    for line in PIN.read_text().splitlines():
        if any(line.startswith(key + '=') for key in drop):
            continue
        for old, new in replacements:
            if line.startswith(old):
                line = new
        lines.append(line)
    path = Path(tmp) / name
    path.write_text('\n'.join(lines) + '\n')
    return path
