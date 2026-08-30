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
        self.assertEqual(
            classify(ext(LicenseShortName="CC BY 4.0", Permission="Non-commercial use only")).state,
            "DENY",
        )

    def test_review_unknown_multiple_special_and_contradiction(self):
        self.assertEqual(classify({}).state, "REVIEW")
        self.assertEqual(classify(ext(LicenseShortName="GFDL 1.2")).state, "REVIEW")
        self.assertEqual(classify(ext(LicenseShortName="CC BY-SA 4.0 / GFDL")).state, "REVIEW")
        self.assertEqual(classify(ext(LicenseShortName="CC BY 4.0", Permission="Contact author")).state, "REVIEW")
        self.assertEqual(classify(ext(LicenseShortName="CC BY 4.0", Copyrighted="false")).state, "REVIEW")

    def test_known_non_restrictive_permission_is_allowed(self):
        flickr = (
            "This image was originally posted to Flickr. On that date, it was "
            "confirmed to be licensed under the terms of CC BY 2.0."
        )
        federal = (
            "This work is in the public domain in the United States because it was "
            "prepared by an employee of the U.S. federal government as part of official duties."
        )
        vector = "A vector version of this image is available and should be used instead."
        attribution = (
            "This work is licensed under Creative Commons Attribution 4.0. "
            "Please attribute Tokyo Metropolitan Government."
        )
        self.assertEqual(classify(ext(LicenseShortName="CC BY 2.0", Permission=flickr)).state, "ALLOW_CC_BY")
        self.assertEqual(classify(ext(LicenseShortName="Public domain", Permission=federal)).state, "ALLOW_PD")
        self.assertEqual(classify(ext(LicenseShortName="CC BY-SA 4.0", Permission=vector)).state, "ALLOW_CC_BY_SA")
        self.assertEqual(classify(ext(LicenseShortName="CC BY 4.0", Permission=attribution)).state, "ALLOW_CC_BY")

    def test_permission_warning_unknown_and_restrictions_stay_review(self):
        warning = "Please provide the source and publication date; this may still be copyrighted."
        self.assertEqual(classify(ext(LicenseShortName="Public domain", Permission=warning)).state, "REVIEW")
        self.assertEqual(classify(ext(LicenseShortName="CC BY 4.0", Permission="See below")).state, "REVIEW")
        decision = classify(ext(LicenseShortName="Public domain", Restrictions="Trademarked emblem"))
        self.assertEqual(decision.state, "REVIEW")
        self.assertIn("Trademarked emblem", decision.reason)


if __name__ == "__main__":
    unittest.main()
