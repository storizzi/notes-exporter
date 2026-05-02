"""Tests for exportnotes.zsh command-line option parsing.

These tests verify that CLI options are parsed correctly by running
a minimal zsh option parser that mirrors the main script.
"""

import os
import subprocess
import pytest

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_option(args: str, env_var: str) -> str:
    """Run a zsh snippet that parses args like exportnotes.zsh and prints the env var."""
    script = f"""
    export NOTES_EXPORT_ROOT_DIR="/tmp/test"
    export NOTES_EXPORT_SUPPRESS_CHROME_HEADER_PDF="true"
    export NOTES_EXPORT_CONVERT_TO_MARKDOWN="false"
    export NOTES_EXPORT_CONVERT_TO_PDF="false"
    export NOTES_EXPORT_CONVERT_TO_WORD="false"
    export NOTES_EXPORT_EXTRACT_IMAGES="true"
    export NOTES_EXPORT_EXTRACT_DATA="true"
    export NOTES_EXPORT_FILENAME_FORMAT="&title-&id"
    export NOTES_EXPORT_SUBDIR_FORMAT="&account-&folder"
    export NOTES_EXPORT_USE_SUBDIRS="true"
    export NOTES_EXPORT_VENV_DIR=""
    export NOTES_EXPORT_REMOVE_VENV="false"
    export NOTES_EXPORT_UPDATE_ALL="false"
    export NOTES_EXPORT_INCLUDE_DELETED="false"
    export NOTES_EXPORT_SET_FILE_DATES="false"
    export NOTES_EXPORT_FILTER_ACCOUNTS=""
    export NOTES_EXPORT_FILTER_FOLDERS=""
    export NOTES_EXPORT_CLEAN="false"
    export NOTES_EXPORT_SYNC="false"
    export NOTES_EXPORT_SYNC_ONLY="false"
    export NOTES_EXPORT_SYNC_DRY_RUN="false"
    export NOTES_EXPORT_CREATE_NEW="false"
    export NOTES_EXPORT_CONFLICT_STRATEGY=""
    export NOTES_EXPORT_NO_OVERWRITE="false"
    export NOTES_EXPORT_MODIFIED_AFTER=""
    export NOTES_EXPORT_IMAGES_BESIDE_DOCS="false"
    export NOTES_EXPORT_HTML_WRAP="false"
    export NOTES_EXPORT_DEDUP_IMAGES="false"
    export NOTES_EXPORT_EXTRACT_PDF_ATTACHMENTS="false"

    set -- {args}

    while [[ $# -gt 0 ]]; do
        case $1 in
            --convert-markdown|-m)
                if [[ -n "$2" && "$2" != -* ]]; then
                    export NOTES_EXPORT_CONVERT_TO_MARKDOWN="$2"; shift 2
                else
                    export NOTES_EXPORT_CONVERT_TO_MARKDOWN="true"; shift
                fi;;
            --convert-pdf|-p)
                if [[ -n "$2" && "$2" != -* ]]; then
                    export NOTES_EXPORT_CONVERT_TO_PDF="$2"; shift 2
                else
                    export NOTES_EXPORT_CONVERT_TO_PDF="true"; shift
                fi;;
            --convert-word|-w)
                if [[ -n "$2" && "$2" != -* ]]; then
                    export NOTES_EXPORT_CONVERT_TO_WORD="$2"; shift 2
                else
                    export NOTES_EXPORT_CONVERT_TO_WORD="true"; shift
                fi;;
            --extract-images|-i)
                if [[ -n "$2" && "$2" != -* ]]; then
                    export NOTES_EXPORT_EXTRACT_IMAGES="$2"; shift 2
                else
                    export NOTES_EXPORT_EXTRACT_IMAGES="true"; shift
                fi;;
            --extract-data|-d)
                if [[ -n "$2" && "$2" != -* ]]; then
                    export NOTES_EXPORT_EXTRACT_DATA="$2"; shift 2
                else
                    export NOTES_EXPORT_EXTRACT_DATA="true"; shift
                fi;;
            --suppress-header-pdf|-s)
                if [[ -n "$2" && "$2" != -* ]]; then
                    export NOTES_EXPORT_SUPPRESS_CHROME_HEADER_PDF="$2"; shift 2
                else
                    export NOTES_EXPORT_SUPPRESS_CHROME_HEADER_PDF="true"; shift
                fi;;
            --use-subdirs|-x)
                if [[ -n "$2" && "$2" != -* ]]; then
                    export NOTES_EXPORT_USE_SUBDIRS="$2"; shift 2
                else
                    export NOTES_EXPORT_USE_SUBDIRS="true"; shift
                fi;;
            --update-all|-U)
                if [[ -n "$2" && "$2" != -* ]]; then
                    export NOTES_EXPORT_UPDATE_ALL="$2"; shift 2
                else
                    export NOTES_EXPORT_UPDATE_ALL="true"; shift
                fi;;
            --include-deleted|-I)
                if [[ -n "$2" && "$2" != -* ]]; then
                    export NOTES_EXPORT_INCLUDE_DELETED="$2"; shift 2
                else
                    export NOTES_EXPORT_INCLUDE_DELETED="true"; shift
                fi;;
            --set-file-dates|-D)
                if [[ -n "$2" && "$2" != -* ]]; then
                    export NOTES_EXPORT_SET_FILE_DATES="$2"; shift 2
                else
                    export NOTES_EXPORT_SET_FILE_DATES="true"; shift
                fi;;
            --conda-env|-c)
                export NOTES_EXPORT_VENV_DIR="$2"; shift 2;;
            --remove-conda-env|-e)
                if [[ -n "$2" && "$2" != -* ]]; then
                    export NOTES_EXPORT_REMOVE_VENV="$2"; shift 2
                else
                    export NOTES_EXPORT_REMOVE_VENV="true"; shift
                fi;;
            --venv-dir|-v)
                export NOTES_EXPORT_VENV_DIR="$2"; shift 2;;
            --remove-venv)
                if [[ -n "$2" && "$2" != -* ]]; then
                    export NOTES_EXPORT_REMOVE_VENV="$2"; shift 2
                else
                    export NOTES_EXPORT_REMOVE_VENV="true"; shift
                fi;;
            --sync|-S)
                if [[ -n "$2" && "$2" != -* ]]; then
                    export NOTES_EXPORT_SYNC="$2"; shift 2
                else
                    export NOTES_EXPORT_SYNC="true"; shift
                fi;;
            --sync-only)
                if [[ -n "$2" && "$2" != -* ]]; then
                    export NOTES_EXPORT_SYNC_ONLY="$2"; shift 2
                else
                    export NOTES_EXPORT_SYNC_ONLY="true"; shift
                fi;;
            --sync-dry-run)
                if [[ -n "$2" && "$2" != -* ]]; then
                    export NOTES_EXPORT_SYNC_DRY_RUN="$2"; shift 2
                else
                    export NOTES_EXPORT_SYNC_DRY_RUN="true"; shift
                fi;;
            --create-new)
                if [[ -n "$2" && "$2" != -* ]]; then
                    export NOTES_EXPORT_CREATE_NEW="$2"; shift 2
                else
                    export NOTES_EXPORT_CREATE_NEW="true"; shift
                fi;;
            --conflict)
                export NOTES_EXPORT_CONFLICT_STRATEGY="$2"; shift 2;;
            --no-overwrite|-O)
                if [[ -n "$2" && "$2" != -* ]]; then
                    export NOTES_EXPORT_NO_OVERWRITE="$2"; shift 2
                else
                    export NOTES_EXPORT_NO_OVERWRITE="true"; shift
                fi;;
            --modified-after)
                export NOTES_EXPORT_MODIFIED_AFTER="$2"; shift 2;;
            --images-beside-docs)
                if [[ -n "$2" && "$2" != -* ]]; then
                    export NOTES_EXPORT_IMAGES_BESIDE_DOCS="$2"; shift 2
                else
                    export NOTES_EXPORT_IMAGES_BESIDE_DOCS="true"; shift
                fi;;
            --html-wrap)
                if [[ -n "$2" && "$2" != -* ]]; then
                    export NOTES_EXPORT_HTML_WRAP="$2"; shift 2
                else
                    export NOTES_EXPORT_HTML_WRAP="true"; shift
                fi;;
            --dedup-images)
                if [[ -n "$2" && "$2" != -* ]]; then
                    export NOTES_EXPORT_DEDUP_IMAGES="$2"; shift 2
                else
                    export NOTES_EXPORT_DEDUP_IMAGES="true"; shift
                fi;;
            --extract-pdf-attachments)
                if [[ -n "$2" && "$2" != -* ]]; then
                    export NOTES_EXPORT_EXTRACT_PDF_ATTACHMENTS="$2"; shift 2
                else
                    export NOTES_EXPORT_EXTRACT_PDF_ATTACHMENTS="true"; shift
                fi;;
            --clean|-C)
                if [[ -n "$2" && "$2" != -* ]]; then
                    export NOTES_EXPORT_CLEAN="$2"; shift 2
                else
                    export NOTES_EXPORT_CLEAN="true"; shift
                fi;;
            --root-dir|-r)
                export NOTES_EXPORT_ROOT_DIR="$2"; shift 2;;
            --note-limit|-n)
                export NOTES_EXPORT_NOTE_LIMIT="$2"; shift 2;;
            --note-limit-per-folder|-f)
                export NOTES_EXPORT_NOTE_LIMIT_PER_FOLDER="$2"; shift 2;;
            --note-pick-probability|-b)
                export NOTES_EXPORT_NOTE_PICK_PROBABILITY="$2"; shift 2;;
            --filename-format|-t)
                export NOTES_EXPORT_FILENAME_FORMAT="$2"; shift 2;;
            --subdir-format|-u)
                export NOTES_EXPORT_SUBDIR_FORMAT="$2"; shift 2;;
            --filter-accounts|-A)
                export NOTES_EXPORT_FILTER_ACCOUNTS="$2"; shift 2;;
            --filter-folders|-F)
                export NOTES_EXPORT_FILTER_FOLDERS="$2"; shift 2;;
            --all-formats|--all|-a)
                export NOTES_EXPORT_CONVERT_TO_MARKDOWN="true"
                export NOTES_EXPORT_CONVERT_TO_PDF="true"
                export NOTES_EXPORT_CONVERT_TO_WORD="true"
                export NOTES_EXPORT_EXTRACT_IMAGES="true"
                shift;;
            *) shift;;
        esac
    done
    echo "${{{env_var}}}"
    """
    result = subprocess.run(
        ["zsh", "-c", script],
        capture_output=True, text=True
    )
    return result.stdout.strip()


