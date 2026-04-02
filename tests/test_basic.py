import pytest
from scribit.main import ScribitApp

def test_app_metadata():
    """Test that the app has the correct metadata."""
    app = ScribitApp()
    assert app.TITLE == "SCRIBIT"
    assert "Real-time" in app.SUB_TITLE

def test_imports():
    """Ensure main components can be imported."""
    from scribit.main import load_settings, ScribitApp
    assert load_settings is not None
    assert ScribitApp is not None
