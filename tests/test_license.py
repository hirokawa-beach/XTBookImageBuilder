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
        self.assertEqual(classify(ext(LicenseShortName="Fair use")).state, "DENY")
        self.assertEqual(classify(ext(LicenseShortName="CC BY-NC 4.0")).state, "DENY")
        self.assertEqual(classify(ext(LicenseShortName="CC BY-ND 4.0")).state, "DENY")

    def test_review_only_missing_or_unsupported_name(self):
        self.assertEqual(classify({}).state, "REVIEW")
        self.assertEqual(classify(ext(LicenseShortName="GFDL 1.2")).state, "REVIEW")
        self.assertEqual(classify(ext(LicenseUrl="https://creativecommons.org/licenses/by/4.0/")).state, "REVIEW")

    def test_other_metadata_does_not_change_supported_license_name(self):
        warning = "Please provide the source and publication date; this may still be copyrighted."
        self.assertEqual(classify(ext(LicenseShortName="Public domain", Permission=warning)).state, "ALLOW_PD")
        self.assertEqual(classify(ext(LicenseShortName="CC BY 4.0", Restrictions="Trademarked")).state, "ALLOW_CC_BY")
        self.assertEqual(classify(ext(LicenseShortName="CC BY 4.0", Copyrighted="false")).state, "ALLOW_CC_BY")
        self.assertEqual(classify(ext(LicenseShortName="CC BY 4.0", NonFree="true")).state, "ALLOW_CC_BY")
        self.assertEqual(classify(ext(LicenseShortName="CC BY-SA 4.0 / GFDL")).state, "ALLOW_CC_BY_SA")


if __name__ == "__main__":
    unittest.main()
