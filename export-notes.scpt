-- Reading environment variables for root directory and note limits
set envRootDir to do shell script "echo $NOTES_EXPORT_ROOT_DIR"
set envNoteLimit to do shell script "echo $NOTES_EXPORT_NOTE_LIMIT"
set envNoteLimitPerFolder to do shell script "echo $NOTES_EXPORT_NOTE_LIMIT_PER_FOLDER"
set envNotePickProbability to do shell script "echo $NOTES_EXPORT_NOTE_PICK_PROBABILITY"

-- Convert envRootDir to an absolute path if necessary - avoid CFURLGetFSRef was passed a URL which has no scheme warning
if envRootDir starts with "./" then
    set currentDirectory to (do shell script "pwd")
    set envRootDir to currentDirectory & (text 2 through -1 of envRootDir)
end if

-- Ensure envRootDir ends with a "/"
if envRootDir does not end with "/" then
    set envRootDir to envRootDir & "/"
end if

if envNoteLimit is equal to "" then
    set noteLimit to -1
else
    set noteLimit to envNoteLimit as number
end if

if envNoteLimitPerFolder is equal to "" then
    set noteLimitPerFolder to -1
else
    set noteLimitPerFolder to envNoteLimitPerFolder as number
end if

if envNotePickProbability is equal to "" then
    set notePickProbability to 100
else
    set notePickProbability to envNotePickProbability as number
end if

set htmlDirectory to envRootDir & "html/"
set textDirectory to envRootDir & "text/"

-- Variables for statistics
set totalNotesOutput to 0
set totalNotesOverall to 0
set folderStatistics to {}

tell application "Notes"
    set theAccounts to every account
    repeat with anAccount in theAccounts
        set accountName to name of anAccount
        set theFolders to every folder of anAccount
        repeat with aFolder in theFolders
            set folderName to name of aFolder
            set combinedFolderName to my makeValidFilename(accountName & "-" & folderName)
            set folderHTMLPath to htmlDirectory & combinedFolderName & "/"
            set folderTextPath to textDirectory & combinedFolderName & "/"

            set theNotes to notes of aFolder
            set folderNoteCount to 0
            set outputNoteCount to 0
            set directoryCreated to false

            log "Notebook: " & (combinedFolderName)

            repeat with theNote in theNotes
                set totalNotesOverall to totalNotesOverall + 1
                if (noteLimit ≠ -1 and totalNotesOutput > noteLimit) or (noteLimitPerFolder ≠ -1 and folderNoteCount ≥ noteLimitPerFolder) then exit repeat
                -- Random note selection
                if (random number from 1 to 100) ≤ notePickProbability then

                    set folderNoteCount to folderNoteCount + 1
                    set totalNotesOutput to totalNotesOutput + 1
                    set outputNoteCount to outputNoteCount + 1

                    log "- Note: " & (name of theNote)

                    set noteName to my makeValidFilename(name of theNote)

                    set noteHTMLPath to folderHTMLPath & noteName & ".html"
                    set noteTextPath to folderTextPath & noteName & ".txt"

                    -- Create directories before writing the first note
                    if directoryCreated is false then
                        my createDirectory(folderHTMLPath)
                        my createDirectory(folderTextPath)
                        set directoryCreated to true
                    end if

                    -- Save HTML content
                    set htmlContent to body of theNote

                    my writeToFile(noteHTMLPath, htmlContent)

                    -- Save text content
                    set textContent to plaintext of theNote
                    my writeToFile(noteTextPath, textContent)

                end if
            end repeat

            set end of folderStatistics to {folderName:folderName, totalNotes:count of theNotes, notesOutput:outputNoteCount}
        end repeat
    end repeat
end tell

-- Output statistics
log "Folders Parsed: " & (count of folderStatistics)
log "Total Notes Output: " & totalNotesOutput
log "Total Notes Overall: " & totalNotesOverall
repeat with stat in folderStatistics
    log "Folder: " & (folderName of stat) & ", Total Notes: " & (totalNotes of stat) & ", Notes Output: " & (notesOutput of stat)
end repeat

-- Subroutine to create a directory if it doesn't exist
on createDirectory(directoryPath)
    do shell script "mkdir -p " & quoted form of directoryPath
end createDirectory

-- Subroutine to write content to a file
on writeToFile(filePath, content)
    try
        -- Convert the file path to a file object
        set fileObject to filePath as POSIX file
        -- Try to open the file for access
        set fileDescriptor to open for access fileObject with write permission
        write content to fileDescriptor starting at eof
        close access fileDescriptor
    on error errMsg
        -- Log the error message
        log "Error writing to file: " & errMsg

        -- If the file does not exist, create it and then open for access
        close access
        do shell script "touch " & quoted form of filePath
        set fileDescriptor to open for access fileObject with write permission
        write content to fileDescriptor starting at eof
        close access fileDescriptor
    end try
end writeToFile

--- Subroutine to generate a valid filename, replace certain characters with dashes, remove non-alphanumeric characters (except dashes), and consolidate multiple dashes
on makeValidFilename(fileName)
    -- Replace slashes, underscores, and spaces with dashes
    set charactersToReplace to {"/", "_", " ", ".", ","}
    repeat with aChar in charactersToReplace
        set AppleScript's text item delimiters to aChar
        set fileName to text items of fileName
        set AppleScript's text item delimiters to "-"
        set fileName to fileName as string
    end repeat

    -- Remove all characters that are not alphanumeric or dashes
    set validFileName to ""
    repeat with i from 1 to length of fileName
        set currentChar to character i of fileName
        if currentChar is in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-" then
            set validFileName to validFileName & currentChar
        end if
    end repeat

    -- Consolidate multiple dashes into a single dash
    set AppleScript's text item delimiters to "--"
    set textItems to text items of validFileName
    set AppleScript's text item delimiters to "-"
    set validFileName to textItems as string

    -- Check and replace again if necessary
    repeat while validFileName contains "--"
        set AppleScript's text item delimiters to "--"
        set textItems to text items of validFileName
        set AppleScript's text item delimiters to "-"
        set validFileName to textItems as string
    end repeat

    -- Remove trailing dash if present
    if validFileName ends with "-" then
        set validFileName to text 1 through -2 of validFileName
    end if

    return validFileName
end makeValidFilename

