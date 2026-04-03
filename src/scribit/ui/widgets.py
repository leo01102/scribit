from textual.app import ComposeResult
from textual.widgets import RichLog, Static, Label
from textual.containers import Vertical, Horizontal, Container

class Header(Container):
    """Header containing centered logo and flanking metrics."""
    def compose(self) -> ComposeResult:
        with Horizontal(id="header-container"):
            # Left Column: Session Metrics
            with Vertical(id="header-left"):
                with Label("SESSION METRICS", classes="header-title"):
                    pass
                with Horizontal(classes="header-row"):
                    yield Label("DUR: ")
                    yield Label("0s", id="stat-duration", classes="stat-value")
                with Horizontal(classes="header-row"):
                    yield Label("TRN: ")
                    yield Label("0", id="stat-turns", classes="stat-value")
                with Horizontal(classes="header-row"):
                    yield Label("WRD: ")
                    yield Label("0", id="stat-words", classes="stat-value")
                with Horizontal(classes="header-row"):
                    yield Label("ACC: ")
                    yield Label("100%", id="stat-accuracy", classes="stat-value")

            # Center Column: ASCII Logo
            with Vertical(id="header-center"):
                yield Static(
                    "[#8b5cf6] ███████╗  ██████╗ ██████╗  ██╗ ██████╗  ██╗ ████████╗ [/]\n"
                    "[#9665f7] ██╔════╝ ██╔════╝ ██╔══██╗ ██║ ██╔══██╗ ██║ ╚══██╔══╝ [/]\n"
                    "[#a26ef9] ███████╗ ██║      ██████╔╝ ██║ ██████╔╝ ██║    ██║    [/]\n"
                    "[#ac76fa] ╚════██║ ██║      ██╔══██╗ ██║ ██╔══██╗ ██║    ██║    [/]\n"
                    "[#b77ffc] ███████║ ╚██████╗ ██║  ██║ ██║ ██████╔╝ ██║    ██║    [/]\n"
                    "[#c084fc] ╚══════╝  ╚═════╝ ╚═╝  ╚═╝ ╚═╝ ╚═════╝  ╚═╝    ╚═╝    [/]",
                    id="logo-text"
                )

            # Right Column: System Status / Perf
            with Vertical(id="header-right"):
                with Label("SYSTEM STATUS", classes="header-title"):
                    pass
                with Horizontal(classes="header-row"):
                    yield Label("STAT: ")
                    yield Label("IDLE", id="status-label", classes="stat-value status-waiting")
                with Horizontal(classes="header-row"):
                    yield Label("LAT:  ")
                    yield Label("0ms", id="stat-latency", classes="stat-value")
                with Horizontal(classes="header-row"):
                    yield Label("VOL:  ")
                    yield Label("[..........]", id="vu-meter", classes="stat-value")
                with Horizontal(classes="header-row"):
                    yield Label("DEV:  ")
                    yield Label("Detecting...", id="device-info", classes="stat-value")

class TranscriptionLog(Vertical):
    """Main area for transcription output log."""
    def compose(self) -> ComposeResult:
        final_log = RichLog(id="final-log", wrap=True, highlight=True, markup=True)
        final_log.border_title = "TRANSCRIPTION"
        yield final_log

class PendingBuffer(Vertical):
    """Bottom area for intermediate transcription results."""
    def compose(self) -> ComposeResult:
        partial_buffer = Static("READY - PRESS SPACE TO START", id="partial-buffer")
        partial_buffer.border_title = "PENDING BUFFER"
        yield partial_buffer
