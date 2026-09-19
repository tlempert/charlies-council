"""Jev advisory checks: snippet triage, council independence, dossier neutrality.

The model is faked: these tests pin the code's decisions — what gets
dropped, what counts as an echo, what counts as steering — not Jev's.
"""
import importlib.util
import os
from types import SimpleNamespace as NS

_SCRIPTS = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), "scripts")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_SCRIPTS, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _answer(nouls=None, choices=None):
    return NS(
        nouls={k: NS(noul=v) for k, v in (nouls or {}).items()},
        choices={k: NS(choice=c, confidence=p, probabilities={c: p}) for k, (c, p) in (choices or {}).items()},
        usage=NS(input_tokens=10), model="jev-fake",
    )


def _fake_ask(answers):
    """answers: list, one per call, in order."""
    it = iter(answers)
    return lambda state, questions: next(it)


# --- jev_snippets ------------------------------------------------------------

snippets = _load("jev_snippets")

RAW = ("SOURCE: Kinsale posts higher profit (https://x/1)\nCONTENT: Net income rose 20% to $120M.\n\n"
       "THREAT: Staff directory\nCONTENT: Employees at Kinsale Capital: 700.\n\n")


class TestSnippetTriage:
    def test_parses_both_source_and_threat_records(self):
        recs = snippets.parse(RAW)
        assert [r["kind"] for r in recs] == ["SOURCE", "THREAT"]
        assert recs[0]["title"] == "Kinsale posts higher profit"

    def test_strips_the_url_from_a_source_title(self):
        assert snippets.parse("SOURCE: Title here (https://a.b/c?d=1)\nCONTENT: x\n\n")[0]["title"] == "Title here"

    def test_relevance_alone_never_drops_a_substantive_finding(self):
        # ROG.SW: Elevidys deaths and pharma tariffs scored p(about)≈0.1 because they reach Roche via a partner and a policy
        a = _answer({"about_company": 0.1, "has_figure": 0.9}, {"category": ("red_flag", 0.9), "status": ("enacted", 1), "role": ("neither", 1)})
        assert not snippets.judge({"title": "t"}, a)["drop"]

    def test_low_relevance_drops_only_when_also_off_topic(self):
        a = _answer({"about_company": 0.2, "has_figure": 0.1}, {"category": ("off_topic", 0.5), "status": ("not_applicable", 1), "role": ("neither", 1)})
        assert snippets.judge({"title": "t"}, a)["drop"]

    def test_drops_off_topic_only_when_confident(self):
        sure = _answer({"about_company": 0.9, "has_figure": 0.1}, {"category": ("off_topic", 0.95), "status": ("not_applicable", 1), "role": ("neither", 1)})
        unsure = _answer({"about_company": 0.9, "has_figure": 0.1}, {"category": ("off_topic", 0.8), "status": ("not_applicable", 1), "role": ("neither", 1)})
        assert snippets.judge({"title": "t"}, sure)["drop"]
        assert not snippets.judge({"title": "t"}, unsure)["drop"]

    def test_report_names_every_drop_and_an_unpaired_accusation(self):
        rows = [
            {"title": "Bear Cave", "about": 0.9, "category": "red_flag", "cat_conf": 1, "status": "enacted", "role": "accusation", "figure": 1, "drop": False},
            {"title": "Directory", "about": 0.9, "category": "off_topic", "cat_conf": 0.8, "status": "n/a", "role": "neither", "figure": 0, "drop": True},
        ]
        text = snippets.report("KNSL", rows, 20, "jev-fake")
        assert "- Directory — about=0.9, off_topic@0.8" in text
        assert "UNPAIRED" in text

    def test_run_keeps_input_order_and_sums_tokens(self):
        recs = snippets.parse(RAW)
        keep = _answer({"about_company": 0.95, "has_figure": 0.9}, {"category": ("accounting", 0.9), "status": ("enacted", 1), "role": ("neither", 1)})
        drop = _answer({"about_company": 0.9, "has_figure": 0.1}, {"category": ("off_topic", 0.9), "status": ("not_applicable", 1), "role": ("neither", 1)})
        rows, tokens, model = snippets.run("KNSL", "Kinsale", recs, _fake_ask([keep, drop]), workers=1)
        assert [r["drop"] for r in rows] == [False, True]
        assert tokens == 20 and model == "jev-fake"

    def test_snippet_run_accepts_workers_and_keeps_order(self):
        recs = snippets.parse(RAW)
        keep = _answer({"about_company": 0.95, "has_figure": 0.9}, {"category": ("accounting", 0.9), "status": ("enacted", 1), "role": ("neither", 1)})
        drop = _answer({"about_company": 0.9, "has_figure": 0.1}, {"category": ("off_topic", 0.9), "status": ("not_applicable", 1), "role": ("neither", 1)})
        rows, _, _ = snippets.run("KNSL", "Kinsale", recs, _fake_ask([keep, drop]), workers=1)
        assert [r["drop"] for r in rows] == [False, True]


