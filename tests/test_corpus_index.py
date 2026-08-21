"""Tests for the CORPUS_INDEX verdict parser."""
import importlib.util
import os
import sys

import pytest

_ROOT = os.path.join(os.path.dirname(__file__), "..")
_SPEC = importlib.util.spec_from_file_location(
    "build_corpus_index", os.path.join(_ROOT, "scripts", "build_corpus_index.py"))
build_corpus_index = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_corpus_index)
parse_verdict = build_corpus_index.parse_verdict


def _write(tmp_path, body):
    p = tmp_path / "V_Analysis_2026-08-20.md"
    p.write_text(body, encoding="utf-8")
    return str(p)


class TestTriggerPriceFallback:
    """A verdict that declines to publish a Buy Zone must still be machine-readable.

    KSPI produced a blank index row — decision, zone and conviction all "—" —
    because Munger returned TOO UNCERTAIN with no buy zone and the parser
    anchors only on '**Buy Zone:**'. An unparseable verdict is an unactionable one.
    """

    def test_parses_trigger_price_when_no_buy_zone(self, tmp_path):
        path = _write(tmp_path, """
# Munger Synthesis
**Decision: TOO UNCERTAIN**
**Trigger Price: $70-85**
Current Price: $101.48
""")
        r = parse_verdict(path)
        assert r['decision'] == 'TOO UNCERTAIN'
        assert r['buy_zone'] == '$70–$85'

    def test_buy_zone_still_wins_when_both_are_present(self, tmp_path):
        """Buy Zone is the stronger declaration; Trigger Price is the fallback."""
        path = _write(tmp_path, """
**Decision: BUY**
**Buy Zone: $40-50**
**Trigger Price: $30-35**
""")
        assert parse_verdict(path)['buy_zone'] == '$40–$50'

    def test_parses_currency_aware_trigger(self, tmp_path):
        path = _write(tmp_path, """
**Decision: WAIT**
**Trigger Price: £24 - £28**
""")
        assert parse_verdict(path)['buy_zone'] == '£24–£28'

    def test_records_no_price_compensates_as_an_explicit_answer(self, tmp_path):
        """'No price works' is a real verdict and must be distinguishable from
        'the parser found nothing', which is what an em-dash means today."""
        path = _write(tmp_path, """
**Decision: TOO UNCERTAIN**
**Trigger Price: NONE — no price compensates**
""")
        assert parse_verdict(path)['buy_zone'] == 'NONE'

    def test_absent_price_still_yields_a_dash(self, tmp_path):
        """Regression guard: a verdict with neither anchor must not crash."""
        path = _write(tmp_path, "**Decision: HOLD**\nNo prices here.\n")
        assert parse_verdict(path)['buy_zone'] == '—'


class TestVerdictHeadingForms:
    """The synthesis states its call as a heading before restating it in prose.

    KSPI's revised memo opens '## THE VERDICT: WAIT' at offset 291, while the
    '**Decision: WAIT.**' restatement fell outside the parser's 15k window — so
    the index row showed a blank decision beside a perfectly good trigger price.
    """

    def test_parses_the_verdict_heading(self, tmp_path):
        path = _write(tmp_path, """
# KSPI — Munger Synthesis: Final Investment Memo (REVISED)

## THE VERDICT: WAIT

**Trigger Price: $70-85**
""")
        r = parse_verdict(path)
        assert r['decision'] == 'WAIT'
        assert r['buy_zone'] == '$70–$85'

    def test_parses_multiword_verdict_heading(self, tmp_path):
        path = _write(tmp_path, "## THE VERDICT: TOO UNCERTAIN\n")
        assert parse_verdict(path)['decision'] == 'TOO UNCERTAIN'

    def test_existing_decision_form_still_parses(self, tmp_path):
        """Regression guard on the established anchors."""
        path = _write(tmp_path, "**Decision: BUY**\n**Buy Zone: $40-50**\n")
        r = parse_verdict(path)
        assert r['decision'] == 'BUY'
        assert r['buy_zone'] == '$40–$50'


