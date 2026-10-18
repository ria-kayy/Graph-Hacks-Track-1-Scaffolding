from evaluation.metrics import metrics


def test_metrics_rank_and_partial_recall():
    assert metrics(["wrong", "b", "a"], ["a", "b", "c"]) == {"top1": 0.0, "top3": 1.0, "top5": 1.0, "mrr": 0.5, "recall5": 2/3}


def test_metrics_empty_predictions():
    assert metrics([], ["actual"])["mrr"] == 0
