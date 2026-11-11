#!/bin/zsh
# exportnotes.zsh - export Apple Notes to HTML, text, Markdown, PDF and Word.
#
# Reading Apple Notes is read-only. Only --sync / --sync-only write to Notes.
#
# Exit codes (stable, see INTEGRATION.md):
#   0  success
#   1  could not start: bad option, missing Python or dependencies, not macOS
#   2  partial: finished, but some notes or steps failed (see the manifest)
#   3  Notes automation refused, or (with --non-interactive) macOS would ask
#   4  another export holds the lock on this root directory
#   5  the export failed (AppleScript error); the manifest says status "failed"

emulate -L zsh
setopt pipefail

SCRIPT_START_TIME=$SECONDS
SCRIPT_DIR=$(dirname "$(realpath "$0")")
NOTES_EXPORTER_VERSION="$(cat "$SCRIPT_DIR/VERSION" 2>/dev/null || echo unknown)"

EXIT_OK=0; EXIT_USAGE=1; EXIT_PARTIAL=2; EXIT_PERMISSION=3; EXIT_LOCKED=4; EXIT_FAILED=5

# ---- Defaults (environment variables override, options override those) ----
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
export NOTES_EXPORT_PYTHON="${NOTES_EXPORT_PYTHON:=}"
export NOTES_EXPORT_REMOVE_VENV="${NOTES_EXPORT_REMOVE_VENV:=false}"
export NOTES_EXPORT_UPDATE_ALL="${NOTES_EXPORT_UPDATE_ALL:=false}"
export NOTES_EXPORT_INCLUDE_DELETED="${NOTES_EXPORT_INCLUDE_DELETED:=false}"
export NOTES_EXPORT_SET_FILE_DATES="${NOTES_EXPORT_SET_FILE_DATES:=false}"
export NOTES_EXPORT_FILTER_ACCOUNTS="${NOTES_EXPORT_FILTER_ACCOUNTS:=}"
export NOTES_EXPORT_FILTER_FOLDERS="${NOTES_EXPORT_FILTER_FOLDERS:=}"
export NOTES_EXPORT_EXCLUDE_FOLDERS="${NOTES_EXPORT_EXCLUDE_FOLDERS:=}"
export NOTES_EXPORT_CLEAN="${NOTES_EXPORT_CLEAN:=false}"
export NOTES_EXPORT_SYNC="${NOTES_EXPORT_SYNC:=false}"
export NOTES_EXPORT_SYNC_ONLY="${NOTES_EXPORT_SYNC_ONLY:=false}"
export NOTES_EXPORT_SYNC_DRY_RUN="${NOTES_EXPORT_SYNC_DRY_RUN:=false}"
export NOTES_EXPORT_CREATE_NEW="${NOTES_EXPORT_CREATE_NEW:=false}"
export NOTES_EXPORT_CONFLICT_STRATEGY="${NOTES_EXPORT_CONFLICT_STRATEGY:=}"
export NOTES_EXPORT_NO_OVERWRITE="${NOTES_EXPORT_NO_OVERWRITE:=false}"
export NOTES_EXPORT_MODIFIED_AFTER="${NOTES_EXPORT_MODIFIED_AFTER:=}"
export NOTES_EXPORT_IMAGES_BESIDE_DOCS="${NOTES_EXPORT_IMAGES_BESIDE_DOCS:=false}"
export NOTES_EXPORT_HTML_WRAP="${NOTES_EXPORT_HTML_WRAP:=false}"
export NOTES_EXPORT_DEDUP_IMAGES="${NOTES_EXPORT_DEDUP_IMAGES:=false}"
export NOTES_EXPORT_IMAGE_FORMAT="${NOTES_EXPORT_IMAGE_FORMAT:=}"
export NOTES_EXPORT_IMAGE_FORMAT_FROM="${NOTES_EXPORT_IMAGE_FORMAT_FROM:=}"
export NOTES_EXPORT_IMAGE_QUALITY="${NOTES_EXPORT_IMAGE_QUALITY:=}"
export NOTES_EXPORT_TAGS="${NOTES_EXPORT_TAGS:=false}"
export NOTES_EXPORT_TAGS_IN_CONTENT="${NOTES_EXPORT_TAGS_IN_CONTENT:=false}"
export NOTES_EXPORT_PRUNE_DELETED="${NOTES_EXPORT_PRUNE_DELETED:=false}"
export NOTES_EXPORT_UPDATE_QDRANT="${NOTES_EXPORT_UPDATE_QDRANT:=false}"
export NOTES_EXPORT_NON_INTERACTIVE="${NOTES_EXPORT_NON_INTERACTIVE:=false}"
export NOTES_EXPORT_JSON_LOG="${NOTES_EXPORT_JSON_LOG:=}"

