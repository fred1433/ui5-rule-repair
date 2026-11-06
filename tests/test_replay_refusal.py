"""Replay must refuse a recorded repair whose failure report no longer matches."""
import json
import shutil

from ui5rules import __main__ as cli
from ui5rules import agent, bench


def test_replay_refuses_a_repair_answering_another_report(tmp_path, monkeypatch):
    links = agent.chain()
    if len(links) < 2:
        return
    for f in links[:2]:
        shutil.copytree(f, tmp_path / f.name)
    meta_path = tmp_path / links[1].name / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["input_sha256"] = "0" * 64
    meta_path.write_text(json.dumps(meta))
    monkeypatch.setattr(agent, "PROPOSALS", tmp_path)
    obs = json.loads((links[0] / "observations.json").read_text())
    monkeypatch.setattr(cli, "_observe", lambda *a, **k: obs)
    monkeypatch.setattr(bench, "run_all", lambda *a, **k: [])

    class FakeLocal:
        def __enter__(self): return self
        def __exit__(self, *a): pass

    class FakePW:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        class chromium:
            @staticmethod
            def launch():
                class B:
                    def close(self): pass
                return B()

    monkeypatch.setattr(cli, "LocalCopy", lambda *a, **k: FakeLocal())
    monkeypatch.setattr(cli, "sync_playwright", lambda: FakePW())
    assert cli.replay(write=False) == 1
