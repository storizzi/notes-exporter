#!/bin/zsh

# Start timing
SCRIPT_START_TIME=$SECONDS

# Determine the directory where the script is located
SCRIPT_DIR=$(dirname $(realpath "$0"))

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
export NOTES_EXPORT_VENV_DIR="${NOTES_EXPORT_VENV_DIR:=}"
export NOTES_EXPORT_REMOVE_VENV="${NOTES_EXPORT_REMOVE_VENV:=false}"
export NOTES_EXPORT_UPDATE_ALL="${NOTES_EXPORT_UPDATE_ALL:=false}"  # Default to incremental updates
export NOTES_EXPORT_INCLUDE_DELETED="${NOTES_EXPORT_INCLUDE_DELETED:=false}"  # Default to excluding deleted records for performance
export NOTES_EXPORT_SET_FILE_DATES="${NOTES_EXPORT_SET_FILE_DATES:=false}"  # Set filesystem dates to match Apple Notes dates
export NOTES_EXPORT_FILTER_ACCOUNTS="${NOTES_EXPORT_FILTER_ACCOUNTS:=}"  # Comma-separated list of account names to include
export NOTES_EXPORT_FILTER_FOLDERS="${NOTES_EXPORT_FILTER_FOLDERS:=}"  # Comma-separated list of folder names to include
export NOTES_EXPORT_CLEAN="${NOTES_EXPORT_CLEAN:=false}"  # Clear output directories before export
export NOTES_EXPORT_SYNC="${NOTES_EXPORT_SYNC:=false}"  # Run sync-back after export
export NOTES_EXPORT_SYNC_ONLY="${NOTES_EXPORT_SYNC_ONLY:=false}"  # Run sync-back without exporting
export NOTES_EXPORT_SYNC_DRY_RUN="${NOTES_EXPORT_SYNC_DRY_RUN:=false}"  # Show what would be synced
export NOTES_EXPORT_CREATE_NEW="${NOTES_EXPORT_CREATE_NEW:=false}"  # Create new notes from unmatched files
export NOTES_EXPORT_CONFLICT_STRATEGY="${NOTES_EXPORT_CONFLICT_STRATEGY:=}"  # Conflict strategy override
export NOTES_EXPORT_NO_OVERWRITE="${NOTES_EXPORT_NO_OVERWRITE:=false}"  # Skip files that already exist
export NOTES_EXPORT_MODIFIED_AFTER="${NOTES_EXPORT_MODIFIED_AFTER:=}"  # Only export notes modified after this date
export NOTES_EXPORT_IMAGES_BESIDE_DOCS="${NOTES_EXPORT_IMAGES_BESIDE_DOCS:=false}"  # Put images next to docs instead of attachments/
export NOTES_EXPORT_HTML_WRAP="${NOTES_EXPORT_HTML_WRAP:=false}"  # Wrap HTML with proper page tags
export NOTES_EXPORT_DEDUP_IMAGES="${NOTES_EXPORT_DEDUP_IMAGES:=false}"  # Deduplicate identical images
export NOTES_EXPORT_UPDATE_QDRANT="${NOTES_EXPORT_UPDATE_QDRANT:=false}"  # Sync notes to Qdrant vector DB

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
        --convert-markdown|-m)
            # Convert notes to Markdown (default: false)
            # Support both boolean flag and explicit value (true/false)
            if [[ -n "$2" && "$2" != -* ]]; then
                # Value provided (true or false)
                export NOTES_EXPORT_CONVERT_TO_MARKDOWN="$2"
                shift 2
            else
                # No value provided, treat as boolean flag (true)
                export NOTES_EXPORT_CONVERT_TO_MARKDOWN="true"
                shift
            fi
            ;;
        --convert-pdf|-p)
            # Convert notes to PDF (default: false)
            # Support both boolean flag and explicit value (true/false)
            if [[ -n "$2" && "$2" != -* ]]; then
                # Value provided (true or false)
                export NOTES_EXPORT_CONVERT_TO_PDF="$2"
                shift 2
            else
                # No value provided, treat as boolean flag (true)
                export NOTES_EXPORT_CONVERT_TO_PDF="true"
                shift
            fi
            ;;
        --convert-word|-w)
            # Convert notes to Word (default: false)
            # Support both boolean flag and explicit value (true/false)
            if [[ -n "$2" && "$2" != -* ]]; then
                # Value provided (true or false)
                export NOTES_EXPORT_CONVERT_TO_WORD="$2"
                shift 2
            else
                # No value provided, treat as boolean flag (true)
                export NOTES_EXPORT_CONVERT_TO_WORD="true"
                shift
            fi
            ;;
        --extract-images|-i)
            # Extract images from notes (default: true)
            # Support both boolean flag and explicit value (true/false)
            if [[ -n "$2" && "$2" != -* ]]; then
                export NOTES_EXPORT_EXTRACT_IMAGES="$2"
                shift 2
            else
                export NOTES_EXPORT_EXTRACT_IMAGES="true"
                shift
            fi
            ;;
        --extract-data|-d)
            # Extract data from Apple Notes (default: true)
            # Support both boolean flag and explicit value (true/false)
            if [[ -n "$2" && "$2" != -* ]]; then
                export NOTES_EXPORT_EXTRACT_DATA="$2"
                shift 2
            else
                export NOTES_EXPORT_EXTRACT_DATA="true"
                shift
            fi
            ;;
        --suppress-header-pdf|-s)
            # Suppress headers/footers in PDF (default: true)
            # Support both boolean flag and explicit value (true/false)
            if [[ -n "$2" && "$2" != -* ]]; then
                export NOTES_EXPORT_SUPPRESS_CHROME_HEADER_PDF="$2"
                shift 2
            else
                export NOTES_EXPORT_SUPPRESS_CHROME_HEADER_PDF="true"
                shift
            fi
            ;;
        --use-subdirs|-x)
            # Use subdirectories for organization (default: true)
            # Support both boolean flag and explicit value (true/false)
            if [[ -n "$2" && "$2" != -* ]]; then
                export NOTES_EXPORT_USE_SUBDIRS="$2"
                shift 2
            else
                export NOTES_EXPORT_USE_SUBDIRS="true"
                shift
            fi
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
        --conda-env|-c)
            # Deprecated: maps to --venv-dir
            if [[ -z "$2" ]]; then
                echo "Error: --conda-env requires an argument."
                exit 1
            fi
            echo "Warning: --conda-env is deprecated. Mapping to --venv-dir instead."
            export NOTES_EXPORT_VENV_DIR="$2"
            shift 2
            ;;
        --remove-conda-env|-e)
            # Deprecated: maps to --remove-venv
            if [[ -n "$2" && "$2" != -* ]]; then
                export NOTES_EXPORT_REMOVE_VENV="$2"
                shift 2
            else
                export NOTES_EXPORT_REMOVE_VENV="true"
                shift
            fi
            echo "Warning: --remove-conda-env is deprecated. Mapping to --remove-venv instead."
            ;;
        --update-all|-U)
            # Force full update of all notes (disable incremental updates)
            # Support both boolean flag and explicit value (true/false)
            if [[ -n "$2" && "$2" != -* ]]; then
                # Value provided (true or false)
                export NOTES_EXPORT_UPDATE_ALL="$2"
                shift 2
            else
                # No value provided, treat as boolean flag (true)
                export NOTES_EXPORT_UPDATE_ALL="true"
                shift
            fi
            ;;
        --include-deleted|-I)
            # Include deleted records in export (default: false for performance)
            # Support both boolean flag and explicit value (true/false)
            if [[ -n "$2" && "$2" != -* ]]; then
                # Value provided (true or false)
                export NOTES_EXPORT_INCLUDE_DELETED="$2"
                shift 2
            else
                # No value provided, treat as boolean flag (true)
                export NOTES_EXPORT_INCLUDE_DELETED="true"
                shift
            fi
            ;;
        --set-file-dates|-D)
            # Set filesystem dates to match Apple Notes dates (default: false)
            # Support both boolean flag and explicit value (true/false)
            if [[ -n "$2" && "$2" != -* ]]; then
                # Value provided (true or false)
                export NOTES_EXPORT_SET_FILE_DATES="$2"
                shift 2
            else
                # No value provided, treat as boolean flag (true)
                export NOTES_EXPORT_SET_FILE_DATES="true"
                shift
            fi
            ;;
        --filter-accounts|-A)
            if [[ -z "$2" || "$2" == -* ]]; then
                echo "Error: --filter-accounts requires a comma-separated list of account names."
                exit 1
            fi
            export NOTES_EXPORT_FILTER_ACCOUNTS="$2"
            shift 2
            ;;
        --filter-folders|-F)
            if [[ -z "$2" || "$2" == -* ]]; then
                echo "Error: --filter-folders requires a comma-separated list of folder names."
                exit 1
            fi
            export NOTES_EXPORT_FILTER_FOLDERS="$2"
            shift 2
            ;;
        --clean|-C)
            # Clear output directories before export (default: false)
            # Support both boolean flag and explicit value (true/false)
            if [[ -n "$2" && "$2" != -* ]]; then
                export NOTES_EXPORT_CLEAN="$2"
                shift 2
            else
                export NOTES_EXPORT_CLEAN="true"
                shift
            fi
            ;;
        --venv-dir|-v)
            if [[ -z "$2" ]]; then
                echo "Error: --venv-dir requires an argument."
                exit 1
            fi
            export NOTES_EXPORT_VENV_DIR="$2"
            shift 2
            ;;
        --remove-venv)
            if [[ -n "$2" && "$2" != -* ]]; then
                export NOTES_EXPORT_REMOVE_VENV="$2"
                shift 2
            else
                export NOTES_EXPORT_REMOVE_VENV="true"
                shift
            fi
            ;;
        --sync|-S)
            # Run sync-back after export (default: false)
            if [[ -n "$2" && "$2" != -* ]]; then
                export NOTES_EXPORT_SYNC="$2"
                shift 2
            else
                export NOTES_EXPORT_SYNC="true"
                shift
            fi
            ;;
        --sync-only)
            # Run sync-back without exporting first
            if [[ -n "$2" && "$2" != -* ]]; then
                export NOTES_EXPORT_SYNC_ONLY="$2"
                shift 2
            else
                export NOTES_EXPORT_SYNC_ONLY="true"
                shift
            fi
            ;;
        --sync-dry-run)
            # Show what would be synced without doing it
            if [[ -n "$2" && "$2" != -* ]]; then
                export NOTES_EXPORT_SYNC_DRY_RUN="$2"
                shift 2
            else
                export NOTES_EXPORT_SYNC_DRY_RUN="true"
                shift
            fi
            ;;
        --create-new)
            # Create new notes from unmatched local files
            if [[ -n "$2" && "$2" != -* ]]; then
                export NOTES_EXPORT_CREATE_NEW="$2"
                shift 2
            else
                export NOTES_EXPORT_CREATE_NEW="true"
                shift
            fi
            ;;
        --conflict)
            if [[ -z "$2" || "$2" == -* ]]; then
                echo "Error: --conflict requires a strategy (abort|local|remote)."
                exit 1
            fi
            export NOTES_EXPORT_CONFLICT_STRATEGY="$2"
            shift 2
            ;;
        --no-overwrite|-O)
            if [[ -n "$2" && "$2" != -* ]]; then
                export NOTES_EXPORT_NO_OVERWRITE="$2"
                shift 2
            else
                export NOTES_EXPORT_NO_OVERWRITE="true"
                shift
            fi
            ;;
        --modified-after)
            if [[ -z "$2" || "$2" == -* ]]; then
                echo "Error: --modified-after requires a date (e.g. '2026-01-15' or 'January 15, 2026')."
                exit 1
            fi
            export NOTES_EXPORT_MODIFIED_AFTER="$2"
            shift 2
            ;;
        --images-beside-docs)
            if [[ -n "$2" && "$2" != -* ]]; then
                export NOTES_EXPORT_IMAGES_BESIDE_DOCS="$2"
                shift 2
            else
                export NOTES_EXPORT_IMAGES_BESIDE_DOCS="true"
                shift
            fi
            ;;
        --html-wrap)
            if [[ -n "$2" && "$2" != -* ]]; then
                export NOTES_EXPORT_HTML_WRAP="$2"
                shift 2
            else
                export NOTES_EXPORT_HTML_WRAP="true"
                shift
            fi
            ;;
        --dedup-images)
            if [[ -n "$2" && "$2" != -* ]]; then
                export NOTES_EXPORT_DEDUP_IMAGES="$2"
                shift 2
            else
                export NOTES_EXPORT_DEDUP_IMAGES="true"
                shift
            fi
            ;;
        --update-qdrant)
            if [[ -n "$2" && "$2" != -* ]]; then
                export NOTES_EXPORT_UPDATE_QDRANT="$2"
                shift 2
            else
                export NOTES_EXPORT_UPDATE_QDRANT="true"
                shift
            fi
            ;;
        --query|-Q)
            # Run a search query against exported notes and exit
            shift
            python "$SCRIPT_DIR/query_notes.py" "$@"
            exit $?
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
            echo "  -s, --suppress-header-pdf          Suppress Chrome header in PDF (default: true)"
            echo "  -m, --convert-markdown             Convert to Markdown (default: false)"
            echo "  -p, --convert-pdf                  Convert to PDF (default: false)"
            echo "  -w, --convert-word                 Convert to Word (default: false)"
            echo "  -i, --extract-images               Extract images (default: true)"
            echo "  -d, --extract-data                 Extract note data (default: true)"
            echo "  -x, --use-subdirs                  Use subdirectories (default: true)"
            echo "  -n, --note-limit NUM               Limit total notes exported"
            echo "  -f, --note-limit-per-folder NUM    Limit notes per folder"
            echo "  -b, --note-pick-probability NUM    Probability (%) to pick each note (default: 100)"
            echo "  -t, --filename-format FORMAT       Filename format (default: &title-&id)"
            echo "  -u, --subdir-format FORMAT         Subdirectory format (default: &account-&folder)"
            echo "  -v, --venv-dir DIR                 Virtual environment directory"
            echo "      --remove-venv                  Remove venv after export"
            echo "  -c, --conda-env NAME               Conda environment name (deprecated, use --venv-dir)"
            echo "  -e, --remove-conda-env             Remove conda environment after export"
            echo "  -U, --update-all                   Force full update (disable incremental updates)"
            echo "  -I, --include-deleted              Include deleted records in export (default: false)"
            echo "  -D, --set-file-dates               Set filesystem dates to match Apple Notes (default: false)"
            echo "  -A, --filter-accounts LIST         Only export from these accounts (comma-separated)"
            echo "  -F, --filter-folders LIST          Only export from these folders (comma-separated)"
            echo "  -C, --clean                        Clear output directories before export"
            echo "  -S, --sync                         Run sync-back after export"
            echo "      --sync-only                    Run sync-back without exporting first"
            echo "      --sync-dry-run                 Show what would be synced without doing it"
            echo "      --create-new                   Create new notes from unmatched local files"
            echo "      --conflict STRATEGY            Conflict strategy: abort, local, or remote"
            echo "  -O, --no-overwrite                 Skip files that already exist (default: false)"
            echo "      --modified-after DATE          Only export notes modified after this date"
            echo "      --images-beside-docs           Put images next to HTML files instead of attachments/"
            echo "      --html-wrap                    Wrap exported HTML with proper page tags"
            echo "      --dedup-images                 Deduplicate identical images by content hash"
            echo "      --update-qdrant                Sync notes to Qdrant vector database for AI search"
            echo "  -Q, --query PATTERN [opts]         Search exported notes (use --query --help for details)"
            echo "  -a, --all-formats, --all           Enable all format conversions"
            echo "  -h, --help                         Show this help message"
            echo ""
            echo "All boolean options accept: flag only (implies true), explicit true/false value,"
            echo "or can be set via environment variables."
            echo ""
            echo "Environment Variables:"
            echo "  NOTES_EXPORT_UPDATE_ALL            Set to 'true' to disable incremental updates (default: false)"
            echo "  NOTES_EXPORT_INCLUDE_DELETED       Set to 'true' to include deleted records (default: false)"
            echo ""
            echo "Update Modes:"
            echo "  Default (incremental): Only processes notes modified since last export"
            echo "  --update-all: Processes all notes regardless of modification date"
            echo ""
            echo "Deleted Records:"
            echo "  Default: Excludes deleted records for better performance"
            echo "  --include-deleted: Includes deleted records (useful for tracking deletions)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information."
            exit 1
            ;;
    esac
