import logging
import os
import time
import json
import math
import struct
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
import platformdirs
from dotenv import load_dotenv, set_key
import pyaudio
from textual import on, work
from textual.reactive import reactive
from textual.app import App, ComposeResult
from textual.widgets import RichLog, Header, Footer, Static, Label, Input, Button, Switch, Checkbox, Select
from textual.containers import Container, Vertical, Horizontal, Grid
from textual.binding import Binding
from textual.screen import ModalScreen
from rich.text import Text
from rich.panel import Panel

import assemblyai as aai
from assemblyai.streaming.v3 import (
    BeginEvent,
    StreamingClient,
    StreamingClientOptions,
    StreamingError,
    StreamingEvents,
    TerminationEvent,
    TurnEvent,
    StreamingParameters,
)

# Constants & Paths
APP_NAME = "scribit"
CONFIG_DIR = Path(platformdirs.user_config_dir(APP_NAME))
LOG_DIR = Path(platformdirs.user_log_dir(APP_NAME))
SETTINGS_FILE = CONFIG_DIR / "settings.json"

# Ensure directories exist
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

def get_audio_devices() -> List[tuple]:
    """Get a list of available input devices for the Select widget."""
    audio = pyaudio.PyAudio()
    devices = []
    
    def clean_name(name: str | bytes) -> str:
        """Clean encoding issues common with PyAudio on Windows."""
        if isinstance(name, bytes):
            try:
                return name.decode('utf-8')
            except UnicodeDecodeError:
                return name.decode('cp1252', errors='replace')
        
        # If already a string but has UTF-8 corruption (e.g. Ã³ for ó)
        try:
            return name.encode('cp1252').decode('utf-8')
        except (UnicodeEncodeError, UnicodeDecodeError):
            return name

    try:
        count = audio.get_device_count()
        for i in range(count):
            info = audio.get_device_info_by_index(i)
            if info.get('maxInputChannels') > 0:
                name = clean_name(info.get('name', 'Unknown Device'))
                devices.append((name, i))
    except Exception:
        pass
    finally:
        audio.terminate()
    return devices

def load_settings() -> Dict[str, Any]:
    """Load settings from JSON file with defaults."""
    defaults = {
        "api_key": os.getenv("ASSEMBLYAI_API_KEY", ""),
        "device_index": 2,
        "save_logs": False
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                settings = json.load(f)
                return {**defaults, **settings}
        except Exception:
            pass
    return defaults

def save_settings(settings: Dict[str, Any]):
    """Save settings to JSON file."""
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=4)
    # Also update .env for compatibility
    if settings.get("api_key"):
        set_key(".env", "ASSEMBLYAI_API_KEY", settings["api_key"])

