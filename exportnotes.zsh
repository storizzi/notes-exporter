#!/bin/zsh

# Start timing
SCRIPT_START_TIME=$SECONDS

# Determine the directory where the script is located
SCRIPT_DIR=$(dirname "$0")

# Set environment variable defaults and export them
export NOTES_EXPORT_ROOT_DIR="${NOTES_EXPORT_ROOT_DIR:=$HOME/Downloads/AppleNotesExport}"
export NOTES_EXPORT_SUPPRESS_CHROME_HEADER_PDF="${NOTES_EXPORT_SUPPRESS_CHROME_HEADER_PDF:=true}"
export NOTES_EXPORT_CONVERT_TO_MARKDOWN="${NOTES_EXPORT_CONVERT_TO_MARKDOWN:=false}"
export NOTES_EXPORT_CONVERT_TO_PDF="${NOTES_EXPORT_CONVERT_TO_PDF:=false}"
export NOTES_EXPORT_CONVERT_TO_WORD="${NOTES_EXPORT_CONVERT_TO_WORD:=false}"
export NOTES_EXPORT_EXTRACT_IMAGES="${NOTES_EXPORT_EXTRACT_IMAGES:=true}"
export NOTES_EXPORT_EXTRACT_DATA="${NOTES_EXPORT_EXTRACT_DATA:=true}"
export NOTES_EXPORT_FILENAME_FORMAT="${NOTES_EXPORT_FILENAME_FORMAT:=&title-&id}"
export NOTES_EXPORT_SUBDIR_FORMAT="${NOTES_EXPORT_SUBDIR_FORMAT:=&account-&folder}"
export NOTES_EXPORT_USE_SUBDIRS="${NOTES_EXPORT_USE_SUBDIRS:=true}"
export NOTES_EXPORT_CONDA_ENV="${NOTES_EXPORT_CONDA_ENV:=}"
export NOTES_EXPORT_REMOVE_CONDA_ENV="${NOTES_EXPORT_REMOVE_CONDA_ENV:=false}"
export NOTES_EXPORT_UPDATE_ALL="${NOTES_EXPORT_UPDATE_ALL:=false}"  # NEW: Default to incremental updates
export NOTES_EXPORT_SET_FILE_DATES="${NOTES_EXPORT_SET_FILE_DATES:=true}"  # Set filesystem dates to match Notes.app
export NOTES_EXPORT_FOLDERS="${NOTES_EXPORT_FOLDERS:=}"  # Comma-separated list of folder names to export (empty = all folders)
export NOTES_EXPORT_CLEANUP="${NOTES_EXPORT_CLEANUP:=false}"  # Cleanup source directories after PDF conversion
export NOTES_EXPORT_CONTINUOUS_PDF="${NOTES_EXPORT_CONTINUOUS_PDF:=false}"  # Export PDFs as continuous page (for handwritten notes)

# Force image extraction if either Markdown, PDF, or Word conversion is enabled
if [[ "${NOTES_EXPORT_CONVERT_TO_MARKDOWN}" == "true" || "${NOTES_EXPORT_CONVERT_TO_PDF}" == "true" || "${NOTES_EXPORT_CONVERT_TO_WORD}" == "true" ]]; then
    export NOTES_EXPORT_EXTRACT_IMAGES=true
fi