# --- jev_summaries -----------------------------------------------------------

summaries = _load("jev_summaries")

BLOCKS = "".join(
    f"=== EXPERT: {k} ===\n---SUMMARY---\nVERDICT: HOLD\nKEY METRIC: x\nTRIGGER PRICE: $200 @ 9% — {basis}\n---END SUMMARY---\n\n"
    for k, basis in [("a", "no-growth yield"), ("b", "no-growth yield"), ("c", "scenario grid")]
)


class TestIndependenceAudit:
    def test_reads_the_fields_of_every_block(self):
        b = summaries.blocks(BLOCKS)
        assert [x["expert"] for x in b] == ["a", "b", "c"]
        assert b[2]["trigger"].endswith("scenario grid")

    def test_warns_when_one_basis_carries_most_of_the_council(self):
        rows = [{"basis": "zero_growth_yield", "metric": f"m{i}"} for i in range(8)] + [{"basis": "scenario_grid_or_dcf", "metric": "g"} for _ in range(4)]
        head, _, _ = summaries.verdict(rows)
        assert head.startswith("WARN") and "zero_growth_yield ×8" in head

    def test_passes_a_council_with_spread_bases(self):
        rows = [{"basis": b, "metric": m} for b, m in zip("abcdef", "uvwxyz")] * 2
        assert summaries.verdict(rows)[0].startswith("OK")

    def test_report_lists_low_confidence_experts_for_hand_reading(self):
        rows = [{"expert": "cook", "verdict": "HOLD", "basis": "zero_growth_yield", "basis_conf": 0.48, "metric": "growth", "metric_conf": 1.0}]
        assert "Read by hand (basis confidence < 0.6): cook" in summaries.report(rows)


# --- jev_neutrality ----------------------------------------------------------

neutrality = _load("jev_neutrality")

DOSSIER = ("## DATA QUALITY SCORECARD\n\n" + "The pipeline's owner-yield figure is operating cash flow, not owner cash; treat it as unreliable. " * 3 + "\n\n"
           "## BUSINESS FACTS\n\n" + "Kinsale writes E&S casualty through wholesale brokers; the 2025 combined ratio was 76%. " * 3 + "\n\n"
           "--- MOAT THREAT SEARCH ---\n\n" + "The DigitalEdge platform is flexible, scalable and highly configurable. " * 3 + "\n")


class TestNeutrality:
    def test_skips_warning_sections_by_title(self):
        calls = []

        def ask(state, qs):
            calls.append(state.get("section_title"))
            return _answer({"editorial": 0.1, "steers": 0.1})

        neutrality.run(DOSSIER, ask, workers=1)
        assert "## DATA QUALITY SCORECARD" not in calls
        assert "## BUSINESS FACTS" in calls

    def test_reports_editorialising_sections_and_steering_paragraphs(self):
        answers = [
            _answer({"editorial": 0.1}), _answer({"steers": 0.2}),     # business facts
            _answer({"editorial": 0.95}), _answer({"steers": 0.8}),    # threat entry with vendor copy
        ]
        read, steering, tokens = neutrality.run(DOSSIER, _fake_ask(answers), workers=1)
        text = neutrality.report(read, steering, tokens)
        assert "- 0.95 — --- MOAT THREAT SEARCH ---" in text
        assert "0.8 [--- MOAT THREAT SEARCH ---]" in text
        assert text.strip().endswith("STEERING: 1 section(s), 1 paragraph(s) — strip or justify each")

    def test_prints_neutral_when_nothing_editorialises(self):
        assert neutrality.report([("## X", 0.1)], [], 5).strip().endswith("NEUTRAL")

    def test_a_weak_signal_is_not_reported(self):
        assert "Editorialising sections (p ≥ 0.75): 0" in neutrality.report([("## X", 0.72)], [], 5)


# --- modules/jev advisory boundary ------------------------------------------

class TestCache:
    def test_cached_only_when_inputs_unchanged(self, tmp_path):
        from modules import jev
        src, out = tmp_path / "in.md", tmp_path / "out.md"
        src.write_text("v1"); out.write_text("result")
        assert not jev.cached(str(out), str(src))
        jev.stamp(str(out), str(src))
        assert jev.cached(str(out), str(src))
        src.write_text("v2")
        assert not jev.cached(str(out), str(src))


