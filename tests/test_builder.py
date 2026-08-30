from pathlib import Path
import unittest

from jawikiimg.builder import info_plist


class BuilderTests(unittest.TestCase):
    def test_xtbook_info_plist(self):
        plist = info_plist()
        self.assertEqual(plist["XTBDictionaryScheme"], "jawikiimg")
        self.assertEqual(plist["XTBDictionaryTypeIdentifier"], "com.nexhawks.XTBook.ImageComplex")
        self.assertEqual(plist["XTBImageComplexImagesFile"], "Images")

    def test_arm64_build_uses_legacy_compatibility_headers(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "scripts" / "build_mkimagecomplex_arm64.sh").read_text(
            encoding="utf-8"
        )
        compat = root / "scripts" / "mkimagecomplex-compat"
        self.assertTrue((compat / "mecab.h").is_file())
        preinclude = (compat / "preinclude.hpp").read_text(encoding="utf-8")
        self.assertIn("#include <algorithm>", preinclude)
        self.assertIn("#include <stdint.h>", preinclude)
        self.assertIn("#include <vector>", preinclude)
        self.assertIn('-I"$compat_dir"', script)
        self.assertIn('-include "$compat_dir/preinclude.hpp"', script)


if __name__ == "__main__":
    unittest.main()
