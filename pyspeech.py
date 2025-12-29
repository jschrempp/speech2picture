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
        python3 -m venv .venv
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
        pip install openai 
        pip install pillow
        pip install pyaudio
        pip install RPi.GPIO
        pip install boto3       needed only if you are going to use teh -q option to store finished images in the AWS S3 cloud
        pip install qrcode      needed if you are using the -q option and S3 to enable instant downloads via QR code

    Note that when run you will see 10 or so lines of errors about sockets and JACKD and whatnot.
    Don't worry, it is still working. If you know how to fix this, please let me know.

    Also note that errors from the audio subsystem are ignored in recordAudioFromMicrophone(). If 
    you are having some real audio issue, you might change the error handler to print the errors.

    If you want to make this run on boot, then see the comments in s2p.desktop
    
Author: Jim Schrempp 2023 

Version History of significant changes:

v 1.0 consolidated GUI into one window using tkinter grid and a pop up to show the transcript
v 0.8 added "without any text or writing in the image" to the image prompt
v 0.7 more code cleanup, improved image resizing for display size
      added QR code
v 0.6 added -g for gokiosk mode
v 0.5 Initial version
v 0.6 2023-11-12 inverted Go Button logic so it is active low (pulled to ground)
v 0.7 updated to python 3.12 and openAI 1.0.0 (wow that was a pain)
      BE SURE to read updated install instructions above
v 1.2 Added capability to store images created in the AWS S3 cloud and display a QR code to them for instant download
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
import select
import sys
import random
import tkinter as tk
import json
import string
from enum import IntEnum
from PIL import Image, ImageDraw, ImageFont, ImageTk
from s3_and_qr import upload_to_s3_and_generate_qr

import openai
S2P_VERSION = "1.2"

g_isMacOS = False
if (platform.system() == "Darwin"):
    g_isMacOS = True
else:
    print ("Not MacOS")

# import platform specific libraries
if g_isMacOS:
    import sounddevice
    import soundfile

else:
    # --------- import for Raspberry Pi -----------------------------------------
    import pyaudio
    import wave
    from ctypes import *
    import RPi.GPIO as GPIO
    import threading
    from queue import Queue



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
    "as a painting by Picasso",
    "as a watercolor by Picasso",
    "as a sketch by Picasso",
    "as a vivid color painting by Monet",
    "as a painting by Van Gogh",
    "as a painting by Dali",
    "in the style of Escher",
    "in the style of Rembrandt",
    "as a photograph by Ansel Adams",
    "as a painting by Edward Hopper",
    "as a painting by Norman Rockwell",
    "in the style of steam punk",
    "in the style of abstract expressionism",
    "in the style of pop art",
    "in the style of impressionism",
    "in the style of Gustav Klimt",
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

if not g_isMacOS:
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


# create root window for display and hide it
root = tk.Tk()
root.withdraw()  # Hide the root window


if not g_isMacOS:
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
    # Communicate by putting a tuple of (onTime, offTime) in the qBlinkControl queue
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
    if not g_isMacOS:
        ipMsg = "IP Address: " + os.popen('hostname -I').read()
        print(ipMsg)
    else:
        print ("IP address is not available on macOS.")
        ipMsg = ""

    directory = "history"
    for dirpath, dirnames, historyFiles in os.walk(directory):
        print(f"Number of files in {dirpath}: {len(historyFiles)}")

    pngFiles = [os.path.join('history',file) for file in historyFiles if file.endswith(".png")]
    numPngFiles = len(pngFiles)
    print("Number of PNG files in history: " + str(numPngFiles))
    historyCount = "Number of files in history: " + str(len(historyFiles))
    print(historyCount)

    # get the creation date of the oldest png file in the history directory
    oldestFile = min(pngFiles, key=os.path.getctime)
    oldestFileTimestamp = os.path.getctime(oldestFile)
    oldestFileDate = datetime.datetime.fromtimestamp(oldestFileTimestamp)
    oldestFileDateFormatted = oldestFileDate.strftime("%m-%d-%Y")
    # get the creation date of oldestFile   
    oldestFileDate = "Oldest file in history: " + oldestFileDateFormatted
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
    '''change the LED blink rate. This routine isolates the RPi specific code'''
    if not g_isMacOS:
        # running on RPi
        qBlinkControl.put(blinkRate)
    else:
        # not running on RPI so do nothing
        pass


