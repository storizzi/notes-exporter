on run argv
    -- Reading environment variables for root directory and note limits from arguments
    set envRootDir to item 1 of argv
    set envNoteLimit to item 2 of argv
    set envNoteLimitPerFolder to item 3 of argv
    set envNotePickProbability to item 4 of argv
    set envFilenameFormat to item 5 of argv
    set envSubdirFormat to item 6 of argv
    set envUseSubdirs to item 7 of argv
    set envUpdateAll to item 8 of argv  -- NEW: update all notes flag
    set envFoldersFilter to item 9 of argv  -- Comma-separated list of folder names to export

    -- Convert envRootDir to an absolute path if necessary - avoid CFURLGetFSRef was passed a URL which has no scheme warning
    if envRootDir starts with "./" then
        set currentDirectory to (do shell script "pwd")
        set envRootDir to currentDirectory & (text 2 through -1 of envRootDir)
    end if

    -- Ensure envRootDir ends with a "/"
    if envRootDir does not end with "/" then
        set envRootDir to envRootDir & "/"
    end if

    -- Log the final envRootDir
    log "Apple notes output directory: " & envRootDir

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

    -- Convert update all flag
    -- Parse folders filter into a list
    set foldersToExport to {}
    if envFoldersFilter is not equal to "" then
        set AppleScript's text item delimiters to ","
        set foldersToExport to text items of envFoldersFilter
        set AppleScript's text item delimiters to ""
        log "Filtering to folders: " & envFoldersFilter
    end if


    set updateAllNotes to false
    if envUpdateAll is equal to "true" then
        set updateAllNotes to true
    end if

    set htmlDirectory to envRootDir & "html/"
    set textDirectory to envRootDir & "text/"
    set dataDirectory to envRootDir & "data/"
    set rawDirectory to envRootDir & "raw/"

    -- Create main directories
    my createDirectory(rawDirectory) 
    my createDirectory(dataDirectory)
    my createDirectory(htmlDirectory)
    my createDirectory(textDirectory)

    -- Variables for statistics
    set totalNotesOutput to 0
    set totalNotesOverall to 0
    set totalNotesSkippedUnchanged to 0
    set totalNotesSkippedOlder to 0
    set folderStatistics to {}
    
    -- Start timing
    set startTime to (current date)
    
    -- Start timing
    set startTime to (current date)

    tell application "Notes"
        set theAccounts to every account
        repeat with anAccount in theAccounts
            set accountName to my makeValidFilename(name of anAccount)
            set accountID to my extractAccountID(id of anAccount)
            set shortAccountID to my extractShortAccountID(accountID)
            set theFolders to every folder of anAccount
            repeat with aFolder in theFolders
                set rawFolderName to name of aFolder
                set folderName to my makeValidFilename(rawFolderName)
                
                -- Check if this folder should be processed (skip if filter is set and folder not in list)
                set shouldProcessFolder to true
                if (count of foldersToExport) > 0 then
                    set shouldProcessFolder to false
                    repeat with allowedFolder in foldersToExport
                        if rawFolderName is equal to allowedFolder or folderName is equal to allowedFolder then
                            set shouldProcessFolder to true
                            exit repeat
                        end if
                    end repeat
                    if not shouldProcessFolder then
                        log "Skipping folder (not in filter): " & rawFolderName
                    end if
                end if
                
                -- Only process if folder passes filter
                if shouldProcessFolder then
                set folderNoteCount to 0
                set theNotes to notes of aFolder
                set outputNoteCount to 0

                -- Determine the data file name based on subdirectory usage
                if envUseSubdirs is "true" then
                    set subdirName to my generateFilename(envSubdirFormat, "", "", accountName, folderName, accountID, shortAccountID)
                    set folderHTMLPath to htmlDirectory & subdirName & "/"
                    set folderTextPath to textDirectory & subdirName & "/"
                    set folderRawPath to rawDirectory & subdirName & "/"
                    my createDirectory(folderHTMLPath)
                    my createDirectory(folderTextPath)
                    my createDirectory(folderRawPath)
                    set notebookDataFile to dataDirectory & subdirName & ".json"
                    log "Notebook: " & (subdirName)
                else
                    set folderHTMLPath to htmlDirectory
                    set folderTextPath to textDirectory
                    set folderRawPath to rawDirectory
                    -- Use a combination of account and folder for flat structure
                    set flatName to accountName & "-" & folderName
                    set notebookDataFile to dataDirectory & flatName & ".json"
                    log "Notebook: " & (folderName)
                end if

                -- Load existing notebook data
                log "Loading existing notebook data from: " & notebookDataFile
                set existingData to my loadNotebookData(notebookDataFile)
                log "Loaded " & (count of existingData) & " existing note records"
                set currentNoteIDs to {}

                -- NEW: Get the latest modification date from existing data for incremental updates
                set latestExistingModDate to missing value
                if not updateAllNotes and (count of existingData) > 0 then
                    log "Calculating latest modification date from " & (count of existingData) & " existing records..."
                    set latestExistingModDate to my getLatestModificationDate(existingData)
                    if latestExistingModDate is not missing value then
                        log "Latest existing modification date: " & (latestExistingModDate as string)
                    else
                        log "No valid modification dates found"
                    end if
                else
                    log "Processing all notes (full update mode or no existing data)"
                end if

                -- Log folder start
                log "Processing " & (count of theNotes) & " notes in folder: " & folderName
                
                repeat with theNote in theNotes
                    set noteID to my extractID(id of theNote)
                    set end of currentNoteIDs to noteID
                    set totalNotesOverall to totalNotesOverall + 1
                    
                    -- Check limits first (cheapest operation)
                    if (noteLimit ≠ -1 and totalNotesOutput ≥ noteLimit) or (noteLimitPerFolder ≠ -1 and folderNoteCount ≥ noteLimitPerFolder) then 
                        log "Reached note limit, stopping processing for this folder"
                        exit repeat
                    end if
                    
                    -- Random selection check early (avoid expensive operations for skipped notes)
                    if (random number from 1 to 100) ≤ notePickProbability then
                        -- Get basic metadata in one batch to minimize API calls
                        set noteModDate to modification date of theNote
                        set noteTitle to my makeValidFilename(name of theNote)
                        set noteName to my generateFilename(envFilenameFormat, noteTitle, noteID, accountName, folderName, accountID, shortAccountID)
                        
                        -- Log progress every 100 notes (less frequent logging)
                        if (totalNotesOverall mod 100) = 0 then
                            log "Processed " & totalNotesOverall & " notes so far..."
                        end if
                        
                        -- Quick incremental update check
                        set shouldProcess to false
                        if updateAllNotes then
                            set shouldProcess to true
                        else
                            -- Simple check: is this note newer than latest existing or not in existing data?
                            if latestExistingModDate is missing value or noteModDate > latestExistingModDate then
                                set shouldProcess to true
                            else
                                -- Only do expensive check if necessary
                                set shouldProcess to my shouldProcessNote(existingData, noteID, noteModDate)
                            end if
                        end if
                        
                        if shouldProcess then
                            -- Get creation date only when we need it
                            set noteCreatedDate to creation date of theNote
                            
                            -- Get old filename for comparison (optimized lookup)
                            set oldFileName to ""
                            repeat with currentRecord in existingData
                                if (noteID_key of currentRecord) = noteID then
                                    set oldFileName to (filename of currentRecord)
                                    exit repeat
                                end if
                            end repeat
                            
                            set folderNoteCount to folderNoteCount + 1
                            set totalNotesOutput to totalNotesOutput + 1
                            set outputNoteCount to outputNoteCount + 1
                            
                            log "- Note: " & noteTitle & " (processing)"
                            
                            -- Read content only when we're actually processing
                            set htmlContent to body of theNote
                            set textContent to plaintext of theNote
                            
                            -- Generate file paths
                            set noteRawPath to POSIX path of (folderRawPath & noteName & ".html")
                            set noteTextPath to POSIX path of (folderTextPath & noteName & ".txt")
                            
                            -- Save files
                            my writeToFile(noteRawPath, htmlContent)
                            my writeToFile(noteTextPath, textContent)
                            
                            -- Handle filename changes
                            my handleFilenameChange(existingData, noteID, oldFileName, noteName, folderRawPath, folderTextPath)
                            
                            -- Update data record
                            set existingData to my updateNoteData(existingData, noteID, noteModDate, noteCreatedDate, noteName)
                        else
                            -- Count skipped notes
                            if latestExistingModDate is not missing value and noteModDate ≤ latestExistingModDate then
                                set totalNotesSkippedOlder to totalNotesSkippedOlder + 1
                            else
                                set totalNotesSkippedUnchanged to totalNotesSkippedUnchanged + 1
                            end if
                        end if
                    end if
                end repeat
                set end of folderStatistics to {folderName, count of theNotes, outputNoteCount}
                
                -- Only save if we actually processed some notes or if we have changes to mark deleted notes
                set existingData to my markDeletedNotes(existingData, currentNoteIDs)
                if outputNoteCount > 0 then
                    log "Saving data because " & outputNoteCount & " notes were processed"
                    my saveNotebookData(notebookDataFile, existingData)
                else
                    log "No notes were processed, skipping data save"
                end if
                end if  -- end folder filter check
            end repeat
        end repeat
    end tell

    -- Calculate timing and rates
    set endTime to (current date)
    set elapsedSeconds to (endTime - startTime)
    
    -- Write statistics to a temporary file for the zsh script to read (using shell for reliability)
    set statsFile to dataDirectory & "export_stats.tmp"
    
    -- Convert numbers to strings and concatenate properly, including elapsed time
    set statsContent to (totalNotesOverall as string) & ":" & (totalNotesOutput as string) & ":" & (totalNotesSkippedUnchanged as string) & ":" & (totalNotesSkippedOlder as string) & ":" & ((count of folderStatistics) as string) & ":" & (elapsedSeconds as string)
    
    log "DEBUG: About to write stats - " & statsContent
    log "DEBUG: Writing to file: " & statsFile
    
    -- Use shell command for reliable text writing
    try
        do shell script "echo " & quoted form of statsContent & " > " & quoted form of statsFile
        log "DEBUG: Successfully wrote stats file"
        
        -- Verify the file was created
        set verifyContent to do shell script "cat " & quoted form of statsFile
        log "DEBUG: File verification - content: " & verifyContent
    on error errMsg
        log "ERROR: Failed to write stats file: " & errMsg
    end try
    
    log "Statistics written to: " & statsFile

    -- Output statistics
    log "==== EXPORT STATISTICS ===="
    log "Folders Parsed: " & (count of folderStatistics)
    log "Total Notes Examined: " & totalNotesOverall
    log "Total Notes Processed/Updated: " & totalNotesOutput
    log "Total Notes Skipped (Unchanged): " & totalNotesSkippedUnchanged
    log "Total Notes Skipped (Not Modified Since Last Export): " & totalNotesSkippedOlder
    log "Processing Time: " & elapsedSeconds & " seconds"
    
    -- Calculate and display rates
    if elapsedSeconds > 0 then
        set overallRate to round((totalNotesOverall / elapsedSeconds) * 10) / 10
        log "Overall Processing Rate: " & overallRate & " notes/second"
        
        if totalNotesOutput > 0 then
            set updateRate to round((totalNotesOutput / elapsedSeconds) * 10) / 10
            log "Update Rate: " & updateRate & " notes/second"
        end if
        
        set totalSkipped to totalNotesSkippedUnchanged + totalNotesSkippedOlder
        if totalSkipped > 0 then
            set skipRate to round((totalSkipped / elapsedSeconds) * 10) / 10
            log "Skip Rate: " & skipRate & " notes/second"
        end if
    end if
    
    -- Calculate percentages
    if totalNotesOverall > 0 then
        set processedPercent to round ((totalNotesOutput / totalNotesOverall) * 100)
        set unchangedPercent to round ((totalNotesSkippedUnchanged / totalNotesOverall) * 100)
        set olderPercent to round ((totalNotesSkippedOlder / totalNotesOverall) * 100)
        log "Processing Rate: " & processedPercent & "% processed, " & unchangedPercent & "% unchanged, " & olderPercent & "% older"
    end if
    
    if updateAllNotes then
        log "Update mode: Full update (all notes processed)"
    else
        log "Update mode: Incremental update (only modified notes processed)"
    end if
    
    -- Output folder-by-folder statistics
    log "==== FOLDER BREAKDOWN ===="
    repeat with stat in folderStatistics
        set folderName to item 1 of stat
        set totalCount to item 2 of stat
        set outputCount to item 3 of stat
        log "Folder: " & folderName & " - Total: " & totalCount & ", Processed: " & outputCount
    end repeat
    log "============================"
