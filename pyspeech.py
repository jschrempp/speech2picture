"""
This program generates photos from random audio conversations and displays 
them on the screen. When run on command, it is an interesting exercise in the power of OpenAI.
When run in continuous mode, it is a creepy photo generator because it shows how good openAI is 
at understanding what you are saying.

There is a step that is now commented out that summarizes the transcript. The summary is 
errily accurate.

Basic flow:
    * record audio from the default microphone and then transcribe it using OpenAI
    * summarize the transcript and generate 4 pictures based on the summary
    * combine the four images into a single image
    * open the picture in a browser
    * optionally, delay for 60 seconds and repeat the process
    * images are stored in the history directory

The program can be run in two modes:
    
1/  python3 pyspeech.py
    This will display a menu and prompt you for a command. 
2/  python3 pyspeech.py -h
    For testing. Use command line arguments  

control-c to stop the program. When run in auto mode it will loop 10 times

For debug output, use the -d 2 argument. This will show the prompts and responses to/from OpenAI.

To run this you need to get an OpenAI API key and put it in a file called "creepy photo secret key".
OpenAI currently costs a few pennies to use. I've run this for an hour at a cost of $1.00. It was
well worth it.

If you want to use the -q option, which stores the completed pictures in the AWS S3 cloud and displays 
QR code to allow instant download, you will need to create an Amazon AWS account and create an S3 bucket, 
and a couple of other things.  More complete instructions are in the file names s3_and_qr_readme.txt


ALSO NOTE: If you are not getting any audio, then you may not have given the program
permission to access your microphone. On OSX it took me some searching to figure this out.
https://superuser.com/questions/1441270/apps-dont-show-up-in-camera-and-microphone-privacy-settings-in-macbook
Until the Terminal app showed up in Settings / Privacy & Security / Microphone this program
just wont work. 
On the RPi I had to add my user to the "audio" group. I did this
with      usermod -a -G audio <username>

Based on the WhisperFrame project idea on Hackaday.
https://hackaday.com/2023/09/22/whisperframe-depicts-the-art-of-conversation/

Specific to Raspberry Pi:
    -1. Make sure your RPi is up on the latest release.
        sudo apt update
        sudo apt-get full-upgrade 

    0. clone repo
       git clone https://github.com/jschrempp/speech2picture.git speech2picture

    1. set up a virtual environment and activate it (to deactive use "deactivate")
        cd speech2picture
        python3 -m venv --system-site-packages .venv
        source .venv/bin/activate

        set your openai key
            https://help.openai.com/en/articles/5112595-best-practices-for-api-key-safety

            nano ~/.bashrc and comment out these lines
                # If not running interactively, don't do anything
                case $- in
                    *i*) ;;
                    *) return;;
                esac

            Then add this line
                export OPENAI_API_KEY='yourkey'

            Check your work
                source ~/.bashrc
                echo $OPENAI_API_KEY

    2. install the following packages

        2a. for RPi version 3 install these
            sudo apt-get install portaudio19-dev
            sudo apt install python3-pyqt6
            On the 2023-10-10 64 bit Raspbian OS you don't need to install these
            #sudo apt-get install libasound2-dev
            #sudo apt-get install libatlas-base-dev
            #sudo apt-get install libopenblas-dev

            cp s2p.desktop ~/Desktop

            then to get it to auto start on boot, do either
            sudo cp ~/Desktop/s2p.desktop /usr/share/xsessions/s2p.desktop

            OR if you on an a version older than Raspbian Debian GNU/Linux 12 (bookworm) try
            (but you might have issues later). I really suggest the latest Raspbian OS.

            cd ..
            mkdir .config/lxsession
            mkdir .config/lxsession/LXDE-pi
            mkdir .config/lxsession/LXDE-pi/autostart
            cp Desktop/s2p.desktop .config/lxsession/LXDE-pi/autostart/s2p.desktop


        2b. on MacOS install these
            brew install portaudio
            brew update-reset   # if your brew isn't working try this
            xcode-select --install  # needed for pyaudio to install
            pip3 install sounddevice
            pip3 install soundfile
            pip3 install numpy

            Use finder and navigate to /Applications/Python 3.12
                  Then doublelick on "Install Certificates.command"

                    
    3. install the following python packages (be sure you are in the virtual environment)   
        pip install -r requirements.txt

        NOTE: On Raspberry Pi, PyQt6 is installed via apt (step 2a above), not pip.
        The venv must be created with --system-site-packages (step 1 above) to see it.

    Note that when run you will see 10 or so lines of errors about sockets and JACKD and whatnot.
    Don't worry, it is still working. If you know how to fix this, please let me know.

    Also note that errors from the audio subsystem are ignored in recordAudioFromMicrophone(). If 
    you are having some real audio issue, you might change the error handler to print the errors.

    If you want to make this run on boot, then see the comments in s2p.desktop
    
Author: Jim Schrempp 2023 

Version History of significant changes:

v 0.8 added "without any text or writing in the image" to the image prompt
v 0.7 more code cleanup, improved image resizing for display size
      added QR code
v 0.6 added -g for gokiosk mode
v 0.5 Initial version
v 0.6 2023-11-12 inverted Go Button logic so it is active low (pulled to ground)
v 0.7 updated to python 3.12 and openAI 1.0.0 (wow that was a pain)
      BE SURE to read updated install instructions above
v 1.0 consolidated GUI into one window using Qt grid and a pop up to show the transcript
v 1.2 Added capability to store images created in the AWS S3 cloud and display a QR code to them for instant download
v 2.0 Added capability to generate 4 images at once, each with a different style modifier.
      Changed from gpt-image-1 to gpt-image-1.5
      Changed from using artist names to just stylistic descriptions to appease the openAI safety filters.
"""

# import common libraries
import platform
import argparse
import logging
from logging.handlers import TimedRotatingFileHandler
import urllib.request
import time
import datetime
import shutil
import re
import os
import socket
import select
import sys
import random
import json
import string
import base64
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from queue import Queue
from enum import IntEnum
from PIL import Image, ImageDraw, ImageFont
from s3_and_qr import upload_to_s3_and_generate_qr

from PyQt6 import QtWidgets, QtCore, QtGui

import openai

# Initialize global config
class Config:
    """Central configuration class to replace global variables.

    Thread safety: All attributes are written once at startup (main thread)
    and read-only thereafter.  The _lock is available for any future mutable
    state that needs cross-thread protection.
    """
    def __init__(self):
        self.isMacOS = False
        self.isRPi = False
        self.version = "2.0"
        self.useS3 = False
        self.kiosk_mode = False
        self.single_image = False
        self.isQuitting = False

        # Window references (only accessed from the main / Qt thread)
        self.windowMain = None
        self.windowForMessages = None
        self.windowForStatus = None

        # Lock for protecting any future mutable shared state
        self._lock = threading.Lock()

config = Config()

# Thread-safe queue for LED blink control (RPi only).
# Initialized to None so it always exists; the real Queue is created
# inside the RPi-specific block below.
qBlinkControl = None
led_thread1 = None

# Detect platform
if (platform.system() == "Darwin"):
    config.isMacOS = True
else:
    # Check if running on Raspberry Pi
    try:
        with open('/proc/device-tree/model', 'r') as f:
            model = f.read().lower()
            config.isRPi = 'raspberry pi' in model
    except:
        config.isRPi = False
    print(f"Running on {'Raspberry Pi' if config.isRPi else 'non-RPi Linux'}")

# import platform specific libraries
if config.isMacOS:
    import sounddevice
    import soundfile

elif config.isRPi:
    # --------- import for Raspberry Pi -----------------------------------------
    import pyaudio
    import wave
    from ctypes import *
    import RPi.GPIO as GPIO
else:
    print("WARNING: Unsupported platform - not macOS or Raspberry Pi")



# Global constants
LOOPS_MAX = 10 # Set the number of times to loop when in auto mode

# Prompt for abstraction
# PROMPT_FOR_ABSTRACTION = "What is the most interesting concept in the following text \
#   expressing the answer as a noun phrase, but not in a full sentence "
PROMPT_FOR_ABSTRACTION = "In 15 words or less, what are the most interesting concepts in the following text \
    expressing the answer as a noun phrase, but not in a full sentence "

# image prompt modifiers
# 'generate a picture [MODIFIER] for the following concept: ...'

IMAGE_MODIFIERS = [
    "as a painting in the style of cubism",
    "as a watercolor in the style of surrealism",
    "as a sketch in the style of surrealism",
    "as a vivid color painting in the style of impressionism",
    "as a painting in the style of the French Breakthrough",
    "as a painting in the style of Nuclear Mysticism",
    "in the style of mathematical graphic art",
    "in the style of the Dutch Golden Age",
    "as a photograph in the style of purist landscape photography",
    "as a painting in the style of American Realism",
    "as a painting in the style of exaggerated realism",
    "in the style of steam punk",
    "in the style of abstract expressionism",
    "in the style of pop art",
    "in the style of impressionism",
    "in the style of Art Nouveau",
    "as a watercolor",
]

# see if the user has their own artists list
if os.path.exists("ARTISTS_USER.txt"):
    prefix = "in the style of "
    new_mods = []
    with open("ARTISTS_USER.txt",'r') as file:
        for line in file:new_mods.append(prefix + str(line.strip()))
    if len(new_mods) > 0:
        IMAGE_MODIFIERS = new_mods


