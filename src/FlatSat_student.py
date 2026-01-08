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
from adafruit_lsm6ds.lsm6dsox import LSM6DSOX as LSM6DS
from adafruit_lis3mdl import LIS3MDL
from git import Repo
from picamera2 import Picamera2

#VARIABLES
THRESHOLD = 3      #Any desired value from the accelerometer
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


def take_photo(delay_sec: float = 7, reading_delay_sec: float = 0.4):
    """
    Takes a photo when the FlatSat is shaken above magnitude THRESHOLD.
    
    :param delay_sec: Delay in seconds before taking the photo after shake is detected.
    :type delay_sec: float
    :param reading_delay_sec: Delay in seconds between accelerometer readings.
    :type reading_delay_sec: float
    """
    name = "KaranK"
    filename = img_gen(name)

    while True:
        accelx_1, accely_1, accelz_1 = accel_gyro.acceleration
        time.sleep(reading_delay_sec) # Small delay to get a second reading
        accelx_2, accely_2, accelz_2 = accel_gyro.acceleration

        # Calculate the magnitude of the shake (don't use acceleration directly to avoid gravity readings)
        if math.sqrt((accelx_1 - accelx_2) ** 2 + (accely_1 - accely_2) ** 2 + (accelz_1 - accelz_2) ** 2) > THRESHOLD:
            time.sleep(delay_sec)
            
            try:
                picam2.capture_file(filename) # Capture an image after a delay and save it as a JPG.
            except Exception as e:
                print("Error capturing image: ", e)
            print("Photo taken")
            git_push()




def main():
    take_photo()


if __name__ == '__main__':
    main()