end run

-- NEW: Get the latest modification date from existing data
on getLatestModificationDate(existingData)
    set latestDate to missing value
    repeat with currentRecord in existingData
        try
            set recordModDate to date ((modified of currentRecord) as string)
            if latestDate is missing value or recordModDate > latestDate then
                set latestDate to recordModDate
            end if
        on error
            -- Skip records with invalid dates
        end try
    end repeat
    return latestDate
end getLatestModificationDate

-- NEW: Sort notes by modification date (newest first)
on sortNotesByModificationDate(notesList)
    tell application "Notes"
        log "Starting to sort notes by modification date..."
        -- Convert to a list of records with dates for sorting
        set noteRecords to {}
        set noteCount to count of notesList
        log "Converting " & noteCount & " notes to sortable records..."
        
        repeat with i from 1 to noteCount
            set aNote to item i of notesList
            set noteModDate to modification date of aNote
            set end of noteRecords to {noteRef:aNote, modDate:noteModDate}
            
            -- Log progress for large collections
            if (i mod 100) = 0 then
                log "Converted " & i & "/" & noteCount & " notes for sorting..."
            end if
        end repeat
        
        log "Starting bubble sort of " & (count of noteRecords) & " note records..."
        -- Simple bubble sort (could be optimized but adequate for most use cases)
        set listSize to count of noteRecords
        repeat with i from 1 to listSize - 1
            repeat with j from 1 to listSize - i
                set currentRecord to item j of noteRecords
                set nextRecord to item (j + 1) of noteRecords
                if (modDate of currentRecord) < (modDate of nextRecord) then
                    -- Swap records
                    set item j of noteRecords to nextRecord
                    set item (j + 1) of noteRecords to currentRecord
                end if
            end repeat
            
            -- Log progress for large sorts
            if (i mod 50) = 0 then
                log "Sort progress: " & i & "/" & (listSize - 1) & " passes completed..."
            end if
        end repeat
        
        log "Extracting sorted note references..."
        -- Extract just the note references in sorted order
        set sortedNotes to {}
        repeat with noteRecord in noteRecords
            set end of sortedNotes to (noteRef of noteRecord)
        end repeat
        
        log "Note sorting completed"
        return sortedNotes
    end tell
