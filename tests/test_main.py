import pytest
from unittest.mock import patch, MagicMock


class TestRunCouncil:
    @patch("main.save_to_markdown")
    @patch("main.run_reality_check")
    @patch("main.run_family_newsletter")
    @patch("main.run_munger")
    @patch("main.run_business_teacher")
    @patch("main.run_futurist")
    @patch("main.run_sherlock")
    @patch("main.ask_psychologist")
    @patch("main.ask_steve_jobs")
    @patch("main.ask_tim_cook")
    @patch("main.ask_michael_burry")
    @patch("main.ask_warren_buffett")
    @patch("main.ask_jeff_bezos")
    @patch("main.refine_dossier")
    @patch("main.run_forensic_interrogation")
    @patch("main.build_initial_dossier")
    @patch("main.normalize_ticker")
    def test_full_flow_verbose_save(
        self,
        mock_normalize,
        mock_build,
        mock_forensic,
        mock_refine,
        mock_bezos,
        mock_buffett,
        mock_burry,
        mock_cook,
        mock_jobs,
        mock_psych,
        mock_sherlock,
        mock_futurist,
        mock_teacher,
        mock_munger,
        mock_newsletter,
        mock_reality,
        mock_save,
    ):
        from main import run_council

        # Setup
        mock_normalize.return_value = "AAPL"
        mock_build.return_value = "base dossier"
        mock_forensic.return_value = "full dossier"
        mock_refine.return_value = "refined dossier"

        mock_bezos.return_value = "bezos report"
        mock_buffett.return_value = "buffett report"
        mock_burry.return_value = "burry report"
        mock_cook.return_value = "cook report"
        mock_jobs.return_value = "jobs report"
        mock_psych.return_value = "psych report"
        mock_sherlock.return_value = "sherlock report"
        mock_futurist.return_value = "futurist report"

        mock_teacher.return_value = "teacher explanation"
        mock_munger.return_value = "BUY verdict"
        mock_newsletter.return_value = "simple report"
        mock_reality.return_value = "reality check"
        mock_save.return_value = {"full": "/path/full.md", "simple": "/path/simple.md"}

        result = run_council("aapl", verbose=True, save_markdown=True)

        # Verify orchestration
        mock_normalize.assert_called_once_with("aapl")
        mock_build.assert_called_once_with("AAPL")
        mock_forensic.assert_called_once_with("AAPL", "base dossier")
        mock_refine.assert_called_once_with("full dossier")

        # All 8 experts called with refined dossier
        mock_bezos.assert_called_once_with("refined dossier")
        mock_buffett.assert_called_once_with("refined dossier")
        mock_burry.assert_called_once_with("refined dossier")
        mock_cook.assert_called_once_with("refined dossier")
        mock_jobs.assert_called_once_with("refined dossier")
        mock_psych.assert_called_once_with("refined dossier")
        mock_sherlock.assert_called_once_with("refined dossier")
        mock_futurist.assert_called_once_with("refined dossier")

        # Verbose mode triggers teacher
        mock_teacher.assert_called_once()

        # Munger gets full dossier + reports
        mock_munger.assert_called_once()
        munger_args = mock_munger.call_args
        assert munger_args[0][0] == "AAPL"

        # Newsletter and reality check
        mock_newsletter.assert_called_once()
        mock_reality.assert_called_once()

        # Save was called, result is the file paths
        mock_save.assert_called_once()
        assert result == {"full": "/path/full.md", "simple": "/path/simple.md"}

    @patch("main.save_to_markdown")
    @patch("main.run_reality_check")
    @patch("main.run_family_newsletter")
    @patch("main.run_munger")
    @patch("main.run_business_teacher")
    @patch("main.run_futurist")
    @patch("main.run_sherlock")
    @patch("main.ask_psychologist")
    @patch("main.ask_steve_jobs")
    @patch("main.ask_tim_cook")
    @patch("main.ask_michael_burry")
    @patch("main.ask_warren_buffett")
    @patch("main.ask_jeff_bezos")
    @patch("main.refine_dossier")
    @patch("main.run_forensic_interrogation")
    @patch("main.build_initial_dossier")
    @patch("main.normalize_ticker")
    def test_minimal_flow_no_verbose_no_save(
        self,
        mock_normalize,
        mock_build,
        mock_forensic,
        mock_refine,
        mock_bezos,
        mock_buffett,
        mock_burry,
        mock_cook,
        mock_jobs,
        mock_psych,
        mock_sherlock,
        mock_futurist,
        mock_teacher,
        mock_munger,
        mock_newsletter,
        mock_reality,
        mock_save,
    ):
        from main import run_council

        mock_normalize.return_value = "META"
        mock_build.return_value = "base"
        mock_forensic.return_value = "full"
        mock_refine.return_value = "refined"

        for m in [mock_bezos, mock_buffett, mock_burry, mock_cook,
                   mock_jobs, mock_psych, mock_sherlock, mock_futurist]:
            m.return_value = "report"

        mock_munger.return_value = "verdict"
        mock_newsletter.return_value = "simple"
        mock_reality.return_value = "reality"

        result = run_council("META", verbose=False, save_markdown=False)

        # Teacher should NOT be called in non-verbose mode
        mock_teacher.assert_not_called()

        # Save should NOT be called
        mock_save.assert_not_called()

        # Returns None when not saving
        assert result is None