# ---- Option parsing ----
# Boolean options accept a bare flag (true) or an explicit true/false value.
typeset -g OPT_SHIFT=1
bool_opt() {   # bool_opt VAR "$2"
    if [[ "$2" == "true" || "$2" == "false" ]]; then
        export "$1=$2"; OPT_SHIFT=2
    else
        export "$1=true"; OPT_SHIFT=1
    fi
}
value_opt() {  # value_opt VAR OPTION "$2"
    if [[ -z "$3" || "$3" == -* ]]; then
        echo "Error: $2 requires a value." >&2
        exit $EXIT_USAGE
    fi
    export "$1=$3"; OPT_SHIFT=2
}

show_help() {
    cat <<EOF
Apple Notes Exporter ${NOTES_EXPORTER_VERSION}

Usage: $0 [OPTIONS]

Output
  -r, --root-dir DIR             Root directory for exports (default: ~/Downloads/AppleNotesExport)
  -m, --convert-markdown         Convert to Markdown
  -p, --convert-pdf              Convert to PDF (needs Google Chrome)
  -w, --convert-word             Convert to Word (needs Pandoc)
  -a, --all-formats, --all       Enable all conversions
  -i, --extract-images           Extract images into attachments/ (default: true)
  -d, --extract-data             Read notes from Apple Notes (default: true)
  -s, --suppress-header-pdf      No Chrome header/footer in PDFs (default: true)
  -x, --use-subdirs              One subdirectory per folder (default: true)
  -t, --filename-format FORMAT   Filename template (default: &title-&id)
  -u, --subdir-format FORMAT     Subdirectory template (default: &account-&folder)
                                 Tokens: &account &accountid &shortaccountid &folder
                                 &folderpath (nested path) &title &id
      --folder-hierarchy         Mirror the real folder tree (= --subdir-format '&account/&folderpath')
      --images-beside-docs       Put images next to the HTML file instead of attachments/
      --html-wrap                Wrap HTML in a full page with a <title>
      --dedup-images             Store identical images once
      --image-format FMT         Convert extracted images: jpeg, png, heic, tiff, webp
      --image-format-from LIST   Only convert these source types (e.g. heic,png)
      --image-quality N          JPEG/HEIC/WebP quality 1-100
      --tags                     Read #tags from the Notes database (needs Full Disk Access)
      --tags-in-content          Also add a "Tags:" line to the exported HTML/Markdown
  -D, --set-file-dates           Give files the notes' created/modified dates
  -O, --no-overwrite             Never replace an existing output file
  -C, --clean                    Remove the format folders before exporting

Selection
  -A, --filter-accounts LIST     Only these accounts (comma-separated)
  -F, --filter-folders LIST      Only these folders (names, or paths like Food/Recipes)
      --exclude-folders LIST     Skip these folders (e.g. "Recently Deleted")
      --modified-after DATE      Only notes modified after DATE (YYYY-MM-DD)
  -n, --note-limit NUM           Export at most NUM notes
  -f, --note-limit-per-folder N  At most N notes per folder
  -b, --note-pick-probability %  Pick each note with this probability (testing)
  -U, --update-all               Export every note, not only changed ones
  -I, --include-deleted          Load deleted records too when comparing
      --prune-deleted            Remove the exported files of notes deleted in Notes

Automation
      --json-log [FILE]          JSON Lines events (progress, result) on stdout or to FILE;
                                 human output then goes to stderr (when on stdout)
      --non-interactive          Never wait for a prompt: fail with exit code 3 if macOS
                                 would ask for permission to control Notes
      --version                  Print the version and exit

Sync back to Apple Notes (writes to Notes)
  -S, --sync                     Sync edited Markdown back after exporting
      --sync-only                Only sync, no export
      --sync-dry-run             Show what would be synced
      --create-new               Create notes from new Markdown files
      --conflict STRATEGY        abort, local or remote

Other
      --update-qdrant            Index notes in Qdrant for AI search
  -Q, --query PATTERN [opts]     Search exported notes (see --query --help)
  -v, --venv-dir DIR             Use (and create) this virtual environment
      --python PATH              Use this Python interpreter
      --remove-venv              Remove the venv afterwards
  -c, --conda-env NAME           Deprecated, maps to --venv-dir
  -h, --help                     This help

Exit codes: 0 ok, 1 could not start, 2 partial, 3 Notes permission, 4 locked, 5 failed.
See INTEGRATION.md for the manifest and event formats.
EOF
}

