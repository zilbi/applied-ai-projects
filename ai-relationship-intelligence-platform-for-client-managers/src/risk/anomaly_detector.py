from statistics import mean


def dropped_by(current: float, history: list[float], ratio: float) -> bool:
    if not history:
        return False
    baseline = mean(history)
    return baseline > 0 and current < baseline * (1 - ratio)
