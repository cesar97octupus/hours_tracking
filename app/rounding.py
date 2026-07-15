def round_up_to_quarter_hour(elapsed_seconds: float) -> float:
    """Round up to the next quarter hour. Exact multiples of 15 minutes are
    left as-is (900s stays 0.25h, does not bump to 0.50h). 0 or negative
    durations return 0.0."""
    if elapsed_seconds <= 0:
        return 0.0
    quarters = -(-int(round(elapsed_seconds)) // 900)  # ceiling division on whole seconds
    return quarters * 0.25