while [[ $# -gt 0 ]]; do
    OPT_SHIFT=1
    case $1 in
        --root-dir|-r)            value_opt NOTES_EXPORT_ROOT_DIR "$1" "$2" ;;
        --convert-markdown|-m)    bool_opt NOTES_EXPORT_CONVERT_TO_MARKDOWN "$2" ;;
        --convert-pdf|-p)         bool_opt NOTES_EXPORT_CONVERT_TO_PDF "$2" ;;
        --convert-word|-w)        bool_opt NOTES_EXPORT_CONVERT_TO_WORD "$2" ;;
        --extract-images|-i)      bool_opt NOTES_EXPORT_EXTRACT_IMAGES "$2" ;;
        --extract-data|-d)        bool_opt NOTES_EXPORT_EXTRACT_DATA "$2" ;;
        --suppress-header-pdf|-s) bool_opt NOTES_EXPORT_SUPPRESS_CHROME_HEADER_PDF "$2" ;;
        --use-subdirs|-x)         bool_opt NOTES_EXPORT_USE_SUBDIRS "$2" ;;
        --note-limit|-n)          value_opt NOTES_EXPORT_NOTE_LIMIT "$1" "$2" ;;
        --note-limit-per-folder|-f) value_opt NOTES_EXPORT_NOTE_LIMIT_PER_FOLDER "$1" "$2" ;;
        --note-pick-probability|-b) value_opt NOTES_EXPORT_NOTE_PICK_PROBABILITY "$1" "$2" ;;
        --filename-format|-t)     value_opt NOTES_EXPORT_FILENAME_FORMAT "$1" "$2" ;;
        --subdir-format|-u)       value_opt NOTES_EXPORT_SUBDIR_FORMAT "$1" "$2" ;;
        --folder-hierarchy)       export NOTES_EXPORT_SUBDIR_FORMAT="&account/&folderpath" ;;
        --conda-env|-c)
            value_opt NOTES_EXPORT_VENV_DIR "$1" "$2"
            echo "Warning: --conda-env is deprecated. Mapping to --venv-dir instead." >&2 ;;
        --remove-conda-env|-e)
            bool_opt NOTES_EXPORT_REMOVE_VENV "$2"
            echo "Warning: --remove-conda-env is deprecated. Mapping to --remove-venv instead." >&2 ;;
        --update-all|-U)          bool_opt NOTES_EXPORT_UPDATE_ALL "$2" ;;
        --include-deleted|-I)     bool_opt NOTES_EXPORT_INCLUDE_DELETED "$2" ;;
        --set-file-dates|-D)      bool_opt NOTES_EXPORT_SET_FILE_DATES "$2" ;;
        --filter-accounts|-A)     value_opt NOTES_EXPORT_FILTER_ACCOUNTS "$1" "$2" ;;
        --filter-folders|-F)      value_opt NOTES_EXPORT_FILTER_FOLDERS "$1" "$2" ;;
        --exclude-folders)        value_opt NOTES_EXPORT_EXCLUDE_FOLDERS "$1" "$2" ;;
        --clean|-C)               bool_opt NOTES_EXPORT_CLEAN "$2" ;;
        --venv-dir|-v)            value_opt NOTES_EXPORT_VENV_DIR "$1" "$2" ;;
        --python)                 value_opt NOTES_EXPORT_PYTHON "$1" "$2" ;;
        --remove-venv)            bool_opt NOTES_EXPORT_REMOVE_VENV "$2" ;;
        --sync|-S)                bool_opt NOTES_EXPORT_SYNC "$2" ;;
        --sync-only)              bool_opt NOTES_EXPORT_SYNC_ONLY "$2" ;;
        --sync-dry-run)           bool_opt NOTES_EXPORT_SYNC_DRY_RUN "$2" ;;
        --create-new)             bool_opt NOTES_EXPORT_CREATE_NEW "$2" ;;
        --conflict)               value_opt NOTES_EXPORT_CONFLICT_STRATEGY "$1" "$2" ;;
        --no-overwrite|-O)        bool_opt NOTES_EXPORT_NO_OVERWRITE "$2" ;;
        --modified-after)         value_opt NOTES_EXPORT_MODIFIED_AFTER "$1" "$2" ;;
        --images-beside-docs)     bool_opt NOTES_EXPORT_IMAGES_BESIDE_DOCS "$2" ;;
        --html-wrap)              bool_opt NOTES_EXPORT_HTML_WRAP "$2" ;;
        --dedup-images)           bool_opt NOTES_EXPORT_DEDUP_IMAGES "$2" ;;
        --image-format)           value_opt NOTES_EXPORT_IMAGE_FORMAT "$1" "$2" ;;
        --image-format-from)      value_opt NOTES_EXPORT_IMAGE_FORMAT_FROM "$1" "$2" ;;
        --image-quality)          value_opt NOTES_EXPORT_IMAGE_QUALITY "$1" "$2" ;;
        --tags)                   bool_opt NOTES_EXPORT_TAGS "$2" ;;
        --tags-in-content)        bool_opt NOTES_EXPORT_TAGS_IN_CONTENT "$2" ;;
        --prune-deleted)          bool_opt NOTES_EXPORT_PRUNE_DELETED "$2" ;;
        --update-qdrant)          bool_opt NOTES_EXPORT_UPDATE_QDRANT "$2" ;;
        --non-interactive)        bool_opt NOTES_EXPORT_NON_INTERACTIVE "$2" ;;
        --json-log)
            if [[ -n "$2" && "$2" != -* ]]; then
                export NOTES_EXPORT_JSON_LOG="$2"; OPT_SHIFT=2
            else
                export NOTES_EXPORT_JSON_LOG="-"
            fi ;;
        --query|-Q)               QUERY_MODE=true; shift; break ;;
        --all-formats|--all|-a)
            export NOTES_EXPORT_CONVERT_TO_MARKDOWN=true NOTES_EXPORT_CONVERT_TO_PDF=true
            export NOTES_EXPORT_CONVERT_TO_WORD=true NOTES_EXPORT_EXTRACT_IMAGES=true ;;
        --version)
            if [[ -n "$NOTES_EXPORT_JSON_LOG" ]]; then
                print -r -- "{\"type\": \"version\", \"version\": \"${NOTES_EXPORTER_VERSION}\", \"manifest_version\": 1}"
            else
                echo "notes-exporter ${NOTES_EXPORTER_VERSION}"
            fi
            exit $EXIT_OK ;;
        --help|-h)                show_help; exit $EXIT_OK ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Use --help for usage information." >&2
            exit $EXIT_USAGE ;;
    esac
    shift $OPT_SHIFT