def recordAudioFromMicrophone(duration):
    '''record duration seconds of audio from the default microphone to a file and return the sound file name'''

    soundFileName = 'recording.wav'
    
    # delete file recording.wav if it exists
    try:
        os.remove(soundFileName)
    except:
        pass # do nothing   
    
    if g_isMacOS:
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

    else:

        # RPi
 
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
    '''get images and return the urls'''

    # pick random modifiers
    random.shuffle(IMAGE_MODIFIERS)
  
    # create the prompt for the image generator
    modifierUsed = IMAGE_MODIFIERS[0]
    # if phrase contains stylistic information
    if ("in the style of" in phrase.lower() 
            or "as a painting by" in phrase.lower() 
            or "as a photograph by" in phrase.lower() 
            or "as a sketch by" in phrase.lower() 
            or "as a watercolor by" in phrase.lower()):
        modifierUsed = ""
        prompt = f"Generate a picture WITHOUT ANY TEXT OR WRITING IN THE PICTURE for the following: '{phrase}'"
    else:
        # add a random modifier to the prompt
        prompt = f"Generate a picture {modifierUsed} WITHOUT ANY TEXT OR WRITING IN THE PICTURE for the following: '{phrase}'"

    logger.info("Generating image...")
    logger.info("image prompt: " + prompt)

    # use openai to generate a picture based on the summary
    if not gw.single_image:
        try:
            responseImage = client.images.generate(
                prompt= prompt,
                n=4,
                size="512x512")
        except Exception as e:
            print("\n\n\n")
            print(e)
            print("\n\n\n")
            raise (e)
            
        loggerTrace.debug("responseImage: " + str(responseImage))

        image_url = [responseImage.data[0].url] * 4
        image_url[1] = responseImage.data[1].url
        image_url[2] = responseImage.data[2].url
        image_url[3] = responseImage.data[3].url
    
    else: 
        try:
            responseImage = client.images.generate(
                prompt= prompt,
                model = "dall-e-3",
                n=1,
                size="1024x1024"
                )
        except Exception as e:
            print("\n\n\n")
            print(e)
            print("\n\n\n")
            raise (e)
            
        loggerTrace.debug("responseImage: " + str(responseImage))

        image_url = [responseImage.data[0].url]

    return image_url, modifierUsed


def postProcessImages(imageURLs, imageModifiers, keywords, timestr, filePrefix):
    '''reformat the images for display and return the new file name'''

    # save the images from a urls into imgObjects[]
    imgObjects = []
    for numURL in range(len(imageURLs)):

        fileName = "history/" + "image" + str(numURL) + ".png"
        urllib.request.urlretrieve(imageURLs[numURL], fileName)

        img = Image.open(fileName)

        imgObjects.append(img)

    # combine the images into one image
    #widths, heights = zip(*(i.size for i in imgObjects))
    if not gw.single_image:
        total_width = 512*2
        max_height = 512*2 + 50
        new_im = Image.new('RGB', (total_width, max_height))
        locations = [(0,0), (512,0), (0,512), (512,512)]
        count = -1
        for loc in locations:
            count += 1
            new_im.paste(imgObjects[count], loc)
    else:
        total_width = 1024
        max_height = 1024 + 50
        new_im = Image.new('RGB', (total_width, max_height))
        new_im.paste(imgObjects[0], (0,0))


    # add text at the bottom
    imageCaption = f'{keywords} {imageModifiers}'
    draw = ImageDraw.Draw(new_im)
    draw.rectangle(((0, new_im.height - 50), (new_im.width, new_im.height)), fill="black")
    font = ImageFont.truetype("arial.ttf", 18)
    # decide if text will exceed the width of the image
    #textWidth, textHeight = font.getsize(text)
    draw.text((10, new_im.height - 30), imageCaption, (255,255,255), font=font)

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
        #width, height = font.getsize(line)
        #draw.text(((new_im.width - width) / 2, y_text), line, font=font) 
        #y_text += height
        height = 25
        draw.text((100, y_text), line, font=font) 
        y_text += height

    #draw.text((10, new_im.height/2), imageCaption, (255,255,255), font=font)

    # save the new image
    newFileName = "errors/" + timestr + "-imageERROR" + ".png"
    new_im.save(newFileName)

    return newFileName