@pytest.mark.unit
@pytest.mark.export
class TestBooleanFlagOptions:
    """All boolean options should work as both flags and with explicit values."""

    @pytest.mark.parametrize("flag,env_var", [
        ("--convert-markdown", "NOTES_EXPORT_CONVERT_TO_MARKDOWN"),
        ("--convert-pdf", "NOTES_EXPORT_CONVERT_TO_PDF"),
        ("--convert-word", "NOTES_EXPORT_CONVERT_TO_WORD"),
        ("--extract-images", "NOTES_EXPORT_EXTRACT_IMAGES"),
        ("--extract-data", "NOTES_EXPORT_EXTRACT_DATA"),
        ("--suppress-header-pdf", "NOTES_EXPORT_SUPPRESS_CHROME_HEADER_PDF"),
        ("--use-subdirs", "NOTES_EXPORT_USE_SUBDIRS"),
        ("--update-all", "NOTES_EXPORT_UPDATE_ALL"),
        ("--include-deleted", "NOTES_EXPORT_INCLUDE_DELETED"),
        ("--set-file-dates", "NOTES_EXPORT_SET_FILE_DATES"),
        ("--remove-conda-env", "NOTES_EXPORT_REMOVE_VENV"),
        ("--remove-venv", "NOTES_EXPORT_REMOVE_VENV"),
        ("--clean", "NOTES_EXPORT_CLEAN"),
        ("--sync", "NOTES_EXPORT_SYNC"),
        ("--sync-only", "NOTES_EXPORT_SYNC_ONLY"),
        ("--sync-dry-run", "NOTES_EXPORT_SYNC_DRY_RUN"),
        ("--create-new", "NOTES_EXPORT_CREATE_NEW"),
        ("--no-overwrite", "NOTES_EXPORT_NO_OVERWRITE"),
        ("--images-beside-docs", "NOTES_EXPORT_IMAGES_BESIDE_DOCS"),
        ("--html-wrap", "NOTES_EXPORT_HTML_WRAP"),
        ("--dedup-images", "NOTES_EXPORT_DEDUP_IMAGES"),
        ("--extract-pdf-attachments", "NOTES_EXPORT_EXTRACT_PDF_ATTACHMENTS"),
    ])
    def test_flag_without_value_sets_true(self, flag, env_var):
        assert parse_option(flag, env_var) == "true"

    @pytest.mark.parametrize("flag,env_var", [
        ("--convert-markdown", "NOTES_EXPORT_CONVERT_TO_MARKDOWN"),
        ("--convert-pdf", "NOTES_EXPORT_CONVERT_TO_PDF"),
        ("--extract-images", "NOTES_EXPORT_EXTRACT_IMAGES"),
        ("--extract-data", "NOTES_EXPORT_EXTRACT_DATA"),
        ("--update-all", "NOTES_EXPORT_UPDATE_ALL"),
        ("--set-file-dates", "NOTES_EXPORT_SET_FILE_DATES"),
        ("--clean", "NOTES_EXPORT_CLEAN"),
        ("--extract-pdf-attachments", "NOTES_EXPORT_EXTRACT_PDF_ATTACHMENTS"),
    ])
    def test_flag_with_explicit_true(self, flag, env_var):
        assert parse_option(f"{flag} true", env_var) == "true"

    @pytest.mark.parametrize("flag,env_var", [
        ("--convert-markdown", "NOTES_EXPORT_CONVERT_TO_MARKDOWN"),
        ("--extract-images", "NOTES_EXPORT_EXTRACT_IMAGES"),
        ("--extract-data", "NOTES_EXPORT_EXTRACT_DATA"),
        ("--update-all", "NOTES_EXPORT_UPDATE_ALL"),
        ("--set-file-dates", "NOTES_EXPORT_SET_FILE_DATES"),
        ("--extract-pdf-attachments", "NOTES_EXPORT_EXTRACT_PDF_ATTACHMENTS"),
    ])
    def test_flag_with_explicit_false(self, flag, env_var):
        assert parse_option(f"{flag} false", env_var) == "false"


