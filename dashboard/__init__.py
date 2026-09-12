"""Headless runner and web dashboard for the Silicon Council.

`python -m dashboard` starts an HTTP server on 127.0.0.1, a runner thread that
executes one analysis at a time as a headless `claude` process, and a follow-up
thread that resumes a finished analysis to answer questions about it.
"""
