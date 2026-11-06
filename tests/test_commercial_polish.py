from pathlib import Path
import re
from wsdash.views import table

def test_icon_pyramid():
    root = Path(__file__).resolve().parents[1] / "assets"
    for name in ["favicon.svg", "icon.svg", "favicon.ico", "favicon-16x16.png", "favicon-32x32.png", "apple-touch-icon.png", "icon-192.png", "icon-512.png", "site.webmanifest"]:
        assert (root / name).is_file(), name

def test_no_emoji_in_cli_sources():
    root = Path(__file__).resolve().parents[1] / "wsdash"
    for source in root.rglob("*.py"):
        assert not re.search(r"[\U0001f300-\U0001faff\u2600-\u27bf]", source.read_text()), source

def test_color_output_uses_terminal_foreground_without_dim_or_neon():
    output = table.render({"workspaces": [], "color": True, "config": {}})
    assert "\x1b[2m" not in output
    assert "magenta" not in output

def test_narrow_table_keeps_status_and_signal_inside_columns(monkeypatch):
    monkeypatch.setenv('COLUMNS', '42')
    doc = {'name': 'customer-operations-console', 'score': 35.0, 'status': 'incomplete', 'kind': 'repo',
           'signals': [{'normalized': 1, 'weight': 1, 'detail': 'Three local changes ready for review', 'name': 'changes'}]}
    output = table.render({'workspaces': [doc], 'color': False, 'config': {}})
    assert 'INCOMPLETE' in output
    assert 'customer-operations-console' in output
    assert max(map(len, output.splitlines())) <= 42

def test_narrow_empty_state_keeps_next_steps_in_view(monkeypatch):
    monkeypatch.setenv('COLUMNS', '42')
    output = table.render({'workspaces': [], 'color': False, 'config': {}})
    assert 'wsdash scan' in output
    assert max(map(len, output.splitlines())) <= 42
