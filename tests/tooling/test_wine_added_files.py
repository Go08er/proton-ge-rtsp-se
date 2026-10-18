#!/usr/bin/env python3
"""Offline registration mutants; no compile, runtime or retained-tree writes."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/audit-wine-added-files.py'
spec = importlib.util.spec_from_file_location('added_files', SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class AddedFilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wine-added-files-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tree = self.root / 'wine'
        self.patches = self.root / 'patches'
        self.tree.mkdir(); self.patches.mkdir()
        self.series = self.root / 'series'
        self.series.write_text('one.patch\n')
        self.write('configure.ac', 'WINE_CONFIG_MAKEFILE(include)\nWINE_CONFIG_MAKEFILE(dlls/example)\n')

    def write(self, path, text):
        target = self.tree / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def added(self, path, text='/* input */\n'):
        self.write(path, text)
        lines = text.splitlines()
        (self.patches / 'one.patch').write_text(
            f'--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n'
            + ''.join('+' + line + '\n' for line in lines))

    def result(self):
        return audit.audit(self.tree, self.series, self.patches)

    def test_exact_0071_omission_red_and_registration_green(self):
        patch = ROOT / 'patches/ge-proton11-7-se2-p19b/0071-mfreadwrite-map-source-origin-metadata.patch'
        (self.patches / 'one.patch').write_bytes(patch.read_bytes())
        header = patch.read_text().split('+++ b/include/wine/mforigin.h\n', 1)[1].split('\n--- ', 1)[0]
        self.write('include/wine/mforigin.h', '\n'.join(line[1:] for line in header.splitlines() if line.startswith('+')) + '\n')
        self.write('include/Makefile.in', 'SOURCES = \\\n\twine/mfinternal.idl \\\n\twine/winedmo.h\n')
        count, rows, errors = self.result()
        self.assertEqual((count, rows, len(errors)), (1, [], 1))
        self.assertIn('include/wine/mforigin.h: absent from include/Makefile.in SOURCES', errors[0])
        self.write('include/Makefile.in', 'SOURCES = \\\n\twine/mfinternal.idl \\\n\twine/mforigin.h \\\n\twine/winedmo.h\n')
        self.assertEqual(len(self.result()[1]), 1)
        self.assertEqual(self.result()[2], [])

    def test_all_69_paths_are_enumerated(self):
        count, added = audit.added_files(ROOT / 'patches/series-ge-proton11-7-se2-p19b', ROOT / 'patches')
        self.assertEqual(count, 69)
        self.assertEqual(added, {'include/wine/mforigin.h':
                                'ge-proton11-7-se2-p19b/0071-mfreadwrite-map-source-origin-metadata.patch'})

    def test_comments_substrings_and_wrong_variable_do_not_register(self):
        self.added('include/wine/mforigin.h')
        for text in ('# SOURCES = wine/mforigin.h\n', 'SOURCES = wine/mforigin.h.old\n',
                     'EXTRA_OBJS = wine/mforigin.h\n', 'SOURCES += wine/mforigin.h\n',
                     'SOURCES := wine/mforigin.h\n', 'SOURCES = wine/mforigin.h\nSOURCES = other.h\n'):
            with self.subTest(text=text):
                self.write('include/Makefile.in', text)
                self.assertTrue(self.result()[2])

    def test_computed_inventory_is_not_assumed(self):
        self.added('include/wine/mforigin.h')
        self.write('include/Makefile.in', 'HEADERS = wine/mforigin.h\nSOURCES = $(HEADERS)\n')
        self.assertIn('computed registration', self.result()[2][0])

    def test_missing_file_and_unconfigured_directory_rejected(self):
        self.added('include/wine/mforigin.h')
        self.write('include/Makefile.in', 'SOURCES = wine/mforigin.h\n')
        self.write('configure.ac', '# WINE_CONFIG_MAKEFILE(include)\n')
        self.assertIn('not explicitly registered', self.result()[2][0])
        (self.tree / 'include/wine/mforigin.h').unlink()
        self.assertIn('missing/non-local', self.result()[2][0])

    def test_registered_c_and_generator_inputs(self):
        for suffix in ('.c', '.idl', '.y', '.l', '.rc', '.S'):
            with self.subTest(suffix=suffix):
                self.added('dlls/example/input' + suffix)
                self.write('dlls/example/Makefile.in', 'SOURCES = input' + suffix + '\n')
                self.assertEqual(self.result()[2], [])
                self.write('dlls/example/Makefile.in', 'SOURCES = input.h\n')
                self.assertTrue(self.result()[2])

    def test_module_spec_is_implicit_but_imports_are_not_a_source_inventory(self):
        self.added('dlls/example/example.spec', '@ stub EntryPoint\n')
        self.write('dlls/example/Makefile.in', 'MODULE = example.dll\nIMPORTLIB = example\nSOURCES = main.c\n')
        self.assertIn('MODULE=example.dll; IMPORTLIB=example', self.result()[1][0][2])
        self.write('dlls/example/Makefile.in', 'MODULE = other.dll\nIMPORTS = example\nSOURCES = main.c\n')
        self.assertTrue(self.result()[2])
        self.write('dlls/example/Makefile.in', 'MODULE = example.dll\nEXTRADLLFLAGS = -Wb,--data-only\nSOURCES = main.c\n')
        self.assertTrue(self.result()[2])
        self.write('dlls/example/Makefile.in', 'SOURCES = example.spec\n')
        self.assertEqual(self.result()[2], [])

    def test_unmodelled_private_header_and_category_fail_closed(self):
        for name in ('private.h', 'blob.bin'):
            self.added('dlls/example/' + name)
            self.write('dlls/example/Makefile.in', 'SOURCES = main.c\n')
            self.assertTrue(self.result()[2])

    def test_generated_header_name_cannot_replace_generator_registration(self):
        self.added('include/new.idl', 'interface New {};\n')
        self.write('include/Makefile.in', 'SOURCES = new.h\n')
        self.assertTrue(self.result()[2])
        self.write('include/Makefile.in', 'SOURCES = new.idl\n')
        self.assertEqual(self.result()[2], [])

    def test_missing_duplicate_empty_and_unsafe_series_rejected(self):
        for text in ('', 'absent.patch\n', '../outside.patch\n', 'one.patch\none.patch\n'):
            self.added('include/new.h')
            self.series.write_text(text)
            with self.subTest(text=text), self.assertRaises(audit.AuditError):
                self.result()

    def test_cli_red_and_green(self):
        self.added('include/wine/mforigin.h')
        self.write('include/Makefile.in', 'SOURCES = other.h\n')
        command = [sys.executable, str(SCRIPT), '--wine-tree', str(self.tree),
                   '--series', str(self.series), '--patch-root', str(self.patches)]
        red = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(red.returncode, 1)
        self.assertIn('mforigin.h', red.stderr)
        self.write('include/Makefile.in', 'SOURCES = wine/mforigin.h\n')
        green = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(green.returncode, 0, green.stderr)
        self.assertIn('1 patches, 1 registered, 0 rejected', green.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
