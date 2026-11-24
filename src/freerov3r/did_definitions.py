"""Traceable, conservative UDS DID definition and decoding support.

Definitions are data, not protocol discoveries. Every definition carries source
provenance and an explicit confidence label. Unknown DIDs remain undecoded.
"""
import json
import math
from pathlib import Path


CONFIDENCE_LEVELS = {"confirmed", "probable", "unverified"}
FIELD_ENCODINGS = {"unsigned", "signed", "hex", "ascii"}
BYTE_ORDERS = {"big", "little"}


def _parse_did(value):
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned.startswith("0x"):
            cleaned = cleaned[2:]
        if not cleaned or len(cleaned) > 4:
            raise ValueError("DID must be a 16-bit hexadecimal value")
        try:
            value = int(cleaned, 16)
        except ValueError as exc:
            raise ValueError("DID must be a 16-bit hexadecimal value") from exc
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFFFF:
        raise ValueError("DID must be a 16-bit hexadecimal value")
    return value


def _normalize_field(field):
    if not isinstance(field, dict):
        raise ValueError("Each DID field must be an object")
    name = str(field.get("name") or "").strip()
    if not name:
        raise ValueError("DID fields require a name")
    try:
        offset = int(field["offset"])
        length = int(field["length"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Field {name!r} requires integer offset and length") from exc
    if offset < 0 or length < 1:
        raise ValueError(f"Field {name!r} has an invalid byte range")

    encoding = str(field.get("encoding", "unsigned")).lower()
    byte_order = str(field.get("byte_order", "big")).lower()
    if encoding not in FIELD_ENCODINGS:
        raise ValueError(f"Field {name!r} has unsupported encoding {encoding!r}")
    if byte_order not in BYTE_ORDERS:
        raise ValueError(f"Field {name!r} has unsupported byte order {byte_order!r}")
    if encoding == "ascii" and byte_order != "big":
        raise ValueError(f"Field {name!r}: byte order does not apply to ASCII")
    try:
        scale = float(field.get("scale", 1))
        bias = float(field.get("bias", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Field {name!r} has invalid scale or bias") from exc
    if not math.isfinite(scale) or not math.isfinite(bias):
        raise ValueError(f"Field {name!r} scale and bias must be finite")

    return {
        "name": name,
        "offset": offset,
        "length": length,
        "encoding": encoding,
        "byte_order": byte_order,
        "scale": scale,
        "bias": bias,
        "unit": str(field.get("unit") or ""),
        "description": str(field.get("description") or ""),
    }


def normalize_did_definition(definition):
    """Validate and normalize one source-backed DID definition."""
    if not isinstance(definition, dict):
        raise ValueError("DID definition must be an object")
    did = _parse_did(definition.get("did"))
    vehicle = str(definition.get("vehicle") or "").strip()
    name = str(definition.get("name") or "").strip()
    if not vehicle or not name:
        raise ValueError("DID definitions require vehicle and name")

    source = definition.get("source")
    if not isinstance(source, dict):
        raise ValueError("DID definitions require source provenance")
    source_title = str(source.get("title") or "").strip()
    source_reference = str(source.get("reference") or "").strip()
    if not source_title or not source_reference:
        raise ValueError("Source provenance requires title and reference")

    confidence = str(definition.get("confidence", "unverified")).lower()
    if confidence not in CONFIDENCE_LEVELS:
        raise ValueError(f"Unsupported confidence level {confidence!r}")

    fields = [_normalize_field(item) for item in definition.get("fields", [])]
    for field in fields:
        if field["offset"] + field["length"] > 65535:
            raise ValueError(f"Field {field['name']!r} byte range is unreasonable")

    return {
        "did": did,
        "vehicle": vehicle,
        "module": str(definition.get("module") or "").strip(),
        "name": name,
        "description": str(definition.get("description") or "").strip(),
        "confidence": confidence,
        "source": {
            "title": source_title,
            "reference": source_reference,
            "url": str(source.get("url") or "").strip(),
        },
        "fields": fields,
    }


class DIDDefinitionRegistry:
    """In-memory registry for explicitly supplied, provenance-backed definitions."""

    def __init__(self, definitions=None):
        self._definitions = {}
        for definition in definitions or []:
            self.add(definition)

    @classmethod
    def from_json(cls, path):
        with Path(path).open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        if isinstance(document, dict):
            definitions = document.get("definitions")
        else:
            definitions = document
        if not isinstance(definitions, list):
            raise ValueError("DID definition file must contain a definitions list")
        return cls(definitions)

    def add(self, definition):
        normalized = normalize_did_definition(definition)
        key = (normalized["vehicle"].casefold(), normalized["did"])
        self._definitions[key] = normalized
        return normalized

    def get(self, did, *, vehicle):
        key = (str(vehicle or "").strip().casefold(), _parse_did(did))
        return self._definitions.get(key)

    def decode_response(self, did, response, *, vehicle):
        """Decode only a matching positive 0x62 response for a known DID."""
        identifier = _parse_did(did)
        try:
            payload = bytes.fromhex(response) if isinstance(response, str) else bytes(response)
        except (TypeError, ValueError):
            return {"status": "invalid_response", "did": identifier, "fields": []}
        if len(payload) < 3 or payload[0] != 0x62:
            return {"status": "not_positive_did_response", "did": identifier, "fields": []}
        if int.from_bytes(payload[1:3], "big") != identifier:
            return {"status": "response_did_mismatch", "did": identifier, "fields": []}

        definition = self.get(identifier, vehicle=vehicle)
        if definition is None:
            return {
                "status": "unknown_definition", "did": identifier,
                "data": payload[3:].hex(), "fields": [],
            }

        data = payload[3:]
        decoded = []
        for field in definition["fields"]:
            start = field["offset"]
            end = start + field["length"]
            raw = data[start:end]
            item = {
                "name": field["name"],
                "offset": start,
                "length": field["length"],
                "raw_hex": raw.hex(),
                "unit": field["unit"],
                "description": field["description"],
            }
            if len(raw) != field["length"]:
                item.update({"status": "truncated", "value": None})
            else:
                encoding = field["encoding"]
                if encoding == "hex":
                    value = raw.hex()
                elif encoding == "ascii":
                    value = raw.decode("ascii", errors="replace").rstrip("\x00 ")
                else:
                    signed = encoding == "signed"
                    number = int.from_bytes(raw, field["byte_order"], signed=signed)
                    scaled = number * field["scale"] + field["bias"]
                    value = int(scaled) if scaled.is_integer() else scaled
                item.update({"status": "decoded", "value": value})
            decoded.append(item)

        return {
            "status": "decoded",
            "did": identifier,
            "definition": {
                "name": definition["name"],
                "module": definition["module"],
                "confidence": definition["confidence"],
                "source": dict(definition["source"]),
            },
            "data": data.hex(),
            "fields": decoded,
        }


def decode_uds_did_transactions(transactions, registry, *, vehicle):
    """Decode only paired, positive, single-DID 0x22 transactions.

    Multi-DID reads and unmatched/negative transactions remain outside this
    decoder until their record boundaries or response semantics are known.
    """
    results = []
    for pair in transactions or []:
        if pair.get("confidence") != "probable" or pair.get("response_kind") != "positive":
            continue
        if pair.get("request_service") != 0x22:
            continue
        request = pair.get("request") or {}
        response = pair.get("response") or {}
        try:
            request_payload = bytes.fromhex(request.get("payload", ""))
            response_payload = bytes.fromhex(response.get("payload", ""))
        except (TypeError, ValueError):
            continue
        if len(request_payload) != 3 or request_payload[0] != 0x22:
            continue
        did = int.from_bytes(request_payload[1:3], "big")
        decoded = registry.decode_response(
            did, response_payload, vehicle=vehicle
        )
        results.append({
            "did": did,
            "request_id": request.get("arbitration_id"),
            "response_id": response.get("arbitration_id"),
            "request_payload": request_payload.hex(),
            "response_payload": response_payload.hex(),
            "decoded": decoded,
        })
    return results



def validate_registry_file(path):
    """Load and validate a registry file, returning a concise audit summary."""
    registry = DIDDefinitionRegistry.from_json(path)
    definitions = sorted(
        registry._definitions.values(),
        key=lambda item: (item["vehicle"].casefold(), item["did"]),
    )
    return {
        "definition_count": len(definitions),
        "vehicles": sorted({item["vehicle"] for item in definitions}),
        "confidence_counts": {
            level: sum(item["confidence"] == level for item in definitions)
            for level in sorted(CONFIDENCE_LEVELS)
        },
        "definitions": definitions,
    }


def main(argv=None):
    """Validate a DID definition JSON file without accessing vehicle hardware."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Validate a FreeRov3r source-backed UDS DID definition registry."
    )
    parser.add_argument("registry", help="Path to DID definition JSON")
    args = parser.parse_args(argv)
    try:
        summary = validate_registry_file(args.registry)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    print(f"VALID: {summary['definition_count']} DID definition(s)")
    for vehicle in summary["vehicles"]:
        print(f"Vehicle: {vehicle}")
    print("Confidence: " + ", ".join(
        f"{level}={count}"
        for level, count in summary["confidence_counts"].items()
    ))
    for item in summary["definitions"]:
        print(
            f"  {item['vehicle']} DID 0x{item['did']:04X}: "
            f"{item['name']} [{item['confidence']}] "
            f"source={item['source']['reference']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