# Parse long and short command line options
while [[ $# -gt 0 ]]; do
    case $1 in
        --root-dir|-r)
            if [[ -z "$2" ]]; then
                echo "Error: --root-dir requires an argument."
                exit 1
            fi
            export NOTES_EXPORT_ROOT_DIR="$2"
            shift 2
            ;;
        --suppress-header-pdf|-s)
            if [[ -z "$2" ]]; then
                echo "Error: --suppress-header-pdf requires an argument."
                exit 1
            fi
            export NOTES_EXPORT_SUPPRESS_CHROME_HEADER_PDF="$2"
            shift 2
            ;;
        --convert-markdown|-m)
            if [[ -z "$2" ]]; then
                echo "Error: --convert-markdown requires an argument."
                exit 1
            fi
            export NOTES_EXPORT_CONVERT_TO_MARKDOWN="$2"
            shift 2
            ;;
        --convert-pdf|-p)
            if [[ -z "$2" ]]; then
                echo "Error: --convert-pdf requires an argument."
                exit 1
            fi
            export NOTES_EXPORT_CONVERT_TO_PDF="$2"
            shift 2
            ;;
        --convert-word|-w)
            if [[ -z "$2" ]]; then
                echo "Error: --convert-word requires an argument."
                exit 1
            fi
            export NOTES_EXPORT_CONVERT_TO_WORD="$2"
            shift 2
            ;;
        --extract-images|-i)
            if [[ -z "$2" ]]; then
                echo "Error: --extract-images requires an argument."
                exit 1
            fi
            export NOTES_EXPORT_EXTRACT_IMAGES="$2"
            shift 2
            ;;
        --extract-data|-d)
            if [[ -z "$2" ]]; then
                echo "Error: --extract-data requires an argument."
                exit 1
            fi
            export NOTES_EXPORT_EXTRACT_DATA="$2"
            shift 2
            ;;
        --note-limit|-n)
            if [[ -z "$2" ]]; then
                echo "Error: --note-limit requires an argument."
                exit 1
            fi
            export NOTES_EXPORT_NOTE_LIMIT="$2"
            shift 2
            ;;
        --note-limit-per-folder|-f)
            if [[ -z "$2" ]]; then
                echo "Error: --note-limit-per-folder requires an argument."
                exit 1
            fi
            export NOTES_EXPORT_NOTE_LIMIT_PER_FOLDER="$2"
            shift 2
            ;;
        --note-pick-probability|-b)
            if [[ -z "$2" ]]; then
                echo "Error: --note-pick-probability requires an argument."
                exit 1
            fi
            export NOTES_EXPORT_NOTE_PICK_PROBABILITY="$2"
            shift 2
            ;;
        --filename-format|-t)
            if [[ -z "$2" ]]; then
                echo "Error: --filename-format requires an argument."
                exit 1
            fi
            export NOTES_EXPORT_FILENAME_FORMAT="$2"
            shift 2
            ;;
        --subdir-format|-u)
            if [[ -z "$2" ]]; then
                echo "Error: --subdir-format requires an argument."
                exit 1
            fi
            export NOTES_EXPORT_SUBDIR_FORMAT="$2"
            shift 2
            ;;
        --use-subdirs|-x)
            if [[ -z "$2" ]]; then
                echo "Error: --use-subdirs requires an argument."
                exit 1
            fi
            export NOTES_EXPORT_USE_SUBDIRS="$2"
            shift 2
            ;;
        --set-file-dates|-D)
            if [[ -z "$2" ]]; then
                echo "Error: --set-file-dates requires an argument."
                exit 1
            fi
            export NOTES_EXPORT_SET_FILE_DATES="$2"
            shift 2
            ;;
        --folders|-F)
            if [[ -z "$2" ]]; then
                echo "Error: --folders requires an argument."
                exit 1
            fi
            export NOTES_EXPORT_FOLDERS="$2"
            shift 2
            ;;
        --cleanup|-C)
            export NOTES_EXPORT_CLEANUP="true"
            shift
            ;;
        --continuous-pdf|-P)
            export NOTES_EXPORT_CONTINUOUS_PDF="true"
            shift
            ;;
        --uv-venv|-c)
            if [[ -z "$2" ]]; then
                echo "Error: --conda-env requires an argument."
                exit 1
            fi
            export NOTES_EXPORT_CONDA_ENV="$2"
            shift 2
            ;;
        --remove-conda-env|-e)
            if [[ -z "$2" ]]; then
                echo "Error: --remove-conda-env requires an argument."
                exit 1
            fi
            export NOTES_EXPORT_REMOVE_CONDA_ENV="$2"
            shift 2
            ;;
        --update-all|-U)
            # NEW: Force full update of all notes (disable incremental updates)
            export NOTES_EXPORT_UPDATE_ALL="true"
            shift
            ;;
        --all-formats|--all|-a)
            export NOTES_EXPORT_CONVERT_TO_MARKDOWN="true"
            export NOTES_EXPORT_CONVERT_TO_PDF="true"
            export NOTES_EXPORT_CONVERT_TO_WORD="true"
            export NOTES_EXPORT_EXTRACT_IMAGES="true"
            shift
            ;;
        --help|-h)
            echo "Apple Notes Exporter"
            echo ""
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -r, --root-dir DIR                Root directory for exports (default: ~/Downloads/AppleNotesExport)"
            echo "  -s, --suppress-header-pdf BOOL    Suppress Chrome header in PDF (default: true)"
            echo "  -m, --convert-markdown BOOL       Convert to Markdown (default: false)"
            echo "  -p, --convert-pdf BOOL             Convert to PDF (default: false)"
            echo "  -w, --convert-word BOOL            Convert to Word (default: false)"
            echo "  -i, --extract-images BOOL          Extract images (default: true)"
            echo "  -d, --extract-data BOOL            Extract note data (default: true)"
            echo "  -n, --note-limit NUM               Limit total notes exported"
            echo "  -f, --note-limit-per-folder NUM    Limit notes per folder"
            echo "  -b, --note-pick-probability NUM    Probability (%) to pick each note (default: 100)"
            echo "  -t, --filename-format FORMAT       Filename format (default: &title-&id)"
            echo "  -u, --subdir-format FORMAT         Subdirectory format (default: &account-&folder)"
            echo "  -x, --use-subdirs BOOL             Use subdirectories (default: true)"
            echo "  -D, --set-file-dates BOOL          Set filesystem dates to match Notes.app (default: true)"
            echo "  -F, --folders FOLDERS              Comma-separated folder names (e.g., 'Work,Personal')"
            echo "                                     Matches all folders with the given names (including nested folders)."
            echo "                                     Spaces after commas are automatically trimmed."
            echo "  -C, --cleanup                      Cleanup source directories after PDF conversion"
            echo "  -P, --continuous-pdf               Export PDFs as continuous page (for handwritten notes)"
            echo "  -c, --conda-env NAME               Conda environment name"
            echo "  -e, --remove-conda-env BOOL        Remove conda environment after export"
            echo "  -U, --update-all                   Force full update (disable incremental updates)"
            echo "  -a, --all-formats, --all           Enable all format conversions"
            echo "  -h, --help                         Show this help message"
            echo ""
            echo "Environment Variables:"
            echo "  NOTES_EXPORT_UPDATE_ALL            Set to 'true' to disable incremental updates (default: false)"
            echo ""
            echo "Update Modes:"
            echo "  Default (incremental): Only processes notes modified since last export"
            echo "  --update-all: Processes all notes regardless of modification date"
            echo ""
            echo "Folder Filter Examples:"
            echo "  --folders 'Scuola'                 Export only 'Scuola' folder"
            echo "  --folders 'Work,Personal'          Export 'Work' and 'Personal' folders"
            echo "  --folders 'My Notes,School Work'   Handles spaces in folder names"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information."
            exit 1
            ;;
    esac