''' 
Window functions
'''
def create_main_window(usingHardwareButton):
    '''
    Create the main window and return the label to display the images
    '''
    global gw   # so that the changes made in here will affect the global variable

    gw.windowMain = tk.Toplevel(root)
    gw.windowMain.title("Speech 2 Picture")
    gw.windowMain.protocol("WM_DELETE_WINDOW", quitButtonPressed)
    
    gw.windowMain.configure(bg='#52837D')
    if gw.kiosk_mode:
        import time
        time.sleep(.5)
        gw.windowMain.attributes("-fullscreen", True)
    else:
        print ("mike - not running in kiosk mode, don't fill the screen")
        # find the screen size and center the window
        screen_width = gw.windowMain.winfo_screenwidth()
        screen_height = gw.windowMain.winfo_screenheight()
        # gw.windowMain.minsize(int(screen_width*.8), int(screen_height*.9))
        #set window size to a bit less than full screen
        gw.windowMain.geometry(str(int(screen_width*.95)) + "x" + str(int(screen_height*.95)))
        #set window position
        gw.windowMain.geometry("+%d+%d" % (screen_width*0.02, screen_height*0.02))
    

    
   
    # Instructions text
    if gw.useS3:  QR_download_text = " Scan the QR to download."  # only show this is the QR for downloading is being displayed.
    else:         QR_download_text = ""

    INSTRUCTIONS_TEXT = ('\r\nTRY ME NOW !\rAn Interactive Art Exhibit\n\rWhen you are ready, press and release the'
                    + ' button. The light will flash quickly. You will have 10 seconds to speak a few words to use to'
                    + ' make an AI image. Then wait.'
                    + ' Images will appear shortly.'
                    + QR_download_text
                    + '\r\nUntil then, enjoy some previous "promptography" images!')

    labelTextLong = tk.Label(gw.windowMain, text=INSTRUCTIONS_TEXT, 
                     font=("Helvetica", 28),
                     justify=tk.CENTER,
                     wraplength=450,
                     bg='#52837D',
                     fg='#FFFFFF',
                     )

    # add the QR to the window
    imgQR = Image.open("S2PQR.png")
    imgQR = imgQR.resize((150,150), Image.NEAREST)
    photoImage = ImageTk.PhotoImage(imgQR)
    labelQR = tk.Label(gw.windowMain,
                    image=photoImage,
                    bg='#52837D')
    labelQR.image = photoImage  # Keep a reference to the image to prevent it from being garbage collected

    # add QR instructions to the window
    labelQRText = tk.Label(gw.windowMain, text="Scan this QR code for more instructions and tips.", 
                     font=("Helvetica", 18),
                     justify=tk.LEFT,
                     wraplength=280,
                     bg='#52837D',
                     fg='#FFFFFF',
                     )

    # add credits to the window
    labelCreditsText = tk.Label(gw.windowMain, text="Created by Jim Schrempp at Maker Nexus in Sunnyvale, California." ,
                     font=("Helvetica", 18),
                     justify=tk.LEFT,
                     wraplength=300,
                     bg='#52837D',
                     fg='#FFFFFF',
                     )

    # add a quit button to the window
    buttonQuit = tk.Button(gw.windowMain, text="Quit", command=quitButtonPressed,
                            font=("Helvetica", 24), 
                            bg='#FF0000', fg='#000000')


    labelCommandHint = tk.Label(gw.windowMain, text="Say 'show commands' for a list of commands.",
                     font=("Helvetica", 18),
                     justify=tk.LEFT,
                     wraplength=300,
                     bg='#52837D',
                     fg='#FFFFFF',
                     )
    labelCommandHint = tk.Label(gw.windowMain, text="show commands  v: " + S2P_VERSION, font=("Helvetica", 12),
                     justify=tk.LEFT, wraplength=300, bg='#52837D', fg='#FFFFFF')

    # add a label to display the images
    labelForImage = tk.Label(gw.windowMain)
    
    # The label will be dimensioned when the image is loaded
    labelForImage.configure(bg='#000000', highlightcolor="#f4ff55", 
                                highlightthickness=10,) 
    
    if gw.useS3:
        # add a label to display the QRcode for the image
        labelQRForImage = tk.Label(gw.windowMain)
        
        # The label will be dimensioned when the image is loaded
        labelQRForImage.configure(bg='#000000')
    else: labelQRForImage = None

    
    # set up the grid
    gw.windowMain.grid_columnconfigure(0, weight=99, minsize=0)
    gw.windowMain.grid_columnconfigure(1, weight=99, minsize=10)
    gw.windowMain.grid_columnconfigure(2, weight=2,  minsize=100)
    gw.windowMain.grid_columnconfigure(3, weight=2,  minsize=100)
    gw.windowMain.grid_columnconfigure(4, weight=99, minsize=10)
    gw.windowMain.grid_columnconfigure(5, weight=99, minsize=10)
    gw.windowMain.grid_columnconfigure(6, weight=1)
    gw.windowMain.grid_columnconfigure(7, weight=99, minsize=10)

    labelTextLong.grid(   row=0, column=1, columnspan=4, padx=(0,0),            sticky=tk.EW)
    labelForImage.grid(   row=0, column=6, rowspan=5,    padx=(0,0),   pady=10, sticky=tk.NSEW)
    if gw.useS3: 
        if gw.single_image:
            labelQRForImage.grid( row=0, column=6, rowspan=5,    padx=(0,0),   pady=10, sticky=tk.NW)
        else:
            labelQRForImage.grid( row=0, column=6, rowspan=5,    padx=(0,0),   pady=10)
    

    labelQR.grid(         row=1, column=2,               padx=(0,10),  pady=10, sticky=tk.NSEW)
    labelQRText.grid(     row=1, column=3,               padx=(10,0),  pady=10, sticky=tk.W)
    labelCreditsText.grid(row=2, column=1, columnspan=4, padx=0,       pady=10, sticky=tk.W)
    buttonQuit.grid(      row=3, column=2, columnspan=3, padx=0,       pady=20, sticky=tk.E)
    labelCommandHint.grid(row=4, column=0, columnspan=3, padx=10,      pady=10, sticky=tk.W)

    if usingHardwareButton:
        # remove button from the window
        buttonQuit.grid_remove()

    '''
    # good debug code
    # add a border around all the widgets
    for widget in [labelTextLong, labelQR, labelQRText, labelCreditsText, buttonQuit, labelCommandHint]:
        widget.configure(highlightcolor="#f4ff55", highlightthickness=10)
    '''

    update_main_window()

    return labelForImage, labelQRForImage
   