done

# Conversions need the processed HTML with extracted images
if [[ "${NOTES_EXPORT_CONVERT_TO_MARKDOWN}" == "true" || "${NOTES_EXPORT_CONVERT_TO_PDF}" == "true" || "${NOTES_EXPORT_CONVERT_TO_WORD}" == "true" ]]; then
    export NOTES_EXPORT_EXTRACT_IMAGES=true
fi

# ---- Event stream (--json-log) ----
# fd 3 carries JSON Lines events. With --json-log (stdout) all human output
# moves to stderr so stdout is pure JSON.
JSON_MODE=false
if [[ -n "$NOTES_EXPORT_JSON_LOG" ]]; then
    JSON_MODE=true
    if [[ "$NOTES_EXPORT_JSON_LOG" == "-" ]]; then
        exec 3>&1 1>&2
    else
        exec 3>>"$NOTES_EXPORT_JSON_LOG"
    fi
    export NOTES_EXPORT_EVENT_FD=3
else
    unset NOTES_EXPORT_EVENT_FD
fi

# emit_event TYPE key=value key:=json ...  (no-op without --json-log)
emit_event() {
    [[ "$JSON_MODE" == "true" && -n "$PYTHON" ]] || return 0
    "$PYTHON" "$SCRIPT_DIR/events.py" emit "$@"
}

# fail CODE MESSAGE: report and exit before any export started
fail_early() {
    local code=$1; shift
    echo "Error: $*" >&2
    if [[ "$JSON_MODE" == "true" ]]; then
        local msg="${*//\\/\\\\}"; msg="${msg//\"/\\\"}"
        print -r -u 3 -- "{\"type\": \"result\", \"status\": \"failed\", \"exit_code\": $code, \"message\": \"$msg\"}"
    fi
    exit $code
}

# ---- Python ----
# Order: --python / NOTES_EXPORT_PYTHON, --venv-dir, a python3 that already
# has the dependencies, else the project's own .venv (created on first run).
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"

deps_ok() {   # deps_ok PYTHON
    "$1" -c 'import sys; assert sys.version_info >= (3, 9); import bs4, markdownify' 2>/dev/null
}

ensure_venv() {   # ensure_venv DIR -> sets PYTHON
    local venv_dir="$1"
    if [[ ! -x "$venv_dir/bin/python" ]]; then
        local base_python="$(command -v python3)"
        [[ -n "$base_python" ]] || fail_early $EXIT_USAGE "python3 not found. Install it with: brew install python"
        echo "Creating virtual environment: $venv_dir"
        "$base_python" -m venv "$venv_dir" || fail_early $EXIT_USAGE "could not create the virtual environment $venv_dir"
    fi
    PYTHON="$venv_dir/bin/python"
    local stamp="$venv_dir/.notes-exporter-requirements"
    local wanted="$(shasum -a 256 "$REQUIREMENTS" | cut -d' ' -f1)"
    if ! deps_ok "$PYTHON" || [[ "$(cat "$stamp" 2>/dev/null)" != "$wanted" ]]; then
        echo "Installing dependencies into $venv_dir ..."
        if ! "$PYTHON" -m pip install --quiet --disable-pip-version-check -r "$REQUIREMENTS" >&2; then
            fail_early $EXIT_USAGE "installing dependencies failed (see pip output above)"
        fi
        deps_ok "$PYTHON" || fail_early $EXIT_USAGE "dependencies are still missing in $venv_dir"
        print -r -- "$wanted" > "$stamp"
    fi
    export VIRTUAL_ENV="$venv_dir"
    export PATH="$venv_dir/bin:$PATH"
}

if [[ -n "$NOTES_EXPORT_PYTHON" ]]; then
    PYTHON="$NOTES_EXPORT_PYTHON"
    deps_ok "$PYTHON" || fail_early $EXIT_USAGE "$PYTHON lacks the dependencies (pip install -r requirements.txt)"
elif [[ -n "$NOTES_EXPORT_VENV_DIR" ]]; then
    ensure_venv "$NOTES_EXPORT_VENV_DIR"
elif deps_ok "$(command -v python3)"; then
    PYTHON="$(command -v python3)"
else
    ensure_venv "$SCRIPT_DIR/.venv"
fi
export NOTES_EXPORT_PYTHON_BIN="$PYTHON"