done

# ---- Virtual Environment Functions ----

# Function to check if a venv exists
venv_exists() {
    [[ -d "$1" && -f "$1/bin/activate" ]]
}

# Function to create a venv
create_venv() {
    local venv_dir="$1"
    echo "Creating virtual environment: $venv_dir"
    python3 -m venv "$venv_dir"
    source "$venv_dir/bin/activate"
    pip install -r "$SCRIPT_DIR/requirements.txt"
}

# Function to activate a venv
activate_venv() {
    local venv_dir="$1"
    source "$venv_dir/bin/activate"
}

# Handle venv environment
if [[ -n "${NOTES_EXPORT_VENV_DIR}" ]]; then
    if venv_exists "${NOTES_EXPORT_VENV_DIR}"; then
        echo "Activating existing virtual environment: ${NOTES_EXPORT_VENV_DIR}"
        activate_venv "${NOTES_EXPORT_VENV_DIR}"
    else
        echo "Creating and activating new virtual environment: ${NOTES_EXPORT_VENV_DIR}"
        create_venv "${NOTES_EXPORT_VENV_DIR}"
    fi
fi

# Optionally clean output directories before export
if [[ "${NOTES_EXPORT_CLEAN}" == "true" ]]; then
    echo "Cleaning output directories..."
    for dir in raw html text md pdf docx; do
        if [[ -d "${NOTES_EXPORT_ROOT_DIR}/${dir}" ]]; then
            rm -rf "${NOTES_EXPORT_ROOT_DIR}/${dir}"
            echo "  Removed ${dir}/"
        fi
    done
    echo "Output directories cleaned. Data tracking files preserved."
