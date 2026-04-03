import pytest
from scribit.app import ScribitApp

def test_app_metadata():
    """Test that the app has the correct metadata."""
    app = ScribitApp()
    assert app.TITLE == "SCRIBIT"
    assert "Real-time" in app.SUB_TITLE

def test_imports():
    """Ensure main components can be imported."""
    from scribit.config import load_settings
    from scribit.app import ScribitApp
    assert load_settings is not None
    assert ScribitApp is not None
