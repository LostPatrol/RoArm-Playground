"""CPU visual demonstrations; all boxes are image-relative, never robot coordinates."""
import os
import time
from pathlib import Path

import cv2
import numpy as np


# YOLOX-Nano release uses 416x416 BGR input with 114-valued letterbox padding.
YOLO_SIZE = 416
COCO_LABELS = (
    "person bicycle car motorcycle airplane bus train truck boat traffic_light "
    "fire_hydrant stop_sign parking_meter bench bird cat dog horse sheep cow "
    "elephant bear zebra giraffe backpack umbrella handbag tie suitcase frisbee "
    "skis snowboard sports_ball kite baseball_bat baseball_glove skateboard "
    "surfboard tennis_racket bottle wine_glass cup fork knife spoon bowl banana "
    "apple sandwich orange broccoli carrot hot_dog pizza donut cake chair couch "
    "potted_plant bed dining_table toilet tv laptop mouse remote keyboard "
    "cell_phone microwave oven toaster sink refrigerator book clock vase "
    "scissors teddy_bear hair_drier toothbrush"
).split()
COLOR_RANGES = {
    "red": [((0, 90, 65), (12, 255, 255)), ((170, 90, 65), (179, 255, 255))],
    "green": [((35, 65, 55), (85, 255, 255))],
    "blue": [((90, 75, 55), (135, 255, 255))],
    "yellow": [((18, 80, 75), (35, 255, 255))],
}


def _box(label, box, shape, confidence=1.0, **extra):
    """Clip a pixel rectangle to the image and normalize its geometry."""
    height, width = shape[:2]
    x, y, w, h = map(float, box)
    x0, y0 = max(0.0, min(width, x)), max(0.0, min(height, y))
    x1, y1 = max(x0, min(width, x + w)), max(y0, min(height, y + h))
    return dict(label=label, x=x0 / width, y=y0 / height,
                w=(x1 - x0) / width, h=(y1 - y0) / height,
                cx=(x0 + x1) / (2 * width), cy=(y0 + y1) / (2 * height),
                confidence=float(confidence), **extra)


