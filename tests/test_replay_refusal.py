"""Replay accepts a recorded repair whose failure report matches, and refuses it otherwise.

The browser is replaced by the results recorded in results/results.json, so both tests see the
same runs; the only difference between them is the hash stored in the repair's meta.json.
"""
import json
import shutil
from pathlib import Path

import pytest

from ui5rules import __main__ as cli
from ui5rules import agent, bench

ROOT = Path(__file__).resolve().parent.parent


class _Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class _PW(_Ctx):
    class chromium:
        @staticmethod
        def launch():
            class B:
                def close(self):
                    pass
            return B()


@pytest.fixture
def recorded(tmp_path, monkeypatch):
    links = agent.chain()
    assert len(links) >= 2, "a generation and a repair must be recorded"
    for f in links[:2]:
        shutil.copytree(f, tmp_path / f.name)
    stages = json.loads((ROOT / "results/results.json").read_text())["stages"]
    queue = [st["results"] for st in stages[:2]]
    obs = json.loads((links[0] / "observations.json").read_text())
    monkeypatch.setattr(agent, "PROPOSALS", tmp_path)
    monkeypatch.setattr(cli, "_observe", lambda *a, **k: obs)
    monkeypatch.setattr(bench, "run_all", lambda *a, **k: queue.pop(0))
    monkeypatch.setattr(cli, "LocalCopy", lambda *a, **k: _Ctx())
    monkeypatch.setattr(cli, "sync_playwright", lambda: _PW())
    return tmp_path / links[1].name / "meta.json"


def test_replay_accepts_the_repair_when_the_failure_report_matches(recorded):
    assert cli.replay(write=False) == 0


def test_replay_refuses_the_repair_when_its_hash_answers_another_report(recorded):
    meta = json.loads(recorded.read_text())
    meta["input_sha256"] = "0" * 64
    recorded.write_text(json.dumps(meta))
    assert cli.replay(write=False) == 1