# Define  constants for blinking the LED (onTime, offTime)
BLINK_FAST = (0.1, 0.1)
BLINK_SLOW = (0.5, 0.5)
BLINK_FOR_AUDIO_CAPTURE = (0.05, 0.05)
BLINK1 = (0.5, 0.2)
BLINK2 = (0.4, 0.2)
BLINK3 = (0.3, 0.2)
BLINK4 = (0.2, 0.2)
BLINK_STOP = (-1, -1)
BLINK_DIE = (-2, -2)

if not config.isMacOS:
    # Define the GPIO pins for RPi
    LED_RED = 8
    BUTTON_GO = 10
    BUTTON_PULL_UP_DOWN = GPIO.PUD_UP
    BUTTON_PRESSED = GPIO.LOW  

# set S3 constants
s3_bucket_to_store_in = "amzn-s3-speech2picture"


# used by command line args to jump into the middle of the process
class processStep(IntEnum):
        NoneSpecified = 0
        CaptureAudio = 1
        Audio = 2
        Transcribe = 3
        Summarize = 4
        Keywords = 5
        ImageCreate = 6
        Done = 7
        UseAudioFile = 8
        UseTranscriptFile = 9
        UseSummaryFile = 10
        UseKeywordsFile = 11
        UseImageFile = 12
        DisplayImage = 13


 # global variables 
class g_args:
   
    # Set the duration of each recording in seconds
    duration = 120

    # if true don't use the command menu if we're using a button
    isUsingHardwareButtons = False  

    # When true don't extract keywords from the transcript, just use it for the image prompt
    isAudioKeywords = False

    # when running auto mode (continuous), this will limit the actual number of iterations
    numLoops = 1

    # when running auto mode (continuous), this will delay between iterations
    autoLoopDelay = 0

    # command line arguments can set this to jump into the middle of the process
    nextProcessStep = processStep.CaptureAudio

    # if command line args specify to use a file, then set this to it
    inputFileName = None

    # if true, then save files that are generated in the process - mostly a debug feature
    isSaveFiles = False

    # if true, then use S3 to store user images and pop a QR code to allow download of displayed images
    useS3 = True



# global window variables
# be sure gw is declared as global in any routine that changes a window attribute
class globalWindowVars:

    windowMain = None
    windowForMessages = None
    windowForStatus = None
    
    # when true, the program is quitting
    isQuitting = False

gw = globalWindowVars()

# XXX client = OpenAI()  # must have set up your key in the shell as noted in comments above
client = openai


def check_dependencies():
    """Check for required hardware and software dependencies at startup.

    Prints clear error messages and returns False if any critical dependency
    is missing.  Warnings are printed for optional dependencies.
    """
    import importlib.util

    all_ok = True
    issues: list[str] = []
    warnings: list[str] = []

    # --- OpenAI API key --------------------------------------------------------
    api_key = os.environ.get("OPENAI_API_KEY", "")
    secret_key_file = "creepy photo secret key"
    if not api_key and os.path.exists(secret_key_file):
        try:
            with open(secret_key_file, "r") as f:
                api_key = f.read().strip()
        except Exception:
            pass
    if not api_key:
        issues.append(
            "OpenAI API key not found.  Set the OPENAI_API_KEY environment "
            "variable or create a file named 'creepy photo secret key' "
            "containing your key."
        )
        all_ok = False

    # --- Pillow (PIL) ----------------------------------------------------------
    if importlib.util.find_spec("PIL") is None:
        issues.append("Pillow is not installed.  Run: pip install Pillow")
        all_ok = False

    # --- Qt (GUI) -------------------------------------------------------------
    if importlib.util.find_spec("PyQt6") is None:
        issues.append(
            "PyQt6 is not installed.  Run: pip install PyQt6"
        )
        all_ok = False

    # --- Platform-specific audio -----------------------------------------------
    if config.isMacOS:
        if importlib.util.find_spec("sounddevice") is None:
            issues.append(
                "sounddevice is not installed.  Run: pip install sounddevice"
            )
            all_ok = False
        if importlib.util.find_spec("soundfile") is None:
            issues.append(
                "soundfile is not installed.  Run: pip install soundfile"
            )
            all_ok = False
    elif config.isRPi:
        if importlib.util.find_spec("pyaudio") is None:
            issues.append(
                "pyaudio is not installed.  Run: pip install pyaudio"
            )
            all_ok = False
        if importlib.util.find_spec("RPi") is None:
            issues.append(
                "RPi.GPIO is not installed.  Run: pip install RPi.GPIO"
            )
            all_ok = False

    # --- Optional: S3 / QR support ---------------------------------------------
    if importlib.util.find_spec("s3_and_qr") is None:
        warnings.append(
            "s3_and_qr module not found.  S3 upload and QR code features "
            "will be unavailable."
        )

    # --- Report ----------------------------------------------------------------
    for w in warnings:
        print(f"WARNING: {w}")
    for i in issues:
        print(f"ERROR: {i}")

    return all_ok


# set up logging
logger = logging.getLogger(__name__) # parameter: -d 1
loggerTrace = logging.getLogger("Prompts") # parameter: -d 2
logging.basicConfig(level=logging.WARNING, format=' %(asctime)s - %(levelname)s - %(message)s')

logToFile = logging.getLogger("s2plog")
logToFile.setLevel(logging.INFO)
handler = TimedRotatingFileHandler('s2plog.log', when="midnight", interval=7, backupCount=10)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logToFile.addHandler(handler)


# create Qt application (must be done before any widgets)
app = QtWidgets.QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)


if not config.isMacOS:
    # --------- Raspberry Pi specific code -----------------------------------------
    logger.info("Setting up GPIO pins")

    # Set the pin numbering mode to BCM
    GPIO.setmode(GPIO.BOARD)

    # Set up pin g.LEDRed as an output
    GPIO.setup(LED_RED, GPIO.OUT, initial=GPIO.LOW)
    
    # Set up pin 10 as an input for the start button
    GPIO.setup(BUTTON_GO, GPIO.IN, pull_up_down=BUTTON_PULL_UP_DOWN)

    # Define a function to blink the LED
    # This function is run on a thread
    # Communicate by putting a tuple of (onTime, offTime) in the qBlinkControl queue.
    # The queue.Queue is inherently thread-safe, so no additional locking is needed.
    #
    def blink_led(q):
        # print("Starting LED thread") # why do I need to have this for the thread to work?
        logger.info("logging, Starting LED thread")

        # initialize the LED
        isBlinking = False
        GPIO.output(LED_RED, GPIO.LOW)

        while True:
            # Get the blink time from the queue
            try:
                blink_time = q.get_nowait()
            except:
                blink_time = None

            if blink_time is None:
                # no change
                pass
            elif blink_time[0] == -2:
                # die
                logger.info("LED thread dying")
                break
            elif blink_time[0] == -1:
                # stop blinking
                GPIO.output(LED_RED, GPIO.LOW)
                isBlinking = False
            else:
                onTime = blink_time[0]
                offTime = blink_time[1]
                isBlinking = True

            if isBlinking:
                # Turn the LED on
                GPIO.output(LED_RED, GPIO.HIGH)
                # Wait for blink_time seconds
                time.sleep(onTime)
                # Turn the LED off
                GPIO.output(LED_RED, GPIO.LOW)
                # Wait for blink_time seconds
                time.sleep(offTime)

    # Create a new thread to blink the LED
    logger.info("Creating LED thread")
    qBlinkControl = Queue()
    led_thread1 = threading.Thread(target=blink_led, args=(qBlinkControl,),daemon=True)
    led_thread1.start()


    # --------- end of Raspberry Pi specific code ----------------------------

def showStatus(labelForStatusDisplay = None):
    '''show the status of the program'''

    # get ip address and print it
    ip_addr = ""
    try:
        # Works cross-platform by asking OS which interface would route outbound traffic.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip_addr = sock.getsockname()[0]
    except OSError:
        pass

    if not ip_addr:
        try:
            # Fallback for Linux/RPi where hostname -I is available.
            ip_addr = os.popen("hostname -I").read().strip().split(" ")[0]
        except Exception:
            ip_addr = ""

    if ip_addr:
        ipMsg = "IP Address: " + ip_addr
    else:
        ipMsg = "IP Address: unavailable"

    print(ipMsg)

    directory = "history"
    pngFiles = []
    historyFileCount = 0
    for dirpath, dirnames, historyFiles in os.walk(directory):
        print(f"Number of files in {dirpath}: {len(historyFiles)}")
        historyFileCount += len(historyFiles)
        for file in historyFiles:
            if file.lower().endswith(".png"):
                file_path = os.path.join(dirpath, file)
                if os.path.isfile(file_path):
                    pngFiles.append(file_path)

    numPngFiles = len(pngFiles)
    print("Number of PNG files in history: " + str(numPngFiles))
    historyCount = "Number of files in history: " + str(historyFileCount)
    print(historyCount)

    # get the creation date of the oldest png file in the history directory
    if pngFiles:
        # Files can disappear between scan and stat; skip any that no longer exist.
        existingPngFiles = [file for file in pngFiles if os.path.exists(file)]
        if existingPngFiles:
            oldestFile = min(existingPngFiles, key=os.path.getctime)
            oldestFileTimestamp = os.path.getctime(oldestFile)
            oldestFileDateObj = datetime.datetime.fromtimestamp(oldestFileTimestamp)
            oldestFileDateFormatted = oldestFileDateObj.strftime("%m-%d-%Y")
            oldestFileDate = "Oldest file in history: " + oldestFileDateFormatted
        else:
            oldestFileDate = "Oldest file in history: unavailable"
    else:
        oldestFileDate = "Oldest file in history: none"

    print (oldestFileDate)

    # get the number of files in randomImages directory
    randomImagesFiles = os.listdir("idleDisplayFiles")
    idleFileCount = "Number of files in idleDisplayFiles: " + str(len(randomImagesFiles))
    print(idleFileCount)

    # get the disk free space
    total, used, free = shutil.disk_usage("/")
    freeSpace =  "{:.2f}".format(free / (1024*1024*1024)) + " GB"

    msg =("Status:\n\n" + ipMsg + "\n" + historyCount + "\n" 
        + oldestFileDate + "\n" + idleFileCount + "\n" 
        + "Free Space: " + freeSpace )

    display_text_in_status_window(msg, labelForStatusDisplay)
    # sleep for 10 seconds
    time.sleep(10)
    display_text_in_status_window()

