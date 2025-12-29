If you set the -q options on the command line, pyspeech.py will try to store each image 
it generates in amazon's  cloud storage site called AWS S3.  For this to work, you need 
to do three things:

1. Create an AWS account.
        Googling "how to set up free AWS account" can provide a good guide. 
        The amazon "free tier" should provide ltorage for lots of images. 

2. Set up "bucket" in AWS S3 to hold the files, that is public read access permissions
    2A. Create the S3 Bucket
        - Sign in to the AWS Management Console and navigate to the S3 service.
        - Click Create bucket.
        - Give your bucket a globally unique name (e.g., my-public-files-12345) and choose a region.
          ** You'll evntually need the bucket name and region when you set your environment variables **
        - Leave default settings for now and click Create bucket
    2B. Configure Bucket Permissions
        - Select your newly created bucket from the list.
        - Go to the Permissions tab.
        - Under Block public access (bucket settings), click Edit.
        - Uncheck Block all public access, then type confirm and click Save changes. 
    2C. Add a bucket policy to allow the public to download files
        - On the same Permissions tab, scroll down to Bucket policy and click Edit.
        - Paste the following JSON policy, replacing YOUR-BUCKET-NAME with your actual bucket name:
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                    "Sid": "PublicReadGetObject",
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": "s3:GetObject",
                    "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/*"
                    }
                ]
                }
        - Click Save changes. You'll see a warning that the bucket is now public

3. Set up a key pair for that is used to access the account when writing the files
    - In the navigation pane, choose Users, and then select the desired user or create a new one.
    - On the user's summary page, select the Security credentials tab.
    - In the Access keys section, choose Create access key.
    - Select the relevant use case (e.g., "Other") and follow the prompts.
    - Download the .csv file containing the Access key ID and Secret access key, or copy 
      them directly from the console. 
      Important: This is the only time you can view the secret key, so store it securely.

4. Set up the permissions file
    - open the file s3_info.json
    - add your access key, secret accessky, region, and s3 bucket
    - save this file with a new name- s3_info-user.json



Add to the python virtual environment:
    pip install boto3             (for interacting with amazon S3)
    pip install qrcode            (to create the qr code images)
    pip install pillow            (required by qrcode)



