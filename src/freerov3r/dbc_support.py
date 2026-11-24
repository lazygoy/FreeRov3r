"""Safe, optional DBC loading and passive CAN signal decoding.

DBC definitions describe frame/signal layouts only. They do not define diagnostic
requests, ECU addressing, or permission to transmit. Imported files are kept in a
local user library and are never silently treated as verified vehicle data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
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
        self.metadata_dir = self.library_dir / "metadata"
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.active_state_path = self.library_dir / "active.json"
        self.database = None
        self.path = None
        self.messages_by_key = {}
        self.signal_count = 0
        self.message_count = 0
        self.metadata = {}
        try:
            state = json.loads(self.active_state_path.read_text(encoding="utf-8"))
            active_path = Path(state.get("path", ""))
            if active_path.is_file():
                self.load_file(active_path)
        except (OSError, ValueError, TypeError, DBCUnavailableError):
            # Missing optional dependency or stale last-used path must not block startup.
            pass

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

        if source.resolve().parent == self.library_dir.resolve():
            self.load_file(source)
            return source
        source_bytes = source.read_bytes()
        digest_full = hashlib.sha256(source_bytes).hexdigest()
        digest = digest_full[:12]
        safe_stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in source.stem)[:48]
        destination = self.library_dir / f"{safe_stem}_{digest}.dbc"
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        metadata = {
            "file": destination.name,
            "sha256": digest_full,
            "source_file": source.name,
            "source_origin": "Not recorded",
            "vehicle_applicability": "Unverified",
            "verification_status": "unverified",
            "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        metadata_path = self.metadata_dir / f"{destination.name}.json"
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
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
        metadata_path = self.metadata_dir / f"{source.name}.json"
        try:
            self.metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.metadata = {
                "file": source.name,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "source_file": source.name,
                "source_origin": "Not recorded",
                "vehicle_applicability": "Unverified",
                "verification_status": "unverified",
                "imported_at": None,
            }
        self.active_state_path.write_text(
            json.dumps({"path": str(source.resolve())}, indent=2), encoding="utf-8"
        )
        return self.summary()

    def summary(self):
        return {
            "path": str(self.path) if self.path else None,
            "name": self.path.name if self.path else None,
            "message_count": self.message_count,
            "signal_count": self.signal_count,
            "metadata": dict(self.metadata),
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


    @classmethod
    def compare_files(cls, left_path, right_path):
        """Compare two DBC definitions structurally without assuming either is correct."""
        left_path = Path(left_path)
        right_path = Path(right_path)
        for path in (left_path, right_path):
            if not path.is_file() or path.suffix.lower() != ".dbc":
                raise ValueError(f"Select an existing .dbc file: {path}")
        cantools = cls._cantools()
        left_db = cantools.database.load_file(str(left_path), strict=True)
        right_db = cantools.database.load_file(str(right_path), strict=True)

        def index_messages(database):
            indexed = {}
            for message in database.messages:
                key = (int(message.frame_id), bool(message.is_extended_frame))
                if key in indexed:
                    raise ValueError(f"Duplicate message definition for 0x{message.frame_id:X}")
                indexed[key] = message
            return indexed

        def signal_signature(signal):
            return {
                "start": int(signal.start),
                "length": int(signal.length),
                "byte_order": str(signal.byte_order),
                "is_signed": bool(signal.is_signed),
                "scale": float(signal.scale),
                "offset": float(signal.offset),
                "unit": str(signal.unit or ""),
            }

        left_messages = index_messages(left_db)
        right_messages = index_messages(right_db)
        left_keys = set(left_messages)
        right_keys = set(right_messages)
        shared = sorted(left_keys & right_keys)
        report = {
            "left": left_path.name,
            "right": right_path.name,
            "left_message_count": len(left_messages),
            "right_message_count": len(right_messages),
            "shared_message_count": len(shared),
            "left_only": [
                {"frame_id": key[0], "extended": key[1], "name": left_messages[key].name}
                for key in sorted(left_keys - right_keys)
            ],
            "right_only": [
                {"frame_id": key[0], "extended": key[1], "name": right_messages[key].name}
                for key in sorted(right_keys - left_keys)
            ],
            "message_differences": [],
        }
        for key in shared:
            left_message = left_messages[key]
            right_message = right_messages[key]
            difference = {
                "frame_id": key[0],
                "extended": key[1],
                "left_name": left_message.name,
                "right_name": right_message.name,
                "left_length": int(left_message.length),
                "right_length": int(right_message.length),
                "signal_differences": [],
            }
            if left_message.length != right_message.length:
                difference["signal_differences"].append({
                    "kind": "message_length",
                    "left": int(left_message.length),
                    "right": int(right_message.length),
                })
            left_signals = {signal.name: signal for signal in left_message.signals}
            right_signals = {signal.name: signal for signal in right_message.signals}
            for name in sorted(set(left_signals) | set(right_signals)):
                if name not in left_signals:
                    difference["signal_differences"].append({
                        "kind": "signal_added", "signal": name,
                    })
                elif name not in right_signals:
                    difference["signal_differences"].append({
                        "kind": "signal_removed", "signal": name,
                    })
                else:
                    left_sig = signal_signature(left_signals[name])
                    right_sig = signal_signature(right_signals[name])
                    changed = {
                        field: {"left": left_sig[field], "right": right_sig[field]}
                        for field in left_sig if left_sig[field] != right_sig[field]
                    }
                    if changed:
                        difference["signal_differences"].append({
                            "kind": "signal_changed", "signal": name, "fields": changed,
                        })
            if left_message.name != right_message.name:
                difference["signal_differences"].insert(0, {
                    "kind": "message_name_changed",
                    "left": left_message.name,
                    "right": right_message.name,
                })
            if difference["signal_differences"]:
                report["message_differences"].append(difference)
        report["identical_shared_definitions"] = (
            report["shared_message_count"] == len(left_messages) == len(right_messages)
            and not report["message_differences"]
        )
        return report

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
            values = message.decode(
                payload, decode_choices=False, allow_truncated=False
            )
        except Exception:
            # Malformed or incompatible payloads are not decoded as valid signals.
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
            try:
                payload = bytes.fromhex(record.get("data", ""))
                result = self.decode(
                    record.get("arbitration_id", -1),
                    payload,
                    record.get("extended", False),
                )
            except (TypeError, ValueError):
                result = None
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
