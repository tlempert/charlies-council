"""`python -m dashboard` — the whole service: web server, runner, follow-ups.

Run by launchd with KeepAlive, so the only startup duty that matters is
admitting that anything left `running` did not survive the restart.
"""
import json
import signal
import sys
import threading

from . import app, followup, runner, store as store_mod


def main():
    home = store_mod.home()
    try:
        config = app.load_config()
    except (OSError, json.JSONDecodeError):
        print(f"No config at {app.config_path()} — run dashboard/install.sh first.", file=sys.stderr)
        return 1

    store = store_mod.Store(home / "council.db")
    analysis_runner = runner.Runner(store, config, home=home)
    questions = followup.FollowupWorker(store, config, home=home)
    recovered = analysis_runner.recover()
    if recovered:
        print(f"marked {recovered} interrupted job(s) failed", flush=True)

    analysis_runner.start()
    questions.start()
    server = app.create_server(store, config)
    host, port = server.server_address[:2]
    print(f"council dashboard on http://{host}:{port}", flush=True)

    def shutdown(*_):
        analysis_runner.stop()
        questions.stop()
        # shutdown() waits for serve_forever, which is this very thread.
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
