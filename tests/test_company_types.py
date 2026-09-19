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


_SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_SCRIPTS_DIR, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestRuleKey:
    def test_a_required_pattern_renders_its_hyphenated_name(self):
        assert ct.rule_key(r"price[- ]to[- ]book|P/B\b|tangible book") == "price-to-book"

    def test_a_forbidden_pattern_drops_its_parenthetical(self):
        assert ct.rule_key(r"operating cash flow (fell|rose|grew|declined|dropped)", forbidden=True) == "operating cash flow"

    def test_a_forbidden_pattern_without_a_parenthetical_is_unchanged(self):
        assert ct.rule_key(r"owner yield", forbidden=True) == "owner yield"


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


class TestGoldLabels:
    def test_load_gold_reads_the_json_file(self, tmp_path):
        p = tmp_path / "gold.json"
        p.write_text(json.dumps({"schema": 2, "generated": "2026-09-19", "AAPL": {"primary": "operating_product"}}))
        data = ct.load_gold(str(p))
        assert data["AAPL"] == {"primary": "operating_product"}
        assert data["schema"] == 2

    def test_save_gold_sorts_tickers_and_keeps_top_level_keys_first(self, tmp_path):
        p = tmp_path / "gold.json"
        data = {"schema": 2, "generated": "2026-09-19", "ZTS": {"primary": "operating_product"}, "AAPL": {"primary": "operating_product"}}
        ct.save_gold(str(p), data)
        text = p.read_text()
        assert text.endswith("\n") and not text.endswith("\n\n")
        assert text.index('"AAPL"') < text.index('"ZTS"')
        assert text.index('"generated"') < text.index('"AAPL"')
        assert json.loads(text) == data

    def test_propose_adds_a_new_ticker(self):
        data = {"schema": 2, "generated": "2026-09-19"}
        added = ct.propose(data, "KNSL", "insurer_pc", None, "run 2026-09-20")
        assert added is True
        assert data["KNSL"] == {"primary": "insurer_pc", "status": "proposed", "source": "run 2026-09-20"}

    def test_propose_includes_also_when_given(self):
        data = {}
        ct.propose(data, "BRK-A", "holding_conglomerate", ["insurer_pc"], "run 2026-09-20")
        assert data["BRK-A"]["also"] == ["insurer_pc"]

    def test_propose_does_not_overwrite_an_existing_proposal(self):
        data = {"KNSL": {"primary": "insurer_pc", "status": "proposed", "source": "seed 2026-09-19"}}
        added = ct.propose(data, "KNSL", "operating_product", None, "run 2026-09-20")
        assert added is False
        assert data["KNSL"]["primary"] == "insurer_pc"

    def test_propose_never_overwrites_a_confirmed_row(self):
        data = {"KNSL": {"primary": "insurer_pc", "status": "confirmed", "source": "user",
                          "confirmed_by": "tal", "date": "2026-09-18"}}
        added = ct.propose(data, "KNSL", "operating_product", None, "run 2026-09-20")
        assert added is False
        assert data["KNSL"]["status"] == "confirmed" and data["KNSL"]["primary"] == "insurer_pc"

    def test_confirm_sets_confirmed_status_with_todays_date(self, monkeypatch):
        import datetime as real_datetime

        class FakeDate(real_datetime.date):
            @classmethod
            def today(cls):
                return real_datetime.date(2026, 9, 19)
        monkeypatch.setattr(ct, "date", FakeDate)
        data = {}
        entry = ct.confirm(data, "KNSL", "insurer_pc", None, "tal")
        assert entry == data["KNSL"]
        assert entry["status"] == "confirmed"
        assert entry["confirmed_by"] == "tal"
        assert entry["date"] == "2026-09-19"
        assert entry["primary"] == "insurer_pc"

    def test_confirm_overwrites_an_existing_proposal(self):
        data = {"KNSL": {"primary": "operating_product", "status": "proposed", "source": "run 2026-09-01"}}
        ct.confirm(data, "KNSL", "insurer_pc", None, "tal")
        assert data["KNSL"]["primary"] == "insurer_pc" and data["KNSL"]["status"] == "confirmed"

    def test_confirm_creates_a_ticker_that_did_not_exist(self):
        data = {}
        ct.confirm(data, "NEWCO", "operating_product", None, "tal")
        assert data["NEWCO"]["status"] == "confirmed"

    def test_confirm_default_by_is_user(self):
        data = {}
        entry = ct.confirm(data, "KNSL", "insurer_pc", None)
        assert entry["confirmed_by"] == "user"


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


