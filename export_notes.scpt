-- export_notes.scpt - read Apple Notes and write raw HTML / text files.
--
-- Read-only: this script never creates, edits or deletes a note.
--
-- Arguments (all text, "" for unset):
--   1 root dir            2 note limit            3 note limit per folder
--   4 pick probability    5 filename format       6 subdir format
--   7 use subdirs         8 update all            9 include deleted
--  10 account filter     11 folder filter        12 modified after
--  13 python executable  14 script directory     15 folder exclusions
--
-- Tracking data goes through tracker_io.py: records are written to a file
-- with AppleScript's own file I/O and only file paths reach the shell, so
-- no note title or folder name is ever part of a shell command (#33).
--
-- Progress for the caller is logged to stderr as lines starting "@@":
--   @@PLAN <tab> folders
--   @@FOLDER <tab> index <tab> total <tab> account <tab> path <tab> notes
--   @@NOTE <tab> processed so far <tab> note id
--   @@NOTE_ERROR <tab> note id <tab> message
--   @@SAVE_ERROR <tab> tracker <tab> message
--
-- A live index of every note seen is written to data/.live_notes.tsv for
-- tracker_io.py finalize, which records deletions and moves (#37).

on run argv
    set envRootDir to item 1 of argv
    set envNoteLimit to item 2 of argv
    set envNoteLimitPerFolder to item 3 of argv
    set envNotePickProbability to item 4 of argv
    set envFilenameFormat to item 5 of argv
    set envSubdirFormat to item 6 of argv
    set envUseSubdirs to item 7 of argv
    set envUpdateAll to item 8 of argv
    set envIncludeDeleted to item 9 of argv
    set envFilterAccounts to item 10 of argv
    set envFilterFolders to item 11 of argv
    set envModifiedAfter to item 12 of argv
    set envPython to ""
    if (count of argv) ≥ 13 then set envPython to item 13 of argv
    set envScriptDir to ""
    if (count of argv) ≥ 14 then set envScriptDir to item 14 of argv
    set envExcludeFolders to ""
    if (count of argv) ≥ 15 then set envExcludeFolders to item 15 of argv

    if envPython is "" then
        set pythonCmd to "/usr/bin/env python3"
    else
        set pythonCmd to quoted form of envPython
    end if
    if envScriptDir is "" then
        set envScriptDir to do shell script "dirname " & quoted form of (POSIX path of (path to me))
    end if
    if envScriptDir does not end with "/" then set envScriptDir to envScriptDir & "/"
    set trackerIO to pythonCmd & " " & quoted form of (envScriptDir & "tracker_io.py")

    set filterAccountsList to my splitByDelimiter(envFilterAccounts, ",")
    set filterFoldersList to my splitByDelimiter(envFilterFolders, ",")
    set excludeFoldersList to my splitByDelimiter(envExcludeFolders, ",")

    if envRootDir starts with "./" then
        set envRootDir to (do shell script "pwd") & (text 2 through -1 of envRootDir)
    end if
    if envRootDir does not end with "/" then set envRootDir to envRootDir & "/"
    log "Apple notes output directory: " & envRootDir

    set noteLimit to -1
    if envNoteLimit is not "" then set noteLimit to envNoteLimit as number
    set noteLimitPerFolder to -1
    if envNoteLimitPerFolder is not "" then set noteLimitPerFolder to envNoteLimitPerFolder as number
    set notePickProbability to 100
    if envNotePickProbability is not "" then set notePickProbability to envNotePickProbability as number
    set updateAllNotes to (envUpdateAll is "true")
    set includeDeleted to (envIncludeDeleted is "true")
    set useSubdirs to (envUseSubdirs is "true")

    set modifiedAfterDate to missing value
    if envModifiedAfter is not "" then
        try
            set parsedDateStr to do shell script "date -j -f '%Y-%m-%d' " & quoted form of envModifiedAfter & " '+%Y-%m-%d'"
            set modifiedAfterKey to parsedDateStr & "T00:00:00"
            set modifiedAfterDate to modifiedAfterKey
            log "Filtering: only notes modified after " & modifiedAfterKey
        on error
            try
                set modifiedAfterDate to my isoLocal(date envModifiedAfter)
                log "Filtering: only notes modified after " & modifiedAfterDate
            on error errMsg
                log "Warning: Could not parse --modified-after date '" & envModifiedAfter & "': " & errMsg
            end try
        end try
    end if

    set htmlDirectory to envRootDir & "html/"
    set textDirectory to envRootDir & "text/"
    set dataDirectory to envRootDir & "data/"
    set rawDirectory to envRootDir & "raw/"
    my createDirectory(rawDirectory)
    my createDirectory(dataDirectory)
    my createDirectory(htmlDirectory)
    my createDirectory(textDirectory)

    -- Statistics
    set totalNotesOverall to 0
    set totalNotesOutput to 0
    set totalNotesUnchanged to 0
    set totalNotesFiltered to 0
    set totalNotesLocked to 0
    set totalNotesErrors to 0
    set foldersDone to 0
    set startTime to (current date)

    set livePath to dataDirectory & ".live_notes.tsv"
    set liveFD to open for access (POSIX file livePath) with write permission
    set eof of liveFD to 0

    set fatalMessage to ""
    set fatalNumber to 0
    try
        with timeout of 900 seconds
            -- ── Phase 1: plan the folders (names, ids, nesting) ──────────
            set plan to {}
            tell application "Notes" to set accountCount to count of accounts
            repeat with ai from 1 to accountCount
                tell application "Notes"
                    set rawAccountName to name of account ai
                    set accountFullID to id of account ai
                end tell
                set accountName to my makeValidFilename(rawAccountName)
                set accountMatches to true
                if envFilterAccounts is not "" then
                    if filterAccountsList does not contain rawAccountName and filterAccountsList does not contain accountName then
                        set accountMatches to false
                        log "Skipping account: " & accountName & " (not in filter)"
                    end if
                end if
                if accountMatches then
                    set accountID to my extractAccountID(accountFullID)
                    set shortAccountID to my extractShortAccountID(accountID)
                    tell application "Notes"
                        set folderIDs to id of every folder of account ai
                        set folderNames to name of every folder of account ai
                    end tell
                    set parentIDs to {}
                    repeat with fi from 1 to count of folderIDs
                        set parentID to ""
                        try
                            tell application "Notes" to set parentID to id of container of folder fi of account ai
                        end try
                        if parentID does not contain "/ICFolder/" then set parentID to ""
                        set end of parentIDs to parentID
                    end repeat
                    repeat with fi from 1 to count of folderIDs
                        set rawFolderName to item fi of folderNames
                        set folderName to my makeValidFilename(rawFolderName)
                        set rawPath to my folderPathNames(fi, folderIDs, folderNames, parentIDs)
                        set rawPathText to my joinList(rawPath, "/")
                        set safePathText to my joinList(my sanitizeList(rawPath), "/")
                        set folderMatches to true
                        if envFilterFolders is not "" then
                            if filterFoldersList does not contain rawFolderName and filterFoldersList does not contain folderName and filterFoldersList does not contain rawPathText then
                                set folderMatches to false
                            end if
                        end if
                        if envExcludeFolders is not "" then
                            if excludeFoldersList contains rawFolderName or excludeFoldersList contains folderName or excludeFoldersList contains rawPathText then
                                set folderMatches to false
                            end if
                        end if
                        if folderMatches then
                            set end of plan to {jAccountIndex:ai, jFolderIndex:fi, jRawAccount:rawAccountName, jAccount:accountName, jAccountFullID:accountFullID, jAccountID:accountID, jShortAccountID:shortAccountID, jFolderID:(item fi of folderIDs), jRawFolder:rawFolderName, jFolder:folderName, jRawPath:rawPath, jSafePath:safePathText}
                        else
                            log "Skipping folder: " & rawPathText & " (filtered)"
                        end if
                    end repeat
                end if
            end repeat

            set planCount to count of plan
            log "@@PLAN" & tab & planCount

            -- ── Phase 2: export each planned folder ─────────────────────
            repeat with planIndex from 1 to planCount
                set job to item planIndex of plan
                set ai to jAccountIndex of job
                set fi to jFolderIndex of job
                set accountName to jAccount of job
                set folderName to jFolder of job

                if useSubdirs then
                    set subdirName to my generateFilename(envSubdirFormat, "", "", accountName, folderName, jAccountID of job, jShortAccountID of job, jSafePath of job)
                    set trackerName to my trackerNameFor(subdirName)
                    set subdirPrefix to subdirName & "/"
                else
                    set subdirName to ""
                    set trackerName to accountName & "-" & folderName
                    set subdirPrefix to ""
                end if
                set folderHTMLPath to htmlDirectory & subdirPrefix
                set folderTextPath to textDirectory & subdirPrefix
                set folderRawPath to rawDirectory & subdirPrefix
                my createDirectory(folderHTMLPath)
                my createDirectory(folderTextPath)
                my createDirectory(folderRawPath)
                set notebookDataFile to dataDirectory & trackerName & ".json"

                -- Existing records: parallel lists for lookups
                set existing to my loadNotebookData(trackerIO, notebookDataFile, includeDeleted)
                set exIDs to item 1 of existing
                set exFilenames to item 2 of existing
                set exISOKeys to item 3 of existing
                set exLegacyKeys to item 4 of existing

                -- Batch fetch: a handful of Apple Events per folder
                tell application "Notes"
                    set aFolder to folder fi of account ai
                    set allFullIDs to id of every note of aFolder
                    set allModDates to modification date of every note of aFolder
                    set allCreated to creation date of every note of aFolder
                    set allNames to name of every note of aFolder
                end tell
                set noteCount to count of allFullIDs
                set allLocked to {}
                try
                    tell application "Notes" to set allLocked to password protected of every note of aFolder
                end try
                set allShared to {}
                try
                    tell application "Notes" to set allShared to shared of every note of aFolder
                end try

                set folderPathField to my tsvEscape(my joinList(jRawPath of job, character id 31))
                log "@@FOLDER" & tab & planIndex & tab & planCount & tab & my tsvEscape(jRawAccount of job) & tab & my tsvEscape(my joinList(jRawPath of job, "/")) & tab & noteCount

                set folderNoteCount to 0
                set liveText to ""
                set changedText to ""
                repeat with i from 1 to noteCount
                    set fullID to item i of allFullIDs
                    set noteID to my extractID(fullID)
                    set noteModDate to item i of allModDates
                    set noteCreatedDate to item i of allCreated
                    set modISO to my isoLocal(noteModDate)
                    set createdISO to my isoLocal(noteCreatedDate)
                    set rawTitle to item i of allNames
                    set isLocked to false
                    if (count of allLocked) ≥ i then set isLocked to (item i of allLocked)
                    set isShared to false
                    if (count of allShared) ≥ i then set isShared to (item i of allShared)
                    set totalNotesOverall to totalNotesOverall + 1

                    set liveText to liveText & "N" & tab & my tsvEscape(trackerName) & tab & noteID & tab & fullID & tab & my tsvEscape(rawTitle) & tab & createdISO & tab & modISO & tab & my tsvEscape(jRawAccount of job) & tab & (jAccountFullID of job) & tab & (jFolderID of job) & tab & folderPathField & tab & my tsvEscape(subdirName) & tab & my boolText(isLocked) & tab & my boolText(isShared) & linefeed

                    -- Decide whether to export this note
                    set wanted to true
                    if (noteLimit ≠ -1 and totalNotesOutput ≥ noteLimit) or (noteLimitPerFolder ≠ -1 and folderNoteCount ≥ noteLimitPerFolder) then set wanted to false
                    if wanted and modifiedAfterDate is not missing value then
                        if modISO ≤ modifiedAfterDate then set wanted to false
                    end if
                    if wanted and notePickProbability < 100 then
                        if (random number from 1 to 100) > notePickProbability then set wanted to false
                    end if
                    if not wanted then set totalNotesFiltered to totalNotesFiltered + 1

                    set exIndex to my indexOfItem(noteID, exIDs)
                    set shouldProcess to false
                    if wanted then
                        if updateAllNotes or exIndex is 0 then
                            set shouldProcess to true
                        else if (item exIndex of exISOKeys) is not "" then
                            set shouldProcess to ((item exIndex of exISOKeys) is not modISO)
                        else
                            set shouldProcess to ((item exIndex of exLegacyKeys) is not (noteModDate as string))
                        end if
                        if not shouldProcess then set totalNotesUnchanged to totalNotesUnchanged + 1
                    end if

                    if shouldProcess and isLocked then
                        set shouldProcess to false
                        set totalNotesLocked to totalNotesLocked + 1
                        log "- Note " & noteID & " is locked (password protected); skipped"
                    end if

                    if shouldProcess then
                        try
                            set theNote to missing value
                            tell application "Notes"
                                try
                                    set theNote to note id fullID
                                end try
                                if theNote is missing value then
                                    set theNote to note i of aFolder
                                    if (id of theNote) is not fullID then error "the folder changed while it was being exported"
                                end if
                                set htmlContent to body of theNote
                                set textContent to plaintext of theNote
                            end tell
                            set noteTitle to my makeValidFilename(rawTitle)
                            set noteName to my generateFilename(envFilenameFormat, noteTitle, noteID, accountName, folderName, jAccountID of job, jShortAccountID of job, jSafePath of job)
                            set oldFileName to ""
                            if exIndex > 0 then set oldFileName to item exIndex of exFilenames

                            if not my writeToFile(POSIX path of (folderRawPath & noteName & ".html"), htmlContent) then error "could not write the raw HTML file"
                            if not my writeToFile(POSIX path of (folderTextPath & noteName & ".txt"), textContent) then error "could not write the text file"
                            my handleFilenameChange(envRootDir, subdirPrefix, oldFileName, noteName)

                            set changedText to changedText & noteID & tab & fullID & tab & noteName & tab & my tsvEscape(rawTitle) & tab & createdISO & tab & modISO & tab & (noteCreatedDate as string) & tab & (noteModDate as string) & tab & my tsvEscape(jRawAccount of job) & tab & (jAccountFullID of job) & tab & (jFolderID of job) & tab & folderPathField & tab & my tsvEscape(subdirName) & linefeed

                            set folderNoteCount to folderNoteCount + 1
                            set totalNotesOutput to totalNotesOutput + 1
                            log "@@NOTE" & tab & totalNotesOutput & tab & noteID
                        on error errMsg number errNum
                            if errNum is -1743 or errNum is -128 or errNum is -600 or errNum is -609 then error errMsg number errNum
                            set totalNotesErrors to totalNotesErrors + 1
                            log "@@NOTE_ERROR" & tab & noteID & tab & my tsvEscape(errMsg)
                            set liveText to liveText & "E" & tab & my tsvEscape(trackerName) & tab & noteID & tab & fullID & tab & my tsvEscape(errMsg) & linefeed
                        end try
                    end if
                end repeat

                -- Save processed notes, then record that this folder was read completely
                if changedText is not "" then
                    set saveResult to my saveNotebookData(trackerIO, notebookDataFile, changedText, dataDirectory)
                    if saveResult is not "" then
                        set totalNotesErrors to totalNotesErrors + 1
                        log "@@SAVE_ERROR" & tab & my tsvEscape(trackerName) & tab & my tsvEscape(saveResult)
                    end if
                end if
                set liveText to liveText & "F" & tab & my tsvEscape(trackerName) & tab & (jFolderID of job) & tab & my tsvEscape(subdirName) & linefeed
                write liveText to liveFD starting at eof as «class utf8»
                set foldersDone to foldersDone + 1
            end repeat
        end timeout
        write ("END" & linefeed) to liveFD starting at eof as «class utf8»
    on error errMsg number errNum
        set fatalMessage to errMsg
        set fatalNumber to errNum
    end try
    try
        close access liveFD
    end try

    set elapsedSeconds to (current date) - startTime
    set statsContent to "total=" & totalNotesOverall & linefeed & "processed=" & totalNotesOutput & linefeed & "unchanged=" & totalNotesUnchanged & linefeed & "filtered=" & totalNotesFiltered & linefeed & "locked=" & totalNotesLocked & linefeed & "errors=" & totalNotesErrors & linefeed & "folders=" & foldersDone & linefeed & "elapsed=" & elapsedSeconds & linefeed & "fatal_number=" & fatalNumber & linefeed
    my writeToFile(dataDirectory & "export_stats.tmp", statsContent)

    log "==== EXPORT STATISTICS ===="
    log "Folders Parsed: " & foldersDone
    log "Total Notes Examined: " & totalNotesOverall
    log "Total Notes Processed/Updated: " & totalNotesOutput
    log "Total Notes Skipped (Unchanged): " & totalNotesUnchanged
    log "Total Notes Skipped (Filtered): " & totalNotesFiltered
    log "Locked Notes Skipped: " & totalNotesLocked
    log "Errors: " & totalNotesErrors
    log "Processing Time: " & elapsedSeconds & " seconds"

    if fatalMessage is not "" then error fatalMessage number fatalNumber
end run

-- ── Folder hierarchy ──────────────────────────────────────────────────────

-- Raw folder names from the top-level folder down to folder fi.
on folderPathNames(fi, folderIDs, folderNames, parentIDs)
    set pathNames to {item fi of folderNames}
    set currentParent to item fi of parentIDs
    set guard to 0
    repeat while currentParent is not "" and guard < 200
        set guard to guard + 1
        set parentIndex to my indexOfItem(currentParent, folderIDs)
        if parentIndex is 0 then exit repeat
        set beginning of pathNames to item parentIndex of folderNames
        set currentParent to item parentIndex of parentIDs
    end repeat
    return pathNames
end folderPathNames

on sanitizeList(theList)
    set out to {}
    repeat with anItem in theList
        set end of out to my makeValidFilename(anItem as text)
    end repeat
    return out
end sanitizeList

-- Tracker file names are flat; '/' from a nested subdir is percent-encoded.
on trackerNameFor(subdirName)
    set encoded to my replaceText("%", "%25", subdirName)
    return my replaceText("/", "%2F", encoded)
end trackerNameFor

-- ── Small pure helpers (tested in tests/test_applescript_handlers.py) ─────

on indexOfItem(theValue, theList)
    repeat with i from 1 to count of theList
        if (item i of theList) is theValue then return i
    end repeat
    return 0
end indexOfItem

on joinList(theList, delimiter)
    set AppleScript's text item delimiters to delimiter
    set joined to theList as text
    set AppleScript's text item delimiters to ""
    return joined
end joinList

on boolText(aValue)
    try
        if aValue then return "1"
    end try
    return "0"
end boolText

on pad2(n)
    set n to n as integer
    if n < 10 then return "0" & n
    return n as text
end pad2

-- Locale-independent local wall-clock time: YYYY-MM-DDTHH:MM:SS
on isoLocal(d)
    set y to (year of d) as integer
    set m to (month of d) as integer
    return (y as text) & "-" & my pad2(m) & "-" & my pad2(day of d) & "T" & my pad2(hours of d) & ":" & my pad2(minutes of d) & ":" & my pad2(seconds of d)
end isoLocal

-- Escape a field for the tab-separated files tracker_io.py reads.
on tsvEscape(t)
    set t to t as text
    set t to my replaceText("\\", "\\\\", t)
    set t to my replaceText(tab, "\\t", t)
    set t to my replaceText(linefeed, "\\n", t)
    set t to my replaceText(return, "\\r", t)
    return t
end tsvEscape

on createDirectory(directoryPath)
    do shell script "mkdir -p " & quoted form of directoryPath
end createDirectory

-- Subroutine to write content to a file (with UTF-8 encoding support).
-- Replaces the file's contents (it used to append at eof, so every re-export
-- doubled the file) and always closes the descriptor it opened.
-- Returns true on success, false on failure.
on writeToFile(filePath, content)
    set fileDescriptor to missing value
    try
        set fileDescriptor to open for access (POSIX file filePath) with write permission
        set eof of fileDescriptor to 0
        write content to fileDescriptor starting at 0 as «class utf8»
        close access fileDescriptor
        return true
    on error errMsg number errNum
        log "Error writing to file " & filePath & ": " & errMsg & " (" & errNum & ")"
        if fileDescriptor is not missing value then
            try
                close access fileDescriptor
            end try
        end if
        return false
    end try
end writeToFile

-- Make a name safe for a file name: problem characters become dashes,
-- runs of dashes collapse, leading/trailing dashes go.
on makeValidFilename(fileName)
    set charactersToReplace to {"/", ":", "\\", "|", "<", ">", "\"", "'", "?", "*", "_", " ", ".", ",", tab, linefeed, return}
    repeat with aChar in charactersToReplace
        set AppleScript's text item delimiters to aChar
        set fileName to text items of fileName
        set AppleScript's text item delimiters to "-"
        set fileName to fileName as string
    end repeat
    set AppleScript's text item delimiters to ""

    repeat while fileName contains "--"
        set AppleScript's text item delimiters to "--"
        set textItems to text items of fileName
        set AppleScript's text item delimiters to "-"
        set fileName to textItems as string
    end repeat
    set AppleScript's text item delimiters to ""

    repeat while fileName starts with "-" and length of fileName > 1
        set fileName to text 2 through -1 of fileName
    end repeat
    repeat while fileName ends with "-" and length of fileName > 1
        set fileName to text 1 through -2 of fileName
    end repeat
    if fileName is "" or fileName is "-" then set fileName to "untitled"
    return fileName
end makeValidFilename

-- Fill a filename / subdirectory template. Longer tokens are replaced first
-- (&accountid used to be eaten by &account, &folderpath by &folder).
on generateFilename(format, title, noteID, account, folder, accountID, shortAccountID, folderPath)
    set s to format
    set s to my replaceText("&shortaccountid", shortAccountID, s)
    set s to my replaceText("&accountid", accountID, s)
    set s to my replaceText("&account", account, s)
    set s to my replaceText("&folderpath", folderPath, s)
    set s to my replaceText("&path", folderPath, s)
    set s to my replaceText("&folder", folder, s)
    set s to my replaceText("&title", title, s)
    set s to my replaceText("&id", noteID, s)
    return s
end generateFilename

on replaceText(find, replace, subject)
    set AppleScript's text item delimiters to find
    set subject to text items of subject
    set AppleScript's text item delimiters to replace
    set subject to subject as string
    set AppleScript's text item delimiters to ""
    return subject
end replaceText

-- x-coredata://STORE/ICNote/p123 -> 123
on extractID(fullID)
    set AppleScript's text item delimiters to "/"
    set idComponents to text items of fullID
    set AppleScript's text item delimiters to ""
    set extractedID to last item of idComponents
    if extractedID starts with "p" then set extractedID to text 2 through -1 of extractedID
    return extractedID
end extractID

-- x-coredata://STORE/ICAccount/p1 -> STORE
on extractAccountID(fullID)
    set AppleScript's text item delimiters to "/"
    set idComponents to text items of fullID
    set AppleScript's text item delimiters to ""
    if (count of idComponents) ≥ 3 then return item 3 of idComponents
    return fullID
end extractAccountID

-- STORE UUID -> its last group
on extractShortAccountID(accountID)
    set AppleScript's text item delimiters to "-"
    set idComponents to text items of accountID
    set AppleScript's text item delimiters to ""
    return last item of idComponents
end extractShortAccountID

on splitByDelimiter(textString, delimiter)
    if textString is "" then return {}
    set AppleScript's text item delimiters to delimiter
    set textItems to text items of textString
    set AppleScript's text item delimiters to ""
    return textItems
end splitByDelimiter

-- ── Tracking data (through tracker_io.py) ────────────────────────────────

-- Returns {ids, filenames, isoKeys, legacyKeys}
on loadNotebookData(trackerIO, filePath, includeDeleted)
    set ids to {}
    set filenames to {}
    set isoKeys to {}
    set legacyKeys to {}
    try
        set flag to "0"
        if includeDeleted then set flag to "1"
        set output to do shell script trackerIO & " load " & quoted form of filePath & " " & flag
        repeat with aLine in paragraphs of output
            set aLine to aLine as text
            if aLine is not "" then
                set parts to my splitByDelimiter(aLine, tab)
                if (count of parts) ≥ 4 then
                    set end of ids to item 1 of parts
                    set end of filenames to my tsvUnescape(item 2 of parts)
                    set end of isoKeys to item 3 of parts
                    set end of legacyKeys to my tsvUnescape(item 4 of parts)
                end if
            end if
        end repeat
    on error errMsg
        log "Error loading tracking data " & filePath & ": " & errMsg
    end try
    return {ids, filenames, isoKeys, legacyKeys}
end loadNotebookData

on tsvUnescape(t)
    if t does not contain "\\" then return t
    set t to my replaceText("\\\\", (character id 1), t)
    set t to my replaceText("\\t", tab, t)
    set t to my replaceText("\\n", linefeed, t)
    set t to my replaceText("\\r", return, t)
    return my replaceText((character id 1), "\\", t)
end tsvUnescape

-- Write the rows to a temp file natively, then merge them with tracker_io.py.
-- Returns "" on success or the error message.
on saveNotebookData(trackerIO, filePath, rowsText, dataDirectory)
    set tmpPath to dataDirectory & ".save_rows.tsv"
    try
        if not my writeToFile(tmpPath, rowsText) then error "could not write " & tmpPath
        do shell script trackerIO & " save " & quoted form of filePath & " " & quoted form of tmpPath
        do shell script "rm -f " & quoted form of tmpPath
        return ""
    on error errMsg
        return errMsg
    end try
end saveNotebookData

-- ── Renames: remove the previous files of a note in every format ─────────

on handleFilenameChange(rootDir, subdirPrefix, oldFileName, newFileName)
    if oldFileName is "" or oldFileName is newFileName then return
    log "Filename changed: " & oldFileName & " -> " & newFileName
    set oldPaths to {}
    repeat with spec in {{"raw", ".html"}, {"html", ".html"}, {"text", ".txt"}, {"md", ".md"}, {"pdf", ".pdf"}, {"docx", ".docx"}}
        set end of oldPaths to rootDir & (item 1 of spec) & "/" & subdirPrefix & oldFileName & (item 2 of spec)
    end repeat
    my deleteOldFilesSafely(oldPaths, oldFileName)
    my deleteAttachmentsFromAllFormats(rootDir, subdirPrefix, oldFileName)
end handleFilenameChange

on deleteAttachmentsFromAllFormats(rootDir, subdirPrefix, oldFileName)
    repeat with formatDir in {"html", "md", "pdf", "docx"}
        set folderPath to rootDir & formatDir & "/" & subdirPrefix
        repeat with attachmentDir in {folderPath & "attachments", folderPath}
            try
                do shell script "if [ -d " & quoted form of (attachmentDir as text) & " ]; then find " & quoted form of (attachmentDir as text) & " -maxdepth 1 -type f -name " & quoted form of (oldFileName & "-attachment-*") & " -delete; fi"
            on error errMsg
                log "Error deleting attachments for " & oldFileName & ": " & errMsg
            end try
        end repeat
    end repeat
end deleteAttachmentsFromAllFormats

on deleteOldFilesSafely(filePaths, oldFileName)
    repeat with filePath in filePaths
        try
            do shell script "rm -f " & quoted form of (filePath as text)
        on error errMsg
            log "Could not delete old file " & filePath & ": " & errMsg
        end try
    end repeat
end deleteOldFilesSafely
