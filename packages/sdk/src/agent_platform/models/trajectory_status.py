from enum import Enum


class TrajectoryStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    IDLE = "idle"
    INTERRUPTED = "interrupted"
    PAUSED = "paused"
    PENDING = "pending"
    RUNNING = "running"
    TIMED_OUT = "timed_out"

    def __str__(self) -> str:
        return str(self.value)
