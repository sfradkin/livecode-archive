add python linting
refactor some of the copy/paste
better error handling and cleanup
better testing flags to limit the number of videos processed for testing
  also flags to change the titles to have "TEST" and archive id to have "test"
  flag to upload to the archive.org "Test Collection" to make testing easier since those items auto-delete
create a shared toplap admin user for archive.org and eulerrom youtube
update all the documentation
are there more things we can drive with muxy metadata rather than put in the ini file?
do a better job with unit testing
github actions to tie linting/testing/etc together when pushing commits and doing PRs
figure out how to make playlists work with the API as this wasn't working in the past
log useful things
retries - can we just re-run the full archiving and the script figures out if we've already archived a video?
compare downloaded video size with what was actually downloaded to detect if a download ended prematurely
better logging of issues with files not fully downloading/uploading or verification that archving worked correctly