def showCommands(labelForStatusDisplay = None):
    '''show the commands that can be used'''
    msg = "Valid Spoken Commands:\n\n" + \
        "    show status\n"+ \
        "    show commands\n"
    display_text_in_status_window(msg, labelForStatusDisplay)
    # sleep for 10 seconds
    time.sleep(10)
    display_text_in_status_window()


# create an array of keywords and functions to call when the keyword is found
# the keyword is the first word in the command 
voice_command_functions = {
    "show status": showStatus,
    "show commands": showCommands,
}



def changeBlinkRate(blinkRate):
    '''change the LED blink rate. This routine isolates the RPi specific code.

    Thread safety: queue.Queue.put() is thread-safe.  On non-RPi platforms
    qBlinkControl is None and this function is a no-op.
    '''
    if qBlinkControl is not None:
        qBlinkControl.put(blinkRate)


def recordAudioFromMicrophone(duration):
    '''record duration seconds of audio from the default microphone to a file and return the sound file name'''
    soundFileName = 'recording.wav'
    
    try:
        os.remove(soundFileName)
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning(f"Failed to remove old recording: {str(e)}")
    
    try:
        if config.isMacOS:
            # print the devices
            # print(sd.query_devices())  # in case you have trouble with the devices

            # Set the sample rate and number of channels for the recording
            sample_rate = int(sounddevice.query_devices(1)['default_samplerate'])
            channels = 1

            logger.debug('sample_rate: %d; channels: %d', sample_rate, channels)

            logger.info("Recording %d seconds...", duration)
            # Record audio from the default microphone
            recording = sounddevice.rec(
                int(duration * sample_rate), 
                samplerate=sample_rate, 
                channels=channels
                )

            # Wait for the recording to finish
            sounddevice.wait()

            # Save the recording to a WAV file
            soundfile.write(soundFileName, recording, sample_rate)

        elif config.isRPi:
            # RPi
            try:
                # all this crap because the ALSA library can't police itself
                ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)
                def py_error_handler(filename, line, function, err, fmt):
                    pass #nothing to see here
                c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)
                asound = cdll.LoadLibrary('libasound.so')
                # Set error handler
                asound.snd_lib_error_set_handler(c_error_handler)
                # Initialize PyAudio
                pa = pyaudio.PyAudio()
                # Reset to default error handler
                asound.snd_lib_error_set_handler(None)
                # now on with the show, sheesh

                stream = pa.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=44100,
                    input=True,
                    frames_per_buffer=1024
                ) #,input_device_index=2)

                wf = wave.open(soundFileName,"wb")
                wf.setnchannels(1)
                wf.setsampwidth(pa.get_sample_size(pyaudio.paInt16))
                wf.setframerate(44100)

                # Write the audio data to the file
                for i in range(0, int(44100/1024*10)):
                    # Get the audio data from the microphone
                    data = stream.read(1024)
                    # Write the audio data to the file
                    wf.writeframes(data)

                # Close the microphone and the wave file
                stream.close()
                wf.close()
            except Exception as e:
                logger.error(f"Failed to record audio on RPi: {str(e)}")
                raise RuntimeError(f"Audio recording failed: {str(e)}")
        else:
            raise RuntimeError("Unsupported platform for audio recording")
    except Exception as e:
        logger.error(f"Failed to record audio: {str(e)}")
        raise RuntimeError(f"Audio recording failed: {str(e)}")

    logger.info(f"Successfully recorded audio to {soundFileName}")
    return soundFileName




def getTranscript(wavFileName):
    '''transcribe the audio file and return the transcript'''

    # transcribe the recording
    logger.info("Transcribing...")
    audio_file= open(wavFileName, "rb")
    # used to use transcription.create, but the text comes back in the language spoken
    responseTranscript = client.audio.translations.create(
        model="whisper-1", 
        file=audio_file)

    # print the transcript object
    loggerTrace.debug("Transcript object: " + str(responseTranscript))

    transcript = responseTranscript.text 
    #remove trailing period
    transcript = transcript.rstrip(".")

    loggerTrace.debug("Transcript text: " + transcript)
    logToFile.info("Transcript text: " + transcript)

    return transcript


def getSummary(textInput):
    '''summarize the transcript and return the summary'''
    '''Used for very long text input - like minutes of speech'''
    
    # summarize the transcript 
    logger.info("Summarizing...")

    responseSummary = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "user", "content" : 
                            f"Please summarize the following text:\n{textInput}" }
                        ])
    loggerTrace.debug("responseSummary: " + str(responseSummary))

    summary = responseSummary.choices[0].message.content.strip()
    
    logger.debug("Summary: " + summary)
    logToFile.info("Summary: " + summary)

    return summary


def getAbstractForImageGen(inputText):
    '''get keywords for the image generator and return the keywords'''

    # extract the keywords from the summary

    logger.info("Extracting...")
    logger.debug("Prompt for abstraction: " + PROMPT_FOR_ABSTRACTION)    

    prompt = PROMPT_FOR_ABSTRACTION + "'''" + inputText + "'''"
    loggerTrace.debug ("prompt for extract: " + prompt)

    responseForImage = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "user", "content": prompt}
                        ])

    loggerTrace.debug("responseForImageGen: " + str(responseForImage))

    # extract the abstract from the response
    abstract = responseForImage.choices[0].message.content.strip()
    
    # Clean up the response from OpenAI
    # delete text before the first double quote
    abstract = abstract[abstract.find("\"")+1:]
    # delete text before the first colon
    abstract = abstract[abstract.find(":")+1:]
    # eliminate phrases that are not useful for image generation
    badPhrases = ["the concept of", "in the supplied text is", "the most interesting concept"
                    "in the text is"]
    for phrase in badPhrases:
        # compilation step to escape the word for all cases
        compiled = re.compile(re.escape(phrase), re.IGNORECASE)
        res = compiled.sub(" ", abstract)
        abstract = str(res) 
    
    #remove trailing period
    abstract = abstract.rstrip(".")

    logger.info("Abstract: " + abstract)
    logToFile.info("Abstract: " + abstract)

    return abstract


def getImageURL(phrase):
    '''get images and return the image data (URLs or base64) and modifier used'''

    try:
        # pick random modifiers
        random.shuffle(IMAGE_MODIFIERS)

        # Check if phrase already contains stylistic information
        phrase_has_style = (
            "in the style of" in phrase.lower()
            or "as a painting by" in phrase.lower()
            or "as a photograph by" in phrase.lower()
            or "as a sketch by" in phrase.lower()
            or "as a watercolor by" in phrase.lower()
        )

        # use openai to generate a picture based on the summary
        if gw.single_image:
            modifierUsed = IMAGE_MODIFIERS[0] if not phrase_has_style else ""
            if phrase_has_style:
                prompt = f"Generate a picture WITHOUT ANY TEXT OR WRITING IN THE PICTURE for the following: '{phrase}'"
            else:
                prompt = f"Generate a picture {modifierUsed} WITHOUT ANY TEXT OR WRITING IN THE PICTURE for the following: '{phrase}'"

            logger.info(f"Generating image with prompt: {prompt}")
            responseImage = client.images.generate(
                prompt=prompt,
                model="dall-e-3",
                n=1,
                size="1024x1024"
            )
            image_urls = [img.url for img in responseImage.data]

        else:
            # Generate 4 images, each with a different modifier for variety
            num_images = 4
            modifiers_to_use = IMAGE_MODIFIERS[:num_images] if not phrase_has_style else [""] * num_images
            modifierUsed = ", ".join(m for m in modifiers_to_use if m)  # combined for caption

            # Show initial progress message
            last_transcript = getattr(gw, 'lastTranscript', '')
            progress_msg = (
                f'I heard you say:\n\r "{last_transcript}"\n\r\n\r'
                f'Creating images... (0 of {num_images})'
            ) if last_transcript else f"Creating images... (0 of {num_images})"
            display_text_in_message_window(
                progress_msg,
                labelToUse=getattr(gw, 'labelForMessage', None))

            # Build prompts for all images
            prompts_and_indices = []
            for i in range(num_images):
                mod = modifiers_to_use[i]
                if phrase_has_style or not mod:
                    prompt = f"Generate a picture WITHOUT ANY TEXT OR WRITING IN THE PICTURE and some randomness for the following: '{phrase}'"
                else:
                    prompt = f"Generate a picture WITHOUT ANY TEXT OR WRITING IN THE PICTURE  {mod} and interpret it creatively for the following: '{phrase}'"
                prompts_and_indices.append((i, prompt))

            # Fire all 4 API calls concurrently
            image_urls = [None] * num_images
            completed_count = 0
            requested_count = 0
            with ThreadPoolExecutor(max_workers=num_images) as executor:
                future_to_index = {}
                for idx, prompt in prompts_and_indices:
                    logger.info(f"Submitting image {idx + 1}/{num_images} request with prompt: {prompt}")
                    future = executor.submit(
                        lambda p=prompt: client.images.generate(
                            prompt=p,
                            model="gpt-image-1.5",
                            n=1,
                            size="1024x1024"
                        )
                    )
                    future_to_index[future] = idx
                    requested_count += 1

                    # Update progress in the message window as each request is submitted.
                    request_msg = (
                        f'I heard you say:\n\r "{last_transcript}"\n\r\n\r'
                        f'requested {requested_count} of {num_images}'
                    ) if last_transcript else f"requested {requested_count} of {num_images}"
                    display_text_in_message_window(
                        request_msg,
                        labelToUse=getattr(gw, 'labelForMessage', None),
                    )

                for future in as_completed(future_to_index):
                    idx = future_to_index[future]
                    responseImage = future.result()
                    # gpt-image-1.5 returns b64_json, not URLs
                    image_urls[idx] = responseImage.data[0].b64_json
                    completed_count += 1
                    logger.info(f"Image {idx + 1}/{num_images} completed ({completed_count}/{num_images} done)")

                    # Update progress in the message window
                    progress_msg = (
                        f'I heard you say:\n\r "{last_transcript}"\n\r\n\r'
                        f'Creating images... {completed_count} of {num_images}'
                    ) if last_transcript else f"Creating images... {completed_count} of {num_images}"
                    display_text_in_message_window(
                        progress_msg,
                        labelToUse=getattr(gw, 'labelForMessage', None))

        loggerTrace.debug("responseImage count: " + str(len(image_urls)))

        return image_urls, modifierUsed

    except Exception as e:
        logger.error(f"Image generation failed: {str(e)}")
        raise


