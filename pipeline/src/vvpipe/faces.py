"""Target-person face matching with OpenCV's YuNet (detector) and SFace (recognizer).

Both models are small ONNX files that run the same way on x86 and ARM, which keeps the
embeddings produced on the GPU box and on the weekly-update boxes comparable.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import cv2
import numpy as np

DET_MODEL = "face_detection_yunet_2023mar.onnx"
REC_MODEL = "face_recognition_sface_2021dec.onnx"


def _unit(v: np.ndarray) -> np.ndarray:
    return v / (np.linalg.norm(v) + 1e-9)


class FaceMatcher:
    def __init__(self, models_dir: Path, ref_path: Path | None = None, det_width: int = 960):
        self.det = cv2.FaceDetectorYN.create(
            str(models_dir / DET_MODEL),
            "",
            (320, 320),
            score_threshold=0.7,
            nms_threshold=0.3,
            top_k=20,
        )
        self.rec = cv2.FaceRecognizerSF.create(str(models_dir / REC_MODEL), "")
        self.det_width = det_width
        self.ref: np.ndarray | None = None
        if ref_path is not None and ref_path.exists():
            self.ref = np.load(ref_path)["proto"]

    def _faces(self, bgr: np.ndarray) -> np.ndarray:
        """Detect on a downscaled copy, return boxes scaled back to the original size."""
        h, w = bgr.shape[:2]
        scale = self.det_width / w if w > self.det_width else 1.0
        small = cv2.resize(bgr, (int(w * scale), int(h * scale))) if scale != 1.0 else bgr
        self.det.setInputSize((small.shape[1], small.shape[0]))
        _, faces = self.det.detect(small)
        if faces is None:
            return np.empty((0, 15), dtype=np.float32)
        faces = faces.copy()
        faces[:, :14] /= scale
        return faces

    def features(self, bgr: np.ndarray) -> list[np.ndarray]:
        out = []
        for f in self._faces(bgr):
            aligned = self.rec.alignCrop(bgr, f)
            out.append(_unit(self.rec.feature(aligned).reshape(-1)))
        return out

    def similarity(self, bgr: np.ndarray) -> float:
        """Best cosine similarity between any face in the frame and the target prototype."""
        if self.ref is None:
            raise RuntimeError("no reference prototype loaded")
        best = 0.0
        for feat in self.features(bgr):
            best = max(best, float(feat @ self.ref))
        return best


def build_prototype(models_dir: Path, zip_path: Path, out_path: Path, limit: int = 1500) -> dict:
    """Average the face features of every reference image into one unit-length prototype."""
    matcher = FaceMatcher(models_dir, det_width=10_000)
    feats: list[np.ndarray] = []
    seen = 0
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith((".jpg", ".jpeg", ".png"))]
        step = max(1, len(names) // limit)
        for name in names[::step]:
            seen += 1
            img = cv2.imdecode(np.frombuffer(zf.read(name), np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue
            # The references are tight face crops: pad so the detector sees some context.
            pad = max(img.shape[:2]) // 2
            img = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
            found = matcher.features(img)
            if len(found) == 1:
                feats.append(found[0])
    if not feats:
        raise RuntimeError("no usable reference faces")
    mat = np.stack(feats)
    proto = _unit(mat.mean(axis=0))
    sims = mat @ proto
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out_path, proto=proto.astype(np.float32))
    return {
        "images": seen,
        "used": len(feats),
        "self_sim_p5": float(np.percentile(sims, 5)),
        "self_sim_mean": float(sims.mean()),
    }
