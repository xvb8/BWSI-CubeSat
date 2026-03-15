import cv2
import numpy as np

def convert_to_grayscale(image):
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return grey

def compute_homography(src_pts, dst_pts, reproj_threshold=5.0):
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
    sift = cv2.SIFT_create()
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
        if m.distance < 0.7 * n.distance:
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

def compare_images(img1, img2, homography):

    # Create a mask of ones (valid pixels) and warp it the same way H warps img1
    h, w = img2.shape[:2]
    canvas = np.ones((img1.shape[0], img1.shape[1]), dtype=np.uint8) * 255
    mask_img1 = cv2.warpPerspective(canvas, homography, (w, h))  # 0 where blackspace is
    mask_img2 = np.ones((h, w), dtype=np.uint8) * 255  # 255 everywhere (all valid)
    print(mask_img1.shape)
    intersection_mask = cv2.bitwise_and(mask_img1, mask_img2)

    difference = cv2.absdiff(img1, img2)

    # Zero out the difference in black/invalid regions
    difference[intersection_mask == 0] = 0

    

    if np.all(difference==0):
        print("no new pixels detected")
    elif (difference !=0).any():
        print ("new pixels detected")
        differences_not_zero= difference[difference!=0]**0 
        number_of_pixels=np.sum(differences_not_zero)
        print(f"Number of new pixels detected: {number_of_pixels}")

# with open('image1.arr' , 'rb') as f:
#     img1 = np.load(f)
# with open('image2.arr' , 'rb') as f:
#     img2 = np.load(f)

img1 = cv2.imread('src/image1.png')
img2 = cv2.imread('src/image2.png')

warped_img1, homography = sift_features(img1, img2)
cv2.imwrite('src/warped_image1.png', warped_img1)

print("Comparing images...")
compare_images(warped_img1, img2, homography)


