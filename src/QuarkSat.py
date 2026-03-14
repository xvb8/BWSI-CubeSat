"""
The Python code you will write for this module should read
acceleration data from the IMU. When a reading comes in that surpasses
an acceleration threshold (indicating a shake), your Pi should pause,
trigger the camera to take a picture, then save the image with a
descriptive filename. You may use GitHub to upload your images automatically,
but for this activity it is not required.

The provided functions are only for reference, you do not need to use them. 
You will need to complete the take_photo() function and configure the VARIABLES section
"""

#AUTHOR: Karan Krishnan
#DATE: 1/7/2026

#import libraries
import math
import time
import board
import zipfile
import cv2
import numpy as np
from adafruit_lsm6ds.lsm6dsox import LSM6DSOX as LSM6DS
from adafruit_lis3mdl import LIS3MDL
from git import Repo
from picamera2 import Picamera2

#VARIABLES    #Any desired value from the accelerometer
REPO_PATH = "/home/pi/BWSI-CubeSat"     #Your github repo path: ex. /home/pi/FlatSatChallenge
FOLDER_PATH = "/images"   #Your image folder path in your GitHub repo: ex. /Images

#imu and camera initialization
i2c = board.I2C()
accel_gyro = LSM6DS(i2c)
mag = LIS3MDL(i2c)
picam2 = Picamera2()
picam2.options["quality"] = 90
picam2.options["compress_level"] = 3
config = picam2.create_still_configuration()
picam2.configure(config)
picam2.start()

def git_push():
    """
    This function is complete. Stages, commits, and pushes new images to your GitHub repo.
    """
    try:
        repo = Repo(REPO_PATH)
        origin = repo.remote('origin')
        print('added remote')
        origin.pull()
        print('pulled changes')
        repo.git.add(REPO_PATH + FOLDER_PATH)
        repo.index.commit('New Photo')
        print('made the commit')
        origin.push()
        print('pushed changes')
    except Exception as e:
        print(e)
        print('Couldn\'t upload to git')


def img_gen(name):
    """
    This function is complete. Generates a new image name.

    Parameters:
        name (str): your name ex. MasonM
    """
    t = time.strftime("_%H%M%S")
    imgname = (f'{REPO_PATH}/{FOLDER_PATH}/{name}{t}.jpg')
    return imgname


def take_photo():
    """
    Takes a photo
    
    :param delay_sec: Delay in seconds before taking the photo after shake is detected.
    :type delay_sec: float
    :param reading_delay_sec: Delay in seconds between accelerometer readings.
    :type reading_delay_sec: float
    """
    name = "QuarkSat"
    filename = img_gen(name)
            
    img_arr = None
    try:
        img_arr = picam2.capture_array(filename)
        print("Photo taken")
    except Exception as e:
        print("Error capturing image: ", e)
    return img_arr

def compress_directly(data):
    with zipfile.ZipFile('QuarkSat_compressed_data.zip', 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('data.txt', data)

def compress_file(input_file):
    with zipfile.ZipFile('QuarkSat_compressed_file.zip', 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(input_file, arcname='data.txt')

def convert_to_grayscale(image):
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return grey

def sift_features(img1, img2):
    gray1 =  convert_to_grayscale(img1) # Convert the images to grayscale for SIFT
    gray2 = convert_to_grayscale(img2)
    sift = cv2.SIFT_create()
    kp1, des1 = sift.detectAndCompute(gray1, None) # Keypoint detection and descriptor computation
    kp2, des2 = sift.detectAndCompute(gray2, None)
    flann_params = dict(algorithm=1, trees=5) # FLANN settings
    search_params = dict(checks=50) # Number of checks for FLANN (higher is more accurate but slower)
    flann = cv2.FlannBasedMatcher(flann_params, search_params)
    matches = flann.knnMatch(des1, des2, k=2)

    # Extract the matched keypoints and their corresponding descriptors
    src_pts = np.float32([kp1[m.queryIdx].pt for m in good_matches])  # 1st image keypoints
    dst_pts = np.float32([kp2[m.trainIdx].pt for m in good_matches]) # 2nd image keypoints

    # Compare "distance"/difference between the best and second-best matches to filter out good matches
    good_matches = []
    for m, n in matches:
        if m.distance < 0.7 * n.distance:
            good_matches.append(m)

TIME_FOR_AOE_CROSS = 19.7012366996

def main():
    flag1 = True
    flag2 = True
    flag3 = True
    take_photo() # take photo at the start of the program

    if mins() >= 123.86 + (4.08/2 - TIME_FOR_AOE_CROSS) and mins() < 123.86 + (4.1/2 - TIME_FOR_AOE_CROSS) and flag1:
        take_photo()
        flag1 = False
        if mins() >= 4.08/2 and mins() < 4.1/2 and flag2:
            take_photo()
            flag2 = False
            if mins() >= TIME_FOR_AOE_CROSS/2 + 4.08 and mins() < TIME_FOR_AOE_CROSS/2 + 4.1 and flag3:
                take_photo()
                flag3 = False
def compare_images(img1, img2):
    difference = img1 - img2
    if np.all(difference==0):
        print("no new meteors detected")
    elif (difference !=0).any():
        print ("new meteors detected")
        differences_not_zero= difference[difference!=0]**0 
        number_of_meteors=np.sum(differences_not_zero)
        print(f"Number of new meteors detected: {number_of_meteors}")




# Define constants for state calculation
STATE_PERIOD_MINUTES = 123.86  # Duration of one cycle in minutes
ACTIVE_WINDOW_MINUTES = 4.08738  # Duration of active window in minutes

# Calculate state based on elapsed time and defined periods
def state():
    return "active" if (time.time() - start_time)/60 % STATE_PERIOD_MINUTES < ACTIVE_WINDOW_MINUTES else "inactive"
def mins():
    return ((time.time() - start_time)/60 % STATE_PERIOD_MINUTES)*100 # ten times speed for testing purposes

if __name__ == '__main__':
    start_time = time.time()
    main()
