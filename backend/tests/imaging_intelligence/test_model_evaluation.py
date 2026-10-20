from dataclasses import replace
import importlib.util
import unittest

from backend.app.imaging_intelligence.model_evaluation import (
    MonaiDiceEvaluationAdapter, synthetic_evaluation_case,
)


class ResearchEvaluationTests(unittest.TestCase):
    def test_real_data_unversioned_or_unbounded_masks_are_rejected_before_runtime(self):
        for changes in ({"synthetic_only":False}, {"case_id":"patient-case"}, {"model_id":"clinical-model"},
                        {"model_artifact_sha256":"unknown"}, {"prediction":(0,2)},
                        {"prediction":(1,)}, {"target":[1,0,1,0]}, {"prediction":(True,1,0,0)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(synthetic_evaluation_case(), **changes)
        with self.assertRaises(ValueError):
            MonaiDiceEvaluationAdapter().evaluate({"synthetic_only":True})

    @unittest.skipUnless(importlib.util.find_spec("monai") and importlib.util.find_spec("torch"), "Optional real MONAI/PyTorch job runs this test.")
    def test_real_monai_dice_and_empty_mask_semantics(self):
        adapter, case = MonaiDiceEvaluationAdapter(), synthetic_evaluation_case()
        partial = adapter.evaluate(case)
        self.assertAlmostEqual(partial["dice"],.5)
        self.assertEqual(partial,adapter.evaluate(case))
        self.assertEqual(adapter.evaluate(replace(case,prediction=case.target))["dice"],1.)
        self.assertEqual(adapter.evaluate(replace(case,prediction=(0,0,0,0),target=(0,0,0,0)))["dice"],1.)
        self.assertFalse(partial["trained_model_loaded"])
        self.assertFalse(partial["is_clinical_validation"])


if __name__ == '__main__':
    unittest.main()
