"""Initial manufacturer-specific capability package for Land Rover L319."""
from .registry import VehicleProfile


class L319Profile:
    def __new__(cls):
        return VehicleProfile(
            profile_id="land_rover_l319",
            display_name="Land Rover L319 (LR3 / LR4)",
            make="Land Rover",
            model="LR3 / LR4",
            year_start=2005,
            year_end=2016,
            description=(
                "Land Rover Discovery 3/LR3 and Discovery 4/LR4. "
                "Manufacturer-specific network and diagnostic features are enabled "
                "only when the VIN and configuration are confirmed."
            ),
            capabilities={
                "can_capture", "obd2", "pid_monitoring", "graphing", "logging",
                "l319_wiring_reference", "l319_module_inventory",
            },
        )