done

# Initialize Conda for Zsh
eval "$(conda shell.zsh hook)"

# Function to check if a conda environment exists
conda_env_exists() {
    conda info --envs | grep -q "^$1 "
}

# Function to create a conda environment
create_conda_env() {
    conda create -y -n "$1" python=3.9
    eval "$(conda shell.zsh hook)" # Ensure conda is reinitialized
    conda activate "$1"
    pip install -r "$SCRIPT_DIR/requirements.txt"
}

# Function to deactivate a conda environment
deactivate_conda_env() {
    echo "Deactivating conda environment"
    conda deactivate
}

# Function to remove a conda environment
remove_conda_env() {
    local env_name="$1"
    if conda_env_exists "$env_name"; then
        echo "Removing conda environment: $env_name"
        conda remove --name "$env_name" --all -y
    else
        echo "Conda environment $env_name does not exist."
    fi
}

# Handle conda environment
if [[ -n "${NOTES_EXPORT_CONDA_ENV}" ]]; then
    if conda_env_exists "${NOTES_EXPORT_CONDA_ENV}"; then
        echo "Activating existing conda environment: ${NOTES_EXPORT_CONDA_ENV}"
        eval "$(conda shell.zsh hook)" # Ensure conda is reinitialized
        conda activate "${NOTES_EXPORT_CONDA_ENV}"
    else
        echo "Creating and activating new conda environment: ${NOTES_EXPORT_CONDA_ENV}"
        create_conda_env "${NOTES_EXPORT_CONDA_ENV}"
    fi
