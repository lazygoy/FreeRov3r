"""Safe, optional DBC loading and passive CAN signal decoding.

DBC definitions describe frame/signal layouts only. They do not define diagnostic
requests, ECU addressing, or permission to transmit. Imported files are kept in a
local user library and are never silently treated as verified vehicle data.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import shutil


class DBCUnavailableError(RuntimeError):
    """Raised when the optional cantools dependency is not installed."""


@dataclass
class DBCDecodeResult:
    decoded: dict
    message_name: str
    frame_id: int


class DBCLibrary:
    """Local library of user-supplied DBC files with read-only decode support."""

    def __init__(self, library_dir=None):
        self.library_dir = Path(library_dir or (Path.home() / ".freerov3r" / "dbc"))
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.database = None
        self.path = None
        self.messages_by_key = {}
        self.signal_count = 0
        self.message_count = 0

    @staticmethod
    def _cantools():
        try:
            import cantools
        except ImportError as exc:
            raise DBCUnavailableError(
                "DBC decoding requires the optional dependency. Install with: "
                "python -m pip install -e \".[protocols]\""
            ) from exc
        return cantools

    def import_file(self, source_path):
        """Validate a DBC with cantools, then copy it into the local library."""
        source = Path(source_path)
        if not source.is_file() or source.suffix.lower() != ".dbc":
            raise ValueError("Select an existing .dbc file.")
        cantools = self._cantools()
        database = cantools.database.load_file(str(source), strict=True)
        if not database.messages:
            raise ValueError("The DBC contains no CAN messages.")

        digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
        safe_stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in source.stem)[:48]
        destination = self.library_dir / f"{safe_stem}_{digest}.dbc"
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        self.load_file(destination)
        return destination

    def load_file(self, path):
        """Load a previously imported DBC, rejecting malformed definitions."""
        source = Path(path)
        if not source.is_file() or source.suffix.lower() != ".dbc":
            raise ValueError("Select an existing .dbc file.")
        database = self._cantools().database.load_file(str(source), strict=True)
        if not database.messages:
            raise ValueError("The DBC contains no CAN messages.")
        index = {}
        for message in database.messages:
            key = (int(message.frame_id), bool(message.is_extended_frame))
            if key in index:
                raise ValueError(
                    f"DBC has duplicate message definition for 0x{message.frame_id:X}."
                )
            index[key] = message
        self.database = database
        self.path = source
        self.messages_by_key = index
        self.message_count = len(database.messages)
        self.signal_count = sum(len(message.signals) for message in database.messages)
        return self.summary()

    def summary(self):
        return {
            "path": str(self.path) if self.path else None,
            "name": self.path.name if self.path else None,
            "message_count": self.message_count,
            "signal_count": self.signal_count,
            "messages": [
                {
                    "frame_id": int(message.frame_id),
                    "extended": bool(message.is_extended_frame),
                    "name": message.name,
                    "length": int(message.length),
                    "signals": [signal.name for signal in message.signals],
                }
                for message in (self.database.messages if self.database else [])
            ],
        }

    def decode(self, frame_id, data, extended=False):
        """Decode one received frame. Returns None when this DBC has no matching ID."""
        if self.database is None:
            return None
        message = self.messages_by_key.get((int(frame_id), bool(extended)))
        if message is None:
            return None
        payload = bytes(data)
        if len(payload) != int(message.length):
            return None
        try:
            values = self.database.decode_message(
                message.frame_id, payload, decode_choices=False,
                allow_truncated=False, allow_excess=False,
            )
        except (ValueError, KeyError, OverflowError):
            return None
        return DBCDecodeResult(
            decoded=values, message_name=message.name, frame_id=int(message.frame_id)
        )

    def decode_coverage(self, records):
        """Summarize observed frame coverage against the currently loaded DBC."""
        if self.database is None:
            return {"matched_frames": 0, "unmatched_frames": len(records), "signals": {}}
        matched = 0
        unmatched = 0
        values = {}
        for record in records:
            result = self.decode(
                record.get("arbitration_id", -1),
                bytes.fromhex(record.get("data", "")),
                record.get("extended", False),
            )
            if result is None:
                unmatched += 1
                continue
            matched += 1
            for name, value in result.decoded.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    values.setdefault(name, []).append(float(value))
        stats = {
            name: {
                "count": len(samples),
                "min": min(samples),
                "max": max(samples),
                "mean": sum(samples) / len(samples),
                "first": samples[0],
                "last": samples[-1],
            }
            for name, samples in values.items() if samples
        }
        return {"matched_frames": matched, "unmatched_frames": unmatched, "signals": stats}