class SystemAudioStream:
    def __init__(self, device_index, sample_rate=16000, chunk_size=1024):
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.audio = pyaudio.PyAudio()
        self.stream = None

    def __enter__(self):
        self.stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.sample_rate,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=self.chunk_size
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except:
                pass
        self.audio.terminate()

    def __iter__(self):
        return self

    def __next__(self):
        if self.stream:
            try:
                data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                return data
            except Exception:
                raise StopIteration
        else:
            raise StopIteration

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
            yield Input(value=self.settings.get("api_key", ""), placeholder="Paste API Key here", id="input-api-key")
            
            yield Label("Input Audio Device")
            yield Select(
                options=self.devices,
                value=self.settings.get("device_index", 2),
                id="select-device"
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

class Sidebar(Vertical):
    """Sidebar containing session info and status."""
    def compose(self) -> ComposeResult:
        with Vertical(id="sidebar-content"):
            yield Label("SCRIBIT", id="logo-text")
            
            status_label = Static("IDLE", id="status-label", classes="status-waiting")
            status_label.border_title = "SYSTEM STATUS"
            yield status_label
            
            with Vertical(id="stats-container") as stats:
                stats.border_title = "SESSION METRICS"
                with Horizontal(classes="stat-row"):
                    yield Label("Duration: ")
                    yield Label("0s", id="stat-duration", classes="stat-value")
                with Horizontal(classes="stat-row"):
                    yield Label("Turns: ")
                    yield Label("0", id="stat-turns", classes="stat-value")
                with Horizontal(classes="stat-row"):
                    yield Label("Total Words: ")
                    yield Label("0", id="stat-words", classes="stat-value")
                with Horizontal(classes="stat-row"):
                    yield Label("Total Chars: ")
                    yield Label("0", id="stat-chars", classes="stat-value")
                with Horizontal(classes="stat-row"):
                    yield Label("Accuracy: ")
                    yield Label("100%", id="stat-accuracy", classes="stat-value")
            
            with Vertical(id="config-container") as config:
                config.border_title = "SYSTEM CONFIG"
                with Horizontal(classes="stat-row"):
                    yield Label("Audio: ")
                    yield Label("Detecting...", id="device-info", classes="stat-value")
                with Horizontal(classes="stat-row"):
                    yield Label("Logging: ")
                    yield Label("ON", id="logging-status", classes="stat-value log-on")

            with Vertical(id="perf-container") as perf:
                perf.border_title = "PERFORMANCE"
                with Horizontal(classes="stat-row"):
                    yield Label("Latency: ")
                    yield Label("0ms", id="stat-latency", classes="stat-value")
                with Horizontal(classes="stat-row"):
                    yield Label("Audio Level: ")
                    yield Label("[..........]", id="vu-meter", classes="stat-value")


class TranscriptionFlow(Vertical):
    """Main area for transcription output."""
    def compose(self) -> ComposeResult:
        final_log = RichLog(id="final-log", wrap=True, highlight=True, markup=True)
        final_log.border_title = "TRANSCRIPTION"
        yield final_log
        
        partial_buffer = Static("READY - PRESS SPACE TO START", id="partial-buffer")
        partial_buffer.border_title = "PENDING BUFFER"
        yield partial_buffer

class ScribitApp(App):
    TITLE = "SCRIBIT"
    SUB_TITLE = "Real-time Transcription TUI"
    
    volume = reactive(0)
    latency = reactive(0)
    last_chunk_time = 0

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("c", "clear_log", "Clear", show=True),
        Binding("space", "toggle_recording", "Record", show=True),
        Binding("s", "open_settings", "Settings", show=True),
        Binding("d", "export_session", "Download", show=True),
    ]

    CSS = """
    $background: #000000;
    $surface: #0a0a0a;
    $panel: #111111;
    $accent: #8b5cf6;
    $secondary: #c084fc;
    $text: #f3f4f6;
    $subtext: #9ca3af;
    $green: #10b981;
    $red: #ef4444;
    $yellow: #f59e0b;

    Screen {
        background: $background;
        color: $text;
    }

    Header {
        display: none;
    }

    #logo-text {
        color: $accent;
        text-style: bold;
        background: transparent;
        width: 100%;
        text-align: center;
        padding: 1 2;
        margin-bottom: 2;
        border: round $accent;
    }

    Footer {
        background: $panel;
        color: $text;
        dock: bottom;
        height: 1;
    }

    Footer > .footer--key {
        background: $accent;
        color: $background;
        text-style: bold;
    }

    #main-container {
        layout: horizontal;
        height: 1fr;
    }

    Sidebar {
        width: 35;
        background: $surface;
        border-right: round $panel;
        padding: 1 2;
    }

    .sidebar-title, .area-title {
        display: none;
    }

    #status-label, #stats-container, #config-container, #perf-container, #final-log, #partial-buffer {
        border-title-align: left;
        border-title-color: $subtext;
        border-title-style: bold;
    }

    #status-label {
        background: transparent;
        color: $text;
        padding: 0 1;
        margin-top: 1;
        margin-bottom: 1;
        text-align: center;
        border: round $accent;
        height: 3;
        content-align: center middle;
    }

    .status-active {
        border: round $green !important;
        color: $green !important;
        text-style: bold;
    }

    .status-error {
        border: round $red !important;
        color: $red !important;
        text-style: bold;
    }

    .status-waiting {
        border: round $yellow !important;
        color: $yellow !important;
        text-style: bold;
    }

    #stats-container {
        background: transparent;
        padding: 1 2;
        margin-top: 1;
        margin-bottom: 1;
        border: round $panel;
    }

    .stat-row {
        height: auto;
        color: $subtext;
    }

    .stat-value {
        color: $text;
        text-style: bold;
    }

    #perf-container {
        background: transparent;
        color: $subtext;
        padding: 1 1;
        margin-top: 1;
        border: round $panel;
    }

    #config-container {
        background: transparent;
        color: $subtext;
        padding: 1 2;
        margin-top: 1;
        border: round $panel;
    }

    #device-info, #logging-status {
        background: transparent;
        text-align: left;
    }

    TranscriptionFlow {
        width: 1fr;
        padding: 1 2;
    }

    .area-title {
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }

    #final-log {
        height: 1fr;
        background: transparent;
        border: round $panel;
        margin-bottom: 1;
        padding: 0 1;
        scrollbar-background: $background;
        scrollbar-color: $accent;
    }

    .logging-active, .log-on {
        color: $green;
        text-style: bold;
    }

    .sidebar-value-dim {
        color: $subtext;
        margin-left: 2;
    }

    #partial-buffer {
        height: 5;
        background: transparent;
        border: round $accent;
        padding: 1 2;
        color: $secondary;
        text-style: italic;
        margin-top: 1;
    }

    /* Modal Styling */
    SettingsScreen {
        background: rgba(0, 0, 0, 0.8);
        align: center middle;
    }

    #settings-form {
        grid-size: 2;
        grid-gutter: 1 2;
        grid-columns: 1fr 2fr;
        padding: 2 4;
        width: 70;
        height: auto;
        background: $surface;
        border: round $accent;
    }

    #settings-title {
        column-span: 2;
        text-align: center;
        text-style: bold;
        color: $accent;
        margin-bottom: 2;
    }

    #input-api-key, #input-device-index {
        background: transparent;
        border: round $panel;
    }

    #settings-buttons {
        column-span: 2;
        margin-top: 2;
        align-horizontal: right;
    }

    /* Export Modal Styling */
    ExportScreen {
        background: rgba(0, 0, 0, 0.8);
        align: center middle;
    }

    #export-form {
        padding: 2 4;
        width: 60;
        height: auto;
        background: $surface;
        border: round $accent;
    }

    #export-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    #export-buttons {
        margin-top: 2;
        align-horizontal: center;
        height: 3;
    }

    #export-buttons Button {
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="main-container"):
            yield Sidebar()
            yield TranscriptionFlow()
        yield Footer()

    def on_mount(self):
        self.settings = load_settings()
        self.start_time = time.time()
        self.turn_count = 0
        self.word_count = 0
        self.char_count = 0
        self.total_confidence = 0.0
        self.is_recording = False
        self.current_worker = None
        self.latency_sum = 0
        self.latency_count = 0
        self.session_log = []
        
        self.log_widget = self.query_one("#final-log", RichLog)
        self.partial_widget = self.query_one("#partial-buffer", Static)
        self.status_widget = self.query_one("#status-label", Static)
        self.duration_widget = self.query_one("#stat-duration", Label)
        self.turns_widget = self.query_one("#stat-turns", Label)
        self.words_widget = self.query_one("#stat-words", Label)
        self.chars_widget = self.query_one("#stat-chars", Label)
        self.accuracy_widget = self.query_one("#stat-accuracy", Label)
        self.latency_widget = self.query_one("#stat-latency", Label)
        self.vu_widget = self.query_one("#vu-meter", Label)
        self.device_widget = self.query_one("#device-info", Label)
        self.logging_widget = self.query_one("#logging-status", Label)

        self.update_device_info()
        self.update_status("IDLE", "waiting")
        self.set_interval(1.0, self.update_stats)

    def update_device_info(self):
        audio = pyaudio.PyAudio()
        idx = self.settings.get("device_index", 2)
        try:
            info = audio.get_device_info_by_index(idx)
            # Use only first 15 chars of name for the sidebar
            name = info['name'][:15] + "..." if len(info['name']) > 15 else info['name']
            self.device_widget.update(f"[{idx}] {name}")
        except Exception:
            self.device_widget.update(f"Error {idx}")
        audio.terminate()

    def update_status(self, message: str, level: str = "active"):
        self.status_widget.update(message.upper())
        self.status_widget.remove_class("status-active", "status-error", "status-waiting")
        self.status_widget.add_class(f"status-{level}")

    def update_stats(self):
        elapsed_seconds = int(time.time() - self.start_time)
        if self.is_recording:
            self.duration_widget.update(f"{elapsed_seconds}s")
        
        self.turns_widget.update(str(self.turn_count))
        self.words_widget.update(str(self.word_count))
        self.chars_widget.update(str(self.char_count))
        self.latency_widget.update(f"{self.latency}ms")
        
        # Update VU Meter
        bar_len = 10
        filled = min(bar_len, int(self.volume / 10))
        meter = "[" + "|" * filled + "." * (bar_len - filled) + "]"
        self.vu_widget.update(meter)
        if filled > 7:
            self.vu_widget.styles.color = "#ef4444" # $red (high volume)
        elif filled > 0:
            self.vu_widget.styles.color = "#8b5cf6" # $accent
        else:
            self.vu_widget.styles.color = "#9ca3af" # $subtext

        # Accuracy %
        accuracy = (self.total_confidence / self.word_count * 100) if self.word_count > 0 else 100.0
        self.accuracy_widget.update(f"{accuracy:.1f}%")
        
        if self.settings.get("save_logs"):
            self.logging_widget.update("ON")
            self.logging_widget.add_class("log-on")
        else:
            self.logging_widget.update("OFF")
            self.logging_widget.remove_class("log-on")

    def action_clear_log(self):
        self.log_widget.clear()

    def action_open_settings(self):
        if self.is_recording:
            self.toggle_recording()
        
        def handle_settings(new_settings):
            if new_settings:
                self.settings = new_settings
                self.update_device_info()
                self.log_widget.write(Text("Settings updated", style="dim green"))
        
        self.push_screen(SettingsScreen(self.settings), handle_settings)

    def action_export_session(self):
        avg_latency = (self.latency_sum / self.latency_count) if self.latency_count > 0 else 0
        
        # Calculate duration
        elapsed = int(time.time() - self.start_time)
        hrs, rem = divmod(elapsed, 3600)
        mins, secs = divmod(rem, 60)
        duration_str = f"{hrs}h {mins}m {secs}s" if hrs > 0 else f"{mins}m {secs}s"

        # Calculate accuracy
        accuracy = f"{(self.total_confidence / self.word_count * 100):.1f}%" if self.word_count > 0 else "0.0%"

        stats = {
            "duration": duration_str,
            "turns": self.turn_count,
            "words": self.word_count,
            "chars": self.char_count,
            "accuracy": accuracy,
            "avg_latency": f"{avg_latency:.1f}ms",
            "device": self.settings.get("audio_device_index", "Default"),
        }

        def handle_export(path):
            if path:
                try:
                    self.save_export(path, stats)
                    self.log_widget.write(Text(f"Session exported to {path}", style="bold green"))
                except Exception as e:
                    self.log_widget.write(Text(f"Export failed: {str(e)}", style="bold red"))

        self.push_screen(ExportScreen(stats), handle_export)

    def save_export(self, path: str, stats: Dict[str, Any]):
        # Gather all logs from the widget
        # Textual's RichLog doesn't have a direct 'get_content' that returns markup-free text easily
        # but we can reconstruct it from our own session data if we had it, 
        # or we can read the current log file if logging is on.
        # For simplicity and robustness, we'll generate a beautiful report.
        
        report = []
        report.append(f"# Scribit Session Report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("\n## Session Metrics")
        report.append(f"- **Duration**: {stats['duration']}")
        report.append(f"- **Turns**: {stats['turns']}")
        report.append(f"- **Total Words**: {stats['words']}")
        report.append(f"- **Total Characters**: {stats['chars']}")
        report.append(f"- **Average Accurary**: {stats['accuracy']}")
        report.append(f"- **Average Latency**: {stats['avg_latency']}")
        report.append(f"- **Audio Device**: {stats['device']}")
        
        report.append("\n## Transcription Log")
        report.append("---")
        
        # Export memory-buffered session log
        if self.session_log:
            report.append("\n".join(self.session_log))
        else:
            report.append("*No transcription for this session.*")
            
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(report))

    def action_clear_log(self):
        """Clears both the UI and the current session memory."""
        self.log_widget.clear()
        self.session_log = []
        self.turn_count = 0
        self.word_count = 0
        self.char_count = 0
        self.total_confidence = 0.0
        self.latency_sum = 0
        self.latency_count = 0
        self.start_time = time.time()
        self.update_stats()
        self.log_widget.write(Text("Session cleared.", style="dim italic"))

    def action_toggle_recording(self):
        self.is_recording = not self.is_recording
        if self.is_recording:
            self.start_time = time.time()
            self.update_status("CONNECTING", "waiting")
            self.current_worker = self.run_worker(self.main_worker, thread=True)
            self.partial_widget.update("Listening...")
        else:
            self.update_status("STOPPING", "waiting")
            self.partial_widget.update("Paused")
            # The worker will terminate itself when is_recording is False

    def log_to_file(self, transcript: str):
        if not self.settings.get("save_logs"):
            return
        
        filename = LOG_DIR / datetime.now().strftime("session_%Y-%m-%d.txt")
        timestamp = datetime.now().strftime("[%H:%M:%S]")
        with open(filename, "a", encoding="utf-8") as f:
            f.write(f"{timestamp} {transcript}\n")

    def main_worker(self):
        api_key = self.settings.get("api_key")
        if not api_key:
            self.app.call_from_thread(self.update_status, "NO API KEY", "error")
            self.log_widget.write(Text("Error: AssemblyAI API key missing in settings", style="bold red"))
            self.is_recording = False
            return

        device_index = self.settings.get("device_index", 2)
        if device_index is None: # Standardize if select was blank
            device_index = 2
        
        client = StreamingClient(
            StreamingClientOptions(
                api_key=api_key,
                api_host="streaming.assemblyai.com",
            )
        )

        client.on(StreamingEvents.Begin, self.on_begin)
        client.on(StreamingEvents.Turn, self.on_turn)
        client.on(StreamingEvents.Termination, self.on_terminated)
        client.on(StreamingEvents.Error, self.on_error)

        try:
            client.connect(
                StreamingParameters(
                    speech_model="u3-rt-pro",
                    sample_rate=16000,
                )
            )
        except Exception as e:
            self.app.call_from_thread(self.update_status, "CONN FAILED", "error")
            self.log_widget.write(Text(f"Connection failed: {str(e)}", style="bold red"))
            self.is_recording = False
            return

        try:
            self.app.call_from_thread(self.update_status, "RECORDING", "active")
            with SystemAudioStream(device_index=device_index) as audio_stream:
                for chunk in audio_stream:
                    if not self.is_recording:
                        break
                    
                    # Calculate volume for VU Meter (native replacement for audioop.rms)
                    count = len(chunk) // 2
                    if count > 0:
                        shorts = struct.unpack(f"<{count}h", chunk)
                        sum_squares = sum(s**2 for s in shorts)
                        rms = math.sqrt(sum_squares / count)
                        self.volume = min(100, int((rms / 4000) * 100))
                    else:
                        self.volume = 0
                    
                    self.last_chunk_time = time.time()
                    client.stream(chunk)
        except Exception as e:
            self.app.call_from_thread(self.update_status, "STREAM ERROR", "error")
            self.log_widget.write(Text(f"Audio error: {str(e)}", style="bold red"))
        finally:
            self.is_recording = False
            try:
                client.disconnect(terminate=True)
            except:
                pass
            self.app.call_from_thread(self.update_status, "IDLE", "waiting")

    def on_begin(self, client, event: BeginEvent):
        pass

    def on_turn(self, client, event: TurnEvent):
        if not event.transcript:
            return

        # Calculate Latency for final transcripts
        if event.end_of_turn and self.last_chunk_time > 0:
            calc_latency = int((time.time() - self.last_chunk_time) * 1000)
            cur_latency = min(999, calc_latency)
            self.latency = cur_latency
            self.latency_sum += cur_latency
            self.latency_count += 1

        if event.end_of_turn:
            self.turn_count += 1
            words_list = event.transcript.split()
            self.word_count += len(words_list)
            self.char_count += len(event.transcript)
            
            # Update confidence (Accuracy)
            if hasattr(event, "words") and event.words:
                self.total_confidence += sum(w.confidence for w in event.words)
            else:
                # Fallback to high confidence if word-level data is missing
                self.total_confidence += len(words_list) * 0.95
            
            timestamp = time.strftime("%H:%M:%S")
            # Custom styling for the transcript lines
            line_str = f"[{timestamp}] {event.transcript}"
            self.session_log.append(line_str)
            
            line = Text.assemble(
                (f"[{timestamp}] ", "dim"),
                ("❯❯ ", "bold #8b5cf6"),
                (f"{event.transcript}", "#f3f4f6")
            )
            self.app.call_from_thread(self.log_widget.write, line)
            self.app.call_from_thread(self.partial_widget.update, "")
            self.log_to_file(event.transcript)
        else:
            self.app.call_from_thread(self.partial_widget.update, event.transcript)

    def on_terminated(self, client, event: TerminationEvent):
        pass

    def on_error(self, client, event: StreamingError):
        error_msg = str(event)
        self.log_widget.write(Text(f"API Error: {error_msg}", style="bold red"))
        self.app.call_from_thread(self.update_status, "ERROR", "error")


def main():
    app = ScribitApp()
    app.run()


if __name__ == "__main__":
    main()