class TestCorpusShadow:
    def test_compare_flags_a_financial_label_on_a_non_financial_gold(self):
        cs = _load("classify_corpus")
        assert cs.compare({"primary": "insurer_pc"}, {"primary": "operating_product"}) == {"agree": False, "false_financial": True}

    def test_would_flag_names_forbidden_and_missing_required(self):
        cs = _load("classify_corpus")
        text = "Owner yield is 12.2%. Operating cash flow fell 10.1%."
        out = cs.would_flag(text, "insurer_pc")
        assert "forbidden:owner yield" in out and any(r.startswith("missing:combined ratio") for r in out)

    def test_summary_line(self):
        cs = _load("classify_corpus")
        rows = [{"ticker": "KNSL", "pred": "insurer_pc", "gold": "insurer_pc", "agree": True, "false_financial": False, "flags": ["forbidden:owner yield"], "gold_status": "confirmed"},
                {"ticker": "FAST", "pred": "operating_product", "gold": "operating_product", "agree": True, "false_financial": False, "flags": [], "gold_status": "confirmed"}]
        assert "AGREEMENT 2/2 (100%) — false financial labels 0 — memos the rules would touch 1" in cs.shadow_report(rows)

    def test_business_excerpt_reports_the_teacher_branch(self):
        cs = _load("classify_corpus")
        text = "intro\n## 1. What This Company Actually Does\nThey sell widgets.\n## 2. Next heading\nmore"
        excerpt, source = cs.business_excerpt(text)
        assert source == "teacher" and "They sell widgets." in excerpt and "Next heading" not in excerpt

    def test_business_excerpt_reports_the_fallback_branch(self):
        cs = _load("classify_corpus")
        text = "### 🕵️ JEFF BEZOS REPORT\nThey sell widgets to businesses.\n"
        excerpt, source = cs.business_excerpt(text)
        assert source == "fallback" and "They sell widgets" in excerpt

    def test_business_excerpt_reports_none_for_a_report_with_no_markers(self):
        cs = _load("classify_corpus")
        excerpt, source = cs.business_excerpt("")
        assert source == "none" and excerpt == ""

    def test_teacher_excerpt_is_capped_at_excerpt_chars(self):
        cs = _load("classify_corpus")
        body = "x" * (cs.EXCERPT_CHARS + 500)
        text = f"## 1. What This Company Actually Does\n{body}\n## 2. Next\nmore"
        excerpt, source = cs.business_excerpt(text)
        assert source == "teacher" and len(excerpt) == cs.EXCERPT_CHARS

    def test_second_summary_line_counts_teacher_excerpt_rows_only(self):
        cs = _load("classify_corpus")
        rows = [{"ticker": "KNSL", "pred": "insurer_pc", "gold": "insurer_pc", "agree": True, "false_financial": False, "flags": [], "excerpt_source": "teacher", "gold_status": "confirmed"},
                {"ticker": "FAST", "pred": "software_subscription", "gold": "operating_product", "agree": False, "false_financial": False, "flags": [], "excerpt_source": "fallback", "gold_status": "confirmed"}]
        report = cs.shadow_report(rows)
        assert "AGREEMENT (teacher-excerpt rows only) 1/1 (100%)" in report

    def test_an_error_row_is_excluded_from_the_agreement_denominator_and_listed(self):
        cs = _load("classify_corpus")
        rows = [{"ticker": "KNSL", "pred": "insurer_pc", "gold": "insurer_pc", "agree": True, "false_financial": False, "flags": [], "excerpt_source": "teacher", "gold_status": "confirmed"},
                {"ticker": "BOOM", "pred": "error", "agree": False, "error": "RuntimeError: boom"}]
        report = cs.shadow_report(rows)
        assert "AGREEMENT 1/1 (100%)" in report
        assert "## Errors" in report and "BOOM" in report and "RuntimeError: boom" in report

    def test_a_raising_ticker_becomes_an_error_row_not_a_crash(self, tmp_path, monkeypatch):
        cs = _load("classify_corpus")
        report_path = tmp_path / "X_Analysis_2026-01-01.md"
        report_path.write_text("### 🕵️ JEFF BEZOS REPORT\nSome text about the business.\n")
        monkeypatch.setattr(cs.cc, "sic_for", lambda t: None)

        class BoomClient:
            def system_one(self, *a, **k):
                raise RuntimeError("boom")

        row = cs._classify_or_error(BoomClient(), "X", str(report_path), {"X": {"primary": "operating_product"}})
        assert row["pred"] == "error" and row["agree"] is False
        assert row["error"] == "RuntimeError: boom"

    def test_proposed_rows_are_excluded_from_agreement_and_listed_separately(self):
        cs = _load("classify_corpus")
        rows = [{"ticker": "KNSL", "pred": "insurer_pc", "gold": "insurer_pc", "agree": True, "false_financial": False, "flags": [], "excerpt_source": "teacher", "gold_status": "confirmed", "pred_p": 0.9},
                {"ticker": "FAST", "pred": "operating_product", "gold": "distributor_wholesale", "agree": False, "false_financial": False, "flags": [], "excerpt_source": "teacher", "gold_status": "proposed", "pred_p": 0.6}]
        report = cs.shadow_report(rows)
        assert "AGREEMENT 1/1 (100%)" in report
        assert "## Awaiting confirmation" in report
        assert "FAST" in report.split("## Awaiting confirmation")[1]
        assert "KNSL" not in report.split("## Awaiting confirmation")[1]
        assert "distributor_wholesale" in report and "operating_product (0.60)" in report
        assert "CONFIRMED 1 of 2 gold rows" in report

    def test_zero_confirmed_rows_prints_the_no_confirmed_message_for_both_lines(self):
        cs = _load("classify_corpus")
        rows = [{"ticker": "FAST", "pred": "operating_product", "gold": "operating_product", "agree": True, "false_financial": False, "flags": [], "excerpt_source": "teacher", "gold_status": "proposed", "pred_p": 0.6}]
        report = cs.shadow_report(rows)
        assert report.count("AGREEMENT 0/0 (n/a) — no confirmed labels yet") == 2
        assert "CONFIRMED 0 of 1 gold rows" in report

    def test_classify_row_records_gold_status(self, tmp_path, monkeypatch):
        cs = _load("classify_corpus")
        report_path = tmp_path / "X_Analysis_2026-01-01.md"
        report_path.write_text("### 🕵️ JEFF BEZOS REPORT\nThey run a widget business.\n")
        monkeypatch.setattr(cs.cc, "sic_for", lambda t: None)
        client = NS(system_one=lambda state, questions: NS(
            choices={"model": NS(probabilities={"operating_product": 0.8})}))
        gold = {"X": {"primary": "operating_product", "status": "confirmed"}}
        row = cs._classify_row(client, "X", str(report_path), gold)
        assert row["gold_status"] == "confirmed"

    def test_classify_row_defaults_gold_status_to_proposed_when_absent(self, tmp_path, monkeypatch):
        cs = _load("classify_corpus")
        report_path = tmp_path / "X_Analysis_2026-01-01.md"
        report_path.write_text("### 🕵️ JEFF BEZOS REPORT\nThey run a widget business.\n")
        monkeypatch.setattr(cs.cc, "sic_for", lambda t: None)
        client = NS(system_one=lambda state, questions: NS(
            choices={"model": NS(probabilities={"operating_product": 0.8})}))
        gold = {"X": {"primary": "operating_product"}}
        row = cs._classify_row(client, "X", str(report_path), gold)
        assert row["gold_status"] == "proposed"

    def test_gold_lookup_has_no_dead_default_for_a_ticker_not_in_gold(self):
        cs = _load("classify_corpus")
        # tickers reaching _classify_row are already filtered to gold in _main;
        # a ticker missing from gold is a programming error, not a silent default.
        import inspect
        assert "operating_product" not in inspect.getsource(cs._classify_row)


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


