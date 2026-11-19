"""Face compositing with an opaque identity region and soft, colour-matched edges."""
import cv2
import numpy as np


def face_mask(landmarks, size=256):
    """Fit a face-shaped mask to aligned eyes and mouth, excluding hair and ears."""
    eyes = np.asarray(landmarks[:2], np.float32)
    mouth = np.asarray(landmarks[3:5], np.float32).mean(axis=0)
    eye_mid = eyes.mean(axis=0)
    eye_width = max(float(np.linalg.norm(eyes[1] - eyes[0])), size * 0.18)
    down = mouth - eye_mid
    length = max(float(np.linalg.norm(down)), size * 0.14)
    down = down / max(float(np.linalg.norm(down)), 1.0)
    across = np.array([down[1], -down[0]], np.float32)
    # Coordinates are relative to the eye line, with a tapered jaw and chin.
    outline = [(-0.65, -0.50), (0.65, -0.50), (1.00, 0.05), (1.08, 0.70),
               (0.85, 1.45), (0.45, 1.90), (0.00, 2.05), (-0.45, 1.90),
               (-0.85, 1.45), (-1.08, 0.70), (-1.00, 0.05)]
    points = np.array([eye_mid + across * x * eye_width + down * y * length
                       for x, y in outline], np.float32)
    mask = np.zeros((size, size), np.uint8)
    cv2.fillConvexPoly(mask, np.rint(points).astype(np.int32), 1)
    distance = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    feather = max(size * 0.06, 1.0)
    alpha = np.clip(distance / feather, 0.0, 1.0)
    return alpha * alpha * (3.0 - 2.0 * alpha)


def match_colour(swapped_rgb, reference_rgb, mask):
    """Match palette gently, bounding contrast changes to preserve facial detail."""
    region = mask > 0.8
    if region.sum() < 100:
        return swapped_rgb
    source = cv2.cvtColor(swapped_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    target = cv2.cvtColor(reference_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    result = source.copy()
    for channel, strength in enumerate((0.35, 0.65, 0.65)):
        source_values = source[..., channel][region]
        target_values = target[..., channel][region]
        scale = np.clip(target_values.std() / max(float(source_values.std()), 1.0), 0.8, 1.2)
        matched = (source[..., channel] - source_values.mean()) * scale + target_values.mean()
        result[..., channel] += strength * (matched - source[..., channel])
    return cv2.cvtColor(np.clip(result, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)


def composite_face(face_rgb, target_rgb, mask, strength):
    """Blend low-frequency lighting broadly and high-frequency face details narrowly."""
    strength = float(strength)
    if not np.isfinite(strength):
        raise ValueError('Face blend strength must be finite')
    strength = np.clip(strength, 0.0, 1.0)
    if strength == 0:
        return target_rgb.copy()
    # Crop around the projected mask to avoid pyramids over the full portrait.
    ys, xs = np.nonzero(mask > 0)
    if not len(xs):
        return target_rgb.copy()
    margin = 32
    h, w = mask.shape
    x0, x1 = max(0, xs.min() - margin), min(w, xs.max() + margin + 1)
    y0, y1 = max(0, ys.min() - margin), min(h, ys.max() + margin + 1)
    face = face_rgb[y0:y1, x0:x1].astype(np.float32)
    target = target_rgb[y0:y1, x0:x1].astype(np.float32)
    alpha = (mask[y0:y1, x0:x1] * strength)[..., None]
    # Keep identity detail intact inside the mask while smoothing illumination at the seam.
    face_low = cv2.GaussianBlur(face, (0, 0), 4.0)
    target_low = cv2.GaussianBlur(target, (0, 0), 4.0)
    broad_alpha = cv2.GaussianBlur(alpha[..., 0], (0, 0), 4.0)[..., None]
    blended = (face_low * broad_alpha + target_low * (1 - broad_alpha)
               + (face - face_low) * alpha + (target - target_low) * (1 - alpha))
    result = target_rgb.copy()
    result[y0:y1, x0:x1] = np.clip(blended, 0, 255).astype(np.uint8)
    return result
