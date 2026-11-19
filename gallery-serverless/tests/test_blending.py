"""Regression checks for identity-preserving face compositing, without model weights."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np

path = Path(__file__).resolve().parents[1] / 'sagemaker/alphaface/code/blending.py'
spec = importlib.util.spec_from_file_location('blending', path)
blending = importlib.util.module_from_spec(spec)
spec.loader.exec_module(blending)


class BlendingTests(unittest.TestCase):
    def setUp(self):
        self.landmarks = np.array([[95, 100], [160, 100], [128, 132], [110, 155], [145, 155]], np.float32)
        self.mask = blending.face_mask(self.landmarks)

    def test_mask_keeps_identity_region_opaque_and_background_clear(self):
        self.assertEqual(self.mask[130, 128], 1.0)
        self.assertEqual(self.mask[155, 128], 1.0)
        self.assertEqual(self.mask[0, 0], 0.0)
        self.assertEqual(self.mask[30, 128], 0.0)
        self.assertTrue(np.any((self.mask > 0) & (self.mask < 1)))

    def test_mask_tracks_face_landmarks(self):
        shifted = blending.face_mask(self.landmarks + [12, 0])
        original_x = np.nonzero(self.mask > .5)[1].mean()
        shifted_x = np.nonzero(shifted > .5)[1].mean()
        self.assertAlmostEqual(shifted_x - original_x, 12, delta=.5)

    def test_colour_transfer_handles_flat_crops(self):
        source = np.full((256, 256, 3), 130, np.uint8)
        target = np.full_like(source, 180)
        result = blending.match_colour(source, target, self.mask)
        self.assertTrue(np.isfinite(result).all())
        self.assertGreater(result.mean(), source.mean())
        self.assertLess(result.mean(), target.mean())

    def test_zero_blend_preserves_target(self):
        source = np.full((256, 256, 3), 180, np.uint8)
        target = np.full_like(source, 40)
        np.testing.assert_array_equal(blending.composite_face(source, target, self.mask, 0), target)

    def test_full_blend_preserves_central_identity_and_outer_background(self):
        source = np.full((256, 256, 3), 180, np.uint8)
        target = np.full_like(source, 40)
        result = blending.composite_face(source, target, self.mask, 1)
        np.testing.assert_allclose(result[130, 128], source[130, 128], atol=1)
        np.testing.assert_array_equal(result[:20], target[:20])

    def test_invalid_blend_is_rejected(self):
        image = np.zeros((256, 256, 3), np.uint8)
        with self.assertRaises(ValueError):
            blending.composite_face(image, image, self.mask, float('nan'))


if __name__ == '__main__':
    unittest.main()
