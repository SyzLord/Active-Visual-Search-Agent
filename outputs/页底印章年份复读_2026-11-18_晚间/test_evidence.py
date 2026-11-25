import unittest

from audit import provenance
from imprint import Prefix, combine, observed_years


class SourceEvidenceTests(unittest.TestCase):
    def test_remote_year_cannot_complete_date(self):
        prefix=Prefix(5,29,"MAY 29","page","stamp",(100,700,210,730),(172,700,210,730),0.)
        line={"text":"1963","confidence":.95}
        self.assertIsNone(combine(prefix,"1963","1963",(225,125,290,155),"page","issue",line))
        self.assertIsNone(combine(prefix,"1963","1963",(225,700,290,730),"other","stamp",line))
        self.assertIsNone(combine(prefix,"1963","1963",(850,700,915,730),"page","other-stamp",line))
        proof=combine(prefix,"1963","1963.",(225,700,290,730),"page","zoom",line)
        self.assertEqual(proof["canonical_date"],"1963-05-29")

    def test_incomplete_year_is_never_filled(self):
        for raw in ("19","196","I963","291963","19638"):
            self.assertEqual(list(observed_years({"words":[{"text":raw,"box":[10,10,50,28]}]})),[])

    def test_raw_year_does_not_correct_month(self):
        words=[{"text":t,"box":b} for t,b in (("WAY",[.1,.1,.25,.3]),("29",[.27,.1,.37,.3]),
                                                ("1963.",[.4,.1,.58,.3]))]
        line={"text":"WAY 29 1963.","box":[.1,.1,.58,.3],"confidence":.9,"words":[],"raw_words":words}
        step={"page":"page","view":"local","stage":"receipt-line","box":[0,700,500,800],
              "size":[500,100],"raw_normalized":[line]}
        winner,_=provenance({"steps":[step]},{"page":(600,1000)},5,29)
        self.assertEqual(winner["year"],"1963")
        self.assertFalse(winner["exact_prefix"])


if __name__=="__main__":
    unittest.main()