end sortNotesByModificationDate

-- Subroutine to create a directory if it doesn't exist
on createDirectory(directoryPath)
    do shell script "mkdir -p " & quoted form of directoryPath
end createDirectory

-- Subroutine to write content to a file
on writeToFile(filePath, content)
    try
        -- Convert the file path to a file object
        set fileObject to POSIX file filePath
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

-- Subroutine to generate a valid filename, replace certain characters with dashes, remove non-alphanumeric characters (except dashes), and consolidate multiple dashes
on makeValidFilename(fileName)
    -- Replace only the genuinely problematic characters with dashes
    set charactersToReplace to {"/", ":", "\\", "|", "<", ">", "\"", "'", "?", "*", "_", " ", ".", ",", tab}
    repeat with aChar in charactersToReplace
        set AppleScript's text item delimiters to aChar
        set fileName to text items of fileName
        set AppleScript's text item delimiters to "-"
        set fileName to fileName as string
    end repeat

    -- Consolidate multiple dashes into a single dash
    repeat while fileName contains "--"
        set AppleScript's text item delimiters to "--"
        set textItems to text items of fileName
        set AppleScript's text item delimiters to "-"
        set fileName to textItems as string
    end repeat

    -- Remove leading/trailing dashes
    repeat while fileName starts with "-" and length of fileName > 1
        set fileName to text 2 through -1 of fileName
    end repeat
    
    repeat while fileName ends with "-" and length of fileName > 1
        set fileName to text 1 through -2 of fileName
    end repeat

    -- Ensure filename isn't empty
    if fileName is "" or fileName is "-" then
        set fileName to "untitled"
    end if

    return fileName
