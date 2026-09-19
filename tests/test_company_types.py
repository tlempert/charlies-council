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


class TestClassify:
    def test_probabilities_become_labels_and_the_file_is_written(self, tmp_path, monkeypatch):
        import importlib.util, json, os
        from types import SimpleNamespace as NS
        spec = importlib.util.spec_from_file_location("classify_company", os.path.join(os.path.dirname(__file__), "..", "scripts", "classify_company.py"))
        cc = importlib.util.module_from_spec(spec); spec.loader.exec_module(cc)
        (tmp_path / "initial_dossier.txt").write_text("INDUSTRY: Insurance - Property & Casualty\n--- SECTION A: BUSINESS ---\nKinsale writes E&S insurance through wholesale brokers.\n")
        monkeypatch.setattr(cc, "sic_for", lambda ticker: "6331")
        monkeypatch.setattr(cc, "xbrl_for", lambda d: {})
        calls = iter([
            NS(choices={"model": NS(choice="insurer_pc", confidence=0.85, probabilities={"insurer_pc": 0.85, "operating_product": 0.4})}, nouls={}, usage=NS(input_tokens=1), model="f"),
            NS(choices={"regime": NS(choice="cyclical_timing", confidence=0.7, probabilities={"cyclical_timing": 0.7})}, nouls={}, usage=NS(input_tokens=1), model="f"),
            NS(choices={"jurisdiction": NS(choice="developed", confidence=0.95, probabilities={"developed": 0.95})}, nouls={}, usage=NS(input_tokens=1), model="f"),
            NS(choices={"capital": NS(choice="float_funded", confidence=0.9, probabilities={"float_funded": 0.9})}, nouls={}, usage=NS(input_tokens=1), model="f"),
        ])
        client = NS(system_one=lambda state, questions: next(calls))
        cc.classify(client, str(tmp_path), "KNSL")
        out = json.load(open(tmp_path / "company_type.json"))
        assert out["primary"] == "insurer_pc" and out["labels"][0]["p"] == 0.9
        assert out["regime"]["label"] == "cyclical_timing" and out["jurisdiction"] == "developed" and out["capital"] == "float_funded"
        assert "SIC 6331" in out["labels"][0]["evidence"]
