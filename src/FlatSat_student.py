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

#AUTHOR: 
#DATE:

#import libraries
import math
import os
import time
import board
from adafruit_lsm6ds.lsm6dsox import LSM6DSOX as LSM6DS
from adafruit_lis3mdl import LIS3MDL
from git import Repo
from picamera2 import Picamera2

#VARIABLES
THRESHOLD = -1      #Any desired value from the accelerometer
REPO_PATH = "/home/pi/BWSI-CubeSat"     #Your github repo path: ex. /home/pi/FlatSatChallenge
FOLDER_PATH = "images"   #Your image folder path in your GitHub repo: ex. /Images

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
    except:
        print('Couldn\'t upload to git')


def img_gen(name):
    """
    This function is complete. Generates a new image name.

    Parameters:
        name (str): your name ex. MasonM
    """
    t = time.strftime("_%H%M%S")
    imgname = (f'{REPO_PATH}/{FOLDER_PATH}/{name}{t}.jpg')
    print(f'Image name: {imgname}')
    return imgname


def take_photo(delay_sec: float = 3):
    """
    Takes a photo when the FlatSat is shaken above magnitude THRESHOLD.
    
    :param delay_sec: Description
    :type delay_sec: float
    """
    #while True:
    accelx, accely, accelz = accel_gyro.acceleration

    if math.sqrt(accelx ** 2 + accely ** 2 + accelz ** 2) > THRESHOLD: # If the magnitude of the shake is above a given value
        time.sleep(delay_sec)
        name = "KaranK"
        print("line 87")
        if not os.path.exists(img_gen(name)):
            try:
                os.makedirs(img_gen(name)) # Make the images directory if it doesn't exist
            except OSError:
                print("Creation of the directory failed")
        image = picam2.capture_file("test.jpg") # Capture an image after a delay and save it as a JPG.
        print("line 94")
        print(image)

        print("Photo taken!")
        git_push()
        print("Photo uploaded to GitHub!")



def main():
    take_photo()
    print(accel_gyro.acceleration)


if __name__ == '__main__':
    main()