end makeValidFilename

-- Subroutine to generate a filename based on the specified format
on generateFilename(format, title, id, account, folder, accountID, shortAccountID)
    set formattedFilename to format
    set formattedFilename to my replaceText("&title", title, formattedFilename)
    set formattedFilename to my replaceText("&id", id, formattedFilename)
    set formattedFilename to my replaceText("&account", account, formattedFilename)
    set formattedFilename to my replaceText("&folder", folder, formattedFilename)
    set formattedFilename to my replaceText("&accountid", accountID, formattedFilename)
    set formattedFilename to my replaceText("&shortaccountid", shortAccountID, formattedFilename)
    return formattedFilename
end generateFilename

-- Subroutine to replace occurrences of a substring within a string
on replaceText(find, replace, subject)
    set AppleScript's text item delimiters to find
    set subject to text items of subject
    set AppleScript's text item delimiters to replace
    set subject to subject as string
    set AppleScript's text item delimiters to ""
    return subject
end replaceText

-- Subroutine to extract the portion of the ID
on extractID(fullID)
    set AppleScript's text item delimiters to "/"
    set idComponents to text items of fullID
    set extractedID to item 5 of idComponents -- The ID is the fifth component
    if extractedID starts with "p" then
        set extractedID to text 2 through -1 of extractedID
    end if
    set AppleScript's text item delimiters to ""
    return extractedID
