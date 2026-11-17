import pytest
from freerov3r.safety import SafetyPolicy

def test_tx_off_by_default():
    with pytest.raises(PermissionError):
        SafetyPolicy().authorize_transmit("request", confirmed=True)

def test_programming_requires_all_preconditions():
    p = SafetyPolicy(allow_programming=True)
    with pytest.raises(PermissionError):
        p.authorize_programming(True, True, False, True)
