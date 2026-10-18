#!/usr/bin/env python3
"""Bound SDK descendants without requiring rootless CPU cgroup delegation."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


def options(jobs, cpuset=None, entrypoint=None):
    command = ['bash', '-eu', '-c',
        'source "$1/scripts/pinned-ge-common.sh"; pinned_ge_container_cpu_options "$2" "$3"',
        'cpu-budget', str(ROOT), str(jobs), json.dumps(entrypoint)]
    if cpuset is not None:
        command = ['taskset', '-c', str(cpuset), *command]
    return subprocess.run(command, capture_output=True, text=True, timeout=10)


class ContainerCpuBudget(unittest.TestCase):
    def command(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        argument, = shlex.split(result.stdout)
        self.assertTrue(argument.startswith('--entrypoint='))
        return json.loads(argument.split('=', 1)[1])

    def test_inherits_actual_half_cpu_affinity(self):
        current = ','.join(map(str, sorted(os.sched_getaffinity(0))[:8]))
        self.assertEqual(self.command(options(8)), ['/usr/bin/taskset', '-c', current])

    def test_narrower_caller_affinity_is_not_broadened(self):
        cpu = min(os.sched_getaffinity(0))
        self.assertEqual(self.command(options(8, cpu)), ['/usr/bin/taskset', '-c', str(cpu)])

    def test_sdk_init_and_argument_boundaries_are_preserved(self):
        original = ['/usr/bin/tini-static', '-s', '-g', '--', "one 'quoted' argument"]
        self.assertEqual(self.command(options(8, entrypoint=original))[3:], original)

    def test_budget_narrows_a_broader_callers_mask(self):
        selected = ','.join(map(str, sorted(os.sched_getaffinity(0))[:1]))
        self.assertEqual(self.command(options(1))[2], selected)

    def test_invalid_quota_is_rejected(self):
        for jobs in ('0', '-1', '8 --privileged', '1.5'):
            self.assertNotEqual(options(jobs).returncode, 0)

    def test_real_build_passes_restrictions_and_keeps_network_off(self):
        text = (ROOT / 'scripts/build-pinned-ge.sh').read_text()
        self.assertIn('container_cpu_options="$(pinned_ge_container_cpu_options "$JOBS" "$sdk_entrypoint")"', text)
        self.assertIn("--format '{{json .Config.Entrypoint}}'", text)
        self.assertIn('DOCKER_OPTS=--pull=never --network=none $container_cpu_options ', text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
