-- sync_notes.scpt
-- AppleScript for writing/creating notes and checking modification dates
-- Accepts a JSON command file, writes results to a JSON output file

on run argv
    set inputFile to item 1 of argv
    set outputFile to item 2 of argv

    -- Read the input JSON command
    set commandJSON to do shell script "cat " & quoted form of inputFile

    -- Parse the command using Python
    set parsedCommand to do shell script "python3 -c \"
import json, sys
cmd = json.loads(sys.stdin.read())
parts = [
    cmd.get('operation', ''),
    cmd.get('fullNoteId', ''),
    cmd.get('title', ''),
    cmd.get('body', ''),
    cmd.get('account', ''),
    cmd.get('folder', '')
]
print('|||'.join(parts))
\" <<< " & quoted form of commandJSON

    -- Split the parsed result
    set AppleScript's text item delimiters to "|||"
    set cmdParts to text items of parsedCommand
    set AppleScript's text item delimiters to ""

    set operation to item 1 of cmdParts
    set fullNoteId to item 2 of cmdParts
    set noteTitle to item 3 of cmdParts
    set noteBody to item 4 of cmdParts
    set accountName to item 5 of cmdParts
    set folderName to item 6 of cmdParts

    set resultJSON to ""

    if operation is "update" then
        set resultJSON to my updateNote(fullNoteId, noteTitle, noteBody)
    else if operation is "create" then
        set resultJSON to my createNote(accountName, folderName, noteTitle, noteBody)
    else if operation is "get_modified" then
        set resultJSON to my getModifiedDate(fullNoteId)
    else
        set resultJSON to "{\"success\": false, \"error\": \"Unknown operation: " & operation & "\"}"
    end if

    -- Write result to output file
    do shell script "cat > " & quoted form of outputFile & " <<'EOFRESULT'\n" & resultJSON & "\nEOFRESULT"
end run

on updateNote(fullNoteId, noteTitle, noteBody)
    try
        tell application "Notes"
            set matchedNote to first note whose id is fullNoteId
            set body of matchedNote to noteBody
            if noteTitle is not "" then
                set name of matchedNote to noteTitle
            end if
            set newModDate to (modification date of matchedNote) as string
        end tell
        return "{\"success\": true, \"modifiedDate\": \"" & my escapeJSON(newModDate) & "\"}"
    on error errMsg
        return "{\"success\": false, \"error\": \"" & my escapeJSON(errMsg) & "\"}"
    end try
end updateNote

on createNote(accountName, folderName, noteTitle, noteBody)
    try
        tell application "Notes"
            set targetAccount to first account whose name is accountName
            set targetFolder to first folder of targetAccount whose name is folderName
            set newNote to make new note at targetFolder with properties {name:noteTitle, body:noteBody}
            set newNoteId to id of newNote
            set newModDate to (modification date of newNote) as string
        end tell
        return "{\"success\": true, \"fullNoteId\": \"" & my escapeJSON(newNoteId) & "\", \"modifiedDate\": \"" & my escapeJSON(newModDate) & "\"}"
    on error errMsg
        return "{\"success\": false, \"error\": \"" & my escapeJSON(errMsg) & "\"}"
    end try
end createNote

on getModifiedDate(fullNoteId)
    try
        tell application "Notes"
            set matchedNote to first note whose id is fullNoteId
            set modDate to (modification date of matchedNote) as string
        end tell
        return "{\"success\": true, \"modifiedDate\": \"" & my escapeJSON(modDate) & "\"}"
    on error errMsg
        return "{\"success\": false, \"error\": \"" & my escapeJSON(errMsg) & "\"}"
    end try
end getModifiedDate

-- Escape special characters for JSON strings
on escapeJSON(inputString)
    set resultString to inputString
    -- Escape backslashes first
    set resultString to my replaceText("\\", "\\\\", resultString)
    -- Escape double quotes
    set resultString to my replaceText("\"", "\\\"", resultString)
    -- Escape newlines
    set resultString to my replaceText(return, "\\n", resultString)
    set resultString to my replaceText(linefeed, "\\n", resultString)
    return resultString
end escapeJSON

on replaceText(find, replace, subject)
    set AppleScript's text item delimiters to find
    set subject to text items of subject
    set AppleScript's text item delimiters to replace
    set subject to subject as string
    set AppleScript's text item delimiters to ""
    return subject
end replaceText
