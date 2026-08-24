import re
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


class ReadmeLocalizationTests(unittest.TestCase):
    def test_chinese_readme_is_default_and_links_to_english(self):
        readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
        pyproject = (PLUGIN_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("[English](README_EN.md)", readme)
        self.assertIn("简体中文（默认）", readme)
        self.assertRegex(pyproject, r'(?m)^readme = "README\.md"$')

    def test_english_readme_links_back_and_covers_core_usage(self):
        readme = (PLUGIN_ROOT / "README_EN.md").read_text(encoding="utf-8")
        required = (
            "[Simplified Chinese (Default)](README.md)",
            "## Installation",
            "## API Key Setup",
            "## Node Catalog",
            "## Concurrent Image and Video Generation",
            "## Example Workflows",
            "## Environment Variables",
            "## Troubleshooting",
            "Wan_3_0_Video",
            "comfy node install seedance",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, readme)

    def test_english_readme_has_no_sensitive_runtime_values(self):
        readme = (PLUGIN_ROOT / "README_EN.md").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"sk-[A-Za-z0-9]{20,}", readme))
        self.assertNotIn("X-Amz-Signature", readme)
        self.assertIsNone(re.search(r"task_[A-Za-z0-9]{12,}", readme))


if __name__ == "__main__":
    unittest.main()
