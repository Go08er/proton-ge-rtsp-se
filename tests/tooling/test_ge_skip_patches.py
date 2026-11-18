#!/usr/bin/env python3
"""Offline checks for the optional PIN_GE_SKIP_PATCHES pin field.

The field removes named GE patch applications from the generated copy of GE's
protonprep-valve-staging.sh driver. These tests exercise the pin loader, the
driver-generation step (extracted verbatim from prepare-pinned-ge-source.sh)
and the provenance check, with a synthetic driver and tree. A pin without the
field must generate exactly what it generated before.
"""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / 'scripts/pinned-ge-common.sh'
PREPARE = ROOT / 'scripts/prepare-pinned-ge-source.sh'
ENV = dict(os.environ, GIT_NO_LAZY_FETCH='1', PACKAGE_RELEASE='0')
SKIP_REL = 'patches/wine-hotfixes/pending/rtworkq-skip-me.patch'
OTHER_REL = 'patches/wine-hotfixes/pending/other.patch'

DRIVER = '''#!/bin/bash

apply_patch() {
    local patch_path="$1"
    patch -Np1 < "$patch_path"
}

apply_all_in_dir() {
    local dir="$1"
    for patch in "$dir"/*.patch; do
        patch -Np1 < "$patch"
    done
}

    apply_all_in_dir "../patches/protonfixes/"
    apply_all_in_dir "../patches/ge-video-rework/"
    ./tools/make_requests

    # https://example.invalid/issues/899
    echo "WINE: -GAME FIXES- rtworkq: first"
    apply_patch "../patches/wine-hotfixes/pending/rtworkq-skip-me.patch"

    echo "WINE: -GAME FIXES- other"
    apply_patch "../patches/wine-hotfixes/pending/other.patch"
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(*args, **kwargs):
    return subprocess.run(args, env=ENV, text=True, capture_output=True, timeout=120, **kwargs)


def generator_source():
    """The driver-generation heredoc, verbatim from the preparation script."""
    text = PREPARE.read_text()
    match = re.search(
        r'python3 - "\$SOURCE_DIR/patches/protonprep-valve-staging.sh" \\\n.*?<<\'PY\'\n(.*?)\nPY\n',
        text, re.S)
    assert match, 'driver-generation heredoc not found'
    return match.group(1) + '\n'


class Fixture:
    def __init__(self, tmp):
        self.root = Path(tmp)
        (self.root / 'patches/wine-hotfixes/pending').mkdir(parents=True)
        (self.root / SKIP_REL).write_bytes(b'skip me\n')
        (self.root / OTHER_REL).write_bytes(b'other\n')
        (self.root / 'patches/protonprep-valve-staging.sh').write_text(DRIVER)
        self.skip_sha = sha(b'skip me\n')
        (self.root / 'gen.py').write_text(generator_source())

    def generate(self, skip='', driver=None):
        if driver is not None:
            (self.root / 'patches/protonprep-valve-staging.sh').write_text(driver)
        out = self.root / 'generated.sh'
        if out.exists() or out.is_symlink():
            out.unlink()
        proc = run('python3', '-I', str(self.root / 'gen.py'),
                   str(self.root / 'patches/protonprep-valve-staging.sh'),
                   str(out), '0', skip)
        return proc, (out.read_text() if out.exists() else None)


def shell(script, *args):
    return run('bash', '-eu', '-c', 'source "$1"; shift; ' + script, 'x', str(COMMON), *args)


def base_config(extra=''):
    # Any existing schema-5 release pin serves; the export repo lacks the SE3 pins.
    for name in ('ge-proton11-11-se3.env', 'ge-proton11-9-se2-p24.env'):
        if (ROOT / 'config' / name).is_file():
            return (ROOT / 'config' / name).read_text() + extra
    raise unittest.SkipTest('no schema-5 release pin available')


class DriverGeneration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='rtsp-ge-skip-')
        self.addCleanup(self.tmp.cleanup)
        self.fx = Fixture(self.tmp.name)

    def entry(self, rel=SKIP_REL, digest=None):
        return rel + ':' + (digest or self.fx.skip_sha)

    def test_without_field_keeps_the_application(self):
        proc, text = self.fx.generate()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(text.count('apply_patch "../' + SKIP_REL + '"'), 1)
        self.assertNotIn('skipping GE patch', text)
        self.assertNotIn('pinned deviation', text)

    def test_field_removes_exactly_that_application(self):
        base_proc, base = self.fx.generate()
        proc, text = self.fx.generate(self.entry())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn('apply_patch "../' + SKIP_REL + '"', text)
        self.assertEqual(text.count('apply_patch "../' + OTHER_REL + '"'), 1)
        marker = '    echo "WINE: -RTSP- skipping GE patch (pinned deviation): ' + SKIP_REL + '"'
        self.assertEqual(text.count(marker), 1)
        # Only that one line differs from the unskipped output.
        a, b = base.splitlines(), text.splitlines()
        self.assertEqual(len(a), len(b))
        diff = [(x, y) for x, y in zip(a, b) if x != y]
        self.assertEqual(diff, [('    apply_patch "../' + SKIP_REL + '"', marker)])

    def test_hash_mismatch_fails(self):
        proc, text = self.fx.generate(self.entry(digest='0' * 64))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('digest differs', proc.stderr)
        self.assertIsNone(text)

    def test_patch_file_changed_fails(self):
        (self.fx.root / SKIP_REL).write_bytes(b'changed\n')
        proc, _ = self.fx.generate(self.entry())
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('digest differs', proc.stderr)

    def test_missing_patch_file_fails(self):
        (self.fx.root / SKIP_REL).unlink()
        proc, _ = self.fx.generate(self.entry())
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('absent or unsafe', proc.stderr)

    def test_symlinked_patch_file_fails(self):
        (self.fx.root / SKIP_REL).unlink()
        (self.fx.root / SKIP_REL).symlink_to(self.fx.root / OTHER_REL)
        proc, _ = self.fx.generate(self.entry(digest=sha(b'other\n')))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('absent or unsafe', proc.stderr)

    def test_line_absent_fails(self):
        proc, _ = self.fx.generate(self.entry(), driver=DRIVER.replace(
            'apply_patch "../' + SKIP_REL + '"', ': # none'))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('exactly one', proc.stderr)

    def test_line_twice_fails(self):
        line = '    apply_patch "../' + SKIP_REL + '"\n'
        proc, _ = self.fx.generate(self.entry(), driver=DRIVER + line)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('exactly one', proc.stderr)

    def test_other_reference_fails(self):
        proc, _ = self.fx.generate(self.entry(), driver=DRIVER + '# see ' + SKIP_REL + '\n')
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('referenced elsewhere', proc.stderr)

    def test_directory_wholesale_application_fails(self):
        proc, _ = self.fx.generate(self.entry(), driver=DRIVER + (
            '    apply_all_in_dir "../patches/wine-hotfixes/pending/"\n'))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('wholesale', proc.stderr)

    def test_indented_line_variants_are_one_line_only(self):
        # A line that merely contains the application as a substring is not it.
        proc, _ = self.fx.generate(self.entry(), driver=DRIVER.replace(
            '    apply_patch "../' + SKIP_REL + '"', '    xapply_patch "../' + SKIP_REL + '"'))
        self.assertNotEqual(proc.returncode, 0)

    def test_two_entries(self):
        both = self.entry() + ',' + self.entry(OTHER_REL, sha(b'other\n'))
        proc, text = self.fx.generate(both)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn('apply_patch "../patches/wine-hotfixes', text)
        self.assertEqual(text.count('pinned deviation'), 2)

    def test_malformed_entry_fails(self):
        for bad in ('x', SKIP_REL, SKIP_REL + ':abc', '../' + SKIP_REL + ':' + self.fx.skip_sha):
            proc, _ = self.fx.generate(bad)
            self.assertNotEqual(proc.returncode, 0, bad)


DIR_REL = 'patches/protonfixes/0003-skip-me.patch'
DIR_MEMBERS = ('0001-a.patch', '0002-b.patch', '0003-skip-me.patch')
DIR_DRIVER = """#!/bin/bash

# patch functions
apply_patch() {
    local patch_path="$1"
    patch -Np1 < "$patch_path"
}

apply_all_in_dir() {
    local dir="$1"
    for patch in "$dir"/*.patch; do
        apply_patch "$patch"
    done
}

    patch -Np1 < ../patches/dxvk/x.patch
    apply_all_in_dir "../patches/protonfixes/"
    apply_all_in_dir "../patches/ge-video-rework/"
    ./tools/make_requests

    apply_patch "../patches/wine-hotfixes/pending/rtworkq-skip-me.patch"
"""


class DirFixture(Fixture):
    def __init__(self, tmp):
        super().__init__(tmp)
        (self.root / 'patches/protonfixes').mkdir(parents=True)
        for name in DIR_MEMBERS:
            (self.root / 'patches/protonfixes' / name).write_bytes(name.encode() + b'\n')
        self.dir_sha = sha(b'0003-skip-me.patch\n')
        (self.root / 'patches/protonprep-valve-staging.sh').write_text(DIR_DRIVER)


class DirMemberGeneration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='rtsp-ge-skip-dir-')
        self.addCleanup(self.tmp.cleanup)
        self.fx = DirFixture(self.tmp.name)

    def entry(self, rel=DIR_REL, digest=None):
        return rel + ':' + (digest or self.fx.dir_sha)

    def test_dir_member_skip_applied(self):
        proc, text = self.fx.generate(self.entry())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        line = 'echo "WINE: -RTSP- skipping GE patch (pinned deviation): ' + DIR_REL + '"'
        self.assertEqual(text.count(line), 1)
        self.assertEqual(text.count('skipping GE patch'), 1)
        self.assertEqual(text.count('apply_all_in_dir "../patches/protonfixes/"'), 1)
        self.assertEqual(text.count('apply_all_in_dir() {'), 1)
        # Behaviour: run the generated functions over real files and see what applies.
        driver = self.fx.root / 'run.sh'
        funcs = text.split('\n    patch -Np1 --batch --no-backup-if-mismatch < ../patches/dxvk')[0].replace(
            'patch -Np1 --batch --no-backup-if-mismatch <', 'echo APPLIED')
        driver.write_text(funcs + '\ncd "$1/work"\napply_all_in_dir "../patches/protonfixes/"\n')
        (self.fx.root / 'work').mkdir()
        done = run('bash', str(driver), str(self.fx.root))
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = done.stdout.splitlines()
        self.assertEqual([x for x in lines if x.startswith('APPLIED')],
                         ['APPLIED ../patches/protonfixes//0001-a.patch',
                          'APPLIED ../patches/protonfixes//0002-b.patch'])
        self.assertEqual(sum('skipping GE patch' in x for x in lines), 1)
        self.assertEqual(sum('applying GE patch (skip-aware directory)' in x for x in lines), 2)

    def test_only_function_and_nothing_else_changes(self):
        base_proc, base = self.fx.generate()
        proc, text = self.fx.generate(self.entry())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # The call sites and every non-function line are untouched.
        keep = [l for l in base.splitlines() if 'apply_all_in_dir "' in l or 'make_requests' in l]
        for l in keep:
            self.assertIn(l, text.splitlines())
        self.assertEqual(text.count('case "$patch" in'), 1)

    def test_wrong_sha_rejected(self):
        proc, text = self.fx.generate(self.entry(digest='0' * 64))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('digest differs', proc.stderr)
        self.assertIsNone(text)

    def test_file_not_in_dir_rejected(self):
        # Present and hashed, but its directory is not applied by the driver.
        rel = 'patches/elsewhere/0003-skip-me.patch'
        (self.fx.root / 'patches/elsewhere').mkdir()
        (self.fx.root / rel).write_bytes(b'0003-skip-me.patch\n')
        proc, _ = self.fx.generate(self.entry(rel))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('exactly one', proc.stderr)
        # A nonexistent member of the applied directory.
        proc, _ = self.fx.generate(self.entry('patches/protonfixes/0009-none.patch', 'a' * 64))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('absent or unsafe', proc.stderr)
        # A member of a subdirectory is not a direct member of the applied directory.
        (self.fx.root / 'patches/protonfixes/sub').mkdir()
        (self.fx.root / 'patches/protonfixes/sub/0003-skip-me.patch').write_bytes(b'0003-skip-me.patch\n')
        proc, _ = self.fx.generate(self.entry('patches/protonfixes/sub/0003-skip-me.patch'))
        self.assertNotEqual(proc.returncode, 0)

    def test_dir_not_applied_exactly_once_rejected(self):
        twice = DIR_DRIVER + '    apply_all_in_dir "../patches/protonfixes/"\n'
        proc, _ = self.fx.generate(self.entry(), driver=twice)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('exactly one', proc.stderr)
        never = DIR_DRIVER.replace('    apply_all_in_dir "../patches/protonfixes/"\n', '')
        proc, _ = self.fx.generate(self.entry(), driver=never)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('exactly one', proc.stderr)
        # Applied by a different spelling of the directory (no trailing slash).
        other = DIR_DRIVER.replace('"../patches/protonfixes/"', '"../patches/protonfixes"')
        proc, _ = self.fx.generate(self.entry(), driver=other)
        self.assertNotEqual(proc.returncode, 0)

    def test_patch_named_elsewhere_in_driver_rejected(self):
        proc, _ = self.fx.generate(self.entry(), driver=DIR_DRIVER + '# see ' + DIR_REL + '\n')
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('referenced elsewhere', proc.stderr)

    def test_function_text_drift_rejected(self):
        for old, new in (('        apply_patch "$patch"\n', '        apply_patch "$patch" || true\n'),
                         ('local dir="$1"', 'local dir=$1'),
                         ('for patch in "$dir"/*.patch; do', 'for patch in "$dir"/*.patch ; do')):
            drift = DIR_DRIVER.replace(old, new, 1)
            self.assertNotEqual(drift, DIR_DRIVER)
            proc, text = self.fx.generate(self.entry(), driver=drift)
            self.assertNotEqual(proc.returncode, 0, new)
            self.assertIn('apply_all_in_dir definition differs', proc.stderr)
            self.assertIsNone(text)
        # The synthetic single-line fixture's function (inline patch) is also drift.
        proc, _ = self.fx.generate(self.entry(), driver=DRIVER.replace(
            '    apply_all_in_dir "../patches/protonfixes/"\n', '    apply_all_in_dir "../patches/protonfixes/"\n'))
        self.assertNotEqual(proc.returncode, 0)

    def test_mixed_line_and_dir_member(self):
        line_rel = 'patches/wine-hotfixes/pending/rtworkq-skip-me.patch'
        (self.fx.root / 'patches/wine-hotfixes/pending').mkdir(parents=True, exist_ok=True)
        (self.fx.root / line_rel).write_bytes(b'skip me\n')
        for order in (0, 1):
            entries = [self.entry(line_rel, self.fx.skip_sha), self.entry()]
            proc, text = self.fx.generate(','.join(entries[::1 if order == 0 else -1]))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(text.count('skipping GE patch (pinned deviation)'), 2)
            self.assertNotIn('apply_patch "../' + line_rel + '"', text)
            self.assertIn('"../patches/protonfixes//0003-skip-me.patch")', text)


class DirMemberChecks(unittest.TestCase):
    """The state/driver/log provenance checks for both forms."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='rtsp-ge-skip-dirchk-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fx = DirFixture(self.tmp.name)
        self.line_rel = 'patches/wine-hotfixes/pending/rtworkq-skip-me.patch'
        (self.fx.root / 'patches/wine-hotfixes/pending').mkdir(parents=True, exist_ok=True)
        (self.fx.root / self.line_rel).write_bytes(b'skip me\n')
        self.field = ','.join([self.line_rel + ':' + self.fx.skip_sha, DIR_REL + ':' + self.fx.dir_sha])
        proc, text = self.fx.generate(self.field)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.driver = self.root / 'generated.sh'
        self.forms = self.line_rel + '=line,' + DIR_REL + '=dir-member'
        self.state = self.root / 'state.tsv'
        self.log = self.root / 'patch-driver.log'
        self.write_state(self.forms)
        self.write_log()

    def write_state(self, forms):
        text = 'pin_id\tx\nge_skipped_patches\t' + self.field + '\n'
        if forms is not None:
            text += 'ge_skipped_patch_forms\t' + forms + '\n'
        self.state.write_text(text)

    def write_log(self, skip=1, members=('0001-a.patch', '0002-b.patch')):
        lines = ['WINE: -RTSP- skipping GE patch (pinned deviation): ' + DIR_REL] * skip
        lines += ['WINE: -RTSP- applying GE patch (skip-aware directory): patches/protonfixes/' + m for m in members]
        lines.append('WINE: -RTSP- skipping GE patch (pinned deviation): ' + self.line_rel)
        self.log.write_text('\n'.join(lines) + '\n')

    def check(self, args=None, field=None):
        cfg = self.root / 'pin.env'
        cfg.write_text(base_config('PIN_GE_SKIP_PATCHES=' + (field or self.field) + '\n'))
        args = args if args is not None else [self.state, self.driver, self.log, self.root]
        return shell('PINNED_GE_CONFIG="$1"; pinned_ge_load_config; shift; pinned_ge_require_ge_skip_state "$@"',
                     str(cfg), *map(str, args))

    def test_forms_and_records(self):
        cfg = self.root / 'pin.env'
        cfg.write_text(base_config('PIN_GE_SKIP_PATCHES=' + self.field + '\n'))
        proc = shell('PINNED_GE_CONFIG="$1"; pinned_ge_load_config; pinned_ge_ge_skip_records "$2"',
                     str(cfg), str(self.driver))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, 'ge_skipped_patches\t' + self.field + '\nge_skipped_patch_forms\t' + self.forms + '\n')
        # Single-line-only pin: no forms record (byte-identical to before).
        only = self.line_rel + ':' + self.fx.skip_sha
        cfg.write_text(base_config('PIN_GE_SKIP_PATCHES=' + only + '\n'))
        proc = shell('PINNED_GE_CONFIG="$1"; pinned_ge_load_config; pinned_ge_ge_skip_records "$2"; pinned_ge_ge_skip_records',
                     str(cfg), str(self.driver))
        self.assertEqual(proc.stdout, 'ge_skipped_patches\t' + only + '\n' + 'ge_skipped_patches\t' + only + '\n')

    def test_accepts_both_forms(self):
        ok = self.check()
        self.assertEqual(ok.returncode, 0, ok.stderr)
        # Without the log, the form record and the driver are still checked.
        self.assertEqual(self.check([self.state, self.driver]).returncode, 0)
        # Without the driver, the form record must still be well formed.
        self.assertEqual(self.check([self.state]).returncode, 0)

    def test_rejects_bad_records(self):
        for forms in (None, self.line_rel + '=line,' + DIR_REL + '=line',
                      DIR_REL + '=dir-member,' + self.line_rel + '=line', self.forms + ',x=line'):
            self.write_state(forms)
            self.assertNotEqual(self.check().returncode, 0, forms)
        self.write_state(self.forms)
        self.state.write_text(self.state.read_text() + 'ge_skipped_patch_forms\t' + self.forms + '\n')
        self.assertNotEqual(self.check().returncode, 0)
        self.write_state(self.line_rel + '=line,' + DIR_REL + '=line')
        self.assertNotEqual(self.check([self.state]).returncode, 0)

    def test_rejects_driver_and_log_drift(self):
        good = self.driver.read_text()
        for text in (good.replace('        case "$patch" in\n', '        case "$patch"  in\n'),
                     good.replace('"../patches/protonfixes//"*)', '"../patches/protonfixes//x"*)'),
                     good + '    apply_patch "../' + DIR_REL + '"\n'):
            self.driver.unlink()
            self.driver.write_text(text)
            self.assertNotEqual(self.check().returncode, 0)
        self.driver.unlink()
        self.driver.write_text(good)
        for kwargs in (dict(skip=0), dict(skip=2), dict(members=('0001-a.patch',)),
                       dict(members=('0001-a.patch', '0002-b.patch', '0003-skip-me.patch'))):
            self.write_log(**kwargs)
            self.assertNotEqual(self.check().returncode, 0, kwargs)
        self.write_log()
        self.assertEqual(self.check().returncode, 0)

    def test_line_only_pin_unchanged(self):
        only = self.line_rel + ':' + self.fx.skip_sha
        proc, _ = self.fx.generate(only)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.state.write_text('ge_skipped_patches\t' + only + '\n')
        self.assertEqual(self.check([self.state, self.driver], field=only).returncode, 0)
        self.state.write_text('ge_skipped_patches\t' + only + '\nge_skipped_patch_forms\t' + self.line_rel + '=line\n')
        self.assertNotEqual(self.check([self.state, self.driver], field=only).returncode, 0)


class PinLoader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='rtsp-ge-skip-pin-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def load(self, extra, script='true'):
        cfg = self.root / 'pin.env'
        cfg.write_text(base_config(extra))
        return shell('PINNED_GE_CONFIG="$1"; pinned_ge_load_config; ' + script, str(cfg))

    def test_existing_pin_has_no_skip(self):
        proc = self.load('', 'pinned_ge_ge_skip_records; pinned_ge_ge_skip_patch_entries; echo end')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, 'end\n')

    def test_valid_field(self):
        entry = SKIP_REL + ':' + 'a' * 64
        proc = self.load('PIN_GE_SKIP_PATCHES=' + entry + '\n',
                         'pinned_ge_ge_skip_records; pinned_ge_ge_skip_patch_entries')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, 'ge_skipped_patches\t' + entry + '\n' + SKIP_REL + '\t' + 'a' * 64 + '\n')

    def test_invalid_fields(self):
        good = SKIP_REL + ':' + 'a' * 64
        for bad in ('', SKIP_REL, SKIP_REL + ':' + 'A' * 64, SKIP_REL + ':' + 'a' * 63,
                    ',' + good, good + ',', good + ',,' + good, good + ',' + good,
                    'wine/x.patch:' + 'a' * 64, 'patches/../x.patch:' + 'a' * 64,
                    'patches//x.patch:' + 'a' * 64, 'patches/x.diff:' + 'a' * 64):
            proc = self.load('PIN_GE_SKIP_PATCHES=' + bad + '\n')
            self.assertNotEqual(proc.returncode, 0, bad)

    def test_state_record_checks(self):
        entry = SKIP_REL + ':' + 'a' * 64
        state = self.root / 'state.tsv'
        driver = self.root / 'driver.sh'
        marker = 'echo "WINE: -RTSP- skipping GE patch (pinned deviation): ' + SKIP_REL + '"'
        state.write_text('pin_id\tx\nge_skipped_patches\t' + entry + '\n')
        driver.write_text('    ' + marker + '\n')
        field = 'PIN_GE_SKIP_PATCHES=' + entry + '\n'
        script = 'pinned_ge_require_ge_skip_state "$2" "$3"'
        ok = self.load(field, script.replace('"$2" "$3"', '"%s" "%s"' % (state, driver)))
        self.assertEqual(ok.returncode, 0, ok.stderr)
        # Record missing, wrong, or duplicated.
        for text in ('pin_id\tx\n', 'ge_skipped_patches\t' + SKIP_REL + ':' + 'b' * 64 + '\n',
                     'ge_skipped_patches\t' + entry + '\nge_skipped_patches\t' + entry + '\n'):
            state.write_text(text)
            bad = self.load(field, script.replace('"$2" "$3"', '"%s" "%s"' % (state, driver)))
            self.assertNotEqual(bad.returncode, 0, text)
        # The generated driver still applying the patch, or lacking the marker.
        state.write_text('ge_skipped_patches\t' + entry + '\n')
        for text in ('    apply_patch "../' + SKIP_REL + '"\n    ' + marker + '\n', '# nothing\n',
                     '    ' + marker + '\n    ' + marker + '\n'):
            driver.write_text(text)
            bad = self.load(field, script.replace('"$2" "$3"', '"%s" "%s"' % (state, driver)))
            self.assertNotEqual(bad.returncode, 0, text)
        # A pin without the field rejects a state that records a skip.
        state.write_text('ge_skipped_patches\t' + entry + '\n')
        bad = self.load('', 'pinned_ge_require_ge_skip_state "%s"' % state)
        self.assertNotEqual(bad.returncode, 0)
        state.write_text('pin_id\tx\n')
        ok = self.load('', 'pinned_ge_require_ge_skip_state "%s"' % state)
        self.assertEqual(ok.returncode, 0, ok.stderr)


class RealDriver(unittest.TestCase):
    """GE-Proton11-12's real driver, when its readiness checkout is present."""
    CHECK = ROOT / 'work/ge11-12-check-20261108/ge'
    REL = 'patches/wine-hotfixes/pending/rtworkq-dont-hold-queues-section-during-system-queue-shutdown.patch'
    DIGEST = 'fa65977bda168c863cffea3faa0643f21c0f990524e7e90fe1105794e501bc7d'

    def test_real_driver(self):
        if not (self.CHECK / self.REL).is_file():
            self.skipTest('GE-Proton11-12 readiness checkout absent')
        tmp = tempfile.TemporaryDirectory(prefix='rtsp-ge-skip-real-')
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'patches').mkdir()
        (root / 'patches/protonprep-valve-staging.sh').write_bytes(
            (self.CHECK / 'patches/protonprep-valve-staging.sh').read_bytes())
        (root / 'gen.py').write_text(generator_source())
        (root / self.REL).parent.mkdir(parents=True)
        (root / self.REL).write_bytes((self.CHECK / self.REL).read_bytes())
        outs = []
        for skip in ('', self.REL + ':' + self.DIGEST):
            out = root / ('gen-%d.sh' % len(outs))
            proc = run('python3', '-I', str(root / 'gen.py'),
                       str(root / 'patches/protonprep-valve-staging.sh'), str(out), '0', skip)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            outs.append(out.read_text().splitlines())
        diff = [(a, b) for a, b in zip(*outs) if a != b]
        self.assertEqual(len(outs[0]), len(outs[1]))
        self.assertEqual(len(diff), 1)
        self.assertEqual(diff[0][0].strip(), 'apply_patch "../' + self.REL + '"')
        self.assertIn('skipping GE patch (pinned deviation): ' + self.REL, diff[0][1])


class RealDriverDirMember(unittest.TestCase):
    """GE-Proton11-12's real driver with both skips: only the two intended edits differ."""
    CHECK = RealDriver.CHECK
    LINE = RealDriver.REL
    LINE_SHA = RealDriver.DIGEST
    DIR = 'patches/protonfixes/0003-gamefix-kingdoms-of-amalur-re-reckoning-d3dcompiler.patch'
    DIR_SHA = '30f6b9b5bd427eadeb114a748fa4ed6666d11f26e26447f6492daa31d0e17311'

    def test_real_driver(self):
        if not (self.CHECK / self.DIR).is_file():
            self.skipTest('GE-Proton11-12 readiness checkout absent')
        tmp = tempfile.TemporaryDirectory(prefix='rtsp-ge-skip-real2-')
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'patches').mkdir()
        (root / 'patches/protonprep-valve-staging.sh').write_bytes(
            (self.CHECK / 'patches/protonprep-valve-staging.sh').read_bytes())
        (root / 'gen.py').write_text(generator_source())
        for rel in (self.LINE, self.DIR):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes((self.CHECK / rel).read_bytes())
        outs = []
        for skip in ('', self.LINE + ':' + self.LINE_SHA + ',' + self.DIR + ':' + self.DIR_SHA):
            out = root / ('gen-%d.sh' % len(outs))
            proc = run('python3', '-I', str(root / 'gen.py'),
                       str(root / 'patches/protonprep-valve-staging.sh'), str(out), '0', skip)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            outs.append(out.read_text())
        base, text = outs
        import difflib
        changed = [l for l in difflib.unified_diff(base.splitlines(), text.splitlines(), lineterm='', n=0)
                   if l[:1] in '+-' and l[:3] not in ('+++', '---')]
        removed = [l for l in changed if l[0] == '-']
        added = [l for l in changed if l[0] == '+']
        # Removed: only the rtworkq application line; everything else is added text
        # (the rtworkq log line and the skip-aware function body).
        self.assertEqual([l[1:].strip() for l in removed], ['apply_patch "../' + self.LINE + '"'])
        self.assertEqual(text.count('skipping GE patch (pinned deviation)'), 2)
        self.assertEqual(text.count('applying GE patch (skip-aware directory)'), 1)
        self.assertEqual(text.count('apply_all_in_dir "../patches/protonfixes/"'), 1)
        self.assertTrue(any('skipping GE patch (pinned deviation): ' + self.LINE in l for l in added))
        self.assertTrue(any('skipping GE patch (pinned deviation): ' + self.DIR in l for l in added))


if __name__ == '__main__':
    unittest.main()