fi

# Log filters if set
if [[ -n "${NOTES_EXPORT_FILTER_ACCOUNTS}" ]]; then
    echo "Filtering accounts: ${NOTES_EXPORT_FILTER_ACCOUNTS}"
fi
if [[ -n "${NOTES_EXPORT_FILTER_FOLDERS}" ]]; then
    echo "Filtering folders: ${NOTES_EXPORT_FILTER_FOLDERS}"
fi

# Log the update mode being used
if [[ "${NOTES_EXPORT_UPDATE_ALL}" == "true" ]]; then
    echo "Running in FULL UPDATE mode - all notes will be processed"
else
    echo "Running in INCREMENTAL UPDATE mode - only modified notes will be processed"
fi

# If --sync-only, skip the export pipeline entirely
if [[ "${NOTES_EXPORT_SYNC_ONLY}" == "true" ]]; then
    export NOTES_EXPORT_EXTRACT_DATA="false"
    export NOTES_EXPORT_EXTRACT_IMAGES="false"
    export NOTES_EXPORT_CONVERT_TO_MARKDOWN="false"
    export NOTES_EXPORT_CONVERT_TO_PDF="false"
    export NOTES_EXPORT_CONVERT_TO_WORD="false"
    export NOTES_EXPORT_SET_FILE_DATES="false"
    export NOTES_EXPORT_SYNC="true"