@pytest.mark.unit
@pytest.mark.export
class TestShortFormOptions:
    """Short-form flags should work the same as long-form."""

    @pytest.mark.parametrize("short,env_var", [
        ("-m", "NOTES_EXPORT_CONVERT_TO_MARKDOWN"),
        ("-p", "NOTES_EXPORT_CONVERT_TO_PDF"),
        ("-w", "NOTES_EXPORT_CONVERT_TO_WORD"),
        ("-i", "NOTES_EXPORT_EXTRACT_IMAGES"),
        ("-d", "NOTES_EXPORT_EXTRACT_DATA"),
        ("-U", "NOTES_EXPORT_UPDATE_ALL"),
        ("-I", "NOTES_EXPORT_INCLUDE_DELETED"),
        ("-D", "NOTES_EXPORT_SET_FILE_DATES"),
        ("-C", "NOTES_EXPORT_CLEAN"),
        ("-S", "NOTES_EXPORT_SYNC"),
        ("-O", "NOTES_EXPORT_NO_OVERWRITE"),
    ])
    def test_short_flag_sets_true(self, short, env_var):
        assert parse_option(short, env_var) == "true"


@pytest.mark.unit
@pytest.mark.export
class TestValueOptions:
    """Options that take non-boolean values."""

    def test_root_dir(self):
        assert parse_option("--root-dir /custom/path", "NOTES_EXPORT_ROOT_DIR") == "/custom/path"

    def test_note_limit(self):
        assert parse_option("--note-limit 50", "NOTES_EXPORT_NOTE_LIMIT") == "50"

    def test_note_limit_per_folder(self):
        assert parse_option("--note-limit-per-folder 10", "NOTES_EXPORT_NOTE_LIMIT_PER_FOLDER") == "10"

    def test_note_pick_probability(self):
        assert parse_option("--note-pick-probability 75", "NOTES_EXPORT_NOTE_PICK_PROBABILITY") == "75"

    def test_filename_format(self):
        result = parse_option("--filename-format '&title-&id'", "NOTES_EXPORT_FILENAME_FORMAT")
        assert "&title" in result and "&id" in result

    def test_filter_accounts(self):
        assert parse_option("--filter-accounts 'iCloud,Gmail'", "NOTES_EXPORT_FILTER_ACCOUNTS") == "iCloud,Gmail"

    def test_filter_folders(self):
        assert parse_option("--filter-folders 'Notes,Evernote'", "NOTES_EXPORT_FILTER_FOLDERS") == "Notes,Evernote"

    def test_venv_dir(self):
        assert parse_option("--venv-dir .venv", "NOTES_EXPORT_VENV_DIR") == ".venv"

    def test_venv_dir_short(self):
        assert parse_option("-v .venv", "NOTES_EXPORT_VENV_DIR") == ".venv"

    def test_conflict_strategy(self):
        assert parse_option("--conflict local", "NOTES_EXPORT_CONFLICT_STRATEGY") == "local"

    def test_conda_env_maps_to_venv(self):
        """--conda-env should map to NOTES_EXPORT_VENV_DIR (deprecated alias)."""
        assert parse_option("--conda-env myenv", "NOTES_EXPORT_VENV_DIR") == "myenv"

    def test_conda_env_short_maps_to_venv(self):
        """Short -c should also map to NOTES_EXPORT_VENV_DIR."""
        assert parse_option("-c myenv", "NOTES_EXPORT_VENV_DIR") == "myenv"

    def test_remove_conda_env_maps_to_remove_venv(self):
        """--remove-conda-env should map to NOTES_EXPORT_REMOVE_VENV."""
        assert parse_option("--remove-conda-env", "NOTES_EXPORT_REMOVE_VENV") == "true"

    def test_modified_after(self):
        assert parse_option("--modified-after 2026-01-15", "NOTES_EXPORT_MODIFIED_AFTER") == "2026-01-15"