def update_main_window():
    global gw

    gw.windowMain.update_idletasks()
    gw.windowMain.update()

def quitButtonPressed():
    '''quit the program'''
    global gw

    gw.isQuitting = True
    gw.windowMain.destroy()
    gw.windowForMessages.destroy()
    exit(0)

def create_message_window():
    '''
    create a window to display the messages; return a label to display the images
    '''
    global gw  # so that the changes made in here will affect the global variable
    
    gw.windowForMessages = tk.Toplevel(root, bg='#555500',
                                      highlightcolor="#550055", 
                                      highlightthickness=20)
    gw.windowForMessages.title("Messages")

    # center this window over the image window
    messageWindowWidth = 500
    messageWindowHeight = 500
    messageWindowX = gw.windowMain.winfo_x() + (0.5*gw.windowMain.winfo_width()) - (0.5*messageWindowWidth)
    messageWindowY = gw.windowMain.winfo_y() + (0.5*gw.windowMain.winfo_height()) - (0.5*messageWindowHeight)
    gw.windowForMessages.geometry("+%d+%d" % (messageWindowX,messageWindowY)) 
    gw.windowForMessages.minsize(messageWindowWidth, messageWindowHeight)
    gw.windowForMessages.maxsize(messageWindowWidth, messageWindowHeight)

    # print("message window x: " + str(messageWindowX))
    # print("message window y: " + str(messageWindowY))

    # Make cell column 0 row 0 expand to fill the window
    gw.windowForMessages.grid_columnconfigure(0, weight=1) 
    gw.windowForMessages.grid_rowconfigure(0, weight=1)


    frameForMessage  = tk.Frame(gw.windowForMessages, bg='#ff0000',
                                highlightcolor="#ffff55", 
                                highlightthickness=2)
    frameForMessage.grid(row=0, column=0, sticky=tk.NSEW)
    # make cell column 0 row 0 expand to fill the frame
    frameForMessage.grid_columnconfigure(0, weight=1)
    frameForMessage.grid_rowconfigure(0, weight=1)

    labelTextLong = tk.Label(frameForMessage,
                     font=("Helvetica", 28),
                     justify=tk.CENTER,
                     wraplength=messageWindowWidth-80,
                     bg='#FFFFFF',
                     fg='#000000',
                     )

    # have the label fill the cell  
    labelTextLong.grid(column=0, row=0, ipadx=5, ipady=5, sticky=tk.NSEW, )

    gw.windowForMessages.attributes('-topmost', 1)  # Make the window always appear on top
    gw.windowForMessages.withdraw()  # Hide the window until needed

    return labelTextLong