end extractID

-- Subroutine to extract the account ID
on extractAccountID(fullID)
    set AppleScript's text item delimiters to "/"
    set idComponents to text items of fullID
    set accountID to item 3 of idComponents -- The account ID is the third component
    set AppleScript's text item delimiters to ""
    return accountID
end extractAccountID

-- Subroutine to extract the short account ID
on extractShortAccountID(accountID)
    set AppleScript's text item delimiters to "-"
    set idComponents to text items of accountID
    set shortAccountID to item 5 of idComponents -- The short account ID is the fifth component
    set AppleScript's text item delimiters to ""
    return shortAccountID
end extractShortAccountID

-- Load existing notebook data from JSON file (optimized)
on loadNotebookData(filePath)
    try
        -- Quick file existence check
        set fileCheckCommand to "test -f " & quoted form of filePath & " && echo 'exists' || echo 'missing'"
        set fileExists to do shell script fileCheckCommand
        
        if fileExists contains "missing" then
            log "JSON file does not exist: " & filePath & " - starting fresh"
            return {}
        end if
        
        log "Loading JSON data from: " & filePath
        set loadCommand to "python3 -c \"
import json, os, sys

try:
    with open('" & filePath & "', 'r') as f:
        data = json.load(f)
    
    if not data:
        print('')
        sys.exit(0)
    
    # Convert to optimized format for AppleScript
    records = []
    for note_id, record in data.items():
        # Skip deleted notes during loading to reduce memory
        if 'deletedDate' in record:
            continue
        
        rec = [
            note_id,
            record.get('filename', ''),
            record.get('created', ''),
            record.get('modified', ''),
            record.get('firstExported', ''),
            record.get('lastExported', ''),
            str(record.get('exportCount', 1))
        ]
        records.append('|'.join(rec))
    
    print('\\n'.join(records))
except Exception as e:
    print('')
\""
        set pythonResult to do shell script loadCommand
        
        if pythonResult is equal to "" then
            log "No active records found - starting fresh"
            return {}
        end if
        
        set parsedData to my parseLoadedData(pythonResult)
        log "Loaded " & (count of parsedData) & " active note records"
        return parsedData
    on error errMsg
        log "Error loading JSON data: " & errMsg
        return {}
    end try
end loadNotebookData

