import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
import ComfyUI_Seedance as plugin


class ReferenceInputContractTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required for frontend contract checks")
    def test_progressive_inputs_match_backend_and_restore_legacy_hidden_slots(self):
        schemas = {name: cls.INPUT_TYPES() for name, cls in plugin.NODE_CLASS_MAPPINGS.items()}
        result = subprocess.run(
            [shutil.which("node"), str(ROOT / "tests" / "progressive_reference_restore.mjs"), "--backend-schema"],
            input=json.dumps(schemas), text=True, encoding="utf-8", capture_output=True, timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("22 families", result.stdout)


if __name__ == "__main__":
    unittest.main()
