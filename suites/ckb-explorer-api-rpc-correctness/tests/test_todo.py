from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ckb_rpc_correctness.todo import (
    build_inventory,
    discover_reviewed_interfaces,
    load_endpoints,
    render_markdown,
)


class TodoModuleTests(unittest.TestCase):
    def test_inventory_is_derived_from_manifest_and_review_markers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "endpoints.json"
            reviews = root / "reviews"
            reviews.mkdir()
            manifest.write_text(
                json.dumps(
                    {
                        "endpoints": [
                            {
                                "method": "GET",
                                "path": "/v1/blocks",
                                "module": "MOD-CHAIN-DATA",
                                "purpose": "区块列表",
                                "wiring": "ACTIVE",
                            },
                            {
                                "method": "GET",
                                "path": "/v1/blocks/:id",
                                "module": "MOD-CHAIN-DATA",
                                "purpose": "区块详情",
                                "wiring": "ACTIVE",
                            },
                            {
                                "method": "POST",
                                "path": "/v2/transactions",
                                "module": "MOD-CHAIN-DATA",
                                "purpose": "创建交易",
                                "wiring": "ROUTE_ONLY",
                            },
                        ]
                    }
                )
            )
            (reviews / "blocks.md").write_text("# Blocks\n\n评审接口：`GET /api/v1/blocks`\n")

            endpoints = load_endpoints(manifest)
            reviewed = discover_reviewed_interfaces(reviews)
            inventory = build_inventory(endpoints, reviewed)
            output = render_markdown(inventory, manifest)

            self.assertEqual(3, inventory.total)
            self.assertEqual(1, len(inventory.reviewed))
            self.assertEqual(1, len(inventory.active))
            self.assertEqual(1, len(inventory.route_audit))
            self.assertIn("- [x] `GET /api/v1/blocks`", output)
            self.assertIn("- [ ] `GET /api/v1/blocks/:id`", output)
            self.assertIn("- [ ] `POST /api/v2/transactions` — 创建交易 [ROUTE_ONLY]", output)

    def test_unknown_review_marker_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "absent from the manifest"):
            build_inventory((), {("GET", "/v1/missing")})


if __name__ == "__main__":
    unittest.main()