fi

# Log the update mode being used
if [[ "${NOTES_EXPORT_UPDATE_ALL}" == "true" ]]; then
    echo "Running in FULL UPDATE mode - all notes will be processed"
else
    echo "Running in INCREMENTAL UPDATE mode - only modified notes will be processed"
fi

# Conditionally execute the AppleScript for data extraction
if [[ "${NOTES_EXPORT_EXTRACT_DATA}" == "true" ]]; then
    echo "Extracting note data..."
    
    # Log folder filter if specified
    if [[ -n "${NOTES_EXPORT_FOLDERS}" ]]; then
        echo "Filtering folders: ${NOTES_EXPORT_FOLDERS}"
    fi
    
    # Run AppleScript (simple, like the working version)
    osascript "$SCRIPT_DIR/export_notes.scpt" "$NOTES_EXPORT_ROOT_DIR" "$NOTES_EXPORT_NOTE_LIMIT" "$NOTES_EXPORT_NOTE_LIMIT_PER_FOLDER" "$NOTES_EXPORT_NOTE_PICK_PROBABILITY" "$NOTES_EXPORT_FILENAME_FORMAT" "$NOTES_EXPORT_SUBDIR_FORMAT" "$NOTES_EXPORT_USE_SUBDIRS" "$NOTES_EXPORT_UPDATE_ALL" "$NOTES_EXPORT_FOLDERS"
    
    # Read statistics from temporary file
    STATS_FILE="${NOTES_EXPORT_ROOT_DIR}/data/export_stats.tmp"
    echo "DEBUG: Looking for stats file at: $STATS_FILE"
    
    if [[ -f "$STATS_FILE" ]]; then
        echo "DEBUG: Stats file found, reading contents..."
        STATS_CONTENT=$(cat "$STATS_FILE" | tr -d '\0\r' | head -1)  # Clean up any null bytes or carriage returns
        echo "DEBUG: Raw stats content: '$STATS_CONTENT'"
        
        # Validate the content looks like numbers separated by colons (now with 6 fields including elapsed time)
        if [[ "$STATS_CONTENT" =~ ^[0-9]+:[0-9]+:[0-9]+:[0-9]+:[0-9]+:[0-9.]+$ ]]; then
            echo "DEBUG: Stats content matches expected format"
            # Parse statistics (format: total:processed:unchanged:older:folders:elapsed_seconds)
            IFS=':' read -r TOTAL_NOTES PROCESSED_NOTES UNCHANGED_NOTES OLDER_NOTES FOLDERS_COUNT APPLESCRIPT_ELAPSED <<< "$STATS_CONTENT"
            echo "DEBUG: Parsed - Total:$TOTAL_NOTES, Processed:$PROCESSED_NOTES, Unchanged:$UNCHANGED_NOTES, Older:$OLDER_NOTES, Folders:$FOLDERS_COUNT, AppleScript Time:${APPLESCRIPT_ELAPSED}s"
            STATS_CAPTURED=true
        else
            echo "Warning: Statistics file contains invalid data: '$STATS_CONTENT'"
            STATS_CAPTURED=false
        fi
        
        # Clean up temp file
        rm -f "$STATS_FILE"
    else
        echo "DEBUG: Stats file not found"
        STATS_CAPTURED=false
    fi
