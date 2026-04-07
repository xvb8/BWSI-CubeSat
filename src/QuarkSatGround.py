import queue

import cv2
import numpy as np
from concurrent.futures import ThreadPoolExecutor

import threading

inlier_src = None
inlier_dst = None
sift_done_event = threading.Event()
warp_done_event = threading.Event()
histogram_done_event = threading.Event()
initial_homography = None
refined_homography = None
cached_warped_img = None
cached_target_img = None
cached_histmatched_img = None
cached_histtarget_img = None

state_machine = "initial"

# --- Pub/sub for state changes (used by SSE endpoint) ---
_state_subscribers = []
_state_sub_lock = threading.Lock()

def subscribe_state():
    q = queue.Queue()
    with _state_sub_lock:
        _state_subscribers.append(q)
    return q

def unsubscribe_state(q):
    with _state_sub_lock:
        try:
            _state_subscribers.remove(q)
        except ValueError:
            pass

def _notify(msg):
    with _state_sub_lock:
        for q in list(_state_subscribers):
            q.put(msg)

def set_state(new_state):
    global state_machine
    state_machine = new_state
    _notify(new_state)

cv2.setNumThreads(0)  # 0 = use all available cores for OpenCV's internal parallelism

_HAS_XIMGPROC = hasattr(cv2, 'ximgproc')

def _smooth(img):
    if _HAS_XIMGPROC:
        return cv2.ximgproc.guidedFilter(img, img, 4, 750)
    return cv2.bilateralFilter(img, d=9, sigmaColor=75, sigmaSpace=75)

THRESHOLD = 30
KP_EXCLUDE_RADIUS = 0
MIN_COMPONENT_AREA = 500

def convert_to_grayscale(image):
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return grey

def refine_alignment(warped_img1, img2, mask, num_levels=3):
    gray1 = cv2.cvtColor(warped_img1, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY).astype(np.float32)

    # Start from identity; warped_img1 is already roughly aligned
    H_refined = np.eye(3, 3, dtype=np.float32)

    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 200, 1e-5)

    gray1_pyr = [gray1]
    gray2_pyr = [gray2]
    mask_pyr  = [mask]
    for _ in range(num_levels - 1):
        gray1_pyr.insert(0, cv2.pyrDown(gray1_pyr[0]))
        gray2_pyr.insert(0, cv2.pyrDown(gray2_pyr[0]))
        m = cv2.pyrDown(mask_pyr[0])
        m = (m > 127).astype(np.uint8) * 255  # keep mask binary
        mask_pyr.insert(0, m)

     # Refine from coarsest to finest level
    for level, (g1, g2, m) in enumerate(zip(gray1_pyr, gray2_pyr, mask_pyr)):

        # Properly scale the homography for this pyramid level
        scale = 2 ** (num_levels - 1 - level)
        S = np.array([[1.0/scale, 0, 0], [0, 1.0/scale, 0], [0, 0, 1]], dtype=np.float32)
        S_inv = np.array([[scale, 0, 0], [0, scale, 0], [0, 0, 1]], dtype=np.float32)
        H_scaled = S @ H_refined @ S_inv
        try:
            _, H = cv2.findTransformECC(
                g2, g1,
                H_scaled,
                cv2.MOTION_HOMOGRAPHY,
                criteria,
                m
            )

            # Scale back to full resolution
            H_refined = S_inv @ H @ S

        except cv2.error:
            print("[WARN] ECC did not converge — using unrefined warp")
            continue


    h, w = img2.shape[:2]
    refined_warp = cv2.warpPerspective(warped_img1, H_refined, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    return refined_warp, H_refined

def compute_homography(src_pts, dst_pts, reproj_threshold=2.0):
    if len(src_pts) < 4:  # Homography requires at least 4 point correspondences
        raise ValueError(f"Not enough matches to compute homography: {len(src_pts)} found, 4 required")

    # Reshape to the format OpenCV expects: (N, 1, 2)
    src_pts = src_pts.reshape(-1, 1, 2)
    dst_pts = dst_pts.reshape(-1, 1, 2)

    # RANSAC filters out outlier matches while estimating the homography matrix
    H, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, reproj_threshold)

    if H is None:
        raise ValueError("Homography could not be computed; insufficient or degenerate matches")

    inliers = mask.ravel().tolist()
    inlier_count = sum(inliers)

    return H, mask, inlier_count

