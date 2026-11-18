#!/usr/bin/env python3
"""Read-only component-selection regressions against a local GE11-6 source.

The frozen old selector reproduces the omitted-GPU-group defect even when
the caller enables both groups. No submodule retrieval or build is performed.
"""

import argparse
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = None
OLD_SELECTOR = r'''pinned_ge_registered_submodules() {
  local source="$1"
  pinned_ge_git -C "$source" config -f .gitmodules \
    --get-regexp '^submodule\..*\.path$' \
    | awk '$2 !~ /^(nvidia-libs|vklayers)\// {print $2}'
}'''


def selected(nvidia, layers, old=False):
    script = 'source "$1/scripts/pinned-ge-common.sh"\n'
    if old:
        script += OLD_SELECTOR + '\n'
    script += 'PIN_WITHOUT_NVIDIA_LIBS="$3"; PIN_WITHOUT_VKLAYERS="$4"\n'
    script += 'pinned_ge_registered_submodules "$2"'
    result = subprocess.run(['bash', '-eu', '-c', script, 'component-test', str(ROOT),
                             str(SOURCE), str(nvidia), str(layers)],
                            text=True, capture_output=True, check=True)
    return result.stdout.splitlines()


class FullGEComponents(unittest.TestCase):
    def test_old_selector_omits_enabled_components(self):
        self.assertEqual(len(selected(0, 0, old=True)), 32)
        self.assertNotEqual(selected(0, 0, old=True), selected(0, 0))

    def test_full_selection_matches_all_actual_gitlinks(self):
        env = dict(os.environ, GIT_NO_LAZY_FETCH='1', GIT_TERMINAL_PROMPT='0',
                   GIT_OPTIONAL_LOCKS='0', GIT_ALLOW_PROTOCOL='file')
        tree = subprocess.run(['git', '-C', str(SOURCE), 'ls-tree', '-r', 'HEAD'],
                              env=env, text=True, capture_output=True, check=True).stdout
        gitlinks = {line.split('\t', 1)[1] for line in tree.splitlines()
                    if line.startswith('160000 commit ')}
        full = selected(0, 0)
        self.assertEqual(len(full), 42)
        self.assertEqual(set(full), gitlinks)
        self.assertNotIn('nvidia-libs/dxvk-nvapi', full)  # stale entry, no pinned object
        self.assertIn('dxvk-nvapi', full)
        self.assertIn('vklayers/vkBasalt', full)  # case-sensitive on Linux

    def test_historical_reduced_selection_unchanged(self):
        self.assertEqual(selected(1, 1), selected(1, 1, old=True))

    def test_groups_can_be_selected_independently(self):
        self.assertEqual(len(selected(0, 1)), 38)
        self.assertEqual(len(selected(1, 0)), 36)
        self.assertFalse(any(p.startswith('vklayers/') for p in selected(0, 1)))
        self.assertFalse(any(p.startswith('nvidia-libs/') for p in selected(1, 0)))

    def test_build_and_resume_record_selected_flags(self):
        build = (ROOT / 'scripts/build-pinned-ge.sh').read_text()
        common = (ROOT / 'scripts/pinned-ge-common.sh').read_text()
        self.assertNotIn('this snapshot requires both optional component groups disabled', build)
        for field, pin in (('without_nvidia_libs', 'PIN_WITHOUT_NVIDIA_LIBS'),
                           ('without_vklayers', 'PIN_WITHOUT_VKLAYERS')):
            self.assertIn(f"printf '{field}\\t%s\\n' \"${pin}\"", build)
            self.assertIn(f'{field}\t${pin}', common)

    def test_local_seed_walk_uses_same_selection(self):
        script = (ROOT / 'scripts/materialize-pinned-ge-submodules.sh').read_text()
        self.assertIn('REGISTERED_MAP["$path"]=1', script)
        self.assertIn('[[ -n "${REGISTERED_MAP[$path]+present}" ]] || continue', script)
        self.assertNotIn('nvidia-libs/*|vklayers/*) continue', script)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    args = parser.parse_args()
    SOURCE = args.source.resolve(strict=True)
    unittest.main(argv=[__file__], verbosity=2)