class TestCacheKey:
    """The XBRL facts are a classification input, so a run that gained an
    xbrl.json must re-classify rather than serve the dossier-only answer."""

    def _prepare(self, tmp_path):
        cc = _load_classify_company()
        (tmp_path / "initial_dossier.txt").write_text("INDUSTRY: Insurance\n", encoding="utf-8")
        runs = []
        cc.classify = lambda client, d, ticker: (runs.append(ticker),
                                                 open(os.path.join(d, "company_type.json"), "w").write("{}"))
        return cc, runs

    def test_a_changed_xbrl_file_invalidates_the_cached_classification(self, tmp_path):
        cc, runs = self._prepare(tmp_path)
        (tmp_path / "xbrl.json").write_text('{"Revenues": 1}', encoding="utf-8")
        cc._run(None, "KNSL", str(tmp_path))
        cc._run(None, "KNSL", str(tmp_path))
        assert runs == ["KNSL"]                       # second call is a cache hit
        (tmp_path / "xbrl.json").write_text('{"Revenues": 2}', encoding="utf-8")
        cc._run(None, "KNSL", str(tmp_path))
        assert runs == ["KNSL", "KNSL"]

    def test_an_xbrl_file_appearing_after_a_cached_run_invalidates_it(self, tmp_path):
        cc, runs = self._prepare(tmp_path)
        cc._run(None, "KNSL", str(tmp_path))
        (tmp_path / "xbrl.json").write_text('{"Revenues": 1}', encoding="utf-8")
        cc._run(None, "KNSL", str(tmp_path))
        assert runs == ["KNSL", "KNSL"]

    def test_without_an_xbrl_file_the_dossier_alone_still_caches(self, tmp_path):
        cc, runs = self._prepare(tmp_path)
        cc._run(None, "KNSL", str(tmp_path))
        cc._run(None, "KNSL", str(tmp_path))
        assert runs == ["KNSL"]

    def test_classify_proposes_the_gold_label_when_something_new(self, tmp_path, monkeypatch):
        cc = _load_classify_company()
        gold_path = tmp_path / "gold.json"
        gold_path.write_text(json.dumps({"schema": 2, "generated": "2026-09-19"}))
        monkeypatch.setattr(cc, "GOLD_PATH", str(gold_path))
        (tmp_path / "initial_dossier.txt").write_text("INDUSTRY: Insurance - Property & Casualty\n--- SECTION A: BUSINESS ---\nKinsale writes E&S insurance.\n")
        monkeypatch.setattr(cc, "sic_for", lambda ticker: "6331")
        monkeypatch.setattr(cc, "xbrl_for", lambda d: {})
        calls = iter([
            NS(choices={"model": NS(choice="insurer_pc", confidence=0.85, probabilities={"insurer_pc": 0.85, "operating_product": 0.4})}, nouls={}, usage=NS(input_tokens=1), model="f"),
            NS(choices={"regime": NS(choice="cyclical_timing", confidence=0.7, probabilities={"cyclical_timing": 0.7})}, nouls={}, usage=NS(input_tokens=1), model="f"),
            NS(choices={"jurisdiction": NS(choice="developed", confidence=0.95, probabilities={"developed": 0.95})}, nouls={}, usage=NS(input_tokens=1), model="f"),
            NS(choices={"capital": NS(choice="float_funded", confidence=0.9, probabilities={"float_funded": 0.9})}, nouls={}, usage=NS(input_tokens=1), model="f"),
        ])
        client = NS(system_one=lambda state, questions: next(calls))
        out, printed = cc.classify(client, str(tmp_path), "KNSL"), None
        gold = ct.load_gold(str(gold_path))
        assert gold["KNSL"]["primary"] == "insurer_pc"
        assert gold["KNSL"]["status"] == "proposed"
        assert gold["KNSL"]["source"].startswith("run ")

    def test_classify_never_overwrites_an_already_confirmed_gold_row(self, tmp_path, monkeypatch):
        cc = _load_classify_company()
        gold_path = tmp_path / "gold.json"
        gold_path.write_text(json.dumps({"schema": 2, "generated": "2026-09-19",
                                          "KNSL": {"primary": "operating_product", "status": "confirmed",
                                                    "source": "user", "confirmed_by": "tal", "date": "2026-09-18"}}))
        monkeypatch.setattr(cc, "GOLD_PATH", str(gold_path))
        (tmp_path / "initial_dossier.txt").write_text("INDUSTRY: Insurance - Property & Casualty\n--- SECTION A: BUSINESS ---\nKinsale writes E&S insurance.\n")
        monkeypatch.setattr(cc, "sic_for", lambda ticker: "6331")
        monkeypatch.setattr(cc, "xbrl_for", lambda d: {})
        calls = iter([
            NS(choices={"model": NS(choice="insurer_pc", confidence=0.85, probabilities={"insurer_pc": 0.85})}, nouls={}, usage=NS(input_tokens=1), model="f"),
            NS(choices={"regime": NS(choice="cyclical_timing", confidence=0.7, probabilities={"cyclical_timing": 0.7})}, nouls={}, usage=NS(input_tokens=1), model="f"),
            NS(choices={"jurisdiction": NS(choice="developed", confidence=0.95, probabilities={"developed": 0.95})}, nouls={}, usage=NS(input_tokens=1), model="f"),
            NS(choices={"capital": NS(choice="float_funded", confidence=0.9, probabilities={"float_funded": 0.9})}, nouls={}, usage=NS(input_tokens=1), model="f"),
        ])
        client = NS(system_one=lambda state, questions: next(calls))
        cc.classify(client, str(tmp_path), "KNSL")
        gold = ct.load_gold(str(gold_path))
        assert gold["KNSL"]["status"] == "confirmed" and gold["KNSL"]["primary"] == "operating_product"

    def test_classify_prints_the_proposed_line_only_when_something_was_added(self, tmp_path, monkeypatch, capsys):
        cc = _load_classify_company()
        gold_path = tmp_path / "gold.json"
        gold_path.write_text(json.dumps({"schema": 2, "generated": "2026-09-19"}))
        monkeypatch.setattr(cc, "GOLD_PATH", str(gold_path))
        (tmp_path / "initial_dossier.txt").write_text("INDUSTRY: Insurance - Property & Casualty\n--- SECTION A: BUSINESS ---\nKinsale writes E&S insurance.\n")
        monkeypatch.setattr(cc, "sic_for", lambda ticker: "6331")
        monkeypatch.setattr(cc, "xbrl_for", lambda d: {})
        calls = iter([
            NS(choices={"model": NS(choice="insurer_pc", confidence=0.85, probabilities={"insurer_pc": 0.85})}, nouls={}, usage=NS(input_tokens=1), model="f"),
            NS(choices={"regime": NS(choice="cyclical_timing", confidence=0.7, probabilities={"cyclical_timing": 0.7})}, nouls={}, usage=NS(input_tokens=1), model="f"),
            NS(choices={"jurisdiction": NS(choice="developed", confidence=0.95, probabilities={"developed": 0.95})}, nouls={}, usage=NS(input_tokens=1), model="f"),
            NS(choices={"capital": NS(choice="float_funded", confidence=0.9, probabilities={"float_funded": 0.9})}, nouls={}, usage=NS(input_tokens=1), model="f"),
        ])
        client = NS(system_one=lambda state, questions: next(calls))
        cc.classify(client, str(tmp_path), "KNSL")
        assert "gold: proposed insurer_pc" in capsys.readouterr().out


