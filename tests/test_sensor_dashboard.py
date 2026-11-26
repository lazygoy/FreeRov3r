import pytest

from freerov3r.sensor_dashboard import PANEL_COUNTS, panel_grid_dimensions


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, (1, 1)),
        (2, (2, 1)),
        (4, (2, 2)),
        (6, (2, 3)),
        (8, (2, 4)),
    ],
)
def test_panel_grid_dimensions(count, expected):
    assert panel_grid_dimensions(count) == expected


@pytest.mark.parametrize("count", [0, 3, 5, 7, 9, 10])
def test_panel_grid_dimensions_rejects_unsupported_counts(count):
    with pytest.raises(ValueError, match="panel count"):
        panel_grid_dimensions(count)


def test_dashboard_panel_counts_are_ordered_and_capped_at_eight():
    assert PANEL_COUNTS == (1, 2, 4, 6, 8)