fi

# Conditionally execute the AppleScript for data extraction
if [[ "${NOTES_EXPORT_EXTRACT_DATA}" == "true" ]]; then
    echo "Extracting note data..."
    
    # Run AppleScript (simple, like the working version)
    osascript "$SCRIPT_DIR/export_notes.scpt" "$NOTES_EXPORT_ROOT_DIR" "$NOTES_EXPORT_NOTE_LIMIT" "$NOTES_EXPORT_NOTE_LIMIT_PER_FOLDER" "$NOTES_EXPORT_NOTE_PICK_PROBABILITY" "$NOTES_EXPORT_FILENAME_FORMAT" "$NOTES_EXPORT_SUBDIR_FORMAT" "$NOTES_EXPORT_USE_SUBDIRS" "$NOTES_EXPORT_UPDATE_ALL" "$NOTES_EXPORT_INCLUDE_DELETED" "$NOTES_EXPORT_FILTER_ACCOUNTS" "$NOTES_EXPORT_FILTER_FOLDERS" "$NOTES_EXPORT_MODIFIED_AFTER"
    
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
    python "$SCRIPT_DIR/extract_images.py"
fi

# Conditionally execute the conversion scripts
if [[ "${NOTES_EXPORT_CONVERT_TO_MARKDOWN}" == "true" ]]; then
    echo "Converting to Markdown..."
    python "$SCRIPT_DIR/convert_to_markdown.py"
