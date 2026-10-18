def metrics(predictions, actual):
    actual = set(actual)
    positions = [index+1 for index, identity in enumerate(predictions) if identity in actual]
    return {"top1": float(any(p <= 1 for p in positions)), "top3": float(any(p <= 3 for p in positions)), "top5": float(any(p <= 5 for p in positions)), "mrr": 1/min(positions) if positions else 0.0, "recall5": len(set(predictions[:5]) & actual)/len(actual) if actual else 0.0}


def aggregate(rows):
    if not rows:
        raise ValueError("Cannot report metrics without measured cases")
    return {key: sum(row[key] for row in rows)/len(rows) for key in rows[0]}