class TestSnippetsCache:
    def test_triage_skips_a_second_call_with_unchanged_input(self, tmp_path):
        p = tmp_path / "raw.txt"
        p.write_text(RAW)
        calls = []

        def ask(state, qs):
            calls.append(1)
            return _answer({"about_company": 0.95, "has_figure": 0.9},
                           {"category": ("accounting", 0.9), "status": ("enacted", 1), "role": ("neither", 1)})

        client = NS(system_one=ask)
        snippets.triage(client, "KNSL", "Kinsale", str(p))
        n = len(calls)
        assert n > 0
        snippets.triage(client, "KNSL", "Kinsale", str(p))
        assert len(calls) == n


class TestNeutralityCache:
    def test_read_skips_a_second_call_with_unchanged_dossier(self, tmp_path):
        p = tmp_path / "refined_dossier.md"
        p.write_text(DOSSIER)
        calls = []

        def ask(state, qs):
            calls.append(1)
            return _answer({"editorial": 0.1, "steers": 0.1})

        client = NS(system_one=ask)
        neutrality.read(client, str(p))
        n = len(calls)
        assert n > 0
        neutrality.read(client, str(p))
        assert len(calls) == n


class TestSummariesCache:
    def test_audit_skips_a_second_call_with_unchanged_input(self, tmp_path):
        p = tmp_path / "all_summaries.md"
        p.write_text(BLOCKS)
        calls = []

        def ask(state, q):
            calls.append(1)
            return _answer({}, {"basis": ("zero_growth_yield", 0.9), "metric": ("growth", 0.9)})

        client = NS(system_one=ask)
        summaries.audit(client, str(p))
        n = len(calls)
        assert n > 0
        summaries.audit(client, str(p))
        assert len(calls) == n


class TestAdvisoryBoundary:
    def test_skips_with_exit_zero_when_there_is_no_key(self, monkeypatch, capsys):
        from modules import jev
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        assert jev.advisory(lambda c: 1 / 0) == 0
        assert "SKIPPED" in capsys.readouterr().out

    def test_a_failing_check_prints_why_and_still_exits_zero(self, monkeypatch, capsys):
        from modules import jev
        monkeypatch.setenv("TYPESAFE_API_KEY", "apikey_fake")
        monkeypatch.setattr(jev, "client", lambda: object())

        def check(c):
            raise RuntimeError("429 rate limited")

        assert jev.advisory(check) == 0
        assert "FAILED (RuntimeError: 429 rate limited)" in capsys.readouterr().out


# --- jev_tiers ---------------------------------------------------------------

tiers = _load("jev_tiers")

MEMO_T = ("# Verdict\n\n```json model_ledger\n{\"price\": 362.48}\n```\n\n"
        "The record shows that soft-priced vintages release little or nothing [SEC]. "
        "Baron added at $300-310, inside my zone [CALC]. A sentence with no tag and no figure here.\n")
DOSSIER_T = ("## RESERVES\n\n[SEC] One construction-liability line of the AY2018-19 vintage went adverse in Q2, net $1.9M against $20.6M gross favorable.\n"
           "[MEDIA per GuruFocus] Baron reported an add at $300-310 on 2026-05-31; the price is inferred from the CEO's 2026-05-05 sale.\n"
           "| Q2-2026 | combined ratio 75.5% |\n")


def _rel(choice, p):
    return NS(choices={"relation": NS(choice=choice, confidence=p, probabilities={choice: p})}, usage=NS(input_tokens=10), model="jev-fake")