def create_status_window():
    '''
    create a window to display the status messages; return a label to display the images
    '''
    global gw  # so that the changes made in here will affect the global variable
    
    gw.windowForStatus = tk.Toplevel(root, bg='#555500',
                                      highlightcolor="#550055", 
                                      highlightthickness=20)
    gw.windowForStatus.title("Status")

    # center this window over the image window
    statusWindowWidth = 800
    statusWindowHeight = 600
    statusWindowX = int(gw.windowMain.winfo_x() + (0.5*gw.windowMain.winfo_width()) - (0.5*statusWindowWidth))
    statusWindowY = int(gw.windowMain.winfo_y() + (0.5*gw.windowMain.winfo_height()) - (0.5*statusWindowHeight))
    #gw.windowForStatus.geometry("+%d+%d" % (statusWindowX,statusWindowY)) 
    gw.windowForStatus.geometry("+%d+%d" % (200,200)) 
    gw.windowForStatus.minsize(statusWindowWidth, statusWindowHeight)
    gw.windowForStatus.maxsize(statusWindowWidth, statusWindowHeight)

    # print ("statusWindowX: " + str(statusWindowX))
    # print ("statusWindowY: " + str(statusWindowY))

    # Make cell column 0 row 0 expand to fill the window
    gw.windowForStatus.grid_columnconfigure(0, weight=1) 
    gw.windowForStatus.grid_rowconfigure(0, weight=1)

    frameForMessage  = tk.Frame(gw.windowForStatus, bg='#ff0000',
                                highlightcolor="#ffff55", 
                                highlightthickness=2)
    frameForMessage.grid(row=0, column=0, sticky=tk.NSEW)
    # make cell column 0 row 0 expand to fill the frame
    frameForMessage.grid_columnconfigure(0, weight=1)
    frameForMessage.grid_rowconfigure(0, weight=1)

    labelTextLong2 = tk.Label(frameForMessage,
                     font=("Helvetica", 24),
                     justify=tk.LEFT,
                     wraplength=statusWindowWidth-80,
                     bg='#FFFFFF',
                     fg='#000000',
                     text="initial test message",
                     )

    # have the label fill the cell  
    labelTextLong2.grid(column=0, row=0, ipadx=5, ipady=5, sticky=tk.NSEW, )

    gw.windowForStatus.attributes('-topmost', 1)  # Make the window always appear on top
    gw.windowForStatus.withdraw()  # Hide the window until needed

    return labelTextLong2