fi

if [[ "${NOTES_EXPORT_CONVERT_TO_PDF}" == "true" ]]; then
    echo "Converting to PDF..."
    python "$SCRIPT_DIR/convert_to_pdf.py"
fi

if [[ "${NOTES_EXPORT_CONVERT_TO_WORD}" == "true" ]]; then
    echo "Converting to Word..."
    python "$SCRIPT_DIR/convert_to_word.py"
fi

# Optionally set filesystem dates to match Apple Notes dates
if [[ "${NOTES_EXPORT_SET_FILE_DATES}" == "true" ]]; then
    echo "Setting file dates to match Apple Notes..."
    python "$SCRIPT_DIR/set_file_dates.py"
fi

# Sync back to Apple Notes if requested
if [[ "${NOTES_EXPORT_SYNC}" == "true" ]]; then
    echo "Syncing changes back to Apple Notes..."
    SYNC_ARGS=""
    if [[ "${NOTES_EXPORT_SYNC_DRY_RUN}" == "true" ]]; then
        SYNC_ARGS="$SYNC_ARGS --dry-run"
    fi
    if [[ "${NOTES_EXPORT_CREATE_NEW}" == "true" ]]; then
        SYNC_ARGS="$SYNC_ARGS --create-new"
    fi
    if [[ -n "${NOTES_EXPORT_CONFLICT_STRATEGY}" ]]; then
        SYNC_ARGS="$SYNC_ARGS --conflict ${NOTES_EXPORT_CONFLICT_STRATEGY}"
    fi
    if [[ -n "${NOTES_EXPORT_FILTER_FOLDERS}" ]]; then
        SYNC_ARGS="$SYNC_ARGS --filter-folders ${NOTES_EXPORT_FILTER_FOLDERS}"
    fi
    if [[ -n "${NOTES_EXPORT_FILTER_ACCOUNTS}" ]]; then
        SYNC_ARGS="$SYNC_ARGS --filter-accounts ${NOTES_EXPORT_FILTER_ACCOUNTS}"
    fi
    python "$SCRIPT_DIR/sync_to_notes.py" $SYNC_ARGS

    # Auto-regenerate formats after sync if settings say so
    # Only runs when not in dry-run mode
    if [[ "${NOTES_EXPORT_SYNC_DRY_RUN}" != "true" ]]; then
        REGEN_ARGS=$(python3 -c "
from sync_settings import load_settings
settings = load_settings()
regen = settings.get('autoRegenerate', {})
formats = []
if regen.get('html', False): formats.append('html')
if regen.get('pdf', False): formats.append('pdf')
if regen.get('word', False): formats.append('word')
print(','.join(formats))
" 2>/dev/null)
        if [[ -n "$REGEN_ARGS" ]]; then
            echo "Auto-regenerating formats after sync: $REGEN_ARGS"
            if [[ "$REGEN_ARGS" == *"html"* ]]; then
                python "$SCRIPT_DIR/extract_images.py"
            fi
            if [[ "$REGEN_ARGS" == *"pdf"* ]]; then
                python "$SCRIPT_DIR/convert_to_pdf.py"
            fi
            if [[ "$REGEN_ARGS" == *"word"* ]]; then
                python "$SCRIPT_DIR/convert_to_word.py"
            fi
        fi
    fi
fi

# Sync notes to Qdrant vector database if requested
if [[ "${NOTES_EXPORT_UPDATE_QDRANT}" == "true" ]]; then
    echo "Syncing notes to Qdrant..."
    python "$SCRIPT_DIR/qdrant_integration.py" sync
fi

# Optionally deactivate and remove the venv
if [[ "${NOTES_EXPORT_REMOVE_VENV}" == "true" && -n "${NOTES_EXPORT_VENV_DIR}" ]]; then
    echo "Removing virtual environment: ${NOTES_EXPORT_VENV_DIR}"
    deactivate 2>/dev/null
    rm -rf "${NOTES_EXPORT_VENV_DIR}"
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