if [[ "$QUERY_MODE" == "true" ]]; then
    "$PYTHON" "$SCRIPT_DIR/query_notes.py" "$@"
    exit $?
fi

# ---- Lock: one export per root directory ----
mkdir -p "$NOTES_EXPORT_ROOT_DIR" || fail_early $EXIT_USAGE "cannot create $NOTES_EXPORT_ROOT_DIR"
NOTES_EXPORT_ROOT_DIR="${NOTES_EXPORT_ROOT_DIR:A}"
export NOTES_EXPORT_ROOT_DIR
LOCK_DIR="$NOTES_EXPORT_ROOT_DIR/.notes-exporter.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    other_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null)"
    if [[ -n "$other_pid" ]] && ! kill -0 "$other_pid" 2>/dev/null; then
        echo "Removing stale lock left by process $other_pid" >&2
        rm -rf "$LOCK_DIR"
        mkdir "$LOCK_DIR" 2>/dev/null || fail_early $EXIT_LOCKED "could not take the lock $LOCK_DIR"
    else
        fail_early $EXIT_LOCKED "another export (pid ${other_pid:-unknown}) is using $NOTES_EXPORT_ROOT_DIR"
    fi
fi
print -r -- $$ > "$LOCK_DIR/pid"
trap 'rm -rf "$LOCK_DIR"' EXIT
trap 'rm -rf "$LOCK_DIR"; exit 130' INT TERM

RUN_ID="$(uuidgen | tr 'A-Z' 'a-z')"
RUN_STARTED_AT="$(date +%Y-%m-%dT%H:%M:%S%z | sed -E 's/([0-9]{2})([0-9]{2})$/\1:\2/')"
RUN_STATUS="ok"
STEP_FAILURES=0
if [[ "${NOTES_EXPORT_UPDATE_ALL}" == "true" ]]; then RUN_MODE="full"; else RUN_MODE="incremental"; fi
[[ "${NOTES_EXPORT_SYNC_ONLY}" == "true" ]] && RUN_MODE="sync-only"

FORMATS=(raw text)
[[ "$NOTES_EXPORT_EXTRACT_IMAGES" == "true" ]] && FORMATS+=(html)
[[ "$NOTES_EXPORT_CONVERT_TO_MARKDOWN" == "true" ]] && FORMATS+=(md)
[[ "$NOTES_EXPORT_CONVERT_TO_PDF" == "true" ]] && FORMATS+=(pdf)
[[ "$NOTES_EXPORT_CONVERT_TO_WORD" == "true" ]] && FORMATS+=(docx)

FORMATS_JSON="[$(printf '"%s",' "${FORMATS[@]}" | sed 's/,$//')]"
emit_event start version="$NOTES_EXPORTER_VERSION" run_id="$RUN_ID" root_dir="$NOTES_EXPORT_ROOT_DIR" \
    mode="$RUN_MODE" formats:="$FORMATS_JSON" manifest_version:=1

# run_step NAME COMMAND...: run a pipeline step, count a failure, emit stage events
run_step() {
    local name="$1"; shift
    emit_event stage stage="$name" status=started
    if "$@"; then
        emit_event stage stage="$name" status=finished
    else
        local rc=$?
        STEP_FAILURES=$((STEP_FAILURES + 1))
        echo "Warning: step '$name' reported errors (exit $rc)" >&2
        emit_event stage stage="$name" status=failed exit_code:=$rc
    fi
}

# ---- Clean ----
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

[[ -n "${NOTES_EXPORT_FILTER_ACCOUNTS}" ]] && echo "Filtering accounts: ${NOTES_EXPORT_FILTER_ACCOUNTS}"
[[ -n "${NOTES_EXPORT_FILTER_FOLDERS}" ]] && echo "Filtering folders: ${NOTES_EXPORT_FILTER_FOLDERS}"
[[ -n "${NOTES_EXPORT_EXCLUDE_FOLDERS}" ]] && echo "Excluding folders: ${NOTES_EXPORT_EXCLUDE_FOLDERS}"
if [[ "${NOTES_EXPORT_UPDATE_ALL}" == "true" ]]; then
    echo "Running in FULL UPDATE mode - all notes will be processed"
else
    echo "Running in INCREMENTAL UPDATE mode - only modified notes will be processed"
fi

if [[ "${NOTES_EXPORT_SYNC_ONLY}" == "true" ]]; then
    export NOTES_EXPORT_EXTRACT_DATA=false NOTES_EXPORT_EXTRACT_IMAGES=false
    export NOTES_EXPORT_CONVERT_TO_MARKDOWN=false NOTES_EXPORT_CONVERT_TO_PDF=false
    export NOTES_EXPORT_CONVERT_TO_WORD=false NOTES_EXPORT_SET_FILE_DATES=false
    export NOTES_EXPORT_SYNC=true
fi