-- Parse loaded data into AppleScript records
on parseLoadedData(dataString)
    set recordList to {}
    
    if dataString = "" then 
        return recordList
    end if
    
    if dataString = "[]" then
        return recordList
    end if
    
    set dataLines to paragraphs of dataString
    
    repeat with i from 1 to count of dataLines
        set dataLine to item i of dataLines
        if dataLine ≠ "" then
            set recordParts to my splitByDelimiter(dataLine, "|")
            if (count of recordParts) ≥ 7 then
                set noteRecord to {noteID_key:(item 1 of recordParts), filename:(item 2 of recordParts), created:(item 3 of recordParts), modified:(item 4 of recordParts), firstExported:(item 5 of recordParts), lastExported:(item 6 of recordParts), exportCount:((item 7 of recordParts) as integer)}
                if (count of recordParts) ≥ 8 and (item 8 of recordParts) ≠ "" then
                    set noteRecord to noteRecord & {deletedDate:(item 8 of recordParts)}
                end if
                set end of recordList to noteRecord
            end if
        end if
    end repeat
    
    log "Parsed " & (count of recordList) & " existing note records from JSON data"
    return recordList
end parseLoadedData

-- Helper to split by delimiter
on splitByDelimiter(textString, delimiter)
    set AppleScript's text item delimiters to delimiter
    set textItems to text items of textString
    set AppleScript's text item delimiters to ""
    return textItems
end splitByDelimiter

-- Update note data record with comprehensive metadata
on updateNoteData(existingData, noteID, noteModDate, noteCreatedDate, fileName)
    set currentTime to (current date as string)
    set foundExisting to false
    set newData to {}
    
    -- Go through existing data and update if found
    if (count of existingData) > 0 then
        repeat with i from 1 to count of existingData
            set currentRecord to item i of existingData
            if (noteID_key of currentRecord) = noteID then
                -- Update existing record, preserve firstExported
                set newRecord to {noteID_key:noteID, filename:fileName, created:(noteCreatedDate as string), modified:(noteModDate as string), firstExported:(firstExported of currentRecord), lastExported:currentTime, exportCount:((exportCount of currentRecord) + 1)}
                set foundExisting to true
            else
                -- Keep existing record unchanged
                set newRecord to currentRecord
            end if
            set end of newData to newRecord
        end repeat
    end if
    
    -- If not found, add new record
    if not foundExisting then
        set newRecord to {noteID_key:noteID, filename:fileName, created:(noteCreatedDate as string), modified:(noteModDate as string), firstExported:currentTime, lastExported:currentTime, exportCount:1}
        set end of newData to newRecord
    end if
    
    return newData
end updateNoteData

-- Check if a note should be processed based on modification date (optimized with hash lookup)
on shouldProcessNote(existingData, noteID, noteModDate)
    -- Convert to string for comparison
    set noteModDateStr to (noteModDate as string)
    
    repeat with currentRecord in existingData
        if (noteID_key of currentRecord) = noteID then
            set storedModDate to (modified of currentRecord)
            if storedModDate = noteModDateStr then
                return false -- unchanged
            else
                return true -- changed
            end if
        end if
    end repeat
    return true -- new note (not found in existing data)
end shouldProcessNote

-- Mark notes as deleted if they no longer exist in the current export
on markDeletedNotes(existingData, currentNoteIDs)
    set currentTime to (current date as string)
    set newData to {}
    
    repeat with currentRecord in existingData
        set recordNoteID to (noteID_key of currentRecord)
        
        if currentNoteIDs contains recordNoteID then
            -- Note still exists, keep record unchanged
            set end of newData to currentRecord
        else
            -- Note was deleted, mark it
            set alreadyDeleted to false
            try
                set testDeleted to (deletedDate of currentRecord)
                set alreadyDeleted to true
            on error
                -- deletedDate doesn't exist, so not already marked as deleted
                set alreadyDeleted to false
            end try
            
            if not alreadyDeleted then
                set deletedRecord to {noteID_key:(noteID_key of currentRecord), filename:(filename of currentRecord), created:(created of currentRecord), modified:(modified of currentRecord), firstExported:(firstExported of currentRecord), lastExported:(lastExported of currentRecord), exportCount:(exportCount of currentRecord), deletedDate:currentTime}
                set end of newData to deletedRecord
            else
                -- Already marked as deleted, keep as is
                set end of newData to currentRecord
            end if
        end if
    end repeat
    
    return newData
