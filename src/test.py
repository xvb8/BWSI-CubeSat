import numpy as np
import cv2

import os
import numpy as np
import cv2

img_path1 = r"C:\\Users\\karya\\BWSI-CubeSat\\src\\img1.png"
img_path2 = r"C:\\Users\\karya\\BWSI-CubeSat\\src\\img2.png"

print("exists1", os.path.exists(img_path1))
print("exists2", os.path.exists(img_path2))

img1 = cv2.imread(img_path1)
img2 = cv2.imread(img_path2)

# if img1 is None or img2 is None:
#     raise FileNotFoundError("One or both images could not be loaded; check the file paths.")

def compare_images(img1, img2):
    difference = img1 - img2
    if np.all(difference==0):
        print("no new meteors detected")
    elif (difference !=0).any():
        print ("new meteors detected")
        differences_not_zero= difference[difference!=0]**0 
        number_of_meteors=np.sum(differences_not_zero)
        print(f"Number of new meteors detected: {number_of_meteors}")

compare_images(img1, img2)