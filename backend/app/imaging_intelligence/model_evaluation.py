"""Research-only MONAI metric adapter; no inference, weights or clinical acceptance rule."""

from dataclasses import asdict, dataclass
import hashlib
import importlib.metadata
import re
from typing import Protocol

from .models import canonical_digest


@dataclass(frozen=True)
class SyntheticEvaluationCase:
    case_id: str
    model_id: str
    model_version: str
    model_artifact_sha256: str
    dataset_inventory_sha256: str
    prediction: tuple[int, ...]
    target: tuple[int, ...]
    synthetic_only: bool = True

    def __post_init__(self):
        if (self.synthetic_only is not True or type(self.case_id) is not str or not self.case_id.startswith("synthetic-")
                or type(self.model_id) is not str or not self.model_id.startswith("synthetic-")
                or type(self.model_version) is not str or not self.model_version
                or any(type(x) is not str or not re.fullmatch(r"[0-9a-f]{64}", x)
                       for x in (self.model_artifact_sha256,self.dataset_inventory_sha256))
                or type(self.prediction) is not tuple or type(self.target) is not tuple
                or not 1 <= len(self.prediction) == len(self.target) <= 4096
                or any(type(x) is not int or x not in {0,1} for x in self.prediction+self.target)):
            raise ValueError("Only bounded, version-attributed synthetic binary masks are accepted.")


class SegmentationEvaluationAdapter(Protocol):
    def evaluate(self, case: SyntheticEvaluationCase) -> dict:
        ...


class MonaiDiceEvaluationAdapter:
    def evaluate(self, case: SyntheticEvaluationCase) -> dict:
        if type(case) is not SyntheticEvaluationCase:
            raise ValueError("A typed synthetic evaluation case is required.")
        try:
            import torch
            from monai.metrics import DiceMetric
        except ImportError:
            raise RuntimeError("Optional MONAI evaluation dependencies are unavailable.") from None
        prediction = torch.tensor(case.prediction, dtype=torch.float32).reshape(1,1,1,-1)
        target = torch.tensor(case.target, dtype=torch.float32).reshape(1,1,1,-1)
        metric = DiceMetric(include_background=True, reduction="mean", ignore_empty=False)
        metric(y_pred=prediction,y=target)
        score = float(metric.aggregate().item())
        metric.reset()
        payload = {
            "schema_version":"synthetic-model-evaluation-v1", "adapter":"monai-dice-1.0.0",
            "case_id":case.case_id, "model_id":case.model_id, "model_version":case.model_version,
            "model_artifact_sha256":case.model_artifact_sha256,
            "dataset_inventory_sha256":case.dataset_inventory_sha256,
            "input_sha256":canonical_digest(asdict(case)), "dice":score,
            "monai_version":importlib.metadata.version("monai"),
            "torch_version":torch.__version__, "scope":"synthetic_metric_evaluation_only",
            "trained_model_loaded":False, "is_clinical_validation":False,
            "authorizes_treatment":False, "requires_independent_review":True,
        }
        return {**payload,"result_sha256":canonical_digest(payload)}


def synthetic_evaluation_case():
    return SyntheticEvaluationCase(
        "synthetic-mask-case-1", "synthetic-manual-mask-fixture", "1.0.0",
        hashlib.sha256(b"synthetic manual masks; no trained model").hexdigest(),
        hashlib.sha256(b"synthetic binary mask inventory v1").hexdigest(),
        (1,1,0,0), (1,0,1,0),
    )
