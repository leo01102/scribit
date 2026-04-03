import time
import struct
from datetime import datetime
from typing import Dict, Any
import pyperclip
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
from textual import on, work
from textual.reactive import reactive
from textual.app import App, ComposeResult
from textual.widgets import RichLog, Static, Label, Footer
from textual.containers import Vertical, Horizontal
from textual.binding import Binding
from rich.text import Text

from .config import load_settings, LOG_DIR
from .audio import SystemAudioStream, get_audio_devices, calculate_volume
from .ui.widgets import Header, TranscriptionLog, PendingBuffer
from .ui.screens import SettingsScreen, ExportScreen

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
        Binding("k", "copy_last_line", "Copy Last", show=True),
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
        layout: vertical;
    }

    Header {
        height: 10;
        background: $surface;
        border-bottom: round $panel;
        padding: 1 2;
        width: 100%;
    }

    #header-container {
        height: 100%;
    }

    #header-left, #header-right {
        width: 30;
        padding: 0 1;
        align: center middle;
    }

    #header-center {
        width: 1fr;
        align: center middle;
    }

    .header-title {
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
        width: 100%;
        text-align: center;
        border-bottom: solid $panel;
    }

    .header-row {
        height: 1;
        color: $subtext;
    }

    #logo-text {
        color: $accent;
        text-style: bold;
        background: transparent;
        text-align: center;
        width: 62;
        height: 7;
        margin: 0;
        padding-top: 1;
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
        height: 1fr;
        padding: 1 2;
    }

    TranscriptionLog {
        height: 1fr;
        width: 100%;
    }

    #final-log {
        height: 1fr;
        background: transparent;
        border: round $panel;
        padding: 0 1;
        scrollbar-background: $background;
        scrollbar-color: $accent;
        border-title-align: left;
        border-title-color: $subtext;
        border-title-style: bold;
    }

    PendingBuffer {
        height: 6;
        width: 100%;
        margin-top: 1;
    }

    #partial-buffer {
        height: 100%;
        background: $surface;
        border: round $accent;
        padding: 1 2;
        color: $secondary;
        text-style: italic;
        border-title-align: left;
        border-title-color: $subtext;
        border-title-style: bold;
    }

    .stat-value {
        color: $text;
        text-style: bold;
    }

    .status-active {
        color: $green !important;
        text-style: bold;
    }

    .status-error {
        color: $red !important;
        text-style: bold;
    }

    .status-waiting {
        color: $yellow !important;
        text-style: bold;
    }

    .log-on {
        color: $green;
        text-style: bold;
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

    #input-api-key {
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
        yield Header()
        with Vertical(id="main-container"):
            yield TranscriptionLog()
            yield PendingBuffer()
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
        self.accuracy_widget = self.query_one("#stat-accuracy", Label)
        self.latency_widget = self.query_one("#stat-latency", Label)
        self.vu_widget = self.query_one("#vu-meter", Label)
        self.device_widget = self.query_one("#device-info", Label)
        # These are gone from the header but kept for internal logic 
        # Actually I removed some, let's check which ones are missing
        # Missing: chars_widget, lang_widget, logging_widget
        self.update_config_info()
        self.update_status("IDLE", "waiting")
        self.set_interval(1.0, self.update_stats)

    def update_config_info(self):
        # Update Audio Device Info
        from .audio import get_audio_devices
        idx = self.settings.get("device_index", 2)
        devices = get_audio_devices()
        name = "Unknown"
        for d_name, d_idx in devices:
            if d_idx == idx:
                name = d_name
                break
        
        display_name = name[:10] + "..." if len(name) > 10 else name
        self.device_widget.update(f"[{idx}] {display_name}")

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
        self.latency_widget.update(f"{self.latency}ms")
        
        # Update VU Meter
        bar_len = 10
        filled = min(bar_len, int(self.volume / 10))
        meter = "[" + "|" * filled + "." * (bar_len - filled) + "]"
        self.vu_widget.update(meter)
        if filled > 7:
            self.vu_widget.styles.color = "#ef4444" # $red
        elif filled > 0:
            self.vu_widget.styles.color = "#8b5cf6" # $accent
        else:
            self.vu_widget.styles.color = "#9ca3af" # $subtext

        # Accuracy %
        accuracy = (self.total_confidence / self.word_count * 100) if self.word_count > 0 else 100.0
        self.accuracy_widget.update(f"{accuracy:.1f}%")

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

    def action_copy_last_line(self):
        """Copies the last transcription turn to the system clipboard."""
        if self.session_log:
            last_line = self.session_log[-1].strip()
            # Remove timestamp if present [HH:MM:SS]
            if last_line.startswith("[") and "]" in last_line:
                last_line = last_line.split("]", 1)[1].strip()
            
            try:
                pyperclip.copy(last_line)
                self.log_widget.write(Text("✓ Last line copied to clipboard", style="dim green"))
            except Exception as e:
                self.log_widget.write(Text(f"✗ Clipboard error: {str(e)}", style="dim red"))
        else:
            self.log_widget.write(Text("nothing to copy", style="dim yellow"))

    def action_open_settings(self):
        if self.is_recording:
            self.action_toggle_recording()
        
        def handle_settings(new_settings):
            if new_settings:
                self.settings = new_settings
                self.update_config_info()
                self.log_widget.write(Text("Settings updated", style="dim green"))
        
        self.push_screen(SettingsScreen(self.settings), handle_settings)

    def action_export_session(self):
        avg_latency = (self.latency_sum / self.latency_count) if self.latency_count > 0 else 0
        elapsed = int(time.time() - self.start_time)
        hrs, rem = divmod(elapsed, 3600)
        mins, secs = divmod(rem, 60)
        duration_str = f"{hrs}h {mins}m {secs}s" if hrs > 0 else f"{mins}m {secs}s"
        accuracy = f"{(self.total_confidence / self.word_count * 100):.1f}%" if self.word_count > 0 else "0.0%"

        stats = {
            "duration": duration_str,
            "turns": self.turn_count,
            "words": self.word_count,
            "chars": self.char_count,
            "accuracy": accuracy,
            "avg_latency": f"{avg_latency:.1f}ms",
            "device": self.settings.get("device_index", "Default"),
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
        report.append(f"- **Language**: {self.settings.get('language_code', 'en').upper()}")
        
        report.append("\n## Transcription Log")
        report.append("---")
        
        if self.session_log:
            report.append("\n".join(self.session_log))
        else:
            report.append("*No transcription for this session.*")
            
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(report))

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
        lang_code = self.settings.get("language_code", "en")
        
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
            supported_pro = ["en", "es", "fr", "de", "it", "pt"]
            model = "u3-rt-pro" if lang_code.lower() in supported_pro else "universal-streaming-multilingual"
            
            client.connect(
                StreamingParameters(
                    speech_model=model,
                    sample_rate=16000,
                    language_code=lang_code
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
                    
                    self.volume = calculate_volume(chunk)
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

        self.latency = int((time.time() - self.last_chunk_time) * 1000)
        self.latency_sum += self.latency
        self.latency_count += 1

        if event.end_of_turn:
            prompt = f"[{datetime.now().strftime('%H:%M:%S')}] {event.transcript}"
            self.log_widget.write(prompt)
            self.session_log.append(prompt)
            self.log_to_file(event.transcript)
            self.partial_widget.update("")
            
            self.turn_count += 1
            words = event.transcript.split()
            self.word_count += len(words)
            self.char_count += len(event.transcript)
            self.total_confidence += sum(w.confidence for w in event.words) if event.words else 1.0 * len(words)
        else:
            self.partial_widget.update(event.transcript)

    def on_terminated(self, client, event: TerminationEvent):
        pass

    def on_error(self, client, event: StreamingError):
        self.log_widget.write(Text(f"Streaming Error: {event.error}", style="bold red"))
