import unittest

from jawikiimg.license import classify


def ext(**values):
    return {key: {"value": value, "source": "commons-desc-page"} for key, value in values.items()}


class LicenseTests(unittest.TestCase):
    def test_allow_families(self):
        self.assertEqual(classify(ext(LicenseShortName="Public domain")).state, "ALLOW_PD")
        self.assertEqual(classify(ext(LicenseShortName="CC0 1.0")).state, "ALLOW_CC0")
        self.assertEqual(classify(ext(LicenseShortName="CC BY 4.0", Copyrighted="true")).state, "ALLOW_CC_BY")
        self.assertEqual(classify(ext(LicenseShortName="CC BY-SA 4.0", Copyrighted="true")).state, "ALLOW_CC_BY_SA")

    def test_deny_non_free_nc_and_nd(self):
        self.assertEqual(classify(ext(LicenseShortName="Fair use", NonFree="true")).state, "DENY")
        self.assertEqual(classify(ext(LicenseShortName="CC BY-NC 4.0")).state, "DENY")
        self.assertEqual(classify(ext(LicenseShortName="CC BY-ND 4.0")).state, "DENY")

    def test_review_unknown_multiple_special_and_contradiction(self):
        self.assertEqual(classify({}).state, "REVIEW")
        self.assertEqual(classify(ext(LicenseShortName="GFDL 1.2")).state, "REVIEW")
        self.assertEqual(classify(ext(LicenseShortName="CC BY-SA 4.0 / GFDL")).state, "REVIEW")
        self.assertEqual(classify(ext(LicenseShortName="CC BY 4.0", Permission="Contact author")).state, "REVIEW")
        self.assertEqual(classify(ext(LicenseShortName="CC BY 4.0", Copyrighted="false")).state, "REVIEW")


if __name__ == "__main__":
    unittest.main()

