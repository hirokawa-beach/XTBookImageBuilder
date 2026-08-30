import unittest

from jawikiimg.builder import info_plist


class BuilderTests(unittest.TestCase):
    def test_xtbook_info_plist(self):
        plist = info_plist()
        self.assertEqual(plist["XTBDictionaryScheme"], "jawikiimg")
        self.assertEqual(plist["XTBDictionaryTypeIdentifier"], "com.nexhawks.XTBook.ImageComplex")
        self.assertEqual(plist["XTBImageComplexImagesFile"], "Images")


if __name__ == "__main__":
    unittest.main()