class TestEvidenceTiers:
    def test_claims_skip_the_ledger_block_and_untagged_unfigured_prose(self):
        c = tiers.claims(MEMO_T)
        assert len(c) == 2 and all("362.48" not in s for s in c)

    def test_a_table_row_is_one_dossier_unit(self):
        assert "| Q2-2026 | combined ratio 75.5% |" in tiers.sentences(DOSSIER_T)

    def test_pairing_prefers_shared_numbers_over_shared_words(self):
        pool = tiers.sentences(DOSSIER_T)
        top = tiers.candidates("Baron added at $300-310, inside my zone [CALC].", pool)[0]
        assert "GuruFocus" in top

    def test_tag_upgrade_is_decided_by_code(self):
        assert tiers.tag_upgraded("x [SEC]", "y [MEDIA per Z]")
        assert not tiers.tag_upgraded("x [MEDIA]", "y [SEC]")
        assert not tiers.tag_upgraded("x", "y [SEC]")

    def test_reports_a_confident_promotion_and_a_tag_upgrade_even_when_same_tier(self):
        def ask(state, q):
            if "soft-priced" in state["memo_sentence"]:
                return _rel("promoted", 0.9)
            if "Baron" in state["memo_sentence"] and "GuruFocus" in state["dossier_sentence"]:
                return _rel("same_tier", 0.8)
            return _rel("not_the_source", 0.9)

        findings, pairs, tokens = tiers.run(MEMO_T, DOSSIER_T, ask)
        assert pairs >= 2 and tokens == 10 * pairs
        assert [f["relation"] for f in findings] == ["promoted", "same_tier"]
        assert findings[1]["tag_upgrade"]      # [CALC] in memo over [MEDIA] in dossier, flagged by code

    def test_a_tag_upgrade_on_a_pair_that_is_not_the_source_is_ignored(self):
        findings, _, _ = tiers.run("Baron added at $300-310 [SEC].", "[MEDIA] Baron added at $300-310.", lambda s, q: _rel("not_the_source", 0.9))
        assert findings == []

    def test_a_pair_sharing_one_number_and_no_word_is_never_asked(self):
        pool = ["Digitized underwriting can cut cycle times by up to 80%."]
        assert tiers.candidates("The sub-80% the bull case requires is the actual result.", pool) == []

    def test_certainty_language_counts_as_a_claim_without_a_tag_or_figure(self):
        assert tiers.claims("The record therefore already shows what soft-priced vintages do: they release little or nothing.") != []

    def test_a_weak_promotion_is_not_reported(self):
        findings, _, _ = tiers.run("Growth was 20% [SEC].", "[SEC] Growth was 20% in FY25.", lambda s, q: _rel("promoted", 0.6))
        assert findings == []

    def test_report_ends_clean_or_review(self):
        assert tiers.report([], 3, 30).strip().endswith("CLEAN — no promoted claim found")
        text = tiers.report([{"p": 0.9, "relation": "promoted", "memo": "m", "dossier": "d", "tag_upgrade": True}], 3, 30)
        assert "TAG UPGRADED" in text and text.strip().endswith("verify each before pass 1")


class TestTiersCache:
    def test_check_skips_a_second_call_with_unchanged_inputs(self, tmp_path):
        (tmp_path / "verdict.md").write_text(MEMO_T)
        (tmp_path / "refined_dossier.md").write_text(DOSSIER_T)
        calls = []

        def ask(state, q):
            calls.append(1)
            return _rel("not_the_source", 0.9)

        client = NS(system_one=ask)
        tiers.check(client, str(tmp_path))
        n = len(calls)
        assert n > 0
        tiers.check(client, str(tmp_path))
        assert len(calls) == n


# --- jev_contradictions -----------------------------------------------------

contra = _load("jev_contradictions")

KNSL_MEMO = ("The pipeline's 12.2% owner yield is float, not owner cash: TTM operating cash flow is $1.04B against net income near $0.57B. "
             "Operating cash flow fell 10.1% while revenue rose 16.8%. My interpretation: the soft market shows in cash conversion before the combined ratio — the print to watch next.")


class TestContradictions:
    def test_pairs_share_a_measure_term_and_a_reject_then_use_shape(self):
        pairs = contra.pairs_for(KNSL_MEMO)
        assert pairs and all("operating cash flow" in a.lower() and "operating cash flow" in b.lower() for a, b in pairs)

    def test_relies_on_rejected_is_a_finding_only_when_confident(self):
        sure = _answer(choices={"relation": ("relies_on_rejected", 0.85)})
        unsure = _answer(choices={"relation": ("relies_on_rejected", 0.5)})
        assert contra.judge(("a", "b"), sure)
        assert contra.judge(("a", "b"), unsure) is None

    def test_report_says_consistent_when_nothing_found(self):
        assert "CONSISTENT" in contra.report([], 3, 30)

    def test_no_pairs_when_no_sentence_rejects_a_measure(self):
        text = ("Operating cash flow rose 10.1% this quarter on strong renewals across the book. "
                "Revenue also grew nicely and margins held up well across every segment we track.")
        assert contra.pairs_for(text) == []

    def test_a_sentence_naming_two_measures_is_paired_once(self):
        rejects = ("Operating cash flow and free cash flow are not owner cash for this pipeline, "
                    "so ignore both figures when sizing the position today.")
        uses = ("Operating cash flow and free cash flow fell sharply last quarter and that is the "
                "print to watch most closely next.")
        pairs = contra.pairs_for(f"{rejects} {uses}")
        assert pairs == [(rejects, uses)]

    def test_check_writes_to_out_name_when_given(self, tmp_path):
        (tmp_path / "memo.md").write_text("Plain prose with no measures worth pairing at all.")
        client = NS(system_one=lambda state, q: _answer(choices={"relation": ("unrelated", 0.9)}))
        contra.check(client, str(tmp_path), memo_name="memo.md", out_name="jev_contradictions.memo.md")
        assert (tmp_path / "jev_contradictions.memo.md").exists()
        assert not (tmp_path / "jev_contradictions.md").exists()