def postProcessImages(imageURLs, imageModifiers, keywords, timestr, filePrefix):
    '''reformat the images for display and return the new file name'''

    # save the images into imgObjects[]
    imgObjects = []
    for numURL in range(len(imageURLs)):

        fileName = "history/" + "image" + str(numURL) + ".png"

        if imageURLs[numURL].startswith("http"):
            # URL-based image (dall-e models)
            urllib.request.urlretrieve(imageURLs[numURL], fileName)
        else:
            # base64-encoded image (gpt-image models)
            with open(fileName, "wb") as f:
                f.write(base64.b64decode(imageURLs[numURL]))

        img = Image.open(fileName)
        imgObjects.append(img)

    # combine the images into one image
    caption_area_height = 140  # taller area for two lines of large text
    if not gw.single_image:
        # Determine image size from the first image (supports 512x512 and 1024x1024)
        img_w, img_h = imgObjects[0].size
        total_width = img_w * 2
        max_height = img_h * 2 + caption_area_height
        new_im = Image.new('RGB', (total_width, max_height))
        locations = [(0, 0), (img_w, 0), (0, img_h), (img_w, img_h)]
        count = -1
        for loc in locations:
            count += 1
            new_im.paste(imgObjects[count], loc)
    else:
        total_width = 1024
        max_height = 1024 + caption_area_height
        new_im = Image.new('RGB', (total_width, max_height))
        new_im.paste(imgObjects[0], (0, 0))


    # add text at the bottom
    imageCaption = f'{keywords}' # {imageModifiers}'
    draw = ImageDraw.Draw(new_im)
    draw.rectangle(
        ((0, new_im.height - caption_area_height), (new_im.width, new_im.height)),
        fill="black")
    font = ImageFont.truetype("arial.ttf", 56)

    # Wrap text across up to 2 lines, using 75% of image width
    import textwrap as _tw
    max_text_width = int(new_im.width * 0.75)
    lines = _tw.wrap(imageCaption, width=60)
    # If the wrapped lines still exceed pixel width, reduce until they fit
    for char_width in range(60, 20, -5):
        lines = _tw.wrap(imageCaption, width=char_width)
        all_fit = True
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            if bbox[2] - bbox[0] > max_text_width:
                all_fit = False
                break
        if all_fit:
            break
    lines = lines[:2]  # max 2 lines
    for idx, line in enumerate(lines):
        y_pos = new_im.height - caption_area_height + 5 + idx * 60
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        x_pos = (new_im.width - text_width) / 2
        draw.text((x_pos, y_pos), line, (255, 255, 255), font=font)

    # save the combined image
    newFileName = "history/" + filePrefix + timestr + "-image" + ".png"
    new_im.save(newFileName)

    return newFileName


def generateErrorImage(e, timestr):
    '''generate an image with the error message and return the new file name'''

    # make an image to display the error
    total_width = 512*2
    max_height = 512*2 + 50
    new_im = Image.new('RGB', (total_width, max_height))
    draw = ImageDraw.Draw(new_im)
    draw.rectangle(((0, 0), (new_im.width, new_im.height)), fill="black")
    
    # add error text
    imageCaption = str(e)
    logToFile.error("Error: " + imageCaption)
    
    font = ImageFont.truetype("arial.ttf", 24)
    # decide if text will exceed the width of the image
    #textWidth, textHeight = font.getsize(text)

    import textwrap
    lines = textwrap.wrap(imageCaption, width=60)  #width is characters
    y_text = new_im.height/2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        draw.text(((new_im.width - text_width) / 2, y_text), line, font=font)
        y_text += height

    #draw.text((10, new_im.height/2), imageCaption, (255,255,255), font=font)

    # save the new image
    newFileName = "errors/" + timestr + "-imageERROR" + ".png"
    new_im.save(newFileName)

    return newFileName

''' 
Window functions
'''

def _pil_to_qpixmap(pil_image: Image.Image) -> QtGui.QPixmap:
    """Convert a PIL Image to a QPixmap."""
    # Use an encoded image payload instead of a raw pixel buffer so Qt handles
    # row stride/padding consistently across image modes and platforms.
    buffer = BytesIO()
    pil_image.save(buffer, format="PNG")
    pixmap = QtGui.QPixmap()
    pixmap.loadFromData(buffer.getvalue(), "PNG")
    return pixmap


