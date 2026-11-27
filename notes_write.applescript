-- notes_write.applescript — the service's only way of writing to Apple Notes
-- (SERVICE-API.md "Writing notes"). Run by notes_write_helper.py, never by the exporter.
--
--   osascript notes_write.applescript modified <note id>
--   osascript notes_write.applescript update <note id> <title> <body file>
--   osascript notes_write.applescript create <account> <title> <body file> <folder> [<subfolder> …]
--   osascript notes_write.applescript backup <note id> <account> <backup folder> <title suffix> [<folder> …]
--   osascript notes_write.applescript delete <note id>
--
-- backup copies the note (its name and body — the HTML Notes gives, pictures embedded) into
-- <backup folder> at the top of <account>, beneath it the folders named (made when missing),
-- titled with <title suffix> added; it answers the copy's id. delete is Notes' own delete: the
-- note goes to Recently Deleted. Neither touches a locked (password protected) note.
--
-- Every value arrives as its own argument and the body (HTML) from a UTF-8 file, so nothing
-- is split or quoted here. The answer, on stdout, is one line:
--   ok<TAB><note id><TAB><modification date, local ISO 8601>
--   error<TAB><number><TAB><message>

on run argv
    set op to item 1 of argv
    try
        if op is "modified" then
            tell application "Notes"
                set theNote to note id (item 2 of argv)
                set noteId to id of theNote
                set modDate to modification date of theNote
            end tell
        else if op is "update" then
            set bodyText to my readFile(item 4 of argv)
            tell application "Notes"
                set theNote to note id (item 2 of argv)
                set body of theNote to bodyText
                if (item 3 of argv) is not "" then set name of theNote to (item 3 of argv)
                set noteId to id of theNote
                set modDate to modification date of theNote
            end tell
        else if op is "create" then
            set bodyText to my readFile(item 4 of argv)
            set folderNames to items 5 thru -1 of argv
            tell application "Notes"
                set target to folder (item 1 of folderNames) of account (item 2 of argv)
                repeat with i from 2 to count of folderNames
                    set target to folder (item i of folderNames) of target
                end repeat
                set theNote to make new note at target with properties {body:bodyText}
                if (item 3 of argv) is not "" then set name of theNote to (item 3 of argv)
                set noteId to id of theNote
                set modDate to modification date of theNote
            end tell
        else if op is "backup" then
            set folderNames to {}
            if (count of argv) > 5 then set folderNames to items 6 thru -1 of argv
            tell application "Notes"
                set theNote to note id (item 2 of argv)
                if password protected of theNote then error "the note is locked" number -10050
                set srcName to name of theNote
                set srcBody to body of theNote
                set target to my childFolder(account (item 3 of argv), item 4 of argv)
                repeat with nm in folderNames
                    set target to my childFolder(target, contents of nm)
                end repeat
                set theCopy to make new note at target with properties {body:srcBody}
                set name of theCopy to (srcName & (item 5 of argv))
                set noteId to id of theCopy
                set modDate to modification date of theCopy
            end tell
        else if op is "delete" then
            tell application "Notes"
                set theNote to note id (item 2 of argv)
                if password protected of theNote then error "the note is locked" number -10050
                set noteId to id of theNote
                set modDate to modification date of theNote
                delete theNote
            end tell
        else
            return "error" & tab & "-1" & tab & "unknown operation " & op
        end if
        return "ok" & tab & noteId & tab & my isoLocal(modDate)
    on error errMsg number errNum
        return "error" & tab & (errNum as text) & tab & my oneLine(errMsg)
    end try
end run

-- The folder called nm directly inside parentObj (an account or a folder), made when missing.
-- "folders of" an account lists nested folders too, so the container is checked.
on childFolder(parentObj, nm)
    tell application "Notes"
        set parentId to id of parentObj
        repeat with f in (every folder of parentObj whose name is nm)
            if (id of (container of f)) is parentId then return contents of f
        end repeat
        return make new folder at parentObj with properties {name:nm}
    end tell
end childFolder

on readFile(p)
    return read (POSIX file p) as «class utf8»
end readFile

on pad2(n)
    set n to n as integer
    if n < 10 then return "0" & (n as text)
    return n as text
end pad2

on isoLocal(d)
    set y to (year of d) as integer
    set m to (month of d) as integer
    return (y as text) & "-" & my pad2(m) & "-" & my pad2(day of d) & "T" & my pad2(hours of d) & ":" & my pad2(minutes of d) & ":" & my pad2(seconds of d)
end isoLocal

on oneLine(t)
    set AppleScript's text item delimiters to {return, linefeed, tab}
    set parts to text items of (t as text)
    set AppleScript's text item delimiters to " "
    set t to parts as text
    set AppleScript's text item delimiters to ""
    return t
end oneLine
