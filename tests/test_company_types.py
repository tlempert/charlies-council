"""Company taxonomy: deterministic facts outrank labels; mixed and unknown are
first-class; nothing here routes production."""
from modules import company_types as ct


class TestEvidence:
    def test_sic_and_xbrl_facts_support_an_insurer(self):
        ev = ct.deterministic_evidence("6331", {"UnearnedPremiums": 1.2e9, "PremiumsEarnedNet": 1.9e9}, "Insurance - Property & Casualty")
        assert "SIC 6331" in ev["insurer_pc"] and "xbrl:UnearnedPremiums" in ev["insurer_pc"]

    def test_a_loan_book_supports_a_lender_even_when_industry_says_software(self):
        ev = ct.deterministic_evidence("7372", {"LoansAndLeasesReceivableNetReportedAmount": 5e9}, "Software - Infrastructure")
        assert "lender_bank" in ev and "insurer_pc" not in ev


class TestCombine:
    def test_a_fact_backed_label_is_never_below_0_9(self):
        out = ct.combine({"software_subscription": 0.8, "insurer_pc": 0.3}, {"insurer_pc": ["SIC 6331"]})
        assert out["primary"] == "insurer_pc" and next(l for l in out["labels"] if l["label"] == "insurer_pc")["p"] == 0.9

    def test_a_confident_financial_label_without_facts_is_capped_and_flagged(self):
        out = ct.combine({"insurer_pc": 0.8, "operating_product": 0.6}, {"operating_product": ["SIC 3570"]})
        ins = next(l for l in out["labels"] if l["label"] == "insurer_pc")
        assert ins["p"] == 0.5 and any(e.startswith("conflict") for e in ins["evidence"])

    def test_mixed_and_unknown(self):
        assert ct.combine({"insurer_pc": 0.6, "holding_conglomerate": 0.5}, {})["mixed"]
        out = ct.combine({"operating_product": 0.4, "distributor_wholesale": 0.3}, {})
        assert out["unknown"] and out["primary"] == "operating_product"