# ---- Read Apple Notes ----
EXPORT_FAILED=false
EXPORT_REFUSED=false
STATS_CAPTURED=false
typeset -A STATS
if [[ "${NOTES_EXPORT_EXTRACT_DATA}" == "true" ]]; then
    [[ "$(uname)" == "Darwin" ]] || fail_early $EXIT_USAGE "reading Apple Notes needs macOS"

    # Permission check that never prompts (NOTES_EXPORT_SKIP_PERMISSION_CHECK=true skips it)
    if [[ "$NOTES_EXPORT_SKIP_PERMISSION_CHECK" != "true" ]]; then
        PERMISSION="$("$PYTHON" "$SCRIPT_DIR/notes_permission.py" 2>/dev/null)"
        if [[ "$PERMISSION" == "not-running" ]]; then
            open -g -j -a Notes 2>/dev/null
            for _ in {1..20}; do
                sleep 0.5
                PERMISSION="$("$PYTHON" "$SCRIPT_DIR/notes_permission.py" 2>/dev/null)"
                [[ "$PERMISSION" != "not-running" ]] && break
            done
        fi
        emit_event permission state="$PERMISSION"
        case "$PERMISSION" in
            denied)
                emit_event result status=failed exit_code:=$EXIT_PERMISSION run_id="$RUN_ID" \
                    message="Notes automation is turned off for this app: System Settings > Privacy & Security > Automation"
                echo "Error: this app may not control Notes. Allow it in System Settings > Privacy & Security > Automation." >&2
                exit $EXIT_PERMISSION ;;
            prompt)
                if [[ "$NOTES_EXPORT_NON_INTERACTIVE" == "true" ]]; then
                    emit_event result status=failed exit_code:=$EXIT_PERMISSION run_id="$RUN_ID" \
                        message="macOS would ask for permission to control Notes; run once interactively and allow it"
                    echo "Error: macOS would ask for permission to control Notes (non-interactive run)." >&2
                    echo "Run the export once from a terminal while someone is at the Mac and click Allow." >&2
                    exit $EXIT_PERMISSION
                fi
                echo "macOS will ask for permission to control Notes; click Allow." ;;
        esac
    fi

    echo "Extracting note data..."
    emit_event stage stage=export status=started
    rm -f "${NOTES_EXPORT_ROOT_DIR}/data/export_stats.tmp"
    # osascript's log (stderr) carries @@ progress lines; the relay turns them
    # into events and passes everything else on to stderr.
    { osascript "$SCRIPT_DIR/export_notes.scpt" "$NOTES_EXPORT_ROOT_DIR" "$NOTES_EXPORT_NOTE_LIMIT" \
        "$NOTES_EXPORT_NOTE_LIMIT_PER_FOLDER" "$NOTES_EXPORT_NOTE_PICK_PROBABILITY" \
        "$NOTES_EXPORT_FILENAME_FORMAT" "$NOTES_EXPORT_SUBDIR_FORMAT" "$NOTES_EXPORT_USE_SUBDIRS" \
        "$NOTES_EXPORT_UPDATE_ALL" "$NOTES_EXPORT_INCLUDE_DELETED" "$NOTES_EXPORT_FILTER_ACCOUNTS" \
        "$NOTES_EXPORT_FILTER_FOLDERS" "$NOTES_EXPORT_MODIFIED_AFTER" "$PYTHON" "$SCRIPT_DIR" \
        "$NOTES_EXPORT_EXCLUDE_FOLDERS" 2>&1 1>&4 } 4>&2 | "$PYTHON" "$SCRIPT_DIR/events.py" relay
    pipe_status=("${pipestatus[@]}")
    OSA_RC=${pipe_status[1]}
    RELAY_RC=${pipe_status[2]}

    STATS_FILE="${NOTES_EXPORT_ROOT_DIR}/data/export_stats.tmp"
    if [[ -f "$STATS_FILE" ]]; then
        while IFS='=' read -r key value; do
            [[ -n "$key" ]] && STATS[$key]="$value"
        done < "$STATS_FILE"
        STATS_CAPTURED=true
        rm -f "$STATS_FILE"
    fi
    if [[ "$OSA_RC" -ne 0 ]]; then
        EXPORT_FAILED=true
        if [[ "$RELAY_RC" -eq 3 || "${STATS[fatal_number]}" == "-1743" ]]; then
            EXPORT_REFUSED=true
            echo "Error: Notes refused automation (-1743). Allow it in System Settings > Privacy & Security > Automation." >&2
        else
            echo "Error: the AppleScript export failed (exit $OSA_RC)." >&2
        fi
        emit_event stage stage=export status=failed exit_code:=$OSA_RC
    else
        emit_event stage stage=export status=finished processed:="${STATS[processed]:-0}" \
            unchanged:="${STATS[unchanged]:-0}" locked:="${STATS[locked]:-0}" errors:="${STATS[errors]:-0}"
    fi
    [[ "${STATS[errors]:-0}" -gt 0 ]] && STEP_FAILURES=$((STEP_FAILURES + 1))

    # Record deletions and moves, refresh folder metadata (#37). An unfinished
    # export writes no END marker, so no deletions are recorded from it.
    run_step tracking "$PYTHON" "$SCRIPT_DIR/tracker_io.py" finalize \
        "${NOTES_EXPORT_ROOT_DIR}/data" "${NOTES_EXPORT_ROOT_DIR}/data/.live_notes.tsv"
    # A moved note was exported again in its new folder; remove the old copy
    run_step tidy "$PYTHON" "$SCRIPT_DIR/prune_deleted.py" --root "$NOTES_EXPORT_ROOT_DIR" --moved