class TestContradictionsCache:
    def test_check_skips_a_second_call_with_unchanged_memo(self, tmp_path):
        (tmp_path / "verdict.md").write_text(KNSL_MEMO)
        calls = []

        def ask(state, q):
            calls.append(1)
            return _answer(choices={"relation": ("unrelated", 0.9)})

        client = NS(system_one=ask)
        contra.check(client, str(tmp_path))
        n = len(calls)
        assert n > 0
        contra.check(client, str(tmp_path))
        assert len(calls) == n


# --- jev_findings -----------------------------------------------------------

jf = _load("jev_findings")
gp = _load("gate_policy")


class TestFindings:
    F = [{"severity": "FATAL", "prose_only": False, "name": "Reserve risk charged twice", "body": "Operation: charge it once."},
         {"severity": "MODERATE", "prose_only": True, "name": "Terminal price label", "body": "Operation: relabel the column."}]

    def test_classes_are_attached_from_jev(self):
        a1 = _answer({"wording_only": 0.1, "prescribes_value": 0.05}, {"resolution": ("addressed", 0.9)})
        a2 = _answer({"wording_only": 0.9, "prescribes_value": 0.05}, {"resolution": ("unaddressed", 0.8)})
        out = jf.run(self.F, "B — removed the IBNR haircut from the multiple", "verdict", _fake_ask([a1, a2]), workers=1)
        assert out[0]["resolution"] == "addressed" and out[1]["wording_only"] == 0.9

    def test_values_in_the_operation_clause_are_struck(self):
        body = "Quote: 'at 17x'. Operation: use an 18x–20x band and a $306 ceiling."
        assert jf.strip_values(body) == "Quote: 'at 17x'. Operation: use an [value struck]–[value struck] band and a [value struck] ceiling."


class TestFindingsCache:
    def test_classify_skips_a_second_call_with_unchanged_inputs(self, tmp_path):
        import json
        (tmp_path / "findings.json").write_text(json.dumps(TestFindings.F))
        (tmp_path / "verdict.md").write_text(KNSL_VERDICT)
        calls = []

        def ask(state, q):
            calls.append(1)
            return _answer({"wording_only": 0.1, "prescribes_value": 0.05}, {"resolution": ("addressed", 0.9)})

        client = NS(system_one=ask)
        jf.classify(client, str(tmp_path))
        n = len(calls)
        assert n > 0
        jf.classify(client, str(tmp_path))
        assert len(calls) == n


# KNSL-shaped: title, a decoy heading that merely mentions "correction" in
# passing, the real §6 log with Pass 1/Pass 2 subsections and J1/J2 items,
# then a following top-level heading the log must not swallow.
KNSL_VERDICT = """# KNSL — Munger Synthesis (revised after Reality Check pass 2)
**Kinsale Capital Group** | Analysis date 2026-09-17 | Price $362.48

## 3. Decision Logic

A note on correction of the prior estimate belongs here, not in the log.

## 6. CORRECTION LOG

### Pass 1 (reviewed 2026-09-16; corrections in draft 2)

- **M1 — $305 growth-table row did not reproduce.** Row and trigger removed.
- **J1 — Multiple 17x -> 16x (judgment, draft 2).** Reasons given at the time: RLI/WRB GAAP P/Es cap the top of the band.

### Pass 2 (reviewed 2026-09-17; corrections in this draft)

- **J2 — Multiple 16x -> 17x (judgment, this draft).** Reasons: the reserve charge was removed and the comparators were corrected.

## 7. Ledger Note

This section must not be included in the correction log.
"""


class TestCorrectionLogOf:
    def test_the_section_after_the_correction_log_heading_is_returned(self):
        log = jf.correction_log_of(KNSL_VERDICT)
        assert "### Pass 1" in log and "J1" in log and "J2" in log
        assert "Ledger Note" not in log
        assert "note on correction of the prior estimate" not in log

    def test_a_flip_in_the_returned_log_is_attributed(self):
        assert gp.flip_attributed(jf.correction_log_of(KNSL_VERDICT))

    def test_no_matching_heading_returns_empty_string(self):
        assert jf.correction_log_of("# Title\n\n## 1. Something else entirely\n\nprose\n") == ""
