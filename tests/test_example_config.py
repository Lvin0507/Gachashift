"""config.example.json, shipped in the zip, must match the defaults the app starts from."""

import json
import pathlib
import unittest

from gachashift.config import DEFAULT_CONFIG

EXAMPLE = pathlib.Path(__file__).resolve().parent.parent / "config.example.json"


class ExampleConfigTest(unittest.TestCase):
    def test_matches_the_defaults(self):
        with open(EXAMPLE, encoding="utf-8") as f:
            self.assertEqual(json.load(f), DEFAULT_CONFIG,
                             "regenerate config.example.json from config.DEFAULT_CONFIG")


if __name__ == "__main__":
    unittest.main()
