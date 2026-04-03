import pyaudio
import math
import struct
from typing import List, Optional

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
        
        try:
            return name.encode('cp1252').decode('utf-8')
        except (UnicodeEncodeError, UnicodeDecodeError):
            return name

    try:
        count = audio.get_device_count()
        for i in range(count):
            info = audio.get_device_info_by_index(i)
            if info.get('maxInputChannels', 0) > 0:
                name = clean_name(info.get('name', 'Unknown Device'))
                devices.append((name, i))
    except Exception:
        pass
    finally:
        audio.terminate()
    return devices

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

def calculate_volume(chunk: bytes) -> int:
    """Calculate volume for VU Meter (native replacement for audioop.rms)."""
    count = len(chunk) // 2
    if count > 0:
        shorts = struct.unpack(f"<{count}h", chunk)
        sum_squares = sum(s**2 for s in shorts)
        rms = math.sqrt(sum_squares / count)
        return min(100, int((rms / 4000) * 100))
    return 0
