from bili_intel import diagnostics


def make_settings(tmp_path, **overrides):
    values = {
        "db_path": tmp_path / "state.sqlite3",
        "artifacts_dir": tmp_path / "artifacts",
        "cookies_file": None,
        "llm_mode": "schema",
        "llm_budget_usd": None,
        "llm_input_usd_per_mtok": None,
        "llm_output_usd_per_mtok": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_diagnostics_are_local_and_never_print_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(diagnostics.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    monkeypatch.setenv("OPENAI_API_KEY", "do-not-print-this-secret")

    results = diagnostics.collect_diagnostics(make_settings(tmp_path))

    assert any(item["name"] == "SQLite FTS5 trigram" and item["status"] == "ok"
               for item in results)
    assert any(item["name"] == "LLM API key" and item["status"] == "ok"
               for item in results)
    assert "do-not-print-this-secret" not in repr(results)
    assert not any(item["status"] == "fail" for item in results)


def test_diagnostics_flags_budget_without_both_prices(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(diagnostics.shutil, "which", lambda name: "/usr/bin/ffmpeg")

    results = diagnostics.collect_diagnostics(make_settings(
        tmp_path, llm_budget_usd=1.0, llm_input_usd_per_mtok=0.5,
        llm_output_usd_per_mtok=None,
    ))

    assert any(item["name"] == "LLM budget configuration" and item["status"] == "fail"
               for item in results)