end markDeletedNotes

on saveNotebookData(filePath, dataRecord)
    try
        log "Saving notebook data to: " & filePath & " with " & (count of dataRecord) & " records"
        
        -- Don't overwrite existing file if we have no data to save
        if (count of dataRecord) = 0 then
            log "Warning: No data to save, checking if file already exists..."
            set checkFileCommand to "if [ -f " & quoted form of filePath & " ]; then echo 'exists'; else echo 'missing'; fi"
            set fileExists to do shell script checkFileCommand
            if fileExists contains "exists" then
                log "Existing file found, preserving it instead of overwriting with empty data"
                return
            else
                log "No existing file, will create new empty file"
            end if
        end if
        
        set saveCommand to "python3 -c \"
import json
import os

# Load existing data if it exists
existing_data = {}
if os.path.exists('" & filePath & "'):
    try:
        with open('" & filePath & "', 'r') as f:
            existing_data = json.load(f)
        print('Loaded existing data with', len(existing_data), 'records')
    except Exception as e:
        print('Error loading existing data:', e)
        existing_data = {}

# Process new records
records = [" & my convertDataToString(dataRecord) & "]
new_data = {}

print('Processing', len(records), 'new records')

for record in records:
    if len(record) >= 7:
        note_id = record[0]
        
        # Start with existing data for this note (preserves unknown fields)
        if note_id in existing_data:
            note_data = existing_data[note_id].copy()
        else:
            note_data = {}
        
        # Update with AppleScript-managed fields
        note_data.update({
            'filename': record[1],
            'created': record[2],
            'modified': record[3],
            'firstExported': record[4],
            'lastExported': record[5],
            'exportCount': int(record[6])
        })
        
        # Handle deleted date
        if len(record) >= 8 and record[7]:
            note_data['deletedDate'] = record[7]
        
        new_data[note_id] = note_data

# Also preserve any notes that exist in file but not in current export
# (in case some notes are temporarily not found)
for note_id, note_data in existing_data.items():
    if note_id not in new_data:
        new_data[note_id] = note_data

print('Final data will have', len(new_data), 'records')

# Save the merged data
with open('" & filePath & "', 'w') as f:
    json.dump(new_data, f, indent=2, sort_keys=True)
    
print('Successfully saved data to file')
\""
        do shell script saveCommand
        log "Notebook data saved successfully"
    on error errMsg
        log "Error saving notebook data: " & errMsg
    end try
end saveNotebookData

-- Convert data record to string for Python
on convertDataToString(dataRecord)
    set recordString to ""
    repeat with i from 1 to count of dataRecord
        set currentRecord to item i of dataRecord
        set recordArray to "['" & (noteID_key of currentRecord) & "','" & (filename of currentRecord) & "','" & (created of currentRecord) & "','" & (modified of currentRecord) & "','" & (firstExported of currentRecord) & "','" & (lastExported of currentRecord) & "'," & (exportCount of currentRecord)
        try
            set recordArray to recordArray & ",'" & (deletedDate of currentRecord) & "']"
        on error
            set recordArray to recordArray & ",'']"
        end try
        set recordString to recordString & recordArray
        if i < count of dataRecord then set recordString to recordString & ","
    end repeat
    return recordString
end convertDataToString