def display_text_in_status_window(message=None, labelToUse=None):
    '''
    display message in the status window
    if labelToUse is None, then hide the window
    '''
    global gw
      
    if (labelToUse is None):
        gw.windowForStatus.withdraw() # Hide the message window
        
    else:
        labelToUse.configure(text=message,)
        gw.windowForStatus.deiconify() # Show the window now that it has a message

    gw.windowForStatus.update_idletasks()
    gw.windowForStatus.update()

    display_text_in_message_window()
    gw.windowForMessages.update_idletasks()
    gw.windowForMessages.update()


def display_text_in_message_window(message=None, labelToUse=None):
    '''
    display message in the message window
    if labelToUse is None, then hide the window
    '''
    global gw
      
    if (labelToUse is None):
        gw.windowForMessages.withdraw() # Hide the message window
        
    else:
        labelToUse.configure(text=message,)
        gw.windowForMessages.deiconify() # Show the window now that it has a message

    gw.windowForMessages.update_idletasks()
    gw.windowForMessages.update()


def display_image(image_path, label=None, labelQR = None):
    '''
    display an image in the window using the label object
    '''

    global gw

    logger.debug("display_image: " + image_path)
    logToFile.debug("display_image: " + image_path)

    if label is None:
        print("Error: label is None")  
        return

    # Open an image file
    try:
        img = Image.open(image_path)
        #resize the image to fit the window
        resizeFactor = 0.95
        window_height = gw.windowMain.winfo_height()
        labelDimensions = int(window_height * resizeFactor)
        label.configure(width=labelDimensions, height=labelDimensions)
        
        new_width = int(labelDimensions * img.width / img.height)
        new_height = int(labelDimensions)
        img = img.resize((new_width,new_height), Image.NEAREST)

        # Convert the image to a PhotoImage
        photoImage = ImageTk.PhotoImage(img)
        label.configure(image=photoImage)
        label.image = photoImage  # Keep a reference to the image to prevent it from being garbage collected

        update_main_window()
        skip_QR = False

    except Exception as e:
        print("Error with image file: " + image_path)
        print(e)
        logger.error("Error with image file: " + image_path)
        logger.error(e)
        skip_QR = True

    #update QR label
    if labelQR and not skip_QR and gw.useS3: 
        QRFile = image_path.replace("-image.png", '-s3_url.jpg')
        if os.path.exists(QRFile):
            QRimg =  Image.open(QRFile)
            QR_resize = .15    # user 10% of full image space for the QR code
            QR_size = int( QR_resize * min(new_width, new_height))
            QRimg = QRimg.resize((QR_size, QR_size), Image.NEAREST)

            # conver to photoImage
            QR_photo = ImageTk.PhotoImage(QRimg)
            labelQR.configure(image = QR_photo)
            labelQR.image = QR_photo  # keep a reference to prevent garbage collection

            update_main_window()

    return label

def display_random_history_image(labelForImageDisplay, labelQRForImage = None):
    '''
    display a random image from the idleDisplayFiles in the window using the label object
    '''
    # static variable to hold last time an image was displayed
    if not hasattr(display_random_history_image, "lastImageDisplayedTime"):
        display_random_history_image.lastImageDisplayedTime = 0  # it doesn't exist yet, so initialize it

    if time.time() - display_random_history_image.lastImageDisplayedTime > 15:
        
        display_random_history_image.lastImageDisplayedTime =  time.time()

        # list all files in the idleDisplayFiles folder
        idleDisplayFolder = "./idleDisplayFiles"
        idleDisplayFiles = os.listdir(idleDisplayFolder)
        #remove any non-png files from Files
        imagesToDisplay = []
        for file in idleDisplayFiles:
            if file.endswith(".png"):
                #add to the list
                imagesToDisplay.append(file)
        random.shuffle(imagesToDisplay) # randomize the list
        display_image(idleDisplayFolder + "/" + imagesToDisplay[0], labelForImageDisplay, labelQRForImage)
        
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
    if args.use_s3: rtn.useS3 = True
    else:           rtn.useS3 = False

    # set flag for single large image (vs default of 4 small)
    if args.mono_image: rtn.single_image = True
    else:               rtn.single_image = False


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


