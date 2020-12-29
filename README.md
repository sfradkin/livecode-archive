# This README requires significant updates, disregard the rest for now

bulk upload of files to the internet archive

This is a script that used to automate multiple uploads to the Internet Archive.  It will apply some defaults that have been used across
previous uploads to the TOPLAP collection at archive.org.

pre-requisites

python 3.X
`pip install internetarchive`
After installing the `internetarchive` python module, setup is required.  Run `ia configure` to configure the authentication details for the module.  You will be asked to login to archive.org and it will write a `~/.ia` file with the s3 keys and archive.org cookie information required to authenticate with archive.org through the API.


copy live-code-uploader-template.ini to live-code-uploader.ini and fill out the required values
--> in the archive.org.uploader section
-----> csv.location - location of the CSV file that will be used by the archive.org uploader

internet archive bulk upload csv file format

file id, file location, title, description, creator, date recorded, the rest of the columns are subject tags

Usage

Fill out the details in the CSV file, one row for each file to be uploaded.
From a terminal run `python bulk-upload-archiveorg.py`.  The Python script will iterate through the CSV file and upload each file to the TOPLAP collection with the appropriate metadata.  Each file uploaded can be found at https://www.archive.org/details/<prefix>-<file id>.  It can take up to 24 hours for the newly uploaded files to be indexed so that they can be found in the TOPLAP collection, but they can generally be found immediately at their detail link.