@pytest.mark.unit
@pytest.mark.export
class TestAllFormatsFlag:
    """The --all flag should enable all conversion formats."""

    def test_all_enables_markdown(self):
        assert parse_option("--all", "NOTES_EXPORT_CONVERT_TO_MARKDOWN") == "true"

    def test_all_enables_pdf(self):
        assert parse_option("--all", "NOTES_EXPORT_CONVERT_TO_PDF") == "true"

    def test_all_enables_word(self):
        assert parse_option("--all", "NOTES_EXPORT_CONVERT_TO_WORD") == "true"

    def test_all_enables_images(self):
        assert parse_option("--all", "NOTES_EXPORT_EXTRACT_IMAGES") == "true"


@pytest.mark.unit
@pytest.mark.export
class TestCombinedOptions:
    """Multiple options used together."""

    def test_markdown_and_pdf(self):
        assert parse_option("--convert-markdown --convert-pdf", "NOTES_EXPORT_CONVERT_TO_MARKDOWN") == "true"
        assert parse_option("--convert-markdown --convert-pdf", "NOTES_EXPORT_CONVERT_TO_PDF") == "true"

    def test_filter_with_limit(self):
        assert parse_option("--filter-accounts iCloud --note-limit 10", "NOTES_EXPORT_FILTER_ACCOUNTS") == "iCloud"
        assert parse_option("--filter-accounts iCloud --note-limit 10", "NOTES_EXPORT_NOTE_LIMIT") == "10"

    def test_boolean_flag_followed_by_another_flag(self):
        """A boolean flag followed by another flag should not consume the next flag as its value."""
        assert parse_option("--convert-markdown --convert-pdf", "NOTES_EXPORT_CONVERT_TO_MARKDOWN") == "true"
        assert parse_option("--convert-markdown --convert-pdf", "NOTES_EXPORT_CONVERT_TO_PDF") == "true"
