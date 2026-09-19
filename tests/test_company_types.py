"""Company taxonomy: deterministic facts outrank labels; mixed and unknown are
first-class; nothing here routes production."""
import importlib.util
import json
import os
import sys
from types import SimpleNamespace as NS

from modules import company_types as ct

_SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "..", "scripts", "classify_company.py")


def _load_classify_company():
    spec = importlib.util.spec_from_file_location("classify_company", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestEvidence:
    def test_sic_and_xbrl_facts_support_an_insurer(self):
        ev = ct.deterministic_evidence("6331", {"UnearnedPremiums": 1.2e9, "PremiumsEarnedNet": 1.9e9}, "Insurance - Property & Casualty")
        assert "SIC 6331" in ev["insurer_pc"] and "xbrl:UnearnedPremiums" in ev["insurer_pc"]

    def test_a_loan_book_supports_a_lender_even_when_industry_says_software(self):
        ev = ct.deterministic_evidence("7372", {"LoansAndLeasesReceivableNetReportedAmount": 5e9}, "Software - Infrastructure")
        assert "lender_bank" in ev and "insurer_pc" not in ev

    def test_sic_prefix_matching_takes_the_longest_prefix(self, monkeypatch):
        # A shorter, coarser prefix ("602") and a longer, more specific one
        # ("6022") both match "6022" — the specific one must win, not
        # whichever happens to come first in dict-iteration order.
        monkeypatch.setattr(ct, "SIC_HINTS", {"602": "lender_bank", "6022": "asset_manager"})
        ev = ct.deterministic_evidence("6022", {}, None)
        assert ev == {"asset_manager": ["SIC 6022"]}


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

    def test_a_shell_sic_does_not_cap_an_unrelated_financial_label(self):
        # SIC 6770 (blank check / shell) lands on the "unknown" label. That
        # must not read as "evidence names some OTHER label" and cap
        # insurer_pc — the shell fact carries no information about it.
        out = ct.combine({"insurer_pc": 0.8}, {"unknown": ["SIC 6770"]})
        ins = next(l for l in out["labels"] if l["label"] == "insurer_pc")
        assert ins["p"] == 0.8 and not any(e.startswith("conflict") for e in ins["evidence"])

    def test_evidence_is_ordered_facts_first_jev_score_last(self):
        out = ct.combine({"insurer_pc": 0.3}, {"insurer_pc": ["SIC 6331"]})
        ins = next(l for l in out["labels"] if l["label"] == "insurer_pc")
        assert ins["evidence"] == ["SIC 6331", "jev 0.30"]


class TestClassify:
    def test_probabilities_become_labels_and_the_file_is_written(self, tmp_path, monkeypatch):
        cc = _load_classify_company()
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
        assert out["facts"] is True
        from datetime import datetime
        assert datetime.fromisoformat(out["generated_at"])

    def test_axis_category_sets_are_exactly_the_specified_ones(self):
        cc = _load_classify_company()
        assert set(cc.REGIME) == {"stable", "cyclical_timing", "commodity_linked", "binary_event",
                                   "regime_political", "narrative_momentum", "turnaround"}
        assert set(cc.JURISDICTION) == {"developed", "emerging", "state_override_risk"}
        assert set(cc.CAPITAL) == {"float_funded", "net_cash", "leveraged", "normal"}


class TestSicFor:
    def test_sic_cache_dir_is_anchored_to_the_repo_root_not_the_cwd(self, tmp_path, monkeypatch):
        cc = _load_classify_company()
        monkeypatch.chdir(tmp_path)
        assert not str(cc.SIC_CACHE_DIR).startswith(str(tmp_path))
        assert os.path.normpath(cc.SIC_CACHE_DIR).replace(os.sep, "/").endswith("tmp/sic")

    def test_a_successful_lookup_is_cached(self, tmp_path, monkeypatch):
        cc = _load_classify_company()
        monkeypatch.setattr(cc, "SIC_CACHE_DIR", str(tmp_path))
        monkeypatch.setattr(cc.tools, "get_cik", lambda t: "0000000123")
        resp = NS(json=lambda: {"sic": "6331"}, raise_for_status=lambda: None)
        monkeypatch.setattr(cc.requests, "get", lambda *a, **k: resp)
        assert cc.sic_for("KNSL") == "6331"
        assert json.load(open(tmp_path / "KNSL.json"))["sic"] == "6331"

    def test_a_request_exception_returns_none_and_writes_nothing(self, tmp_path, monkeypatch):
        cc = _load_classify_company()
        monkeypatch.setattr(cc, "SIC_CACHE_DIR", str(tmp_path))
        monkeypatch.setattr(cc.tools, "get_cik", lambda t: "0000000123")

        def boom(*a, **k):
            raise Exception("network down")
        monkeypatch.setattr(cc.requests, "get", boom)
        assert cc.sic_for("KNSL") is None
        assert list(tmp_path.iterdir()) == []

    def test_a_body_without_sic_returns_none_and_writes_nothing(self, tmp_path, monkeypatch):
        cc = _load_classify_company()
        monkeypatch.setattr(cc, "SIC_CACHE_DIR", str(tmp_path))
        monkeypatch.setattr(cc.tools, "get_cik", lambda t: "0000000123")
        resp = NS(json=lambda: {}, raise_for_status=lambda: None)
        monkeypatch.setattr(cc.requests, "get", lambda *a, **k: resp)
        assert cc.sic_for("KNSL") is None
        assert list(tmp_path.iterdir()) == []

    def test_a_cached_null_sic_is_treated_as_a_miss(self, tmp_path, monkeypatch):
        cc = _load_classify_company()
        monkeypatch.setattr(cc, "SIC_CACHE_DIR", str(tmp_path))
        (tmp_path / "KNSL.json").write_text(json.dumps({"sic": None}))
        monkeypatch.setattr(cc.tools, "get_cik", lambda t: "0000000123")
        resp = NS(json=lambda: {"sic": "6331"}, raise_for_status=lambda: None)
        monkeypatch.setattr(cc.requests, "get", lambda *a, **k: resp)
        assert cc.sic_for("KNSL") == "6331"

    def test_raise_for_status_failure_returns_none_and_writes_nothing(self, tmp_path, monkeypatch):
        cc = _load_classify_company()
        monkeypatch.setattr(cc, "SIC_CACHE_DIR", str(tmp_path))
        monkeypatch.setattr(cc.tools, "get_cik", lambda t: "0000000123")

        def raise_it():
            raise Exception("HTTP 500")
        resp = NS(json=lambda: {"sic": "6331"}, raise_for_status=raise_it)
        monkeypatch.setattr(cc.requests, "get", lambda *a, **k: resp)
        assert cc.sic_for("KNSL") is None
        assert list(tmp_path.iterdir()) == []


class TestCli:
    def test_default_run_dir_uses_council_root_env(self, monkeypatch):
        cc = _load_classify_company()
        monkeypatch.setenv("COUNCIL_ROOT", "/x/y")
        assert cc._default_run_dir("KNSL") == os.path.join("/x/y", "KNSL")

    def test_default_run_dir_falls_back_without_council_root(self, monkeypatch):
        cc = _load_classify_company()
        monkeypatch.delenv("COUNCIL_ROOT", raising=False)
        assert cc._default_run_dir("KNSL") == os.path.join("/tmp/silicon_council", "KNSL")

    def test_a_bad_invocation_prints_usage_and_never_touches_the_client(self, monkeypatch, capsys):
        cc = _load_classify_company()
        monkeypatch.setattr(sys, "argv", ["classify_company.py"])
        touched = []
        client = NS(system_one=lambda *a, **k: touched.append(1))
        cc._main(client)
        assert "usage" in capsys.readouterr().out.lower()
        assert touched == []


class TestOfflineHelpers:
    def test_xbrl_for_returns_empty_dict_without_a_file(self, tmp_path):
        cc = _load_classify_company()
        assert cc.xbrl_for(str(tmp_path)) == {}

    def test_xbrl_for_returns_the_cached_facts_dict(self, tmp_path):
        cc = _load_classify_company()
        (tmp_path / "xbrl.json").write_text(json.dumps({"latest": {"UnearnedPremiums": 1}}))
        assert cc.xbrl_for(str(tmp_path)) == {"UnearnedPremiums": 1}

    def test_item1_excerpt_is_empty_without_a_section_a_marker(self):
        cc = _load_classify_company()
        assert cc.item1_excerpt("no markers here") == ""

    def test_item1_excerpt_caps_at_6000_chars_after_the_marker(self):
        cc = _load_classify_company()
        body = "x" * 7000
        text = f"--- SECTION A: BUSINESS ---\n{body}"
        excerpt = cc.item1_excerpt(text)
        assert len(excerpt) == 6000
        assert excerpt == ("\n" + body)[:6000]