-- Handle filename changes - delete old files including attachments from all format directories
on handleFilenameChange(existingData, noteID, oldFileName, newFileName, folderRawPath, folderTextPath)
    if oldFileName ≠ newFileName and oldFileName ≠ "" then
        log "Filename changed for note " & noteID & ": " & oldFileName & " → " & newFileName
        
        -- Build old file paths for main files
        set oldRawPath to POSIX path of (folderRawPath & oldFileName & ".html")
        set oldTextPath to POSIX path of (folderTextPath & oldFileName & ".txt")
        
        -- Build paths for processed HTML (in html directory)
        set htmlDirectory to my replaceText("/raw/", "/html/", folderRawPath)
        set oldHTMLPath to POSIX path of (htmlDirectory & oldFileName & ".html")
        
        -- Build paths for converted formats (in their respective directories)
        set rootDir to my replaceText("/raw/" & my getSubdirFromPath(folderRawPath), "/", folderRawPath)
        if rootDir ends with "/" then set rootDir to text 1 through -2 of rootDir
        
        set oldMarkdownPath to rootDir & "/md/" & my getSubdirFromPath(folderRawPath) & oldFileName & ".md"
        set oldPDFPath to rootDir & "/pdf/" & my getSubdirFromPath(folderRawPath) & oldFileName & ".pdf"
        set oldWordPath to rootDir & "/docx/" & my getSubdirFromPath(folderRawPath) & oldFileName & ".docx"
        
        -- Delete main files (safe to delete completely)
        my deleteOldFilesSafely({oldMarkdownPath, oldPDFPath, oldWordPath, oldHTMLPath, oldTextPath, oldRawPath}, oldFileName)
        
        -- Delete attachment files from ALL format directories
        my deleteAttachmentsFromAllFormats(rootDir, my getSubdirFromPath(folderRawPath), oldFileName)
    end if
end handleFilenameChange

-- Delete attachment files from all format directories (html, md, pdf, docx)
on deleteAttachmentsFromAllFormats(rootDir, subdir, oldFileName)
    -- List of format directories that might contain attachments
    set formatDirs to {"html", "md", "pdf", "docx"}
    
    repeat with formatDir in formatDirs
        try
            -- Build the attachments path for this format
            set attachmentsPath to rootDir & "/" & formatDir & "/" & subdir & "attachments"
            
            -- Check if this attachments directory exists
            set checkCommand to "if [ -d " & quoted form of attachmentsPath & " ]; then echo 'exists'; else echo 'not found'; fi"
            set dirExists to do shell script checkCommand
            
            if dirExists contains "exists" then
                -- Count files before deletion (for logging)
                set countCommand to "find " & quoted form of attachmentsPath & " -name " & quoted form of (oldFileName & "-attachment-*") & " -type f 2>/dev/null | wc -l"
                set fileCount to do shell script countCommand
                
                if (fileCount as number) > 0 then
                    -- Delete only files that start with the old filename
                    set deleteCommand to "find " & quoted form of attachmentsPath & " -name " & quoted form of (oldFileName & "-attachment-*") & " -type f -delete"
                    do shell script deleteCommand
                    
                    log "Deleted " & fileCount & " attachment files from " & formatDir & " for: " & oldFileName
                else
                    log "No attachment files found in " & formatDir & " for: " & oldFileName
                end if
            end if
            
        on error errMsg
            -- Only log if it's not a "file not found" type error
            if errMsg does not contain "No such file" and errMsg does not contain "not found" then
                log "Error deleting attachments from " & formatDir & " for " & oldFileName & ": " & errMsg
            end if
        end try
    end repeat
end deleteAttachmentsFromAllFormats

-- Safely delete old files with error handling
on deleteOldFilesSafely(filePaths, oldFileName)
    repeat with filePath in filePaths
        try
            -- Check if file/directory exists before trying to delete
            do shell script "if [ -e " & quoted form of filePath & " ]; then rm -rf " & quoted form of filePath & "; echo 'Deleted: " & filePath & "'; fi"
        on error errMsg
            -- Only log if it's not a "file not found" type error
            if errMsg does not contain "No such file" then
                log "Could not delete old file " & filePath & ": " & errMsg
            end if
        end try
    end repeat
    log "Cleaned up old files for: " & oldFileName
end deleteOldFilesSafely

-- Helper to extract subdirectory from path
on getSubdirFromPath(folderPath)
    if folderPath contains "/raw/" then
        set pathParts to my splitByDelimiter(folderPath, "/")
        -- Find the part after "raw"
        repeat with i from 1 to count of pathParts
            if item i of pathParts is "raw" and i < count of pathParts then
                return (item (i + 1) of pathParts) & "/"
            end if
        end repeat
    end if
    return ""
end getSubdirFromPath
