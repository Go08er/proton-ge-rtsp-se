#!/usr/bin/env python3
"""Make GE's optional low-latency layer manifest relocatable (no compilation)."""
import argparse
import json
from pathlib import Path

LIBRARY = 'libVkLayer_KORTHOS_LowLatency.so'
MANIFEST = Path('files/share/low_latency_layer/implicit_layer.d/low_latency_layer.json')


def normalize(tool, check=False):
    path = tool / MANIFEST
    text = path.read_text()
    layer = json.loads(text)['layer']
    if layer['name'] != 'VK_LAYER_KORTHOS_low_latency':
        raise ValueError('unexpected low-latency layer identity')
    if not (tool / 'files/lib/x86_64-linux-gnu' / LIBRARY).is_file():
        raise ValueError('packaged low-latency layer library is missing')
    current = layer['library_path']
    if current == LIBRARY:
        return
    if check:
        raise ValueError('low-latency layer manifest retains a non-relocatable library path')
    if not Path(current).is_absolute() or Path(current).name != LIBRARY:
        raise ValueError('unexpected low-latency layer library path; not rewriting it')
    # Match GE's other layers: Proton adds the packaged architecture library
    # directory to LD_LIBRARY_PATH. Keep all other JSON fields/format unchanged.
    old = json.dumps(current)
    if text.count(old) != 1:
        raise ValueError('ambiguous low-latency layer library path')
    path.write_text(text.replace(old, json.dumps(LIBRARY), 1))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool-dir', required=True, type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        normalize(args.tool_dir, args.check)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f'ERROR: {error}\n')
    print('Low-latency layer manifest: relocatable, packaged library present')
