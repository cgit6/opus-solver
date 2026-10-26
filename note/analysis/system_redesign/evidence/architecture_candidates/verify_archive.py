"""Read-only archive integrity check. Does not import or run experimental code."""
import argparse
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compare-originals', action='store_true',
                        help='also read and compare original /tmp files (must still exist)')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / 'manifest.json').read_text())
    counts = Counter()
    total = 0
    recorded = set()
    for entry in manifest['files']:
        relative = entry['archive_relative_path']
        path = (root / relative).resolve()
        assert path.is_relative_to(root), relative
        assert relative not in recorded, relative
        recorded.add(relative)
        archived = path.read_bytes()
        encoding = entry['encoding']
        if encoding == 'base64':
            # The final newline belongs to the textual encoding, not the source.
            content = base64.b64decode(archived.strip(), validate=True)
            assert not entry['ends_with_newline'], relative
        else:
            assert encoding == 'identity', relative
            content = archived
        assert len(content) == entry['decoded_size'], relative
        assert hashlib.sha256(content).hexdigest() == entry['original_sha256'], relative
        assert content.endswith(b'\n') == entry['ends_with_newline'], relative
        origin = Path(manifest['original_roots'][entry['group']]) / entry['source_relative_path']
        assert str(origin) == entry['original_path'], relative
        if args.compare_originals:
            assert origin.read_bytes() == content, relative
        counts[entry['group']] += 1
        counts[encoding] += 1
        total += len(content)
    actual = {str(path.relative_to(root)) for group in manifest['original_roots']
              for path in (root / group).rglob('*') if path.is_file()}
    assert actual == recorded, {'extra': sorted(actual - recorded), 'missing': sorted(recorded - actual)}
    assert len(recorded) == manifest['file_count'] == 411
    assert total == manifest['total_original_bytes'] == 4487283
    assert counts['identity'] == 403 and counts['base64'] == 8
    print(json.dumps({'passed': True, 'original_files': len(recorded),
                      'original_bytes': total, 'counts': dict(counts),
                      'original_tmp_compared': args.compare_originals,
                      'experimental_code_executed': False,
                      'unarchived_full_outputs_rechecked': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