class _MainWindow(QtWidgets.QMainWindow):
    """Main application window for Speech2Picture."""

    def __init__(self, usingHardwareButton: bool):
        super().__init__()
        global gw

        self.setWindowTitle("Speech 2 Picture")
        self.setStyleSheet("background-color: #52837D;")

        # --- Central widget and main layout ---
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        self._main_grid = QtWidgets.QGridLayout(central)
        self._main_grid.setContentsMargins(10, 10, 10, 10)
        self._main_grid.setSpacing(10)

        # Base column stretch values; image column stretch is recomputed from ratio.
        self._main_grid.setColumnStretch(0, 1)
        self._main_grid.setColumnStretch(1, 1)
        self._main_grid.setColumnStretch(2, 1)
        self._main_grid.setColumnStretch(3, 1)
        self._main_grid.setColumnStretch(4, 1)
        self._main_grid.setColumnStretch(5, 1)
        self._main_grid.setColumnStretch(6, 14)
        self._main_grid.setColumnStretch(7, 0)
        self._main_grid.setColumnMinimumWidth(2, 100)
        self._main_grid.setColumnMinimumWidth(3, 100)

        # Row stretch: give instructions rows more vertical space
        self._main_grid.setRowStretch(0, 3)  # instructions top
        self._main_grid.setRowStretch(1, 3)  # instructions bottom
        self._main_grid.setRowStretch(2, 1)  # QR
        self._main_grid.setRowStretch(3, 1)  # credits
        self._main_grid.setRowStretch(4, 1)  # command hint
        self._main_grid.setRowStretch(5, 1)  # quit button
        self._image_pane_ratio = 0.52  # picture display width

        # --- Instructions text ---
        qr_text = " Scan the QR to download." if gw.useS3 else ""
        INSTRUCTIONS_TEXT = (
            '\r\nTRY ME NOW !\r\nAn Interactive Art Exhibit\n\r\n'
            'When you are ready, press and release the button. '
            'The light will flash quickly. You will have 10 seconds '
            'to speak a few words to use to make an AI image. Then wait. '
            'Images will appear shortly.' + qr_text +
            '\r\n\nUntil then, enjoy some previous "promptography" images!'
        )
        self._labelInstructions = QtWidgets.QLabel(INSTRUCTIONS_TEXT)
        self._labelInstructions.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignTop
        )
        self._labelInstructions.setWordWrap(True)
        self._labelInstructions.setMinimumHeight(360)
        self._labelInstructions.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self._instruction_font_max_px = 48
        self._instruction_font_min_px = 24
        self._instruction_font_family = self._pick_instruction_font_family()
        self._set_instructions_font_size(self._instruction_font_max_px)
        self._main_grid.addWidget(self._labelInstructions, 0, 0, 2, 6)

        # --- Main image label ---
        self.labelForImage = QtWidgets.QLabel()
        self.labelForImage.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.labelForImage.setStyleSheet(
            "background-color: #000000; border: 10px solid #f4ff55;"
        )
        self.labelForImage.setMinimumSize(400, 400)
        self.labelForImage.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        self._main_grid.addWidget(self.labelForImage, 0, 6, 6, 1)

        # --- QR code (static) + QR instructions in a horizontal layout ---
        imgQR = Image.open("S2PQR.png")
        imgQR = imgQR.resize((150, 150), Image.NEAREST)
        self._labelQR = QtWidgets.QLabel()
        self._labelQR.setPixmap(_pil_to_qpixmap(imgQR))
        self._labelQR.setStyleSheet("background-color: #52837D;")
        self._labelQR.setFixedWidth(160)

        self._labelQRText = QtWidgets.QLabel(
            "Scan this QR code for more instructions and tips."
        )
        self._labelQRText.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        self._labelQRText.setWordWrap(True)
        self._labelQRText.setStyleSheet(
            "font: 18px Helvetica; color: #FFFFFF; background-color: #52837D;"
        )

        self._qr_layout = QtWidgets.QHBoxLayout()
        self._qr_layout.setSpacing(20)
        self._qr_layout.addWidget(self._labelQR)
        self._qr_layout.addWidget(self._labelQRText, 1)
        self._main_grid.addLayout(self._qr_layout, 2, 0, 1, 6)

        # --- Credits ---
        self._labelCredits = QtWidgets.QLabel(
            "Created by Jim Schrempp at Maker Nexus in Sunnyvale, California."
        )
        self._labelCredits.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        self._labelCredits.setWordWrap(True)
        self._labelCredits.setStyleSheet(
            "font: 18px Helvetica; color: #FFFFFF; background-color: #52837D;"
        )
        self._main_grid.addWidget(
            self._labelCredits,
            3,
            0,
            1,
            6,
            alignment=QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop,
        )

        # --- Buttons ---
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()

        self._buttonWindow = QtWidgets.QPushButton("Window")
        self._buttonWindow.setStyleSheet(
            "font: 12px Helvetica; background-color: #D3D3D3; color: #000000;"
        )
        self._buttonWindow.clicked.connect(exitFullscreenButtonPressed)
        button_layout.addWidget(self._buttonWindow)
        button_layout.addSpacing(24)

        self._buttonQuit = QtWidgets.QPushButton("Quit")
        self._buttonQuit.setStyleSheet(
            "font: 24px Helvetica; background-color: #D3D3D3; color: #000000;"
        )
        self._buttonQuit.clicked.connect(quitButtonPressed)

        # --- Command hint ---
        self._labelCommandHint = QtWidgets.QLabel(
            "show commands  v: " + config.version
        )
        self._labelCommandHint.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        self._labelCommandHint.setWordWrap(True)
        self._labelCommandHint.setStyleSheet(
            "font: 12px Helvetica; color: #FFFFFF; background-color: #52837D;"
        )
        self._main_grid.addWidget(
            self._labelCommandHint,
            4,
            0,
            1,
            6,
            alignment=QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop,
        )

        # Place Quit in the lower-left area of the main window.
        self._main_grid.addWidget(
            self._buttonQuit,
            5,
            0,
            alignment=QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignBottom,
        )

        self._main_grid.addLayout(button_layout, 5, 2, 1, 2)

        # --- QR for generated image (only if S3 enabled) ---
        if gw.useS3:
            self.qrContainer = QtWidgets.QWidget(
                None,
                QtCore.Qt.WindowType.FramelessWindowHint | QtCore.Qt.WindowType.WindowStaysOnTopHint,
            )
            self.qrContainer.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, False)
            self.qrContainer.setStyleSheet("background-color: #FFFFFF;")

            self.labelQRForImage = QtWidgets.QLabel()
            self.labelQRForImage.setStyleSheet(
                "background-color: #000000; border: none;"
            )
            self.labelQRForImage.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

            self.labelQRForImageText = QtWidgets.QLabel("scan to download image")
            self.labelQRForImageText.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.labelQRForImageText.setStyleSheet(
                "font: 10px Helvetica; color: #000000; background-color: #FFFFFF;"
            )

            qr_layout = QtWidgets.QVBoxLayout()
            qr_layout.setContentsMargins(0, 0, 0, 0)
            qr_layout.setSpacing(0)
            qr_layout.addWidget(self.labelQRForImage)
            qr_layout.addWidget(self.labelQRForImageText)
            self.qrContainer.setLayout(qr_layout)
            self.qrContainer.hide()
        else:
            self.qrContainer = None
            self.labelQRForImage = None
            self.labelQRForImageText = None

        # --- Visibility toggles ---
        if usingHardwareButton:
            self._buttonQuit.hide()
        if not gw.kiosk_mode:
            self._buttonWindow.hide()

        # --- Kiosk / sizing ---
        if gw.kiosk_mode:
            time.sleep(4.0)
            self.showFullScreen()
        else:
            screen = app.primaryScreen().availableGeometry()
            w = int(screen.width() * 0.95)
            h = int(screen.height() * 0.95)
            x = int(screen.width() * 0.025)
            y = int(screen.height() * 0.025)
            self.setGeometry(x, y, w, h)

        self._apply_image_pane_width()
        self._fit_instructions_font()
        QtCore.QTimer.singleShot(0, self._apply_image_pane_width)
        QtCore.QTimer.singleShot(0, self._fit_instructions_font)

        gw.windowMain = self

    def _apply_image_pane_width(self):
        """Apply responsive width and stretch for the image column."""
        margins = self._main_grid.contentsMargins()
        available = self.width() - margins.left() - margins.right()
        ratio = max(0.15, min(0.85, self._image_pane_ratio))
        target = int(max(0, available) * ratio)

        # Keep a practical floor that still allows ratio changes to be visible.
        self._main_grid.setColumnMinimumWidth(6, max(400, target))

        # Convert desired width ratio to grid stretch so extra space follows ratio.
        other_total_stretch = 7  # columns 0-5 and 7 are each stretch 1
        image_stretch = max(1, int(round((other_total_stretch * ratio) / (1.0 - ratio))))
        self._main_grid.setColumnStretch(6, image_stretch)

    def _pick_instruction_font_family(self) -> str:
        """Pick the first available readable font for kiosk instructions."""
        preferred_fonts = ["Noto Sans", "DejaVu Sans", "Verdana", "Arial", "Helvetica"]
        available_fonts = set(QtGui.QFontDatabase.families())
        for font_name in preferred_fonts:
            if font_name in available_fonts:
                return font_name
        return self._labelInstructions.font().family()

    def _set_instructions_font_size(self, size_px: int):
        """Apply instruction font family and pixel size."""
        self._labelInstructions.setStyleSheet(
            f"font-size: {size_px}px; font-weight: 700; font-family: '{self._instruction_font_family}';"
            " color: #FFFFFF; background-color: #52837D;"
        )

    def _fit_instructions_font(self):
        """Reduce instruction font size until full text fits the label bounds."""
        text = self._labelInstructions.text()
        if not text:
            return

        rect = self._labelInstructions.contentsRect()
        if rect.width() <= 0 or rect.height() <= 0:
            return

        fit_flags = int(QtCore.Qt.TextFlag.TextWordWrap | QtCore.Qt.TextFlag.TextExpandTabs)
        best_size = self._instruction_font_min_px

        for size_px in range(self._instruction_font_max_px, self._instruction_font_min_px - 1, -1):
            font = QtGui.QFont(self._instruction_font_family)
            font.setPixelSize(size_px)
            font.setWeight(QtGui.QFont.Weight.Bold)

            metrics = QtGui.QFontMetrics(font)
            text_rect = metrics.boundingRect(
                QtCore.QRect(0, 0, rect.width(), 20000),
                fit_flags,
                text,
            )

            if text_rect.height() <= rect.height():
                best_size = size_px
                break

        self._set_instructions_font_size(best_size)

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        """ESC exits fullscreen / quits."""
        if event.key() == QtCore.Qt.Key.Key_Escape:
            quitButtonPressed()
        super().keyPressEvent(event)

    def closeEvent(self, event: QtGui.QCloseEvent):
        """Window close → quit."""
        quitButtonPressed()
        event.ignore()

    def resizeEvent(self, event: QtGui.QResizeEvent):
        """Keep image pane width proportional as the window changes size."""
        super().resizeEvent(event)
        self._apply_image_pane_width()
        self._fit_instructions_font()


def create_main_window(usingHardwareButton: bool):
    """Create the main window and return widget references."""
    global gw
    win = _MainWindow(usingHardwareButton)
    win.show()
    QtWidgets.QApplication.processEvents()
    return win.labelForImage, win.labelQRForImage, win.labelQRForImageText


def update_main_window():
    """Process pending Qt events."""
    global gw
    if gw.isQuitting:
        return
    QtWidgets.QApplication.processEvents()


def exitFullscreenButtonPressed():
    """Exit fullscreen mode and resize window."""
    global gw
    win = gw.windowMain
    if win is None:
        return
    win.showNormal()
    screen = app.primaryScreen().availableGeometry()
    w = int(screen.width() * 0.95)
    h = int(screen.height() * 0.95)
    x = int(screen.width() * 0.025)
    y = int(screen.height() * 0.025)
    win.setGeometry(x, y, w, h)


def quitButtonPressed():
    """Quit the program."""
    global gw
    gw.isQuitting = True
    QtWidgets.QApplication.quit()
    # Give event loop a moment, then force exit
    time.sleep(0.1)
    os._exit(0)


