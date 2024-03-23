# Apple Notes Export Tool for Terminal

This script will backup all Apple Notes to a compressed zip archive that contains both the text and html versions of the notes. 

Simply run the script from the directory where you want the archive to be created. The created date of the note will be appended to the file.

Does not support embedded images or attachments, or password protected notes at this stage. 

Simply run `./backup_and_compress_apple_notes.sh` from the terminal to get started.

You might need to make the script executable by running `chmod +x backup_and_compress_apple_notes.sh` first.