fi

if [[ "$EXPORT_FAILED" != "true" ]]; then
    # Tags from the Notes database (before images, which can add a Tags line)
    if [[ "${NOTES_EXPORT_TAGS}" == "true" ]]; then
        echo "Reading tags from the Notes database..."
        run_step tags "$PYTHON" "$SCRIPT_DIR/notes_db.py" tags --root "$NOTES_EXPORT_ROOT_DIR"
    fi
    if [[ "${NOTES_EXPORT_EXTRACT_IMAGES}" == "true" ]]; then
        echo "Extracting images..."
        run_step images "$PYTHON" "$SCRIPT_DIR/extract_images.py"
    fi
    if [[ "${NOTES_EXPORT_CONVERT_TO_MARKDOWN}" == "true" ]]; then
        echo "Converting to Markdown..."
        run_step markdown "$PYTHON" "$SCRIPT_DIR/convert_to_markdown.py"
    fi
    if [[ "${NOTES_EXPORT_CONVERT_TO_PDF}" == "true" ]]; then
        echo "Converting to PDF..."
        run_step pdf "$PYTHON" "$SCRIPT_DIR/convert_to_pdf.py"
    fi
    if [[ "${NOTES_EXPORT_CONVERT_TO_WORD}" == "true" ]]; then
        echo "Converting to Word..."
        run_step word "$PYTHON" "$SCRIPT_DIR/convert_to_word.py"
    fi
    if [[ "${NOTES_EXPORT_SET_FILE_DATES}" == "true" ]]; then
        echo "Setting file dates to match Apple Notes..."
        run_step dates "$PYTHON" "$SCRIPT_DIR/set_file_dates.py"
    fi
    if [[ "${NOTES_EXPORT_PRUNE_DELETED}" == "true" ]]; then
        echo "Removing files of deleted notes..."
        run_step prune "$PYTHON" "$SCRIPT_DIR/prune_deleted.py" --root "$NOTES_EXPORT_ROOT_DIR" --deleted
    fi
fi

