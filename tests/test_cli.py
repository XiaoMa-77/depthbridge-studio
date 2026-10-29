import sys

import pytest

from depthbridge.__main__ import main


def test_cli_devices(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["depthbridge", "--devices"])
    monkeypatch.setattr("depthbridge.cameras.list_devices", lambda: {"sdk_installed": True, "devices": []})
    main()
    assert '"sdk_installed": true' in capsys.readouterr().out


def test_cli_loopback_server_entry(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["depthbridge", "--no-browser", "--port", "8899"])
    calls = []
    monkeypatch.setattr("depthbridge.__main__.uvicorn.run", lambda app, **kwargs: calls.append(kwargs))
    main()
    assert calls == [{"host": "127.0.0.1", "port": 8899, "log_level": "info"}]


def test_invalid_port(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["depthbridge", "--port", "99999"])
    with pytest.raises(SystemExit):
        main()
