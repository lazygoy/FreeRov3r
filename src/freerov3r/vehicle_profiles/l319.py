"""Initial manufacturer-specific capability packages for Land Rover L319."""

from .registry import VehicleProfile


class L319FamilyProfile:
    """Shared default workspace for unidentified LR3/LR4 vehicles."""

    def __new__(cls):
        return VehicleProfile(
            profile_id="land_rover_l319",
            display_name="Land Rover L319 (LR3 / LR4)",
            make="Land Rover",
            model="LR3 / LR4",
            year_start=2005,
            year_end=2016,
            description=(
                "Shared L319 workspace. Variant-specific factory references remain "
                "clearly identified and must be checked against the actual vehicle."
            ),
            capabilities={
                "can_capture", "obd2", "pid_monitoring", "graphing", "logging",
                "l319_module_inventory",
            },
        )


class L319LR3Profile:
    def __new__(cls):
        return VehicleProfile(
            profile_id="land_rover_l319_lr3",
            display_name="Land Rover LR3 / Discovery 3 (L319)",
            make="Land Rover",
            model="LR3 / Discovery 3",
            year_start=2005,
            year_end=2009,
            description=(
                "LR3 vehicle profile. Generic OBD-II/CAN features are available; "
                "LR3-specific factory network and module definitions are not yet implemented."
            ),
            capabilities={"can_capture", "obd2", "pid_monitoring", "graphing", "logging"},
        )


class L319Profile:
    """The currently developed LR4 / Discovery 4 profile."""

    def __new__(cls):
        return VehicleProfile(
            profile_id="land_rover_l319_lr4",
            display_name="Land Rover LR4 / Discovery 4 (L319)",
            make="Land Rover",
            model="LR4 / Discovery 4",
            year_start=2010,
            year_end=2016,
            description=(
                "LR4 vehicle profile. The current factory network reference is a "
                "2010 LHD PV8 5.0L baseline; VIN-specific equipment and calibration "
                "must still be verified."
            ),
            capabilities={
                "can_capture", "obd2", "pid_monitoring", "graphing", "logging",
                "l319_wiring_reference", "l319_module_inventory",
            },
        )