fi

# Conditionally execute the image extraction script
if [[ "${NOTES_EXPORT_EXTRACT_IMAGES}" == "true" ]]; then
    echo "Extracting images..."
    python3 "$SCRIPT_DIR/extract_images.py"
fi

# Conditionally execute the conversion scripts
if [[ "${NOTES_EXPORT_CONVERT_TO_MARKDOWN}" == "true" ]]; then
    echo "Converting to Markdown..."
    python3 "$SCRIPT_DIR/convert_to_markdown.py"
fi

if [[ "${NOTES_EXPORT_CONVERT_TO_PDF}" == "true" ]]; then
    echo "Converting to PDF..."
    python3 "$SCRIPT_DIR/convert_to_pdf.py"
fi

if [[ "${NOTES_EXPORT_CONVERT_TO_WORD}" == "true" ]]; then
    echo "Converting to Word..."
    python3 "$SCRIPT_DIR/convert_to_word.py"
fi

# Optionally set file dates to match Notes.app
if [[ "${NOTES_EXPORT_SET_FILE_DATES}" == "true" ]]; then
    echo "Setting file dates to match Notes.app..."
    python3 "$SCRIPT_DIR/set_file_dates.py"
fi

# Optionally cleanup source directories after PDF conversion
if [[ "${NOTES_EXPORT_CLEANUP}" == "true" && "${NOTES_EXPORT_CONVERT_TO_PDF}" == "true" ]]; then
    echo "Cleaning up source directories..."
    # Remove raw, html, and text directories since we have PDFs
    if [[ -d "${NOTES_EXPORT_ROOT_DIR}/raw" ]]; then
        rm -rf "${NOTES_EXPORT_ROOT_DIR}/raw"
        echo "  Removed: raw/"
    fi
    if [[ -d "${NOTES_EXPORT_ROOT_DIR}/html" ]]; then
        rm -rf "${NOTES_EXPORT_ROOT_DIR}/html"
        echo "  Removed: html/"
    fi
    if [[ -d "${NOTES_EXPORT_ROOT_DIR}/text" ]]; then
        rm -rf "${NOTES_EXPORT_ROOT_DIR}/text"
        echo "  Removed: text/"
    fi
    echo "Cleanup completed - only PDF and data directories remain."
fi

# Optionally deactivate and remove the UV virtual environment
if [[ "${NOTES_EXPORT_REMOVE_UV_VENV}" == "true" && -n "${NOTES_EXPORT_UV_VENV}" ]]; then
    deactivate_uv_venv
    remove_uv_venv "${NOTES_EXPORT_UV_VENV}"
fi

# Calculate and display elapsed time
SCRIPT_END_TIME=$SECONDS
ELAPSED_TIME=$((SCRIPT_END_TIME - SCRIPT_START_TIME))
ELAPSED_MINUTES=$((ELAPSED_TIME / 60))
ELAPSED_SECONDS=$((ELAPSED_TIME % 60))

echo ""
echo "===================================="
echo "Export completed successfully!"

# Display timing
if [[ $ELAPSED_TIME -ge 60 ]]; then
    echo "Total elapsed time: ${ELAPSED_MINUTES}m ${ELAPSED_SECONDS}s"
else
    echo "Total elapsed time: ${ELAPSED_TIME}s"
fi

