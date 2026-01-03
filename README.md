# speech2picture
Use your voice and OpenAI to make new art. Or, monitor an ongoing conversation
and have the picture frame change to reflect the conversation - an
eveasdropping picture frame!

A video of this project in action: https://www.youtube.com/watch?v=Wzuj7Vhyl8w

A full write up: https://www.jimschrempp.com/features/computer/speech_to_picture.htm

Based on the WhisperFrame project idea on Hackaday.  
https://hackaday.com/2023/09/22/whisperframe-depicts-the-art-of-conversation/

- Python code to record audio from the default microphone and 
- transcribe it using OpenAI
- summarize the transcript 
- generate 4 pictures based on the summary and combine them into one
- open the picture
- delay for 60 seconds
- repeat the process 10 times

Runs on Mac OSX and Raspberry Pi. RPi has the option to trigger the process with a button. Includes
"kiosk" mode so the RPi will boot into a running session, ready for a button press.

## Installation

### Prerequisites
- Python 3.8 or higher
- OpenAI API key (set as environment variable `OPENAI_API_KEY`)
- For AWS S3 features: AWS account with S3 bucket configured (see [s3_and_qr_readme.txt](s3_and_qr_readme.txt))

### Setup

1. Clone this repository:
   ```bash
   git clone https://github.com/jschrempp/speech2picture.git
   cd speech2picture
   ```

2. Create and activate a virtual environment (recommended):
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   
   **For macOS:**
   ```bash
   pip install -r requirements.txt
   ```
   
   **For Raspberry Pi:**
   ```bash
   pip install -r requirements.txt
   ```
   Note: On Raspberry Pi, you may need to install additional system packages:
   ```bash
   sudo apt-get install portaudio19-dev python3-pyaudio
   ```
   Also add your user to the audio group:
   ```bash
   sudo usermod -a -G audio $USER
   ```

4. Set up your OpenAI API key:
   ```bash
   export OPENAI_API_KEY='your-api-key-here'
   ```
   Or add it to your shell profile for persistence.

5. (Optional) For AWS S3 features:
   - Follow instructions in [s3_and_qr_readme.txt](s3_and_qr_readme.txt)
   - Create `s3_info-user.json` with your AWS credentials

Author: Jim Schrempp 2023 

## Usage

To run:  python3 pyspeech.py

- control-c to stop the program or it will end after loopsMax loops about (duration + delay)*loopsMax seconds
- control-h to see all command line options

## Command Line Options

Useful options:

-d [0,1,2] Level 0 has progress messages. Level 1 lists returns from OpenAI. Level 2 is a trace.

-s Save all the intermediate files in the history/ folder (images are saved in all cases)

-o Only Keywords ... The audio transcript is passed directly to the image generation service
   without any interpretation. Useful mostly for 10 second audio recording to let people speak
   a few words and get a picture from it. 

-h Hardware ... Goes into a loop waiting for a button to be pressed (a pin to be pulled low)

-g Goes into Kiosk mode, useful for autostart installations. If the program goes full screen
   then use ESC to kill it.

-q Store images in AWS S3 cloud and display QR codes (requires AWS setup)

Command line options exist to let you pass in an existing file to one of the steps. For instance, if you want to experiment with how the final image files are displayed, -i <filename> will jump right to that step so you don't have to do all the previous steps.

## Examples

Typical execution:
   ```bash
   python3 pyspeech.py -o
   ```

To run this you need to get an OpenAI API key and set it as an environment variable OPENAI_API_KEY. See Installation section above for details.

Kiosk hardware set up:  
https://github.com/jschrempp/speech2picture/wiki

## Important Notes

### Microphone Permissions
ALSO NOTE: If you are not getting any audio, then you may not have given the program permission to access your microphone.

- **On macOS**: Go to Settings / Privacy & Security / Microphone and ensure Terminal (or your terminal app) has permission. See: https://superuser.com/questions/1441270/apps-dont-show-up-in-camera-and-microphone-privacy-settings-in-macbook
- **On Raspberry Pi**: Add your user to the "audio" group:
  ```bash
  sudo usermod -a -G audio $USER
  ```

### Image Content Safety
### Image Content Safety

NOTE: With the Jan 8, 2024 commit there has been a significant change. We have found that OpenAI can 
occasionally create offensive images. For that reason we have changed how the idle display of images
works. Random images are now displayed from the `./idleDisplayFiles` folder. New images are automatically
saved in the `./history` folder. As a result, new images will not be in the idle display rotation. We 
suggest that you periodically review the files in the `./history` folder and move acceptable images into
the `./idleDisplayFiles` folder.

### Managing Images Remotely

We suggest that you periodically look at the new files, remove any offensive ones, and add them to the 
list of files for idle display. To do this remotely:

1. `mkdir temp`
2. `cd temp`
3. `scp -r <user>@<ip address>:~/speech2picture/history .`
4. Examine the files you just downloaded and remove any you have concerns about
5. `scp -r . <user>@<ip address>:~/speech2picture/idleDisplayFiles`

If you are using the s3 option to store the files with a QR code, then instead 
copy new files to the folder addToIdleDisplayFiles and then run 
   python s3_and_qr.py
to copy the files to AWS s3 and generate QR codes.

## Cost
OpenAI currently costs a few pennies to use. Running this for an hour typically costs around $1.00 depending on usage.

## Credits
Based on the WhisperFrame project idea on Hackaday:  
https://hackaday.com/2023/09/22/whisperframe-depicts-the-art-of-conversation/