def sift_features(img1, img2):
    print("Converting images to grayscale...")
    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(convert_to_grayscale, img1)
        f2 = pool.submit(convert_to_grayscale, img2)
        gray1 = f1.result()
        gray2 = f2.result()

    # Downscale for SIFT — process 4x fewer pixels; SIFT is scale-invariant
    scale_factor = 0.5
    gray1_small = cv2.resize(gray1, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_AREA)
    gray2_small = cv2.resize(gray2, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_AREA)

    print("Creating SIFT detector...")
    sift = cv2.SIFT_create(nfeatures=5000)
    print("Detecting keypoints and computing descriptors (parallel)...")
    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(sift.detectAndCompute, gray1_small, None)
        f2 = pool.submit(sift.detectAndCompute, gray2_small, None)
        kp1, des1 = f1.result()
        kp2, des2 = f2.result()

    if des1 is None or des2 is None:
        raise ValueError("SIFT could not find descriptors in one of the images")

    print("Creating FLANN params...")
    flann_params = dict(algorithm=1, trees=5) # FLANN settings
    print("Creating search params...")
    search_params = dict(checks=50) # Number of checks for FLANN (higher is more accurate but slower)
    print("Creating FLANN matcher...")
    flann = cv2.FlannBasedMatcher(flann_params, search_params)
    print("Matching descriptors with FLANN...")
    matches = flann.knnMatch(des1, des2, k=2)

    # Compare "distance"/difference between the best and second-best matches to filter out good matches

    print("Filtering good matches...")
    good_matches = []
    for m, n in matches:
        if m.distance < 0.5 * n.distance:
            good_matches.append(m)

    # Extract matched keypoints and scale back to full resolution
    print("Extracting matched keypoints...")
    inv_scale = 1.0 / scale_factor
    src_pts = np.float32([kp1[m.queryIdx].pt for m in good_matches]) * inv_scale
    dst_pts = np.float32([kp2[m.trainIdx].pt for m in good_matches]) * inv_scale

    print("Computing homography with RANSAC...")
    set_state("compute_homography_matrix")
    H, ransac_mask, inlier_count = compute_homography(src_pts, dst_pts)
    global initial_homography
    initial_homography = H

    inlier_mask = ransac_mask.ravel().astype(bool)
    global inlier_src, inlier_dst
    inlier_src = src_pts[inlier_mask]  # keypoint locations in img1
    inlier_dst = dst_pts[inlier_mask]  # corresponding locations in img2
    
    set_state("sift_done_start_homography")
    sift_done_event.set()

    print(f"Homography matrix:\n{H}")
    print(f"Inliers: {inlier_count} / {len(good_matches)}")

    # Warp img1 into the perspective of img2
    print("Warping image 1 to align with image 2...")
    h, w = img2.shape[:2]
    warped_img1 = cv2.warpPerspective(img1, H, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    return (warped_img1, H, inlier_src, inlier_dst)

from shapely.geometry import Polygon

def match_histograms(source, target, mask):
    """
    Per-channel histogram matching of source to target within the masked region.
    Adjusts the brightness/color of source so its distribution matches target
    where mask is nonzero, compensating for exposure or white-balance differences.
    """
    result = source.copy()
    for c in range(source.shape[2]):
        src_vals = source[mask != 0, c].astype(np.float32)
        tgt_vals = target[mask != 0, c].astype(np.float32)
        if len(src_vals) == 0 or len(tgt_vals) == 0:
            continue
        src_mean, src_std = src_vals.mean(), src_vals.std()
        tgt_mean, tgt_std = tgt_vals.mean(), tgt_vals.std()
        if src_std < 1e-6:
            continue
        adjusted = (source[:, :, c].astype(np.float32) - src_mean) * (tgt_std / src_std) + tgt_mean
        result[:, :, c] = np.clip(adjusted, 0, 255).astype(np.uint8)
    return result

def get_warp_polygon(img1, H, img2_shape):
    h1, w1 = img1.shape[:2]
    h2, w2 = img2_shape[:2]

    # The 4 corners of img1 warped into img2's space
    corners = np.float32([[0,0], [w1,0], [w1,h1], [0,h1]]).reshape(-1,1,2)
    warped_corners = cv2.perspectiveTransform(corners, H).reshape(-1,2)

    # img2's bounding rectangle
    img2_rect = Polygon([(0,0), (w2,0), (w2,h2), (0,h2)])

    # img1's warped footprint
    img1_poly = Polygon(warped_corners)

    # True intersection — corners outside img2 are removed, not moved
    intersection = img2_rect.intersection(img1_poly)

    if intersection.is_empty:
        return np.zeros((h2, w2), dtype=np.uint8)

    # Draw the intersection polygon as a mask
    pts = np.array(intersection.exterior.coords, dtype=np.int32)
    polygon_mask = np.zeros((h2, w2), dtype=np.uint8)
    cv2.fillConvexPoly(polygon_mask, pts, 255)
    kernel = np.ones((3,3), np.uint8)
    polygon_mask = cv2.erode(polygon_mask, kernel, iterations=30) # Erode to remove border artifacts from warping interpolation

    return polygon_mask

def compare_images(img1, img2, intersection_mask, inlier_pts):
    global state_machine
    # # Create a mask of ones (valid pixels) and warp it the same way H warps img1
    # h, w = img2.shape[:2]
    # canvas = np.ones((img1.shape[0], img1.shape[1]), dtype=np.uint8) * 255
    # cv2.imwrite('src/canv.png', canvas)
    # mask_img1 = cv2.warpPerspective(
    # canvas, homography, (w, h),
    # flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT  # hard edge, no interpolation bleed
    # )

    # mask_img2 = np.ones((h, w), dtype=np.uint8) * 255  # 255 everywhere (all valid)
    # print(mask_img1.shape)\

    # intersection_mask = cv2.bitwise_and(mask_img1, mask_img2)

    # cv2.imwrite('src/int_mask.png', intersection_mask)
    # cv2.imwrite('src/1mask.png', mask_img1)
    # cv2.imwrite('src/2mask.png', mask_img2)

    # Do keypoint exclusion: create a mask that excludes a small radius around each inlier keypoint, to avoid false positives from small misalignments around those points
    kp_exclusion = np.ones(img2.shape[:2], dtype=np.uint8) * 255
    for pt in inlier_pts:
        x, y = int(pt[0]), int(pt[1])
        cv2.circle(kp_exclusion, (x, y), radius=KP_EXCLUDE_RADIUS, color=0, thickness=-1)

    # Edge-preserving smoothing (guidedFilter if available, else bilateralFilter)
    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_smooth, img1)
        f2 = pool.submit(_smooth, img2)
        img1_blur = f1.result()
        img2_blur = f2.result()
    difference = cv2.absdiff(img1_blur, img2_blur)

    # Zero out the difference in black/invalid regions
    difference[intersection_mask == 0] = 0
    difference[difference <= THRESHOLD] = 0
    diff_mask_df = np.any(difference != 0, axis=2)
    difference[kp_exclusion == 0] = 0
    diff_mask = np.any(difference != 0, axis=2)

    # Morphological opening to remove small noise speckles (JPEG artifacts, interpolation noise)
    morph_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    diff_mask_u8 = diff_mask.astype(np.uint8) * 255
    diff_mask_u8 = cv2.morphologyEx(diff_mask_u8, cv2.MORPH_OPEN, morph_kernel, iterations=2)

    # Remove small connected components below MIN_AREA (vectorized)
    nlabels, labels, stats, _ = cv2.connectedComponentsWithStats(diff_mask_u8, connectivity=8)
    small = np.where(stats[1:, cv2.CC_STAT_AREA] < MIN_COMPONENT_AREA)[0] + 1
    if len(small) > 0:
        diff_mask_u8[np.isin(labels, small)] = 0

    diff_mask = diff_mask_u8 > 0

    if not diff_mask.any():
        print("no new pixels detected")
    else:
        print ("new pixels detected")
        number_of_pixels = np.count_nonzero(diff_mask)
        print(f"Number of new pixels detected: {number_of_pixels}")

    # Build a visualisation: show intersection with differences highlighted red
    vis = img2.copy()  # start with img2 as the base

    # Grey out everything outside the intersection
    vis[intersection_mask == 0] = [50, 50, 50]

    # Paint those pixels red
    vis[diff_mask] = [0, 0, 255]  # BGR — red in OpenCV

    # Paint inlier keypoints green
    for pt in inlier_pts:
        x, y = int(pt[0]), int(pt[1])
        if diff_mask_df[y, x]:  # If this keypoint is in a different pixel, paint it yellow instead of green
            cv2.circle(vis, (x, y), radius=KP_EXCLUDE_RADIUS, color=(0, 255, 255), thickness=-1)  # yellow
        else:
            cv2.circle(vis, (x, y), radius=KP_EXCLUDE_RADIUS, color=(0, 255, 0), thickness=-1)

    return vis

