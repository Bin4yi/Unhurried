from server import llm


def test_spark_cost_uses_cached_tokens():
    usage = {"prompt_tokens": 1000, "completion_tokens": 100,
             "prompt_tokens_details": {"cached_tokens": 400}}
    expected = (600 * 1.25 + 400 * 0.15 + 100 * 4.25) / 1_000_000
    assert abs(llm.spark_cost(usage) - expected) < 1e-12
    assert llm.spark_cost(None) == 0.0


def test_transcribe_cost_whole_seconds():
    assert llm.transcribe_cost(3600.9) == 0.18
    assert llm.transcribe_cost(0.9) == 0.0


def test_realtime_url():
    assert llm.realtime_url("https://api.meta.ai/v1") == "wss://api.meta.ai/v1/asr/realtime"


def test_handshake_has_keywords_and_bearer():
    s = llm.TranscribeStream(keywords=["Binula", ""], rate=16000)
    hs = s.handshake("k")
    assert hs["authorization"]["accessToken"] == "Bearer k"
    assert hs["audioEncoding"] == "PCM_16KHZ"
    assert hs["keywords"] == ["Binula"]
    assert hs["mode"] == "ENDPOINTING"


def test_log_call_writes_row(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "CALL_LOG", tmp_path / "calls.jsonl")
    llm.log_call("chat", "m", 12.34, 0.001, purpose="test")
    assert '"purpose": "test"' in (tmp_path / "calls.jsonl").read_text()
