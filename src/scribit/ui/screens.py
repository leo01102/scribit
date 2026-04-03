from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List
from textual.app import ComposeResult
from textual.widgets import Label, Input, Button, Switch, Select
from textual.containers import Horizontal, Grid, Vertical
from textual.screen import ModalScreen
from ..config import save_settings, SUPPORTED_LANGUAGES, load_settings
from ..audio import get_audio_devices

class SettingsScreen(ModalScreen):
    """Modal screen for configuring application settings."""
    def __init__(self, settings: Dict[str, Any]):
        super().__init__()
        self.settings = settings
        self.devices = get_audio_devices()

    def compose(self) -> ComposeResult:
        with Grid(id="settings-form"):
            yield Label("SETTINGS", id="settings-title")
            
            yield Label("AssemblyAI API Key")
            yield Input(value=self.settings.get("api_key", ""), placeholder="Paste API Key here", id="input-api-key", password=True)
            
            yield Label("Input Audio Device")
            yield Select(
                options=self.devices,
                value=self.settings.get("device_index", 2),
                id="select-device"
            )

            yield Label("Transcription Language")
            yield Select(
                options=SUPPORTED_LANGUAGES,
                value=self.settings.get("language_code", "en"),
                id="select-language"
            )
            
            yield Label("Save Transcript Logs")
            yield Switch(value=self.settings.get("save_logs", False), id="switch-save-logs")
            
            with Horizontal(id="settings-buttons"):
                yield Button("SAVE", variant="primary", id="btn-save")
                yield Button("CANCEL", variant="error", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save":
            new_settings = {
                "api_key": self.query_one("#input-api-key", Input).value.strip(),
                "device_index": self.query_one("#select-device", Select).value,
                "language_code": self.query_one("#select-language", Select).value,
                "save_logs": self.query_one("#switch-save-logs", Switch).value
            }
            save_settings(new_settings)
            self.dismiss(new_settings)
        else:
            self.dismiss(None)

class ExportScreen(ModalScreen):
    """Modal screen for exporting the transcription session."""
    def __init__(self, stats: Dict[str, Any]):
        super().__init__()
        self.stats = stats
        # Default path to Downloads
        default_path = str(Path.home() / "Downloads" / f"scribit_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md")
        self.default_path = default_path

    def compose(self) -> ComposeResult:
        with Vertical(id="export-form"):
            yield Label("EXPORT SESSION", id="export-title")
            yield Label("Export Path (Markdown)")
            yield Input(value=self.default_path, id="input-export-path")
            with Horizontal(id="export-buttons"):
                yield Button("EXPORT", variant="primary", id="btn-do-export")
                yield Button("CANCEL", variant="error", id="btn-export-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-do-export":
            path = self.query_one("#input-export-path", Input).value.strip()
            self.dismiss(path)
        else:
            self.dismiss(None)

    def on_key(self, event) -> None:
        if event.key == "d" or event.key == "escape":
            self.dismiss(None)
