def redistribute_weights(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if not total:
        return dict.fromkeys(weights, 0.0)
    return {k: v / total for k, v in weights.items()}
