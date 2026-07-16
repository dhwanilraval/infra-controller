from app.models.machine import MachineState

VALID_TRANSITIONS: dict[MachineState, list[MachineState]] = {
    MachineState.DISCOVERED: [MachineState.ENROLLING, MachineState.ERROR],
    MachineState.ENROLLING: [MachineState.ENROLLED, MachineState.ERROR],
    MachineState.ENROLLED: [
        MachineState.PROVISIONING,
        MachineState.DECOMMISSIONING,
        MachineState.ERROR,
    ],
    MachineState.PROVISIONING: [MachineState.READY, MachineState.ERROR],
    MachineState.READY: [
        MachineState.IN_USE,
        MachineState.MAINTENANCE,
        MachineState.PROVISIONING,
        MachineState.DECOMMISSIONING,
        MachineState.ERROR,
    ],
    MachineState.IN_USE: [
        MachineState.READY,
        MachineState.MAINTENANCE,
        MachineState.DECOMMISSIONING,
        MachineState.ERROR,
    ],
    MachineState.MAINTENANCE: [
        MachineState.READY,
        MachineState.PROVISIONING,
        MachineState.DECOMMISSIONING,
        MachineState.ERROR,
    ],
    MachineState.DECOMMISSIONING: [MachineState.DECOMMISSIONED, MachineState.ERROR],
    MachineState.DECOMMISSIONED: [MachineState.DISCOVERED],
    MachineState.ERROR: [
        MachineState.DISCOVERED,
        MachineState.ENROLLED,
        MachineState.MAINTENANCE,
        MachineState.DECOMMISSIONING,
    ],
}


class InvalidTransition(Exception):
    pass


def validate_transition(current: MachineState, target: MachineState) -> bool:
    allowed = VALID_TRANSITIONS.get(current, [])
    if target not in allowed:
        raise InvalidTransition(
            f"Cannot transition from {current.value} to {target.value}. "
            f"Allowed: {[s.value for s in allowed]}"
        )
    return True