# --- verdict must be found regardless of how long the synthesis preamble is ---

def _long_report_with_late_verdict(tmp_path):
    """A report shaped like GTT.PA 2026-08-20.

    Three Munger drafts and two red-team passes push the actual decision past
    the old 15,000-char window, and the appended red-team sections quote the
    SUPERSEDED buy zones from earlier drafts.
    """
    filler = ("Cumulative withdrawal narrative. " * 40 + "\n\n") * 22   # ~16k chars
    body = f"""# 🦁 THE SILICON COUNCIL REPORT: ZZZ

## ⚖️ MUNGER'S VERDICT
# MUNGER SYNTHESIS — Test Co

## 0. WHAT I WITHDRAW (CUMULATIVE)
{filler}

## VI. FINAL DECISION
**Buy Zone: €78–€135.**

## EXECUTIVE SUMMARY (distilled from synthesis above)

**Decision:** WAIT
**Conviction:** Moderate

## 👨‍🏫 THE BUSINESS EXPLANATION
Some teaching prose.

## 🔍 REALITY CHECK
Reviewing: Munger Synthesis — PASS, Buy Zone €117–155, Position 0%
The ceiling should be **Buy Zone: €120–165**, not €155.
"""
    p = tmp_path / "ZZZ_Analysis_2026-08-20.md"
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_finds_the_decision_even_when_the_preamble_is_very_long(tmp_path):
    parsed = parse_verdict(_long_report_with_late_verdict(tmp_path))
    assert parsed.get("decision") == "WAIT"


def test_does_not_pick_up_a_superseded_buy_zone_quoted_by_the_red_team(tmp_path):
    parsed = parse_verdict(_long_report_with_late_verdict(tmp_path))
    zone = parsed.get("buy_zone") or ""
    assert "78" in zone, f"should read the current zone, got {zone!r}"
    assert "117" not in zone and "120" not in zone, \
        f"picked up a superseded zone from the red-team section: {zone!r}"


def test_a_synthesist_heading_does_not_truncate_the_verdict_section(tmp_path):
    """NXPI 2026-08-21: the memo contained its own heading

        ## §I. THE COUNCIL, AND WHY I DO NOT USE IT

    which matched a loose 'THE COUNCIL' end-marker and cut the verdict section
    at line 54 of 209, losing both the Decision and the Buy Zone.

    The assembler's own section headings are emoji-marked and fixed; anchor on
    those, not on words the synthesist is free to use in prose.
    """
    body = """# 🦁 THE SILICON COUNCIL REPORT: ZZZ

---
## ⚖️ MUNGER'S VERDICT
# MUNGER SYNTHESIS

## §I. THE COUNCIL, AND WHY I DO NOT USE IT
The unanimity is an artifact.

## §VI. FINAL DECISION
**Buy Zone: $110 – $160**

## EXECUTIVE SUMMARY (distilled from synthesis above)

**Decision:** WAIT
**Conviction:** Moderate

---
## 👨‍🏫 THE BUSINESS EXPLANATION
Teaching prose.

---
# 🏛️ THE FINAL REALITY CHECK
Reviewing: PASS, Buy Zone $99-$105
"""
    p = tmp_path / "ZZZ_Analysis_2026-08-21.md"
    p.write_text(body, encoding="utf-8")
    parsed = parse_verdict(str(p))
    assert parsed.get("decision") == "WAIT"
    assert "110" in (parsed.get("buy_zone") or "")
    assert "99" not in (parsed.get("buy_zone") or ""), "must not reach the red-team section"


def test_reads_a_buy_zone_written_with_spaces_around_the_dash(tmp_path):
    p = tmp_path / "YYY_Analysis_2026-08-21.md"
    p.write_text("## ⚖️ MUNGER'S VERDICT\n**Buy Zone: $110 – $160**\n**Decision:** WAIT\n",
                 encoding="utf-8")
    zone = parse_verdict(str(p)).get("buy_zone") or ""
    assert "110" in zone and "160" in zone