class VisionEngine:
    """Lightweight detectors with explicit missing-resource and target-loss results."""

    def __init__(self, model_dir=None):
        # RK's vendor OpenCL compiler fails on standard remap kernels; this module
        # deliberately uses CPU paths instead of repeatedly compiling/falling back.
        if hasattr(cv2, "ocl"):
            cv2.ocl.setUseOpenCL(False)
        self.model_dir = Path(model_dir or os.environ.get(
            "ROARM_MODEL_DIR", str(Path(__file__).resolve().parent.parent / "models")))
        cv_data = getattr(getattr(cv2, "data", None), "haarcascades", "")
        candidates = [self.model_dir / "haarcascade_frontalface_default.xml"]
        if cv_data:
            candidates.append(Path(cv_data) / "haarcascade_frontalface_default.xml")
        candidates += [Path("/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml"),
                       Path("/usr/share/opencv/haarcascades/haarcascade_frontalface_default.xml")]
        self.face = None
        for path in candidates:
            if path.is_file():
                cascade = cv2.CascadeClassifier(str(path))
                if not cascade.empty():
                    self.face = cascade
                    break
        self.net = None
        self.model_error = None
        self.face_detector = None
        self.face_model_error = None
        yunet = self.model_dir / "face_detection_yunet_2023mar.onnx"
        if yunet.is_file() and hasattr(cv2, "FaceDetectorYN_create"):
            try:
                # YuNet's actual network score reduces Haar's false faces on furniture/walls.
                self.face_detector = cv2.FaceDetectorYN_create(
                    str(yunet), "", (320, 320), 0.8, 0.3, 5000,
                    cv2.dnn.DNN_BACKEND_OPENCV, cv2.dnn.DNN_TARGET_CPU)
            except cv2.error as exc:
                self.face_model_error = str(exc)
        elif not yunet.is_file():
            self.face_model_error = "YuNet model missing; Haar fallback has more false detections"
        else:
            self.face_model_error = "This OpenCV build lacks FaceDetectorYN; Haar fallback active"
        self.template = None
        self.target_shape = None
        self.track_box = None
        self.track_gray = self.track_points = None
        self.track_quad = self.anchor_template = None
        self.flow_consistency = 0.0
        self.aruco = getattr(cv2, "aruco", None)

    def capabilities(self):
        """Availability describes resources, not unmeasured recognition accuracy."""
        return {
            "face": {"available": self.face_detector is not None or self.face is not None,
                     "backend": "YuNet OpenCV DNN CPU" if self.face_detector is not None else "OpenCV Haar fallback",
                     "fallback": self.face_detector is None, "error": self.face_model_error},
            "color": {"available": True, "backend": "OpenCV HSV"},
            "markers": {"available": self.aruco is not None, "backend": "AprilTag tag36h11"},
            "objects": {"available": (self.model_dir / "yolox_nano.onnx").is_file()
                        and not self.model_error, "backend": "YOLOX-Nano OpenCV DNN CPU",
                        "error": self.model_error},
            "track": {"available": True, "backend": "OpenCV adaptive tracking + multiscale template reacquisition"},
            "foam": {"available": True, "backend": "OpenCV low-saturation/brightness contour heuristic"},
            "manual": {"available": True, "backend": "image only"},
            "difference": {"available": True, "backend": "OpenCV absolute image difference"},
            "stitch": {"available": hasattr(cv2, "Stitcher_create"), "backend": "OpenCV Stitcher"},
        }

    def process(self, frame, mode, options=None):
        """Return JSON-serializable detections; algorithm failures produce error fields."""
        started = time.perf_counter()
        result = {"detections": [], "width": 0, "height": 0, "mode": mode}
        try:
            self._check_frame(frame)
            result.update(width=int(frame.shape[1]), height=int(frame.shape[0]))
            options = options or {}
            if mode == "face":
                use_yunet = self.face_detector is not None and options.get("face_backend") != "haar"
                result["backend"] = "YuNet OpenCV DNN CPU" if use_yunet else "OpenCV Haar fallback"
                if use_yunet:
                    self.face_detector.setInputSize((frame.shape[1], frame.shape[0]))
                    self.face_detector.setScoreThreshold(float(options.get("face_confidence", 0.8)))
                    _, faces = self.face_detector.detect(frame)
                    if faces is not None:
                        result["detections"] = [_box("face", row[:4], frame.shape, row[-1]) for row in faces]
                    result["confidence_kind"] = "YuNet neural detector score"
                else:
                    if self.face is None:
                        raise ValueError("No face model available; run scripts/fetch_vision_models.sh")
                    gray = cv2.equalizeHist(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
                    boxes = self.face.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5,
                                                      minSize=(30, 30))
                    result["detections"] = [_box("face", b, frame.shape) for b in boxes]
                    result["confidence_kind"] = "Haar presence flag, not probability"
                    result["warning"] = self.face_model_error or "Haar explicitly selected; false positives possible"
            elif mode == "color":
                result["detections"] = self._color(frame, options)
                result["confidence_kind"] = "contour solidity, not class probability"
            elif mode == "markers":
                result["detections"] = self._markers(frame)
                result["backend"] = "AprilTag tag36h11"
                result["confidence_kind"] = "decoded marker presence flag"
            elif mode == "objects":
                result["detections"] = self._objects(frame, options)
                result["backend"] = "YOLOX-Nano OpenCV DNN CPU"
            elif mode == "track":
                result.update(self._track(frame, options))
            elif mode == "foam":
                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                # Exposure can lift black foam to V≈170. Compare with the current tabletop
                # instead of admitting all low-saturation pixels up to V220 (including blank mat).
                ceiling = max(0, min(255, int(options.get("dark_threshold", 220))))
                saturation = max(0, min(255, int(options.get("max_saturation", 100))))
                mask = np.full(frame.shape[:2], 255, np.uint8)
                roi = options.get("roi")
                if roi is not None:
                    # Mask in full-frame coordinates so returned boxes retain the public normalized geometry.
                    values = [roi.get(key, float("nan")) for key in ("x", "y", "w", "h")] if isinstance(roi, dict) else list(roi)
                    if (len(values) != 4 or not all(np.isfinite(v) and 0 <= v <= 1 for v in values)
                            or values[2] <= 0 or values[3] <= 0
                            or values[0] + values[2] > 1 or values[1] + values[3] > 1):
                        raise ValueError("Foam ROI must be normalized x,y,w,h within the image")
                    x, y, w, h = values
                    height, width = frame.shape[:2]
                    region = np.zeros(mask.shape, np.uint8)
                    region[int(y * height):int((y + h) * height),
                           int(x * width):int((x + w) * width)] = 255
                    mask &= region
                values = hsv[:, :, 2][mask != 0]
                reference = float(np.percentile(values, 75)) if values.size else 0
                threshold = min(ceiling, int(reference * .88))
                mask &= cv2.inRange(hsv, (0, 0, 0), (179, saturation, threshold))
                result["detections"] = self._contours(frame, mask, "dark_foam_candidate", options)
                result["backend"] = "CV low-saturation/brightness heuristic; not material identification"
                result["confidence_kind"] = "convex-hull solidity, not material probability"
                result["parameters"] = dict(dark_threshold=ceiling, effective_dark_threshold=threshold,
                                            tabletop_brightness=reference, max_saturation=saturation, roi=roi)
            elif mode != "manual":
                raise ValueError("Unknown vision mode: " + str(mode))
        except (ValueError, TypeError, cv2.error, OSError) as exc:
            result["error"] = str(exc)
        result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return result

    @staticmethod
    def _check_frame(frame):
        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("Expected non-empty uint8 BGR image")
        if frame.size == 0 or frame.dtype != np.uint8:
            raise ValueError("Expected non-empty uint8 BGR image")

    def _color(self, frame, options):
        """Support named colors or explicit HSV lower/upper triples (H: 0..179)."""
        color = str(options.get("color", "red"))
        if "lower" in options and "upper" in options:
            ranges = [(options["lower"], options["upper"])]
            if len(ranges[0][0]) != 3 or len(ranges[0][1]) != 3:
                raise ValueError("HSV lower and upper must each contain three numbers")
        elif color in COLOR_RANGES:
            ranges = COLOR_RANGES[color]
        else:
            raise ValueError("Unknown color; choose red/green/blue/yellow or supply HSV limits")
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = np.zeros(frame.shape[:2], np.uint8)
        for lower, upper in ranges:
            mask |= cv2.inRange(hsv, np.asarray(lower, np.uint8), np.asarray(upper, np.uint8))
        return self._contours(frame, mask, color, options)

    @staticmethod
    def _contours(frame, mask, label, options):
        # 0.15% area suppresses noise without requiring fine positioning.
        minimum = max(0.0, float(options.get("min_area", 0.0015))) * mask.size
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        contours = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2]
        found = []
        for contour in sorted(contours, key=cv2.contourArea, reverse=True):
            area = cv2.contourArea(contour)
            if area < minimum:
                continue
            box = cv2.boundingRect(contour)
            # A dark frame border is not a useful foam candidate.
            if label == "dark_foam_candidate" and area > mask.size * 0.75:
                continue
            if label == "dark_foam_candidate" and max(box[2], box[3]) / max(1, min(box[2], box[3])) > 3.5:
                continue  # Thin camera-edge shadows/cables are not the intended block shape.
            # Perspective makes a rectangular block occupy only half its axis-aligned box;
            # hull solidity describes its contour without penalizing that camera angle.
            denominator = (cv2.contourArea(cv2.convexHull(contour))
                           if label == "dark_foam_candidate" else box[2] * box[3])
            found.append(_box(label, box, frame.shape, area / max(1, denominator)))
        return found[:int(options.get("max_detections", 10))]

    def _markers(self, frame):
        if self.aruco is None:
            raise ValueError("ArUco unavailable; use OpenCV contrib/system python3-opencv")
        aruco = self.aruco
        dictionary = aruco.getPredefinedDictionary(aruco.DICT_APRILTAG_36h11)
        if hasattr(aruco, "ArucoDetector"):
            corners, ids, _ = aruco.ArucoDetector(dictionary).detectMarkers(frame)
        else:
            corners, ids, _ = aruco.detectMarkers(frame, dictionary)
        if ids is None:
            return []
        height, width = frame.shape[:2]
        return [_box("tag36h11_%d" % int(marker_id), cv2.boundingRect(corner), frame.shape,
                     id=int(marker_id), family="tag36h11",
                     corners=(corner.reshape(-1, 2) / (width, height)).tolist())
                for corner, marker_id in zip(corners, ids.ravel())]

    def _objects(self, frame, options):
        """Decode the official raw YOLOX heads, then suppress overlapping same-class boxes."""
        model = self.model_dir / "yolox_nano.onnx"
        if not model.is_file():
            raise ValueError("YOLOX-Nano model missing; run scripts/fetch_vision_models.sh")
        if self.net is None:
            try:
                self.net = cv2.dnn.readNetFromONNX(str(model))
                self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
                self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
            except cv2.error as exc:
                self.model_error = str(exc)
                raise
        height, width = frame.shape[:2]
        ratio = min(YOLO_SIZE / height, YOLO_SIZE / width)
        resized = cv2.resize(frame, (int(width * ratio), int(height * ratio)))
        padded = np.full((YOLO_SIZE, YOLO_SIZE, 3), 114, np.uint8)
        padded[:resized.shape[0], :resized.shape[1]] = resized
        # No RGB swap and no /255 normalization: required by official post-0.1.1 model.
        self.net.setInput(cv2.dnn.blobFromImage(padded, 1.0, (YOLO_SIZE, YOLO_SIZE), swapRB=False))
        output = self.net.forward()[0].copy()
        grids, strides = [], []
        for stride in (8, 16, 32):
            size = YOLO_SIZE // stride
            xx, yy = np.meshgrid(np.arange(size), np.arange(size))
            grids.append(np.stack((xx, yy), axis=2).reshape(-1, 2))
            strides.append(np.full((size * size, 1), stride))
        grid, stride = np.concatenate(grids), np.concatenate(strides)
        if output.shape != (len(grid), 85):
            raise ValueError("Unsupported YOLOX output shape: " + str(output.shape))
        output[:, :2] = (output[:, :2] + grid) * stride
        output[:, 2:4] = np.exp(np.clip(output[:, 2:4], -20, 20)) * stride
        scores = output[:, 4:5] * output[:, 5:]
        class_ids = scores.argmax(axis=1)
        confidence = scores.max(axis=1)
        threshold = float(options.get("confidence", 0.35))
        found = []
        for class_id in np.unique(class_ids[confidence >= threshold]):
            selected = np.where((class_ids == class_id) & (confidence >= threshold))[0]
            values = output[selected, :4] / ratio
            boxes = np.column_stack((values[:, :2] - values[:, 2:4] / 2, values[:, 2:4]))
            indices = cv2.dnn.NMSBoxes(boxes.tolist(), confidence[selected].tolist(),
                                       threshold, float(options.get("nms", 0.45)))
            for index in np.asarray(indices).reshape(-1):
                detection = _box(COCO_LABELS[int(class_id)], boxes[int(index)], frame.shape,
                                 confidence[selected[int(index)]], id=int(class_id))
                if detection["w"] > 0 and detection["h"] > 0:
                    found.append(detection)
        return sorted(found, key=lambda item: item["confidence"], reverse=True)[:20]

    def set_target(self, frame, box):
        """Capture a user-selected normalized x/y/w/h template; reject untrackable flat areas."""
        self._check_frame(frame)
        if isinstance(box, dict):
            values = [box[key] for key in ("x", "y", "w", "h")]
        else:
            values = list(box)
        if len(values) != 4 or not all(np.isfinite(v) and 0 <= v <= 1 for v in values):
            raise ValueError("Target box must contain normalized x,y,w,h")
        x, y, w, h = values
        height, width = frame.shape[:2]
        x0, y0 = int(x * width), int(y * height)
        x1, y1 = min(width, int((x + w) * width)), min(height, int((y + h) * height))
        target = frame[y0:y1, x0:x1]
        if target.shape[0] < 8 or target.shape[1] < 8:
            raise ValueError("Target region must be at least 8x8 pixels")
        gray = cv2.cvtColor(target, cv2.COLOR_BGR2GRAY)
        if gray.std() < 4:
            raise ValueError("Target has insufficient texture; include visible object edges")
        self.template = gray.copy()
        self.anchor_template = gray.copy()
        self.target_shape = frame.shape[:2]
        self.track_box = (x0, y0, x1 - x0, y1 - y0)
        self._init_tracker(frame, self.track_box)

    def _init_tracker(self, frame, box):
        """Initialize sparse optical flow using the same base OpenCV API as the RK board."""
        self.track_box = box
        self.track_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mask = np.zeros(self.track_gray.shape, np.uint8)
        x, y, w, h = map(int, box)
        self.track_quad = np.asarray([[[x, y], [x + w, y], [x + w, y + h], [x, y + h]]], np.float32)
        mask[max(0, y):y + h, max(0, x):x + w] = 255
        self.track_points = cv2.goodFeaturesToTrack(self.track_gray, 80, .01, 3, mask=mask)

    def _flow_track(self, gray):
        """Track real image corners, reject inconsistent flow, and estimate translation/scale/rotation."""
        self.flow_consistency = 0.0
        points = self.track_points
        if points is None or len(points) < 6:
            return None
        moved, status, errors = cv2.calcOpticalFlowPyrLK(self.track_gray, gray, points, None,
                                                 winSize=(31, 31), maxLevel=3)
        if moved is None:
            return None
        returned, reverse_status, _ = cv2.calcOpticalFlowPyrLK(gray, self.track_gray, moved, None,
                                                            winSize=(31, 31), maxLevel=3)
        if returned is None:
            return None
        # A forward/backward error over 1.5 pixels indicates lost/occluded features.
        good = (status.ravel() != 0) & (reverse_status.ravel() != 0)
        good &= np.linalg.norm(points - returned, axis=2).ravel() < 1.5
        good &= errors.ravel() < 30  # Strong appearance mismatch is not a valid motion measurement.
        if np.count_nonzero(good) < 6:
            self.track_points = None
            return None
        transform, inliers = cv2.estimateAffinePartial2D(points[good], moved[good],
                                                        method=cv2.RANSAC, ransacReprojThreshold=2)
        if transform is None or inliers.sum() < 6 or inliers.mean() < .6:
            self.track_points = None
            return None
        self.flow_consistency = float(good.mean() * inliers.mean())
        self.track_quad = cv2.transform(self.track_quad, transform)
        corners = self.track_quad[0]
        low, high = corners.min(axis=0), corners.max(axis=0)
        self.track_gray = gray
        self.track_points = moved[good][inliers.ravel() != 0].reshape(-1, 1, 2)
        return (*low, *(high - low))

    def _track(self, frame, options):
        if self.template is None:
            raise ValueError("Select a textured target before tracking")
        if frame.shape[:2] != self.target_shape:
            raise ValueError("Camera resolution changed; select the target again")
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        source = "Lucas-Kanade optical flow"
        tracked = self._flow_track(gray)
        if tracked is not None:
            x, y, w, h = map(int, tracked)
            patch = gray[max(0, y):y + h, max(0, x):x + w]
            if not patch.size or patch.std() < 4:
                tracked = None
        best = (-1.0, None)
        # Global reacquisition covers jumps beyond optical flow's window. The original
        # template is retained for recovery after loss; the recent template follows appearance.
        h0, w0 = self.template.shape
        for candidate in (self.template, self.anchor_template):
            for scale in (.75, 1.0, 1.25):
                w, h = max(8, int(w0 * scale)), max(8, int(h0 * scale))
                if w > gray.shape[1] or h > gray.shape[0]:
                    continue
                template = cv2.resize(candidate, (w, h))
                response = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
                _, score, _, position = cv2.minMaxLoc(response)
                if np.isfinite(score) and score > best[0]:
                    best = (float(score), (*position, w, h))
        score, matched = best
        if matched is not None and score >= float(options.get("match_threshold", .65)):
            if tracked is None or abs(tracked[0] - matched[0]) + abs(tracked[1] - matched[1]) > 30:
                self._init_tracker(frame, matched)
            tracked = matched
            source = "multiscale template reacquisition"
        if tracked is None:
            return {"detections": [], "lost": True, "match_score": score, "track_confidence": 0.0}
        self.track_box = tracked
        x, y, w, h = map(int, tracked)
        patch = gray[max(0, y):y + h, max(0, x):x + w]
        if patch.size and patch.std() >= 4:
            self.template = cv2.resize(patch, (w0, h0))
        confidence = max(0, score) if source.startswith("multiscale") else self.flow_consistency
        return {"detections": [_box("tracked_target", tracked, frame.shape, confidence)],
                "lost": False, "match_score": score, "track_confidence": confidence, "backend": source,
                "confidence_kind": "template correlation / consistent optical-flow presence, not class probability"}

    def difference(self, before, after, options=None):
        """Compare fixed-camera frames; camera motion/exposure changes can cause false changes."""
        started = time.perf_counter()
        result = {"detections": [], "width": 0, "height": 0}
        try:
            self._check_frame(before)
            self._check_frame(after)
            if before.shape != after.shape:
                raise ValueError("Before/after image dimensions differ")
            result.update(width=int(after.shape[1]), height=int(after.shape[0]))
            options = options or {}
            delta = cv2.absdiff(cv2.GaussianBlur(before, (5, 5), 0),
                                cv2.GaussianBlur(after, (5, 5), 0))
            gray = cv2.cvtColor(delta, cv2.COLOR_BGR2GRAY)
            _, mask = cv2.threshold(gray, int(options.get("threshold", 30)), 255, cv2.THRESH_BINARY)
            result["changed_fraction"] = float(np.count_nonzero(mask) / mask.size)
            result["detections"] = self._contours(after, mask, "changed", options)
        except (ValueError, TypeError, cv2.error) as exc:
            result["error"] = str(exc)
        result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return result

    def stitch(self, frames):
        """Attempt a feature-based panorama; return failure instead of merely concatenating images."""
        try:
            if len(frames) < 2:
                raise ValueError("At least two overlapping frames are required")
            for frame in frames:
                self._check_frame(frame)
            status, panorama = cv2.Stitcher_create(cv2.Stitcher_PANORAMA).stitch(frames)
            if status != cv2.Stitcher_OK:
                errors = {1: "insufficient overlapping features", 2: "homography estimation failed",
                          3: "camera parameter adjustment failed"}
                return None, "Panorama failed: " + errors.get(status, "OpenCV status %d" % status)
            return panorama, None
        except (ValueError, TypeError, cv2.error) as exc:
            return None, str(exc)
