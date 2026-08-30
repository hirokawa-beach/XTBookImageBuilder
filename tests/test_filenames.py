import unittest

from jawikiimg.filenames import safe_xtbook_filename


class FilenameTests(unittest.TestCase):
    def test_original_extension_is_retained(self):
        self.assertEqual(safe_xtbook_filename("Example.jpg"), "Example.jpg.jpg")
        self.assertEqual(safe_xtbook_filename("Example.png"), "Example.png.jpg")
        self.assertEqual(safe_xtbook_filename("File:Example.svg"), "Example.svg.jpg")

    def test_path_separators_cannot_escape_output_directory(self):
        name = safe_xtbook_filename("a/b\\c.png")
        self.assertNotIn("/", name)
        self.assertNotIn("\\", name)


if __name__ == "__main__":
    unittest.main()