class TestGoldCli:
    def test_confirm_cli_writes_and_prints_the_entry(self, tmp_path, capsys):
        cs = _load("classify_corpus")
        gold_path = tmp_path / "gold.json"
        gold_path.write_text(json.dumps({"schema": 2, "generated": "2026-09-19"}))
        rc = cs._cli(["confirm", "KNSL", "insurer_pc"], gold_path=str(gold_path))
        assert rc == 0
        out = capsys.readouterr().out
        assert "KNSL" in out and "insurer_pc" in out
        gold = ct.load_gold(str(gold_path))
        assert gold["KNSL"]["status"] == "confirmed" and gold["KNSL"]["confirmed_by"] == "user"

    def test_confirm_cli_honors_by_flag(self, tmp_path):
        cs = _load("classify_corpus")
        gold_path = tmp_path / "gold.json"
        gold_path.write_text(json.dumps({"schema": 2, "generated": "2026-09-19"}))
        cs._cli(["confirm", "KNSL", "insurer_pc", "--by", "tal"], gold_path=str(gold_path))
        gold = ct.load_gold(str(gold_path))
        assert gold["KNSL"]["confirmed_by"] == "tal"

    def test_confirm_cli_accepts_also_labels(self, tmp_path):
        cs = _load("classify_corpus")
        gold_path = tmp_path / "gold.json"
        gold_path.write_text(json.dumps({"schema": 2, "generated": "2026-09-19"}))
        cs._cli(["confirm", "BRK-A", "holding_conglomerate", "insurer_pc,asset_manager"], gold_path=str(gold_path))
        gold = ct.load_gold(str(gold_path))
        assert gold["BRK-A"]["also"] == ["insurer_pc", "asset_manager"]

    def test_propose_cli_writes_and_prints_the_entry(self, tmp_path, capsys):
        cs = _load("classify_corpus")
        gold_path = tmp_path / "gold.json"
        gold_path.write_text(json.dumps({"schema": 2, "generated": "2026-09-19"}))
        rc = cs._cli(["propose", "KNSL", "insurer_pc", "--source", "run 2026-09-20"], gold_path=str(gold_path))
        assert rc == 0
        out = capsys.readouterr().out
        assert "KNSL" in out and "insurer_pc" in out
        gold = ct.load_gold(str(gold_path))
        assert gold["KNSL"]["status"] == "proposed" and gold["KNSL"]["source"] == "run 2026-09-20"

    def test_propose_cli_does_not_overwrite_a_confirmed_row(self, tmp_path):
        cs = _load("classify_corpus")
        gold_path = tmp_path / "gold.json"
        gold_path.write_text(json.dumps({"schema": 2, "generated": "2026-09-19",
                                          "KNSL": {"primary": "insurer_pc", "status": "confirmed",
                                                    "source": "user", "confirmed_by": "tal", "date": "2026-09-18"}}))
        cs._cli(["propose", "KNSL", "operating_product", "--source", "run 2026-09-20"], gold_path=str(gold_path))
        gold = ct.load_gold(str(gold_path))
        assert gold["KNSL"]["status"] == "confirmed" and gold["KNSL"]["primary"] == "insurer_pc"

    def test_confirm_via_subprocess_cli(self, tmp_path):
        cs = _load("classify_corpus")
        gold_path = tmp_path / "gold.json"
        gold_path.write_text(json.dumps({"schema": 2, "generated": "2026-09-19"}))
        import subprocess
        result = subprocess.run(
            [sys.executable, cs.__file__ if hasattr(cs, "__file__") else os.path.join(_SCRIPTS_DIR, "classify_corpus.py"),
             "confirm", "KNSL", "insurer_pc", "--by", "tal", "--gold-path", str(gold_path)],
            capture_output=True, text=True, cwd=os.path.join(os.path.dirname(__file__), ".."))
        assert result.returncode == 0, result.stderr
        assert "KNSL" in result.stdout
        gold = ct.load_gold(str(gold_path))
        assert gold["KNSL"]["confirmed_by"] == "tal"