def audioToPicture(settings, labelForImageDisplay, labelForMessageDisplay, labelForStatusDisplay, filePrefix, labelQRForImage = None ):
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

        # record audio from the default microphone
        display_text_in_message_window("Speak Now\r\nYou have 10 seconds", labelForMessageDisplay)
        if g_isMacOS: os.system('say "Recording."')
        soundFileName = recordAudioFromMicrophone(settings.duration)
        display_text_in_message_window("Recording Complete, now analyzing", labelForMessageDisplay)
        if g_isMacOS: os.system('say "Recording complete."')

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

            if 'content_policy_violation' in str(e):
                # this is a common error, so we'll display a message to the user
                msg = f'Content Policy Violation.  Your prompt may contain text that is not allowed by our safety system.'
            elif 'something went wrong' in str(e):
                msg = f'Something went wrong with the OpenAI image generation.  Please try again'
            elif 'server had an error' in str(e):
                msg = f'OpenAI had an unspecified server error.  Please try again'
            else:
                msg = f'We had an error:\n\r "{str(e)}" \n\r\n\rPlease try again.'

            display_text_in_message_window(msg, labelForMessageDisplay)
            time.sleep(5) # delay for 5 seconds
            display_text_in_message_window() # Hide the message window
            update_main_window()

            changeBlinkRate(BLINK_STOP)
            nextProcessStep = processStep.Done  
        


    # Display - display imageURL
    if nextProcessStep == processStep.DisplayImage:
        changeBlinkRate(BLINK_SLOW)
        logger.info("Displaying image...")

        try:
            display_image(newImageFileName, labelForImageDisplay, labelQRForImage)
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
            config = json.load(f)
    else:
        # create a default config file
        # three random characters to make the file name unique
        randomString = ''.join(random.choices(string.ascii_uppercase, k=3))
        config = {
            "Installation Id": randomString
        }
        writeToFile = open('s2pconfig.json', 'w')
        json.dump(config, writeToFile)
        writeToFile.close()

    # this prefix is prepended to all files saved to allow us to know the source system
    # when combining files from multiple systems
    filePrefix = config['Installation Id'] + "-"

    # args
    settings = parseCommandLineArgs() # get the command line arguments
    gw.useS3 = settings.useS3         # useS3 added to globals so it can be used as a switch in image creation and display 
    gw.kiosk_mode = settings.kiosk_mode
    gw.single_image = settings.single_image
 
    # create the main window
    labelForImageDisplay, labelQRForImage = create_main_window(settings.isUsingHardwareButtons)

    display_random_history_image(labelForImageDisplay, labelQRForImage) # display a random image

    # create the message window
    labelForMessageDisplay = create_message_window()
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

    display_random_history_image(labelForImageDisplay, labelQRForImage)

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
                if not g_isMacOS:
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
                        display_random_history_image(labelForImageDisplay, labelQRForImage)

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
                        display_random_history_image(labelForImageDisplay, labelQRForImage)


        if settings.isAudioKeywords: 
            # we are not going to extract keywords from the transcript
            settings.duration = 10

        # we have a command. Either a command line file argument, a menu command, or a button press
        if executeImageGeneration:

            # loop through a number of picture generation cycles
            for i in range(0, settings.numLoops, 1):
                # this is where all the work happens
                # collect audio, transcribe, summarize, extract keywords, generate images, display images
                audioToPicture(settings, labelForImageDisplay, labelForMessageDisplay, labelForStatusDisplay, filePrefix, labelQRForImage)  # XXX

                if not settings.isUsingHardwareButtons and settings.numLoops > 1: 
                    # delay before the next for loop iteration, we don't do this when using hardware buttons
                    print("delaying " + str(settings.autoLoopDelay) + " seconds...")
                    time.sleep(settings.autoLoopDelay)            

        # let the tkinter window events happen
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
    if not g_isMacOS:
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











