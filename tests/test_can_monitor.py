from freerov3r.can_monitor import CanMonitor
from freerov3r.models import CanFrame


def frame(can_id, extended=False):
    return CanFrame(arbitration_id=can_id, data=b"\x01\x02", is_extended_id=extended)


def test_monitor_keeps_bounded_recent_buffer_and_counts_drops():
    monitor = CanMonitor(capacity=2)
    monitor.add(frame(0x100), now=1.0)
    monitor.add(frame(0x101), now=1.2)
    monitor.add(frame(0x102), now=1.4)
    assert len(monitor.frames) == 2
    assert monitor.total_received == 3
    assert monitor.dropped_from_buffer == 1
    assert monitor.frames[0].arbitration_id == 0x101


def test_rates_are_counted_per_id_in_rolling_window():
    monitor = CanMonitor(rate_window=2)
    monitor.add(frame(0x100), now=10.0)
    monitor.add(frame(0x100), now=10.5)
    monitor.add(frame(0x101), now=10.5)
    stats = {item.arbitration_id: item for item in monitor.id_stats(now=10.5)}
    assert stats[0x100].frames_per_second == 1.0
    assert stats[0x101].frames_per_second == 0.5
    assert monitor.rate(now=10.5) == 1.5


def test_filter_supports_exact_id_ranges_and_frame_format():
    standard = frame(0x7E8)
    extended = frame(0x18DAF110, extended=True)
    assert CanMonitor.matches(standard, "7E8")
    assert CanMonitor.matches(standard, "700-7FF", "Standard")
    assert not CanMonitor.matches(standard, "700-7FF", "Extended")
    assert CanMonitor.matches(extended, "18DAF000-18DAFFFF", "Extended")
    assert not CanMonitor.matches(extended, "not-an-id")


def test_same_numeric_id_is_tracked_separately_by_frame_format():
    monitor = CanMonitor(rate_window=2)
    monitor.add(frame(0x123, extended=False), now=4.0)
    monitor.add(frame(0x123, extended=True), now=4.5)
    stats = monitor.id_stats(now=4.5)
    assert len(stats) == 2
    assert {(item.arbitration_id, item.extended) for item in stats} == {
        (0x123, False), (0x123, True)
    }



def test_id_stats_report_payload_changes_and_recent_median_interval():
    monitor = CanMonitor(rate_window=2)
    first = CanFrame(arbitration_id=0x321, data=b"\\x01", timestamp=1.0)
    changed = CanFrame(arbitration_id=0x321, data=b"\\x02", timestamp=1.1)
    monitor.add(first, now=1.0)
    monitor.add(changed, now=1.1)
    monitor.add(changed, now=1.3)

    stats = monitor.id_stats(now=1.3)[0]
    assert stats.payload_changes == 1
    assert stats.median_interval_ms == 150.0


def test_payload_change_tracking_is_separate_for_standard_and_extended_ids():
    monitor = CanMonitor(rate_window=2)
    monitor.add(frame(0x123), now=1.0)
    monitor.add(CanFrame(arbitration_id=0x123, data=b"\\x02", is_extended_id=True), now=1.1)
    monitor.add(frame(0x123), now=1.2)

    stats = {(item.arbitration_id, item.extended): item for item in monitor.id_stats(now=1.2)}
    assert stats[(0x123, False)].payload_changes == 0
    assert stats[(0x123, True)].payload_changes == 0


def test_reset_clears_payload_and_interval_history():
    monitor = CanMonitor()
    monitor.add(frame(0x100), now=1.0)
    monitor.add(CanFrame(arbitration_id=0x100, data=b"\\x03"), now=1.1)
    monitor.reset()

    assert monitor.id_stats(now=1.1) == []
    assert monitor.payload_changes == {}
    assert monitor.intervals == {}
