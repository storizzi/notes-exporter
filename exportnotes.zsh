#!/bin/zsh

# Set environment variable defaults
if [[ -z "${NOTES_EXPORT_ROOT_DIR}" ]]; then
    export NOTES_EXPORT_ROOT_DIR=$HOME/Downloads/AppleNotesExport
    # export NOTES_EXPORT_ROOT_DIR=$(pwd)/AppleNotesExport
fi
if [[ -z "${NOTES_EXPORT_SUPPRESS_CHROME_HEADER_PDF}" ]]; then
    export NOTES_EXPORT_SUPPRESS_CHROME_HEADER_PDF=true
fi
if [[ -z "${NOTES_EXPORT_CONVERT_TO_MARKDOWN}" ]]; then
    export NOTES_EXPORT_CONVERT_TO_MARKDOWN=false
fi
if [[ -z "${NOTES_EXPORT_CONVERT_TO_PDF}" ]]; then
    export NOTES_EXPORT_CONVERT_TO_PDF=false
fi
if [[ -z "${NOTES_EXPORT_CONVERT_TO_WORD}" ]]; then
    export NOTES_EXPORT_CONVERT_TO_WORD=false
fi
if [[ -z "${NOTES_EXPORT_EXTRACT_IMAGES}" ]]; then
    export NOTES_EXPORT_EXTRACT_IMAGES=true
fi
if [[ -z "${NOTES_EXPORT_EXTRACT_DATA}" ]]; then
    export NOTES_EXPORT_EXTRACT_DATA=true
fi
if [[ -z "${NOTES_EXPORT_NOTE_ID_IN_FILENAME}" ]]; then
    export NOTES_EXPORT_NOTE_ID_IN_FILENAME=false
fi

# Force image extraction if either Markdown, PDF, or Word conversion is enabled
if [[ "${NOTES_EXPORT_CONVERT_TO_MARKDOWN}" == "true" || "${NOTES_EXPORT_CONVERT_TO_PDF}" == "true" || "${NOTES_EXPORT_CONVERT_TO_WORD}" == "true" ]]; then
    export NOTES_EXPORT_EXTRACT_IMAGES=true
fi

# Parse long command line options first
while [[ $# -gt 0 ]]; do
    case $1 in
        --root-dir) export NOTES_EXPORT_ROOT_DIR="$2"; shift 2 ;;
        --suppress-header-pdf) export NOTES_EXPORT_SUPPRESS_CHROME_HEADER_PDF="$2"; shift 2 ;;
        --convert-markdown) export NOTES_EXPORT_CONVERT_TO_MARKDOWN="$2"; shift 2 ;;
        --convert-pdf) export NOTES_EXPORT_CONVERT_TO_PDF="$2"; shift 2 ;;
        --convert-word) export NOTES_EXPORT_CONVERT_TO_WORD="$2"; shift 2 ;;
        --extract-images) export NOTES_EXPORT_EXTRACT_IMAGES="$2"; shift 2 ;;
        --extract-data) export NOTES_EXPORT_EXTRACT_DATA="$2"; shift 2 ;;
        --note-limit) export NOTES_EXPORT_NOTE_LIMIT="$2"; shift 2 ;;
        --note-limit-per-folder) export NOTES_EXPORT_NOTE_LIMIT_PER_FOLDER="$2"; shift 2 ;;
        --note-pick-probability) export NOTES_EXPORT_NOTE_PICK_PROBABILITY="$2"; shift 2 ;;
        --id-in-filename) export NOTES_EXPORT_NOTE_ID_IN_FILENAME="$2"; shift 2 ;;
        --) shift; break ;;
        -*) break ;;
        *) echo "Invalid -- option: $1" >&2; exit 1 ;;
    esac
done

# Parse short command line options using getopts
while getopts "r:s:m:p:i:l:f:b:w:e:" opt; do
  case $opt in
    r) export NOTES_EXPORT_ROOT_DIR="$OPTARG" ;;
    s) export NOTES_EXPORT_SUPPRESS_CHROME_HEADER_PDF="$OPTARG" ;;
    m) export NOTES_EXPORT_CONVERT_TO_MARKDOWN="$OPTARG" ;;
    p) export NOTES_EXPORT_CONVERT_TO_PDF="$OPTARG" ;;
    w) export NOTES_EXPORT_CONVERT_TO_WORD="$OPTARG" ;;
    i) export NOTES_EXPORT_EXTRACT_IMAGES="$OPTARG" ;;
    l) export NOTES_EXPORT_NOTE_LIMIT="$OPTARG" ;;
    f) export NOTES_EXPORT_NOTE_LIMIT_PER_FOLDER="$OPTARG" ;;
    b) export NOTES_EXPORT_NOTE_PICK_PROBABILITY="$OPTARG" ;;
    e) export NOTES_EXPORT_EXTRACT_DATA="$OPTARG" ;;
    d) export NOTES_EXPORT_NOTE_ID_IN_FILENAME="$OPTARG" ;;
    \?) echo "Invalid - option: -$OPTARG" >&2; exit 1 ;;
  esac
done

# Path to your AppleScript
APPLESCRIPT_PATH="./export-notes.scpt"

# Conditionally execute the AppleScript for data extraction
if [[ "${NOTES_EXPORT_EXTRACT_DATA}" == "true" ]]; then
    osascript "$APPLESCRIPT_PATH"
fi

# Conditionally execute the image extraction script
if [[ "${NOTES_EXPORT_EXTRACT_IMAGES}" == "true" ]]; then
    python3 ./extract-images.py
fi

# Conditionally execute the conversion scripts
if [[ "${NOTES_EXPORT_CONVERT_TO_MARKDOWN}" == "true" ]]; then
    python3 ./convert-to-markdown.py
fi

if [[ "${NOTES_EXPORT_CONVERT_TO_PDF}" == "true" ]]; then
    python3 ./convert-to-pdf.py
fi

if [[ "${NOTES_EXPORT_CONVERT_TO_WORD}" == "true" ]]; then
    python3 ./convert-to-word.py
fi
