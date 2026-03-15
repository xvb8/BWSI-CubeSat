import cv2
import numpy as np

def convert_to_grayscale(image):
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return grey

def refine_alignment(warped_img1, img2, mask, num_levels=3):
    gray1 = cv2.cvtColor(warped_img1, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY).astype(np.float32)

    # Start from identity; warped_img1 is already roughly aligned
    H_refined = np.eye(3, 3, dtype=np.float32)

    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 500, 1e-5)

    gray1_pyr = [gray1]
    gray2_pyr = [gray2]
    mask_pyr  = [mask]
    for _ in range(num_levels - 1):
        gray1_pyr.insert(0, cv2.pyrDown(gray1_pyr[0]))
        gray2_pyr.insert(0, cv2.pyrDown(gray2_pyr[0]))
        mask_pyr.insert(0, cv2.pyrDown(mask_pyr[0]))
     # Refine from coarsest to finest level
    for level, (g1, g2, m) in enumerate(zip(gray1_pyr, gray2_pyr, mask_pyr)):

        # Scale H for this pyramid level
        scale = 2 ** (num_levels - 1 - level)
        H_scaled = H_refined.copy()
        H_scaled[0, 2] /= scale
        H_scaled[1, 2] /= scale
        try:
            _, H_refined = cv2.findTransformECC(
                g2, g1,
                H_scaled,
                cv2.MOTION_HOMOGRAPHY,
                criteria,
                m
            )
        except cv2.error:
            print("[WARN] ECC did not converge — using unrefined warp")
            continue
            # Scale H back up for the next level
        H_refined = H_scaled.copy()
        H_refined[0, 2] *= scale
        H_refined[1, 2] *= scale

    h, w = img2.shape[:2]
    refined_warp = cv2.warpPerspective(warped_img1, H_refined, (w, h))
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
    gray1 = convert_to_grayscale(img1) # Convert the images to grayscale for SIFT
    gray2 = convert_to_grayscale(img2)
    print("Creating SIFT detector...")
    sift = cv2.SIFT_create() #nfeatures=0, contrastThreshold=0.03, edgeThreshold=20
    print("Detecting keypoints and computing descriptors (1/2)...")
    kp1, des1 = sift.detectAndCompute(gray1, None) # Keypoint detection and descriptor computation
    print("Detecting keypoints and computing descriptors (2/2)...")
    kp2, des2 = sift.detectAndCompute(gray2, None)

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

    # Extract the matched keypoints and their corresponding descriptors
    print("Extracting matched (src) keypoints...")
    src_pts = np.float32([kp1[m.queryIdx].pt for m in good_matches])  # 1st image keypoints
    print("Extracting matched (dst) keypoints...")
    dst_pts = np.float32([kp2[m.trainIdx].pt for m in good_matches]) # 2nd image keypoints


    print("Computing homography with RANSAC...")
    H, mask, inlier_count = compute_homography(src_pts, dst_pts)

    print(f"Homography matrix:\n{H}")
    print(f"Inliers: {inlier_count} / {len(good_matches)}")

    # Warp img1 into the perspective of img2
    print("Warping image 1 to align with image 2...")
    h, w = img2.shape[:2]
    warped_img1 = cv2.warpPerspective(img1, H, (w, h))
    return (warped_img1, H)

from shapely.geometry import Polygon

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
    polygon_mask = cv2.erode(polygon_mask, kernel, iterations=1) # Erode to remove edge pixels that might be noisy

    return polygon_mask

def compare_images(img1, img2, intersection_mask):

    # # Create a mask of ones (valid pixels) and warp it the same way H warps img1
    # h, w = img2.shape[:2]
    # canvas = np.ones((img1.shape[0], img1.shape[1]), dtype=np.uint8) * 255
    # cv2.imwrite('src/canv.png', canvas)
    # mask_img1 = cv2.warpPerspective(
    # canvas, homography, (w, h),
    # flags=cv2.INTER_NEAREST  # hard edge, no interpolation bleed
    # )

    # mask_img2 = np.ones((h, w), dtype=np.uint8) * 255  # 255 everywhere (all valid)
    # print(mask_img1.shape)\

    # intersection_mask = cv2.bitwise_and(mask_img1, mask_img2)

    cv2.imwrite('src/int_mask.png', intersection_mask)
    # cv2.imwrite('src/1mask.png', mask_img1)
    # cv2.imwrite('src/2mask.png', mask_img2)

    difference = cv2.absdiff(img1, img2)

    # Zero out the difference in black/invalid regions
    difference[intersection_mask == 0] = 0

    difference[difference <= THRESHOLD] = 0
    diff_mask = np.any(difference != 0, axis=2)

    # diff_gray = cv2.cvtColor(difference, cv2.COLOR_BGR2GRAY)
    # adaptive = cv2.adaptiveThreshold(diff_gray, 255,
    #     cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
    #     cv2.THRESH_BINARY,
    #     blockSize=51,
    #     C=-20)
    # diff_mask = adaptive.astype(bool)

    if not diff_mask.any():
        print("no new pixels detected")
    else:
        print ("new pixels detected")
        differences_not_zero = difference[difference!=0]**0 
        number_of_pixels=np.sum(differences_not_zero)
        print(f"Number of new pixels detected: {number_of_pixels}")

    # Build a visualisation: show intersection with differences highlighted red
    vis = img2.copy()  # start with img2 as the base

    # Grey out everything outside the intersection
    vis[intersection_mask == 0] = [50, 50, 50]

    # Find pixels that are different within the intersection
    diff_mask = np.any(difference != 0, axis=2)  # (H, W) bool — True where any channel differs

    # Paint those pixels red
    vis[diff_mask] = [0, 0, 255]  # BGR — red in OpenCV

    cv2.imwrite('src/diff_visualisation.png', vis)
    print("Visualisation saved to src/diff_visualisation.png")

# with open('image1.arr' , 'rb') as f:
#     img1 = np.load(f)
# with open('image2.arr' , 'rb') as f:
#     img2 = np.load(f)

THRESHOLD = 30

img1 = cv2.imread('src/image1.png')
img2 = cv2.imread('src/image2.png')

warped_img1, homography = sift_features(img1, img2)
intersection_mask = get_warp_polygon(img1, homography, img2.shape)
warped_img1, homography_refined = refine_alignment(warped_img1, img2, intersection_mask)
H_total = homography_refined @ homography
polygon_mask = get_warp_polygon(img1, H_total, img2.shape)  # recompute with refined H
cv2.imwrite('src/warped_image1.png', warped_img1)


print("Comparing images...")
compare_images(warped_img1, img2, polygon_mask)


