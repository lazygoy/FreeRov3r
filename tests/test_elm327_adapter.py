from freerov3r.hardware.elm327_serial_adapter import parse_elm_vin_response


def test_parse_elm_vin_single_frame_payload():
    response = "7E8 10 14 49 02 01 53 41 4C 41 47 32 56 36 32 47 41 37 38 30 31 30 35"
    assert parse_elm_vin_response(response) == "SALAG2V62GA780105"


def test_parse_elm_vin_consecutive_iso_tp_frames():
    response = "\n".join([
        "7E8 10 14 49 02 01 53 41 4C 41 47 32 56",
        "7E8 21 36 32 47 41 37 38 30",
        "7E8 22 31 30 35 00 00 00 00",
    ])
    assert parse_elm_vin_response(response) == "SALAG2V62GA780105"
