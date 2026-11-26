"""Offline guard for storage protections: fails if any protected resource loses
its destroy protection. Pure stdlib; parses resource blocks by brace counting
and asserts the pinned protections.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Resource -> required protection text inside its block.
REQUIRED_PROTECTIONS = {
    ("google_storage_bucket", "journals"): ["prevent_destroy = true"],
    ("google_storage_bucket", "consumer_ledger"): ["prevent_destroy = true"],
    ("google_bigquery_dataset", "event_archive"): ["prevent_destroy = true"],
    ("google_bigquery_table", "raw_events"): [
        "prevent_destroy = true",
        "deletion_protection = true",
    ],
    ("google_bigquery_table", "open_positions"): [
        "prevent_destroy = true",
        "deletion_protection = true",
    ],
}


def resource_blocks():
    blocks = {}
    for path in sorted(ROOT.glob("*.tf")):
        text = path.read_text()
        depth = 0
        header = None
        for line in text.splitlines():
            stripped = line.strip()
            if depth == 0 and stripped.startswith('resource "'):
                header = stripped
                depth = line.count("{") - line.count("}")
                continue
            if depth > 0:
                depth += line.count("{") - line.count("}")
                if depth == 0:
                    kind, name = _split_header(header)
                    blocks[(kind, name)] = (path.name, "\n".join(
                        _block_lines(text, header)))
    return blocks


def _split_header(header):
    parts = [p.strip('"') for p in header.split()]
    return parts[1], parts[2]


def _block_lines(text, header):
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == header)
    depth = 0
    for i in range(start, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if depth == 0:
            return lines[start:i + 1]
    return lines[start:]


class ProtectionTests(unittest.TestCase):
    def test_every_protected_resource_exists(self) -> None:
        blocks = resource_blocks()
        for key in REQUIRED_PROTECTIONS:
            self.assertIn(key, blocks, f"missing resource {key}")

    def test_protected_resources_keep_their_protections(self) -> None:
        blocks = resource_blocks()
        for key, required in REQUIRED_PROTECTIONS.items():
            source, block = blocks[key]
            for snippet in required:
                self.assertIn(
                    snippet,
                    block,
                    f"{source}: {key} lost protection `{snippet}`",
                )


if __name__ == "__main__":
    result = unittest.main(exit=False).result
    sys.exit(0 if result.wasSuccessful() else 1)