# Display statistics if captured
if [[ "$STATS_CAPTURED" == "true" ]]; then
    echo ""
    echo "PROCESSING STATISTICS:"
    echo "  Folders processed: $FOLDERS_COUNT"
    echo "  Total notes examined: $TOTAL_NOTES"
    echo "  Notes processed/updated: $PROCESSED_NOTES"
    echo "  Notes skipped (unchanged): $UNCHANGED_NOTES"
    echo "  Notes skipped (older): $OLDER_NOTES"
    
    # Calculate and display percentages
    if [[ $TOTAL_NOTES -gt 0 ]]; then
        PROCESSED_PERCENT=$(( (PROCESSED_NOTES * 100) / TOTAL_NOTES ))
        UNCHANGED_PERCENT=$(( (UNCHANGED_NOTES * 100) / TOTAL_NOTES ))
        OLDER_PERCENT=$(( (OLDER_NOTES * 100) / TOTAL_NOTES ))
        echo "  Processing rate: ${PROCESSED_PERCENT}% processed, ${UNCHANGED_PERCENT}% unchanged, ${OLDER_PERCENT}% older"
    fi
    
    echo ""
    echo "PERFORMANCE METRICS:"
    
    # Overall rate (all notes examined)
    if [[ $ELAPSED_TIME -gt 0 && $TOTAL_NOTES -gt 0 ]]; then
        OVERALL_RATE=$(echo "scale=1; $TOTAL_NOTES / $ELAPSED_TIME" | bc -l)
        echo "  Overall examination rate: ${OVERALL_RATE} notes/second"
    fi
    
    # Update rate (only processed notes)
    if [[ $ELAPSED_TIME -gt 0 && $PROCESSED_NOTES -gt 0 ]]; then
        UPDATE_RATE=$(echo "scale=1; $PROCESSED_NOTES / $ELAPSED_TIME" | bc -l)
        echo "  Update rate: ${UPDATE_RATE} notes/second"
        
        # Time per updated note
        TIME_PER_UPDATE=$(echo "scale=2; $ELAPSED_TIME / $PROCESSED_NOTES" | bc -l)
        echo "  Time per update: ${TIME_PER_UPDATE} seconds/note"
    elif [[ $PROCESSED_NOTES -eq 0 ]]; then
        echo "  Update rate: N/A (no notes updated)"
    fi
    
    # Skip rate (skipped notes)
    TOTAL_SKIPPED=$((UNCHANGED_NOTES + OLDER_NOTES))
    if [[ $ELAPSED_TIME -gt 0 && $TOTAL_SKIPPED -gt 0 ]]; then
        SKIP_RATE=$(echo "scale=1; $TOTAL_SKIPPED / $ELAPSED_TIME" | bc -l)
        echo "  Skip rate: ${SKIP_RATE} notes/second"
        
        # Time per skipped note
        TIME_PER_SKIP=$(echo "scale=3; $ELAPSED_TIME / $TOTAL_SKIPPED" | bc -l)
        echo "  Time per skip: ${TIME_PER_SKIP} seconds/note"
    fi
    
    # AppleScript vs Total time breakdown
    if [[ -n "$APPLESCRIPT_ELAPSED" ]] && [[ $(echo "$APPLESCRIPT_ELAPSED > 0" | bc -l) -eq 1 ]]; then
        APPLESCRIPT_PERCENT=$(echo "scale=1; ($APPLESCRIPT_ELAPSED * 100) / $ELAPSED_TIME" | bc -l)
        OTHER_TIME=$(echo "scale=1; $ELAPSED_TIME - $APPLESCRIPT_ELAPSED" | bc -l)
        OTHER_PERCENT=$(echo "scale=1; ($OTHER_TIME * 100) / $ELAPSED_TIME" | bc -l)
        
        echo ""
        echo "TIME BREAKDOWN:"
        echo "  AppleScript processing: ${APPLESCRIPT_ELAPSED}s (${APPLESCRIPT_PERCENT}%)"
        echo "  Other operations: ${OTHER_TIME}s (${OTHER_PERCENT}%)"
        
        # AppleScript-specific rates
        if [[ $(echo "$APPLESCRIPT_ELAPSED > 0" | bc -l) -eq 1 ]]; then
            AS_OVERALL_RATE=$(echo "scale=1; $TOTAL_NOTES / $APPLESCRIPT_ELAPSED" | bc -l)
            echo "  AppleScript rate: ${AS_OVERALL_RATE} notes/second"
        fi
    fi
fi

echo "===================================="
