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


def take_photo(save_file = True):
    """
    Takes a photo
    
    :param delay_sec: Delay in seconds before taking the photo after shake is detected.
    :type delay_sec: float
    :param reading_delay_sec: Delay in seconds between accelerometer readings.
    :type reading_delay_sec: float
    """
    name = "QuarkSat"
            
    img_arr = None
    try:
        img_arr = picam2.capture_array()
        if save_file:
            filename = img_gen(name)
            with open(f'{filename}.arr', 'wb') as f:
                np.save(f, img_arr)
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

TIME_FOR_AOE_CROSS = 19.7012366996

images1 = []
images2 = []
images3 = []

def main():
    # flag1 = True
    # flag2 = True
    # flag3 = True

    # while True:
    #     if mins > TIME_FOR_AOE_CROSS/2 + 4.5 and mins() < TIME_FOR_AOE_CROSS/2 + 4.5 + 0.3:
    #             flag1 = True
    #             flag2 = True
    #             flag3 = True
    #     if mins() >= 123.86 + (4.08/2 - TIME_FOR_AOE_CROSS) and mins() < 123.86 + (4.1/2 - TIME_FOR_AOE_CROSS) and flag1:
    #         take_photo()
    #         flag1 = False
    #     if mins() >= 4.08/2 and mins() < 4.1/2 and flag2:
    #             take_photo()
    #             flag2 = False
    #             if mins() >= TIME_FOR_AOE_CROSS/2 + 4.08 and mins() < TIME_FOR_AOE_CROSS/2 + 4.1 and flag3:
    #                 take_photo()
    #                 flag3 = False
    images = []
    while True:
        if len(images) == 2: # Keep only the last two images for comparison
            cv2.imwrite('image1.png', images[0])
            cv2.imwrite('image2.png', images[1])
            while True:
                pass
        accelx_1, accely_1, accelz_1 = accel_gyro.acceleration
        time.sleep(7) # Small delay to get a second reading
        accelx_2, accely_2, accelz_2 = accel_gyro.acceleration

        # Calculate the magnitude of the shake (don't use acceleration directly to avoid gravity readings)
        if math.sqrt((accelx_1 - accelx_2) ** 2 + (accely_1 - accely_2) ** 2 + (accelz_1 - accelz_2) ** 2) > 4:
            time.sleep(7)
            
            try:
                images.append(picam2.capture_array()) # Capture an image after a delay and save it as a JPG.
            except Exception as e:
                print("Error capturing image: ", e)
            print("Photo taken")
            git_push()




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
