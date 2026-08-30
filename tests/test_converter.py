from pathlib import Path
import tempfile
import unittest

from PIL import Image

from jawikiimg.converter import convert_image, output_size


class ConverterTests(unittest.TestCase):
    def test_resize_preserves_aspect_and_never_upscales(self):
        self.assertEqual(output_size((1600, 900)), (800, 450))
        self.assertEqual(output_size((600, 1000)), (288, 480))
        self.assertEqual(output_size((100, 50)), (100, 50))

    def test_alpha_is_composited_on_white_and_saved_as_jpeg(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "source.png"
            target = Path(td) / "Example.png.jpg"
            image = Image.new("RGBA", (1000, 500), (255, 0, 0, 0))
            image.putpixel((500, 250), (0, 0, 255, 255))
            image.save(source)
            size = convert_image(source, target)
            self.assertEqual(size, (800, 400))
            with Image.open(target) as result:
                self.assertEqual(result.format, "JPEG")
                self.assertEqual(result.mode, "RGB")
                self.assertEqual(result.size, (800, 400))
                self.assertGreater(result.getpixel((0, 0))[0], 240)


if __name__ == "__main__":
    unittest.main()

