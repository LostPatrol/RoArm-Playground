"""Visual algorithm checks: synthetic geometry, marker decoding, loss handling, real optional YOLO."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rk3588"))
from vision import VisionEngine


class VisionTests(unittest.TestCase):
    def setUp(self):
        self.engine = VisionEngine()
        self.frame = np.full((240, 320, 3), 240, np.uint8)

    def test_red_wraparound_and_normalized_geometry(self):
        # Both ends of OpenCV's hue interval must match red.
        hsv = np.zeros((240, 320, 3), np.uint8)
        hsv[40:100, 50:130] = (175, 240, 220)
        hsv[130:190, 180:260] = (5, 240, 220)
        result = self.engine.process(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR), "color")
        self.assertNotIn("error", result)
        self.assertEqual(len(result["detections"]), 2)
        for box in result["detections"]:
            self.assertAlmostEqual(box["w"], 80 / 320)
            self.assertAlmostEqual(box["h"], 60 / 240)
            self.assertAlmostEqual(box["cx"], box["x"] + box["w"] / 2)

    def test_color_switch_and_small_noise_filter(self):
        self.frame[40:100, 50:130] = (255, 0, 0)
        self.frame[5:7, 5:7] = (255, 0, 0)
        self.assertEqual(len(self.engine.process(self.frame, "color", {"color": "blue"})["detections"]), 1)
        self.assertEqual(self.engine.process(self.frame, "color")["detections"], [])

    def test_custom_hsv_and_invalid_mode(self):
        self.frame[40:100, 50:130] = (0, 255, 0)
        found = self.engine.process(self.frame, "color", {"lower": [40, 80, 80], "upper": [80, 255, 255]})
        self.assertEqual(len(found["detections"]), 1)
        self.assertIn("error", self.engine.process(self.frame, "imaginary"))
        self.assertIn("error", self.engine.process(self.frame, "color", {"color": "purple"}))

    def test_foam_is_brightness_candidate(self):
        self.frame[70:130, 100:170] = (15, 15, 15)
        result = self.engine.process(self.frame, "foam")
        self.assertEqual(len(result["detections"]), 1)
        self.assertEqual(result["detections"][0]["label"], "dark_foam_candidate")
        self.assertIn("not material identification", result["backend"])
        self.assertEqual(self.engine.process(np.zeros_like(self.frame), "foam")["detections"], [])

    def test_foam_auto_exposure_and_roi(self):
        # A black object lifted by camera exposure stays less saturated than the colored tabletop.
        hsv = np.full((240, 320, 3), (85, 200, 205), np.uint8)
        hsv[100:200, 100:220] = (0, 57, 170)
        hsv[10:30, 20:90] = (0, 20, 80)  # A distracting dark camera support near the top.
        image = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        result = self.engine.process(image, "foam", {"roi": [0, .3, 1, .7]})
        self.assertNotIn("error", result)
        self.assertEqual(len(result["detections"]), 1)
        box = result["detections"][0]
        self.assertAlmostEqual(box["x"], 100 / 320)
        self.assertAlmostEqual(box["y"], 100 / 240)
        self.assertAlmostEqual(box["w"], 120 / 320)
        self.assertEqual(result["parameters"]["dark_threshold"], 220)
        self.assertEqual(result["parameters"]["max_saturation"], 100)
        # The former V-only limits missed the real candidate: preserve this cause as a regression.
        old = self.engine.process(image, "foam", {"dark_threshold": 95, "roi": [0, .3, 1, .7]})
        self.assertEqual(old["detections"], [])
        strict = self.engine.process(image, "foam", {"max_saturation": 20, "roi": [0, .3, 1, .7]})
        self.assertEqual(strict["detections"], [])
        invalid = self.engine.process(image, "foam", {"roi": [.9, 0, .2, 1]})
        self.assertIn("error", invalid)

    def test_marker_roundtrip(self):
        if not hasattr(cv2, "aruco"):
            self.skipTest("OpenCV build lacks ArUco")
        aruco = cv2.aruco
        dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
        if hasattr(aruco, "generateImageMarker"):
            marker = aruco.generateImageMarker(dictionary, 17, 100)
        else:
            marker = aruco.drawMarker(dictionary, 17, 100)
        self.frame[60:160, 100:200] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
        result = self.engine.process(self.frame, "markers")
        self.assertNotIn("error", result)
        self.assertEqual(result["detections"][0]["id"], 17)
        self.assertAlmostEqual(result["detections"][0]["cx"], 150 / 320, delta=0.005)

    def test_missing_objects_model_explicit_error(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = VisionEngine(directory)
            self.assertFalse(engine.capabilities()["objects"]["available"])
            result = engine.process(self.frame, "objects")
            self.assertIn("model missing", result["error"])
            self.assertEqual(result["detections"], [])

    def test_face_blank_frame(self):
        if self.engine.face is None:
            self.skipTest("Haar cascade not installed")
        result = self.engine.process(self.frame, "face")
        self.assertNotIn("error", result)
        self.assertEqual(result["detections"], [])

    def test_haar_fallback_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = VisionEngine(directory)
            if engine.face is None:
                self.skipTest("No system Haar cascade available for fallback")
            result = engine.process(self.frame, "face")
            self.assertEqual(result["backend"], "OpenCV Haar fallback")
            self.assertIn("YuNet model missing", result["warning"])
            self.assertTrue(engine.capabilities()["face"]["fallback"])

    def test_track_translation_and_loss(self):
        # Texture is unique; follow the actual moved pixels, not a synthetic reported center.
        rng = np.random.RandomState(23)
        texture = rng.randint(0, 255, (40, 50, 3), dtype=np.uint8)
        self.frame[60:100, 80:130] = texture
        self.engine.set_target(self.frame, {"x": 80 / 320, "y": 60 / 240,
                                             "w": 50 / 320, "h": 40 / 240})
        moved = np.full_like(self.frame, 240)
        moved[100:140, 170:220] = texture
        result = self.engine.process(moved, "track")
        self.assertFalse(result["lost"])
        self.assertAlmostEqual(result["detections"][0]["x"], 170 / 320)
        self.assertAlmostEqual(result["detections"][0]["y"], 100 / 240)
        lost = self.engine.process(np.full_like(self.frame, 240), "track")
        self.assertTrue(lost["lost"])
        self.assertEqual(lost["detections"], [])

    def test_track_requires_texture_and_same_resolution(self):
        with self.assertRaises(ValueError):
            self.engine.set_target(self.frame, (0.1, 0.1, 0.2, 0.2))
        self.assertIn("error", self.engine.process(self.frame, "track"))
        with self.assertRaises(ValueError):
            self.engine.set_target(self.frame, (-0.1, 0.1, 0.2, 0.2))

    def test_difference_and_unchanged_image(self):
        after = self.frame.copy()
        after[80:140, 120:180] = 0
        result = self.engine.difference(self.frame, after)
        self.assertNotIn("error", result)
        self.assertEqual(len(result["detections"]), 1)
        box = result["detections"][0]
        self.assertAlmostEqual(box["cx"], 150 / 320, delta=0.01)
        self.assertGreater(result["changed_fraction"], 0.04)
        self.assertEqual(self.engine.difference(after, after)["detections"], [])
        self.assertIn("error", self.engine.difference(after, after[:120]))

    def test_stitch_failure_is_not_concatenated(self):
        panorama, error = self.engine.stitch([self.frame, self.frame])
        self.assertIsNone(panorama)
        self.assertIn("Panorama failed", error)
        self.assertIsNone(self.engine.stitch([self.frame])[0])

    def test_stitch_overlapping_textured_frames(self):
        # Known overlapping crops require actual feature alignment and a wider output.
        rng = np.random.RandomState(40)
        canvas = np.full((360, 800, 3), 240, np.uint8)
        for _ in range(1000):
            position = (int(rng.randint(0, 800)), int(rng.randint(0, 360)))
            color = tuple(int(v) for v in rng.randint(0, 255, 3))
            cv2.circle(canvas, position, int(rng.randint(2, 8)), color, -1)
        frames = [canvas[:, :500].copy(), canvas[:, 180:680].copy(), canvas[:, 300:].copy()]
        cv2.setRNGSeed(1)
        panorama, error = self.engine.stitch(frames)
        self.assertIsNone(error, error)
        self.assertGreater(panorama.shape[1], 700)
        self.assertLess(panorama.shape[1], 850)

    def test_invalid_image_and_manual_mode(self):
        for image in (None, np.zeros((0, 0, 3), np.uint8), np.zeros((20, 20), np.uint8)):
            self.assertIn("error", self.engine.process(image, "color"))
        self.assertNotIn("error", self.engine.process(self.frame, "manual"))

    @unittest.skipUnless(os.environ.get("ROARM_VISION_REAL_IMAGE"), "Set official dog.jpg path for real inference")
    def test_yolox_real_reference_image(self):
        image = cv2.imread(os.environ["ROARM_VISION_REAL_IMAGE"])
        result = self.engine.process(image, "objects")
        self.assertNotIn("error", result)
        labels = {item["label"] for item in result["detections"]}
        self.assertTrue({"dog", "bicycle"}.issubset(labels), result)
        for box in result["detections"]:
            for key in ("x", "y", "w", "h", "cx", "cy", "confidence"):
                self.assertGreaterEqual(box[key], 0)
                self.assertLessEqual(box[key], 1)

    @unittest.skipUnless(os.environ.get("ROARM_VISION_FACE_IMAGE"), "Set portrait path for real Haar inference")
    def test_face_real_portrait(self):
        result = self.engine.process(cv2.imread(os.environ["ROARM_VISION_FACE_IMAGE"]), "face")
        self.assertNotIn("error", result)
        self.assertGreaterEqual(len(result["detections"]), 1)
        if self.engine.face_detector is not None:
            self.assertEqual(result["backend"], "YuNet OpenCV DNN CPU")
            self.assertTrue(all(box["confidence"] >= .8 for box in result["detections"]))

    @unittest.skipUnless(os.environ.get("ROARM_VISION_EMPTY_IMAGE"), "Set real no-person camera image for regression")
    def test_yunet_real_no_person_scene(self):
        self.assertIsNotNone(self.engine.face_detector, "This regression requires actual YuNet, not Haar fallback")
        result = self.engine.process(cv2.imread(os.environ["ROARM_VISION_EMPTY_IMAGE"]), "face")
        self.assertNotIn("error", result)
        self.assertEqual(result["backend"], "YuNet OpenCV DNN CPU")
        self.assertEqual(result["detections"], [], result)

    @unittest.skipUnless(os.environ.get("ROARM_FOAM_REAL_IMAGE"), "Set prepared green-table foam image path")
    def test_foam_real_prepared_green_table(self):
        image = cv2.imread(os.environ["ROARM_FOAM_REAL_IMAGE"])
        result = self.engine.process(image, "foam", {"roi": [0, .35, 1, .65]})
        self.assertNotIn("error", result)
        self.assertGreaterEqual(len(result["detections"]), 1, result)
        height, width = image.shape[:2]
        # Real fixture's visible foam spans approximately x150..434, y247..bottom.
        expected = (150 / width, 247 / height, 434 / width, 1.0)
        def overlap(box):
            x0, y0, x1, y1 = expected
            intersection = max(0, min(x1, box["x"] + box["w"]) - max(x0, box["x"]))
            intersection *= max(0, min(y1, box["y"] + box["h"]) - max(y0, box["y"]))
            union = (x1 - x0) * (y1 - y0) + box["w"] * box["h"] - intersection
            return intersection / union
        self.assertGreater(max(overlap(box) for box in result["detections"]), .85, result)
        self.assertTrue(all(box["y"] >= .35 for box in result["detections"]))


if __name__ == "__main__":
    unittest.main()