class _PopupDialog(QtWidgets.QDialog):
    """Reusable popup dialog for messages and status."""

    def __init__(self, title: str, width: int, height: int,
                 font_size: int, alignment, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(width, height)
        self.setMaximumSize(width, height)
        self.setWindowFlags(
            self.windowFlags() | QtCore.Qt.WindowType.WindowStaysOnTopHint
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        frame = QtWidgets.QFrame()
        frame.setStyleSheet(
            "background-color: #ff0000; border: 2px solid #ffff55;"
        )
        frame_layout = QtWidgets.QVBoxLayout(frame)
        frame_layout.setContentsMargins(5, 5, 5, 5)

        self.label = QtWidgets.QLabel()
        self.label.setAlignment(alignment)
        self.label.setWordWrap(True)
        self.label.setStyleSheet(
            f"font: {font_size}px Helvetica; color: #000000;"
            " background-color: #FFFFFF;"
        )
        frame_layout.addWidget(self.label)

        layout.addWidget(frame)
        self.hide()

    def closeEvent(self, event: QtGui.QCloseEvent):
        """Ignore close — just hide."""
        self.hide()
        event.ignore()


def create_message_window():
    """Create the message popup and return its label."""
    global gw
    dlg = _PopupDialog(
        "Messages", 500, 500, 28,
        QtCore.Qt.AlignmentFlag.AlignCenter,
        parent=gw.windowMain,
    )
    gw.windowForMessages = dlg
    return dlg.label


def create_status_window():
    """Create the status popup and return its label."""
    global gw
    dlg = _PopupDialog(
        "Status", 800, 600, 24,
        QtCore.Qt.AlignmentFlag.AlignLeft,
        parent=gw.windowMain,
    )
    gw.windowForStatus = dlg
    return dlg.label


def _center_popup_over_parent(popup: QtWidgets.QDialog):
    """Center a popup dialog over its parent window."""
    parent = popup.parentWidget()
    if parent is None:
        return
    pg = parent.geometry()
    pw, ph = pg.width(), pg.height()
    px, py = pg.x(), pg.y()
    dw, dh = popup.width(), popup.height()
    popup.move(px + (pw - dw) // 2, py + (ph - dh) // 2)


def display_text_in_status_window(message=None, labelToUse=None):
    """Show/hide the status popup."""
    global gw
    if gw.isQuitting:
        return
    try:
        if gw.windowForStatus is None or not gw.windowForStatus.isVisible():
            # Recreate if needed
            if gw.windowForStatus is None:
                create_status_window()
            else:
                pass  # exists but hidden, that's fine

        if message is None or labelToUse is None:
            if gw.windowForStatus is not None:
                gw.windowForStatus.hide()
        else:
            labelToUse.setText(message)
            _center_popup_over_parent(gw.windowForStatus)
            gw.windowForStatus.show()

        QtWidgets.QApplication.processEvents()

        # Also process message window events
        display_text_in_message_window()
        if gw.windowForMessages is not None and gw.windowForMessages.isVisible():
            QtWidgets.QApplication.processEvents()
    except Exception:
        pass


def display_text_in_message_window(message=None, labelToUse=None):
    """Show/hide the message popup."""
    global gw
    if gw.isQuitting:
        return
    try:
        if gw.windowForMessages is None or not gw.windowForMessages.isVisible():
            if gw.windowForMessages is None:
                create_message_window()

        if message is None or labelToUse is None:
            if gw.windowForMessages is not None:
                gw.windowForMessages.hide()
        else:
            labelToUse.setText(message)
            _center_popup_over_parent(gw.windowForMessages)
            gw.windowForMessages.show()

        QtWidgets.QApplication.processEvents()
    except Exception:
        pass


def display_image(image_path, label=None, labelQR=None, labelQRText=None):
    """Display an image in the main window."""
    global gw
    if gw.isQuitting:
        return

    logger.debug("display_image: " + image_path)
    logToFile.debug("display_image: " + image_path)

    if label is None:
        print("Error: label is None")
        return

    try:
        img = Image.open(image_path)
        pixmap = _pil_to_qpixmap(img)

        # Scale to the actual label space assigned by the layout. This avoids
        # forcing a size larger than the grid cell, which can crop the bottom.
        available_size = label.contentsRect().size()
        if available_size.width() <= 1 or available_size.height() <= 1:
            available_size = label.size()

        scaled_pixmap = pixmap.scaled(
            available_size,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        label.setPixmap(scaled_pixmap)

        new_width = scaled_pixmap.width()
        new_height = scaled_pixmap.height()

        update_main_window()
        skip_QR = False

    except Exception as e:
        print("Error with image file: " + image_path)
        print(e)
        logger.error("Error with image file: " + image_path)
        logger.error(e)
        skip_QR = True

    # Update QR label
    if labelQR and not skip_QR and gw.useS3:
        QRFile = image_path.replace("-image.png", '-s3_url.jpg')
        if os.path.exists(QRFile):
            QRimg = Image.open(QRFile)
            QR_resize = 0.15
            QR_size = int(QR_resize * min(new_width, new_height))
            QRimg = QRimg.resize((QR_size, QR_size), Image.NEAREST)

            labelQR.setPixmap(_pil_to_qpixmap(QRimg))
            labelQR.setFixedSize(QR_size, QR_size)

            if labelQRText:
                labelQRText.setFixedWidth(QR_size)

            # Position the combined container at lower-right of the image label
            container = labelQR.parentWidget()
            if container:
                container.adjustSize()
                label_top_left = label.mapToGlobal(QtCore.QPoint(0, 0))
                container.move(
                    label_top_left.x() + label.width() - QR_size,
                    label_top_left.y() + label.height() - container.height(),
                )
                container.show()
                container.raise_()
        else:
            # No QR file for this image — hide the container
            container = labelQR.parentWidget()
            if container:
                container.hide()
    elif labelQR:
        # skip_QR is True or S3 not in use — hide the container
        container = labelQR.parentWidget()
        if container:
            container.hide()

    update_main_window()

    return label


def display_random_history_image(labelForImageDisplay, labelQRForImage=None,
                                  labelQRForImageText=None):
    """Display a random image from idleDisplayFiles."""
    if not hasattr(display_random_history_image, "lastImageDisplayedTime"):
        display_random_history_image.lastImageDisplayedTime = 0

    if time.time() - display_random_history_image.lastImageDisplayedTime > 15:
        display_random_history_image.lastImageDisplayedTime = time.time()

        idleDisplayFolder = "./idleDisplayFiles"
        idleDisplayFiles = os.listdir(idleDisplayFolder)
        imagesToDisplay = [
            f for f in idleDisplayFiles if f.endswith(".png")
        ]
        random.shuffle(imagesToDisplay)
        display_image(
            idleDisplayFolder + "/" + imagesToDisplay[0],
            labelForImageDisplay, labelQRForImage, labelQRForImageText,
        )
        update_main_window()


def parseCommandLineArgs():
    '''
    parse the command line arguments and set the global variables
    '''
    rtn = g_args()

    # parse the command line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--savefiles", help="save the files", action="store_true") # optional argument
    parser.add_argument("-d", "--debug", help="0:info, 1:prompts, 2:responses", type=int) # optional argument
    parser.add_argument("-w", "--wav", help="use audio from file", type=str, default=0) # optional argument
    parser.add_argument("-t", "--transcript", help="use transcript from file", type=str, default=0) # optional argument
    parser.add_argument("-T", "--summary", help="use summary from file", type=str, default=0) # optional argument
    parser.add_argument("-k", "--keywords", help="use keywords from file", type=str, default=0) # optional argument
    parser.add_argument("-i", "--image", help="use image from file", type=str, default=0) # optional argument
    parser.add_argument("-o", "--onlykeywords", help="use audio directly without extracting keywords", action="store_true") # optional argument
    parser.add_argument("-g", "--gokiosk", help="jump into Kiosk mode", action="store_true") # optional argument
    parser.add_argument("-q", "--use_s3", help = "try to store image files to AWS S3, and generate QRcodes", action="store_true")
    parser.add_argument("-m", "--mono_image", help = "create a single, large image using dall-e-3", action="store_true")
    args = parser.parse_args()

    # set the debug level
    logger.setLevel(logging.INFO)

    if args.debug == 1:
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug level set to show prompts")
    elif args.debug == 2:
        logger.setLevel(logging.DEBUG)
        loggerTrace.setLevel(logging.DEBUG)
        logger.debug("Debug level set to show prompts and response JSON")

    # set S3 use or not
    if args.use_s3: 
        rtn.useS3 = True
        print("\r\nUsing AWS S3 for image storage and QR code generation\r\n")
    else:           
        rtn.useS3 = False

    # set flag for single large image (vs default of 4 small)
    if args.mono_image: 
        rtn.single_image = True
    else:               
        rtn.single_image = False


    # if true, don't ask user for input, rely on hardware buttons
    rtn.isUsingHardwareButtons = False

    if args.gokiosk:
        # jump into Kiosk mode
        print("\r\nKiosk mode enabled\r\n")
        rtn.isUsingHardwareButtons = True
        rtn.isAudioKeywords = True
        rtn.numLoops = 1
        rtn.autoLoopDelay = 0
        rtn.nextProcessStep = processStep.NoneSpecified
        rtn.kiosk_mode = True
    else:
        rtn.kiosk_mode = False

        # if we're given a file via the command line then start at that step
        # check in reverse order so that processStartStep will be the latest step for any set of arguments
        rtn.nextProcessStep = processStep.NoneSpecified
        if args.image != 0: 
            rtn.nextProcessStep = processStep.UseImageFile
            rtn.inputFileName = args.image
        elif args.keywords != 0: 
            rtn.nextProcessStep = processStep.UseKeywordsFile
            rtn.inputFileName = args.keywords
        elif args.summary != 0: 
            rtn.nextProcessStep = processStep.UseSummaryFile
            rtn.inputFileName = args.summary
        elif args.transcript != 0: 
            rtn.nextProcessStep  = processStep.UseTranscriptFile
            rtn.inputFileName = args.transcript
        elif args.wav != 0:
            rtn.nextProcessStep = processStep.UseAudioFile
            rtn.inputFileName = args.wav

        # if set, then record only 10 seconds of audio and use that for the keywords
        rtn.isAudioKeywords = False
        if args.onlykeywords:
            rtn.isAudioKeywords = True
            rtn.duration = 10

        rtn.isSaveFiles = False
        if args.savefiles:
            rtn.isSaveFiles = True

    return rtn


def audioToPicture(settings, labelForImageDisplay, labelForMessageDisplay, labelForStatusDisplay, filePrefix, labelQRForImage = None, labelQRForImageText = None ):
    '''
    main routine to process audio to picture
    '''
    # format a time string to use as a file name
    timestr = time.strftime("%Y%m%d-%H%M%S")

    soundFileName = ""
    transcript = ""
    summary = ""
    keywords = ""
    imageURLs = ""
    newImageFileName = ""

    nextProcessStep = settings.nextProcessStep
    print ("nextProcessStep: " + str(nextProcessStep))


    # first check to see if we are using a file for the input (from a command line argument)

    if nextProcessStep == processStep.UseAudioFile:
        # use the audio file specified 
        soundFileName = settings.inputFileName
        logger.info("Using audio file: " + settings.inputFileName)
        nextProcessStep = processStep.Transcribe

    if nextProcessStep == processStep.UseTranscriptFile:
        # use the text file specified 
        transcriptFile = open(settings.inputFileName, "r")
        # read the transcript file
        transcript = transcriptFile.read()
        logger.info("Using transcript file: " + settings.inputFileName)
        nextProcessStep = processStep.Summarize

    if nextProcessStep == processStep.UseSummaryFile:
        # use the text file specified 
        summaryFile = open(settings.inputFileName, "r")
        # read the transcript file
        summary = summaryFile.read()
        logger.info("Using summary file: " + settings.inputFileName)
        nextProcessStep = processStep.ImageCreate

    if nextProcessStep == processStep.UseKeywordsFile:
        # use the extract file specified by the extract argument
        summaryFile = open(settings.inputFileName, "r")
        # read the summary file
        keywords = summaryFile.read()
        logger.info("Using abstract file: " + settings.inputFileName)
        nextProcessStep = processStep.ImageCreate

    if nextProcessStep == processStep.UseImageFile:
        imageURLs = [settings.inputFileName]
        newImageFileName = settings.inputFileName
        logger.info("Using image file: " + settings.inputFileName )
        nextProcessStep = processStep.DisplayImage


    # Below is the pipeline for processing audio to picture. 
    # Each step changes the nextProcessStep to the next step in the pipeline
    # The code above can set the nextProcessStep to a specific step to skip steps in the pipeline

    # Audio - get a recording.wav file
    if nextProcessStep == processStep.CaptureAudio:

        changeBlinkRate(BLINK_FOR_AUDIO_CAPTURE)

        if config.isMacOS:
            # On macOS, wait for spoken prompt to finish before showing Speak Now.
            os.system('say "Now recording."')

        # record audio from the default microphone
        display_text_in_message_window("Speak Now\r\nYou have 10 seconds", labelForMessageDisplay)
        soundFileName = recordAudioFromMicrophone(settings.duration)
        display_text_in_message_window("Recording Complete, now analyzing", labelForMessageDisplay)
        if config.isMacOS: os.system('say "Recording complete."')

        if settings.isSaveFiles:
            print("Saving audio file: " + soundFileName)
            #copy the file to a new name with the time stamp
            shutil.copy(soundFileName, "history/" + filePrefix + timestr + "-recording" + ".wav")
            soundFileName = "history/" + filePrefix + timestr + "-recording" + ".wav"
    
        changeBlinkRate(BLINK_STOP)
        nextProcessStep = processStep.Transcribe


    # Transcribe - set transcript
    if nextProcessStep == processStep.Transcribe:
    
        changeBlinkRate(BLINK1)

        # transcribe the recording
        transcript = getTranscript(soundFileName)
        logToFile.info("Transcript: " + transcript)

        if settings.isSaveFiles:
            f = open("history/" + filePrefix + timestr + "-rawtranscript" + ".txt", "w")
            f.write(transcript)
            f.close()

        msg = f'I heard you say:\n\r "{transcript}" \n\r\n\rNow we wait for the images.'
        display_text_in_message_window(msg, labelForMessageDisplay)
        gw.lastTranscript = transcript  # store for progress updates during image generation
        nextProcessStep = processStep.Summarize

        changeBlinkRate(BLINK_STOP)
    
    # always check for a command in the transcript
    # check for command
    if transcript:
        for keyword in voice_command_functions:
            if keyword.lower() in transcript.lower():
                # perform the corresponding action for the keyword
                voice_command_functions[keyword](labelForStatusDisplay)
                print("voice command done")
                nextProcessStep = processStep.Done
    
    # Summary - set summary
    if nextProcessStep == processStep.Summarize:
        nextProcessStep = processStep.Keywords

        """ Skip summarization for now
        changeBlinkRate(BLINK2)

        if args.summary == 0:
            # summarize the transcript
            summary = getSummary(transcript)

            if args.savefiles:
                f = open("history/" + filePrefix + timestr + "-summary" + ".txt", "w")
                f.write(summary)
                f.close()

        else:
            # use the text file specified by the transcript argument
            summaryFile = open(summaryArg, "r")
            # read the summary file
            summary = summaryFile.read()
            logger.info("Using summary file: " + summaryArg)
        
        changeBlinkRate(BLINK_STOP)
        """


    # Keywords - set keywords
    if nextProcessStep == processStep.Keywords:

        changeBlinkRate(BLINK3)

        #if not settings.isAudioKeywords:
        # does transcript contain more than 20 blank spaces?
        if transcript.count(" ") > 20:
            # extract the keywords from the summary
            keywords = getAbstractForImageGen(transcript) 
            logToFile.info("Keywords: " + keywords)

            if settings.isSaveFiles:
                f = open("history/" + filePrefix + timestr + "-keywords" + ".txt", "w")
                f.write(keywords)
                f.close()
        else:
            keywords = transcript
        
        changeBlinkRate(BLINK_STOP)
        nextProcessStep = processStep.ImageCreate

    # Image - set imageURL
    if nextProcessStep == processStep.ImageCreate:

        changeBlinkRate(BLINK4)

        # use the keywords to generate images
        try:
            imagesInfo = getImageURL(keywords)

            imageURLs = imagesInfo[0]
            imageModifiers = imagesInfo[1]

            # combine the images into one image
            newImageFileName = postProcessImages(imageURLs, imageModifiers, keywords, timestr, filePrefix)

            imageURLs = "file://" + os.getcwd() + "/" + newImageFileName
            logger.debug("imageURL: " + imageURLs)

            logToFile.info("Image file: " + newImageFileName)

            if gw.useS3:
                 result = upload_to_s3_and_generate_qr( file_path = newImageFileName, S3_dir= "idleDisplayFiles")

            changeBlinkRate(BLINK_STOP)
            nextProcessStep = processStep.DisplayImage  

        except Exception as e:

            print ("AI Image Error: " + str(e))
            logToFile.info("AI Image Error: " + str(e), exc_info=True)

            error_text = str(e)
            error_text_lower = error_text.lower()

            if 'insufficient_quota' in error_text_lower or 'rate limit' in error_text_lower or 'error code: 429' in error_text_lower:
                msg = (
                    "OpenAI API quota/rate limit reached. "
                    "Please check your OpenAI billing/quota, then try again."
                )
            elif 'content_policy_violation' in error_text:
                # this is a common error, so we'll display a message to the user
                msg = f'The AI Safety System rejected this prompt. Please try again.'
            elif 'safety' in error_text_lower:
                msg = f'The AI Safety System rejected this prompt. Please try again.'
            elif 'something went wrong' in error_text_lower:
                msg = f'Something went wrong with the OpenAI image generation.  Please try again'
            elif 'server had an error' in error_text_lower:
                msg = f'OpenAI had an unspecified server error.  Please try again'
            else:
                msg = f'We had an error:\n\r "{str(e)}" \n\r\n\rPlease try again.'

            display_text_in_message_window(msg, labelForMessageDisplay)
            # Wait 10 seconds while keeping the GUI responsive so the
            # window renders properly and hide() works correctly.
            for _ in range(100):
                QtWidgets.QApplication.processEvents()
                time.sleep(0.1)
            display_text_in_message_window()  # Hide the message window
            update_main_window()

            changeBlinkRate(BLINK_STOP)
            nextProcessStep = processStep.Done  
        


    # Display - display imageURL
    if nextProcessStep == processStep.DisplayImage:
        changeBlinkRate(BLINK_SLOW)
        logger.info("Displaying image...")

        try:
            display_image(newImageFileName, labelForImageDisplay, labelQRForImage, labelQRForImageText)
            display_text_in_message_window() # Hide the message window
        except Exception as e:
            logger.error("Error displaying image: " + newImageFileName, exc_info=True)
            logger.error(e)
    
        update_main_window()
        
        changeBlinkRate(BLINK_STOP)
        nextProcessStep = processStep.Done

    if nextProcessStep == processStep.Done:
        # done with processing
        pass

    return 


def main():
    # ----------------------
    # main program starts here
    #
    #
    # ----------------------

    global gw # so that the changes made in here will affect the global variables

    # --- Startup dependency check ----------------------------------------------
    if not check_dependencies():
        print("\nFATAL: One or more required dependencies are missing.")
        print("Please fix the errors above and try again.")
        sys.exit(1)

    # create a directory if one does not exist
    if not os.path.exists("history"):
        os.makedirs("history")
    if not os.path.exists("errors"):
        os.makedirs("errors")
    if not os.path.exists("idleDisplayFiles"):
        os.makedirs("idleDisplayFiles")
    if not os.path.exists("addToIdleDisplayFiles"):
        os.makedirs("addToIdleDisplayFiles")

    # read configuration file
    if os.path.exists('s2pconfig.json'):
        with open('s2pconfig.json') as f:
            app_config = json.load(f)
    else:
        # create a default config file
        # three random characters to make the file name unique
        randomString = ''.join(random.choices(string.ascii_uppercase, k=3))
        app_config = {
            "Installation Id": randomString
        }
        writeToFile = open('s2pconfig.json', 'w')
        json.dump(app_config, writeToFile)
        writeToFile.close()

    # this prefix is prepended to all files saved to allow us to know the source system
    # when combining files from multiple systems
    filePrefix = app_config['Installation Id'] + "-"

    # args
    settings = parseCommandLineArgs() # get the command line arguments
    gw.useS3 = settings.useS3         # useS3 added to globals so it can be used as a switch in image creation and display 
    gw.kiosk_mode = settings.kiosk_mode
    gw.single_image = settings.single_image
 
    # create the main window
    labelForImageDisplay, labelQRForImage, labelQRForImageText = create_main_window(settings.isUsingHardwareButtons)

    display_random_history_image(labelForImageDisplay, labelQRForImage, labelQRForImageText) # display a random image

    # create the message window
    labelForMessageDisplay = create_message_window()
    gw.labelForMessage = labelForMessageDisplay  # store so getImageURL can use it
    display_text_in_message_window() # hide the message window

    # create the status window
    labelForStatusDisplay = create_status_window()
    display_text_in_status_window() # hide the status window

    # capture a second of audio to initialize driver on RPi
    recordAudioFromMicrophone(.25)

    # ----------------------
    # Main Loop 
    #

  
    settings.autoLoopDelay = 60 # delay between loops in seconds

    randomDisplayMode = True 

    lastCommandTime = 0

    display_random_history_image(labelForImageDisplay, labelQRForImage, labelQRForImageText)

    while not gw.isQuitting:

        executeImageGeneration = True

        if settings.nextProcessStep > processStep.CaptureAudio:

            # we have file parameters, so only loop once
            settings.numLoops = 1
            settings.autoLoopDelay = 1   # no delay if we're not looping XXX

        else:
            # no command line input parameters so get a command from the user

            if not settings.isUsingHardwareButtons: 
                # print menu
                print("\r\n\n\n")
                print("Commands:")
                print("   o: Once, record and display; default")
                print("   a: Auto mode, record, display, and loop")
                if not config.isMacOS:
                    # running on RPi
                    print("   h: Hardware control")
                print("   q: Quit")

                inputCommand = ''
                while inputCommand == '' and not gw.isQuitting:
                    
                    if select.select([sys.stdin], [], [], 0)[0]:
                        while sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                            inputCommand += sys.stdin.read(1)
                        # remove whitespace
                        inputCommand = inputCommand.strip()

                        randomDisplayMode = False  # we have command input
                        print("Command input: " + inputCommand)
                        if inputCommand == 'h':
                            # not in the menu except on RPi
                            # don't ask the user for input again, rely on hardware buttons
                            settings.isUsingHardwareButtons = True
                            print("\r\nHardware control enabled")

                        elif inputCommand == 'q': # quit
                            gw.isQuitting = True
                            settings.numLoops = 0
                            settings.autoLoopDelay = 0

                        elif inputCommand == 'a': # auto mode
                            settings.numLoops = LOOPS_MAX
                            print("Will loop: " + str(settings.numLoops) + " times")

                        elif inputCommand == 'o': # once
                            lastCommandTime = time.time()
                            settings.nextProcessStep = processStep.CaptureAudio
                            settings.numLoops = 1
                            settings.autoLoopDelay = 0

                        elif inputCommand == 'x': # experimental for testing out new features
                            lastCommandTime = time.time()
                            voice_command_functions["show status"](labelForStatusDisplay)
                            executeImageGeneration = False
                            
                        else: # default is no action
                            print("No action input " + inputCommand)
                            inputCommand = ''

                    # if the last command was more than 90 seconds ago
                    if (time.time() - lastCommandTime > 90):
                        lastCommandTime = time.time()
                        randomDisplayMode = True 

                    if randomDisplayMode:
                        display_random_history_image(labelForImageDisplay, labelQRForImage, labelQRForImageText)

                    update_main_window()


            # we can't use else from the if above because the command menu input might set this value
            if settings.isUsingHardwareButtons:
                # we're not going to prompt the user for input, rely on hardware buttons
                isButtonPressed = False

                while not isButtonPressed:
                    # running on RPi
                    update_main_window()
                    # read gpio pin, if pressed, then do a cycle of keyword input
                    if GPIO.input(BUTTON_GO) == BUTTON_PRESSED:
                        settings.isAudioKeywords = True
                        settings.numLoops = 1
                        isButtonPressed = True
                        lastCommandTime = time.time()
                        randomDisplayMode = False
                        logToFile.info("Button pressed")
                        settings.nextProcessStep = processStep.CaptureAudio

                    else:
                        # if the last command was more than 90 seconds ago, then display history
                        if (time.time() - lastCommandTime > 90):
                            lastCommandTime = time.time()
                            randomDisplayMode = True 
                            
                    if randomDisplayMode:
                        display_random_history_image(labelForImageDisplay, labelQRForImage, labelQRForImageText)


        if settings.isAudioKeywords: 
            # we are not going to extract keywords from the transcript
            settings.duration = 10

        # we have a command. Either a command line file argument, a menu command, or a button press
        if executeImageGeneration:

            # loop through a number of picture generation cycles
            for i in range(0, settings.numLoops, 1):
                # this is where all the work happens
                # collect audio, transcribe, summarize, extract keywords, generate images, display images
                try:
                    audioToPicture(settings, labelForImageDisplay, labelForMessageDisplay, labelForStatusDisplay, filePrefix, labelQRForImage, labelQRForImageText)  # XXX
                except Exception as e:
                    error_text = str(e)
                    error_text_lower = error_text.lower()

                    if ('insufficient_quota' in error_text_lower
                        or 'rate limit' in error_text_lower
                        or 'error code: 429' in error_text_lower):
                        msg = (
                            "OpenAI API quota/rate limit reached. "
                            "Please check your OpenAI billing/quota, then try again."
                        )
                        display_text_in_message_window(msg, labelForMessageDisplay)

                        # Keep GUI responsive while message is shown.
                        for _ in range(100):
                            QtWidgets.QApplication.processEvents()
                            time.sleep(0.1)

                        display_text_in_message_window()  # Hide the message window
                        update_main_window()
                        changeBlinkRate(BLINK_STOP)

                        logger.warning("Quota/rate-limit error handled without aborting program.", exc_info=True)
                    else:
                        raise

                if not settings.isUsingHardwareButtons and settings.numLoops > 1: 
                    # delay before the next for loop iteration, we don't do this when using hardware buttons
                    print("delaying " + str(settings.autoLoopDelay) + " seconds...")
                    time.sleep(settings.autoLoopDelay)            

            # Reset the history-display timer so the generated image stays
            # on screen for 90 seconds before history images resume.
            lastCommandTime = time.time()
            randomDisplayMode = False            

        # let the Qt window events happen
        update_main_window()

        if settings.nextProcessStep in {processStep.UseAudioFile, processStep.UseTranscriptFile, 
                                        processStep.UseSummaryFile, processStep.UseKeywordsFile, 
                                        processStep.UseImageFile}:
            # we're done with the command line file argument
            gw.isQuitting = True 
            print("Done with command line file argument. Pause for 15 seconds.")
            time.sleep(15)
        
        # end of loop

    # all done
    if led_thread1 is not None:
        # running on RPi
        # Stop the LED thread
        changeBlinkRate(BLINK_DIE)
        led_thread1.join()

        # Clean up the GPIO pins
        GPIO.cleanup()

    # exit the program
    print("\r\n")


'''
Beginning of execution
'''
logToFile.info("Starting Speech2Picture")

try:
    main()
except Exception as e:
    print("\n\n\n")
    print(e)
    print("\n\n\n")
    logToFile.error(e, exc_info=True)

exit()