# ---- Sync back to Apple Notes (writes to Notes; only when asked) ----
if [[ "${NOTES_EXPORT_SYNC}" == "true" && "$EXPORT_FAILED" != "true" ]]; then
    echo "Syncing changes back to Apple Notes..."
    SYNC_ARGS=()   # an array, so each option stays one argument (#31)
    [[ "${NOTES_EXPORT_SYNC_DRY_RUN}" == "true" ]] && SYNC_ARGS+=(--dry-run)
    [[ "${NOTES_EXPORT_CREATE_NEW}" == "true" ]] && SYNC_ARGS+=(--create-new)
    [[ -n "${NOTES_EXPORT_CONFLICT_STRATEGY}" ]] && SYNC_ARGS+=(--conflict "${NOTES_EXPORT_CONFLICT_STRATEGY}")
    [[ -n "${NOTES_EXPORT_FILTER_FOLDERS}" ]] && SYNC_ARGS+=(--filter-folders "${NOTES_EXPORT_FILTER_FOLDERS}")
    [[ -n "${NOTES_EXPORT_FILTER_ACCOUNTS}" ]] && SYNC_ARGS+=(--filter-accounts "${NOTES_EXPORT_FILTER_ACCOUNTS}")
    run_step sync "$PYTHON" "$SCRIPT_DIR/sync_to_notes.py" "${SYNC_ARGS[@]}"

    if [[ "${NOTES_EXPORT_SYNC_DRY_RUN}" != "true" ]]; then
        REGEN_ARGS=$(cd "$SCRIPT_DIR" && "$PYTHON" -c "
from sync_settings import load_settings
regen = load_settings().get('autoRegenerate', {})
print(','.join(f for f in ('html', 'pdf', 'word') if regen.get(f, False)))
" 2>/dev/null)
        if [[ -n "$REGEN_ARGS" ]]; then
            echo "Auto-regenerating formats after sync: $REGEN_ARGS"
            [[ "$REGEN_ARGS" == *html* ]] && run_step images "$PYTHON" "$SCRIPT_DIR/extract_images.py"
            [[ "$REGEN_ARGS" == *pdf* ]] && run_step pdf "$PYTHON" "$SCRIPT_DIR/convert_to_pdf.py"
            [[ "$REGEN_ARGS" == *word* ]] && run_step word "$PYTHON" "$SCRIPT_DIR/convert_to_word.py"
        fi
    fi
fi

if [[ "${NOTES_EXPORT_UPDATE_QDRANT}" == "true" && "$EXPORT_FAILED" != "true" ]]; then
    echo "Syncing notes to Qdrant..."
    run_step qdrant "$PYTHON" "$SCRIPT_DIR/qdrant_integration.py" sync
fi

# ---- Outcome and manifest (always, even after a failure) ----
if [[ "$EXPORT_REFUSED" == "true" ]]; then
    RUN_STATUS="failed"; RUN_EXIT=$EXIT_PERMISSION
elif [[ "$EXPORT_FAILED" == "true" ]]; then
    RUN_STATUS="failed"; RUN_EXIT=$EXIT_FAILED
elif [[ $STEP_FAILURES -gt 0 ]]; then
    RUN_STATUS="partial"; RUN_EXIT=$EXIT_PARTIAL
else
    RUN_STATUS="ok"; RUN_EXIT=$EXIT_OK
fi

MANIFEST_PATH="$NOTES_EXPORT_ROOT_DIR/manifest.json"
RUN_INFO="$NOTES_EXPORT_ROOT_DIR/data/.run_info.json"
mkdir -p "$NOTES_EXPORT_ROOT_DIR/data"
"$PYTHON" - "$RUN_INFO" <<PYEOF
import json, os, sys
env = os.environ
info = {
    "id": "$RUN_ID", "started_at": "$RUN_STARTED_AT", "mode": "$RUN_MODE",
    "tool_version": "$NOTES_EXPORTER_VERSION", "status": "$RUN_STATUS", "exit_code": $RUN_EXIT,
    "formats": "${(j:,:)FORMATS}".split(","),
    "subdir_format": env.get("NOTES_EXPORT_SUBDIR_FORMAT", ""),
    "filename_format": env.get("NOTES_EXPORT_FILENAME_FORMAT", ""),
    "use_subdirs": env.get("NOTES_EXPORT_USE_SUBDIRS", "true") == "true",
    "filters": {k: env.get(v, "") for k, v in (
        ("accounts", "NOTES_EXPORT_FILTER_ACCOUNTS"), ("folders", "NOTES_EXPORT_FILTER_FOLDERS"),
        ("exclude_folders", "NOTES_EXPORT_EXCLUDE_FOLDERS"), ("modified_after", "NOTES_EXPORT_MODIFIED_AFTER"))},
    "notes_examined": int("${STATS[total]:-0}" or 0), "notes_exported": int("${STATS[processed]:-0}" or 0),
    "notes_unchanged": int("${STATS[unchanged]:-0}" or 0), "errors": int("${STATS[errors]:-0}" or 0),
    "step_failures": $STEP_FAILURES,
}
with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(info, f)
PYEOF
if [[ "$NOTES_EXPORT_EXTRACT_DATA" == "true" || -f "$MANIFEST_PATH" || -d "$NOTES_EXPORT_ROOT_DIR/data" ]]; then
    if ! "$PYTHON" "$SCRIPT_DIR/build_manifest.py" --root "$NOTES_EXPORT_ROOT_DIR" --run-info "$RUN_INFO"; then
        echo "Error: could not write the manifest" >&2
        [[ $RUN_EXIT -eq 0 ]] && { RUN_STATUS="partial"; RUN_EXIT=$EXIT_PARTIAL; }
    fi
fi

# ---- Remove the venv if asked ----
if [[ "${NOTES_EXPORT_REMOVE_VENV}" == "true" && -n "${NOTES_EXPORT_VENV_DIR}" ]]; then
    echo "Removing virtual environment: ${NOTES_EXPORT_VENV_DIR}"
    rm -rf "${NOTES_EXPORT_VENV_DIR}"
fi

# ---- Human summary ----
ELAPSED_TIME=$((SECONDS - SCRIPT_START_TIME))
echo ""
echo "===================================="
case "$RUN_STATUS" in
    ok)      echo "Export completed successfully!" ;;
    partial) echo "Export completed with errors (see above)." ;;
    *)       echo "Export failed." ;;
esac
if [[ $ELAPSED_TIME -ge 60 ]]; then
    echo "Total elapsed time: $((ELAPSED_TIME / 60))m $((ELAPSED_TIME % 60))s"
else
    echo "Total elapsed time: ${ELAPSED_TIME}s"
fi
if [[ "$STATS_CAPTURED" == "true" ]]; then
    echo ""
    echo "PROCESSING STATISTICS:"
    echo "  Folders processed: ${STATS[folders]}"
    echo "  Total notes examined: ${STATS[total]}"
    echo "  Notes processed/updated: ${STATS[processed]}"
    echo "  Notes skipped (unchanged): ${STATS[unchanged]}"
    echo "  Notes skipped (filtered): ${STATS[filtered]}"
    echo "  Locked notes skipped: ${STATS[locked]}"
    echo "  Errors: ${STATS[errors]}"
    echo "  AppleScript time: ${STATS[elapsed]}s"
fi
[[ -f "$MANIFEST_PATH" ]] && echo "Manifest: $MANIFEST_PATH"
echo "===================================="

emit_event result status="$RUN_STATUS" exit_code:=$RUN_EXIT run_id="$RUN_ID" manifest="$MANIFEST_PATH" \
    elapsed_seconds:=$ELAPSED_TIME
exit $RUN_EXIT
