#!/bin/zsh

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
export NOTES_EXPORT_FILENAME_FORMAT="${NOTES_EXPORT_FILENAME_FORMAT:=&title}"
export NOTES_EXPORT_SUBDIR_FORMAT="${NOTES_EXPORT_SUBDIR_FORMAT:=&account-&folder}"
export NOTES_EXPORT_USE_SUBDIRS="${NOTES_EXPORT_USE_SUBDIRS:=true}"
export NOTES_EXPORT_CONDA_ENV="${NOTES_EXPORT_CONDA_ENV:=}"
export NOTES_EXPORT_REMOVE_CONDA_ENV="${NOTES_EXPORT_REMOVE_CONDA_ENV:=false}"

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
        --conda-env|-c)
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
        *)
            echo "Unknown option: $1"
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

# Conditionally execute the AppleScript for data extraction
if [[ "${NOTES_EXPORT_EXTRACT_DATA}" == "true" ]]; then
    osascript "$SCRIPT_DIR/export-notes.scpt" "$NOTES_EXPORT_ROOT_DIR" "$NOTES_EXPORT_NOTE_LIMIT" "$NOTES_EXPORT_NOTE_LIMIT_PER_FOLDER" "$NOTES_EXPORT_NOTE_PICK_PROBABILITY" "$NOTES_EXPORT_FILENAME_FORMAT" "$NOTES_EXPORT_SUBDIR_FORMAT" "$NOTES_EXPORT_USE_SUBDIRS"
fi

# Conditionally execute the image extraction script
if [[ "${NOTES_EXPORT_EXTRACT_IMAGES}" == "true" ]]; then
    python "$SCRIPT_DIR/extract-images.py"
fi

# Conditionally execute the conversion scripts
if [[ "${NOTES_EXPORT_CONVERT_TO_MARKDOWN}" == "true" ]]; then
    python "$SCRIPT_DIR/convert-to-markdown.py"
fi

if [[ "${NOTES_EXPORT_CONVERT_TO_PDF}" == "true" ]]; then
    python "$SCRIPT_DIR/convert-to-pdf.py"
fi

if [[ "${NOTES_EXPORT_CONVERT_TO_WORD}" == "true" ]]; then
    python "$SCRIPT_DIR/convert-to-word.py"
fi

# Optionally deactivate and remove the conda environment
if [[ "${NOTES_EXPORT_REMOVE_CONDA_ENV}" == "true" && -n "${NOTES_EXPORT_CONDA_ENV}" ]]; then
    deactivate_conda_env
    remove_conda_env "${NOTES_EXPORT_CONDA_ENV}"
fi