# with open('image1.arr' , 'rb') as f:
#     img1 = np.load(f)
# with open('image2.arr' , 'rb') as f:
#     img2 = np.load(f)

def return_keypoint_map(img1, img2):
    """
    Draw green circles on copies of the original images at each inlier keypoint location.
    """
    keypoint_map_1 = img1.copy()
    keypoint_map_2 = img2.copy()
    if inlier_dst is None or inlier_src is None:
        return None

    for pt in inlier_dst:
        x, y = int(pt[0]), int(pt[1])
        cv2.circle(keypoint_map_1, (x, y), radius=10, color=(0, 255, 0), thickness=-1)
    for pt in inlier_src:
        x, y = int(pt[0]), int(pt[1])
        cv2.circle(keypoint_map_2, (x, y), radius=10, color=(0, 255, 0), thickness=-1)
    return (keypoint_map_1, keypoint_map_2)

def main(img1, img2):
    set_state("loading_start")
    warped_img1, homography, _, dst_points = sift_features(img1, img2)
    intersection_mask = get_warp_polygon(img1, homography, img2.shape)

    set_state("refining_alignment")
    _, homography_refined = refine_alignment(warped_img1, img2, intersection_mask)
    H_total = homography_refined @ homography
    global refined_homography
    refined_homography = H_total
    h, w = img2.shape[:2]
    set_state("warping_image")
    warped_img1 = cv2.warpPerspective(img1, H_total, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    polygon_mask = get_warp_polygon(img1, H_total, img2.shape)  # recompute with refined H

    global cached_warped_img, cached_target_img
    cached_warped_img = warped_img1.copy()
    cached_target_img = img2.copy()
    warp_done_event.set()

    # Normalize warped_img1 brightness/color to match img2 in the overlap region
    set_state("matching_histograms")
    warped_img1 = match_histograms(warped_img1, img2, polygon_mask)
    cv2.imwrite('src/warped_image1.png', warped_img1)

    global cached_histmatched_img, cached_histtarget_img
    cached_histmatched_img = warped_img1.copy()
    cached_histtarget_img = img2.copy()
    set_state("histogram_done")
    histogram_done_event.set()

    set_state("comparing_images")
    print("Comparing images...")
    return compare_images(warped_img1, img2, polygon_mask, dst_points)

if __name__ == "__main__":
    img1 = cv2.imread('src/image1.jpg')
    img2 = cv2.imread('src/image2.jpg')
    result = main(img1, img2)
    cv2.imwrite('src/diff_visualisation.png', result)
    print("Visualisation saved to src/diff_visualisation.png")
