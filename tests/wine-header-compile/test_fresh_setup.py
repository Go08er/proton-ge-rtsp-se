#!/usr/bin/env python3
"""Pure parser/source-map controls; no compiler, container or Wine execution."""
import tempfile
from pathlib import Path
import unittest

import fresh_setup as gate


def config_log(tail='', arch='x86_64'):
    flags = ('--host=x86_64-linux-gnu CC=x86_64-linux-gnu-gcc --enable-archs=x86_64 --enable-win64'
             if arch == 'x86_64' else '--host=i686-linux-gnu CC=i686-linux-gnu-gcc')
    return '  $ /old/src-wine/configure ' + flags + ' ' + tail + '\n'


class FreshSetupTests(unittest.TestCase):
    def test_configure_argv_relocates_assignments_not_shell_evaluation(self):
        text = config_log("-C '--prefix=/old/dst wine' 'CFLAGS=-I/old/include -DVALUE=two words' PATH=/old/tools:/usr/bin --with-wine-tools=/old/obj-wine-x86_64", 'i386')
        command = gate.configure_argv(text, Path('/new'), 'i386')
        self.assertEqual(command, ['/new/src-wine/configure', '--host=i686-linux-gnu',
            'CC=i686-linux-gnu-gcc', '--prefix=/new/dst wine',
            'CFLAGS=-I/new/include -DVALUE=two words', 'PATH=/new/tools:/usr/bin',
            '--cache-file=/dev/null', '--with-wine-tools=/new/fresh-green-x86_64'])

    def test_cache_and_tool_arguments_never_reused(self):
        text = config_log('--config-cache --cache-file /old/cache --with-wine-tools /old/tools')
        command = gate.configure_argv(text, Path('/scratch'), 'x86_64')
        self.assertEqual(command[-1], '--cache-file=/dev/null')
        self.assertFalse(any(arg.startswith('--with-wine-tools') for arg in command))
        for bad in ('nothing', text + text, '  $ relative/configure -C\n',
                    config_log('--cache-file')):
            with self.assertRaises(ValueError):
                gate.configure_argv(bad, Path('/scratch'), 'x86_64')

    def test_old_path_prefix_collision_is_not_rewritten(self):
        command = gate.configure_argv(config_log('FLAG=/older/foo'),
                                      Path('/new'), 'x86_64')
        self.assertIn('FLAG=/older/foo', command)

    def test_wrong_architecture_template_cannot_compile_x64_twice(self):
        for arch, text in (('i386', config_log()), ('x86_64', config_log(arch='i386')),
                           ('x86_64', config_log().replace('--enable-win64', '')),
                           ('i386', config_log('--enable-win64', 'i386')),
                           ('x86_64', config_log('CC=i686-linux-gnu-gcc'))):
            with self.assertRaises(ValueError):
                gate.configure_argv(text, Path('/scratch'), arch)

    def test_red_toggles_only_exact_header_registration(self):
        data = b'SOURCES = \\\n\twine/mfinternal.idl \\\n' + gate.REGISTRATION + b'\twine/mmsystem16.h\n'
        self.assertEqual(gate.failing_inventory(data), data.replace(gate.REGISTRATION, b''))
        for bad in (data.replace(gate.REGISTRATION, b''), data + gate.REGISTRATION,
                    data.replace(b'\twine/mforigin', b' wine/mforigin')):
            with self.assertRaises(ValueError):
                gate.failing_inventory(bad)

    def test_red_requires_specific_makedep_error_not_any_failure(self):
        log = 'src-wine/dlls/mfsrcsnk/media_source.c:28: error: wine/mforigin.h: No such file or directory\nconfig.status: error: could not create Makefile\n'
        self.assertTrue(gate.reproduced(log, 1))
        self.assertFalse(gate.reproduced(log, 0))
        self.assertFalse(gate.reproduced(log, 124))
        self.assertFalse(gate.reproduced(log, -15))
        self.assertFalse(gate.reproduced('the Wine tools have not yet been built', 1))
        self.assertFalse(gate.reproduced(log.replace('mforigin', 'different'), 1))

    def test_complete_bridge_rejects_unlisted_product_change(self):
        with tempfile.TemporaryDirectory() as temp:
            before, after = Path(temp) / 'before', Path(temp) / 'after'
            before.mkdir()
            after.mkdir()
            for root in (before, after):
                (root / 'configure').write_text('same')
                (root / 'product.c').write_text('same')
            (after / 'configure').write_text('generated')
            changes = gate.source_bridge(before, after)
            self.assertEqual(set(changes), {'configure'})
            self.assertEqual(changes['configure']['compiled_sha256'], gate.digest(after / 'configure'))
            (after / 'product.c').write_text('unexpected')
            with self.assertRaisesRegex(ValueError, 'non-generator source difference: product.c'):
                gate.source_bridge(before, after)

    def test_bridge_rejects_mode_and_symlink_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            before, after = Path(temp) / 'before', Path(temp) / 'after'
            before.mkdir()
            after.mkdir()
            for root in (before, after):
                (root / 'configure').write_text('same')
            (after / 'configure').chmod(0o755)
            with self.assertRaises(ValueError):
                gate.source_bridge(before, after)
            (after / 'configure').unlink()
            (after / 'configure').symlink_to(before / 'configure')
            with self.assertRaises(ValueError):
                gate.source_bridge(before, after)

    def test_root_git_excluded_but_nested_git_not_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / '.git').mkdir()
            (root / '.git/config').write_text('private admin')
            (root / 'nested').mkdir()
            (root / 'nested/.git').write_text('not admin')
            self.assertEqual(set(gate.inventory_tree(root)), {'nested', 'nested/.git'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
