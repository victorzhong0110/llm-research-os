"""Static HTML/Markdown Run reports rebuilt from EventStore."""

from llm_research_os.report.errors import ReportError
from llm_research_os.report.fold import RunReport, build_run_report
from llm_research_os.report.render import render_html, render_markdown

__all__ = [
    "ReportError",
    "RunReport",
    "build_run_report",
    "render_html",
    "render_markdown",
]
