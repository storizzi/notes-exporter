import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any

from tracker_io import tracker_files

def _tracker_stem(json_file) -> str:
    """'data/iCloud-Notes.json' -> 'iCloud-Notes'; a bare tracker name is returned as is."""
    name = str(json_file)
    if name.endswith(".json"):
        return Path(name).stem
    return name


class NotesExportTracker:
    """Utility class for tracking notes export status across different conversion formats"""
    
    def __init__(self, root_directory: str = None):
        if root_directory:
            self.root_directory = root_directory
        else:
            # Smart default detection
            self.root_directory = self._find_export_directory()
        
        self.data_directory = os.path.join(self.root_directory, 'data')
        
    def _find_export_directory(self) -> str:
        """Smart detection of Apple Notes export directory"""
        # First check environment variable
        env_dir = os.getenv('NOTES_EXPORT_ROOT_DIR')
        if env_dir and os.path.exists(env_dir):
            return env_dir
        
        # Common locations to check
        possible_locations = [
            # Current directory
            './AppleNotesExport',
            './notes',
            # Downloads folder
            os.path.expanduser('~/Downloads/AppleNotesExport'),
            os.path.expanduser('~/Downloads/notes'),
            # Desktop
            os.path.expanduser('~/Desktop/AppleNotesExport'),
            os.path.expanduser('~/Desktop/notes'),
            # Documents
            os.path.expanduser('~/Documents/AppleNotesExport'),
            os.path.expanduser('~/Documents/notes'),
        ]
        
        for location in possible_locations:
            if os.path.exists(location):
                # Check if it looks like a notes export (has data directory with JSON files)
                data_dir = os.path.join(location, 'data')
                if os.path.exists(data_dir):
                    json_files = tracker_files(data_dir)
                    if json_files:
                        print(f"Auto-detected notes export directory: {location}")
                        return location
        
        # Fallback to environment default or current directory
        fallback = os.getenv('NOTES_EXPORT_ROOT_DIR', './notes')
        print(f"Warning: Could not find notes export directory. Using fallback: {fallback}")
        print("Set NOTES_EXPORT_ROOT_DIR environment variable to specify the correct path.")
        return fallback
        
    def get_all_data_files(self) -> List[Path]:
        """Get all JSON data files in the data directory"""
        data_path = Path(self.data_directory)
        if not data_path.exists():
            print(f"Warning: Data directory does not exist: {self.data_directory}")
            return []
        return tracker_files(data_path)
    
    @staticmethod
    def subdir_for(json_file, note_info: Optional[Dict[str, Any]] = None) -> str:
        """Output subdirectory (relative, '/'-separated) for a tracker's notes.

        Records written since 1.4.0 carry ``subdir`` (it can be nested, e.g.
        ``iCloud/Food/Recipes`` with ``--subdir-format '&account/&folderpath'``).
        Older records fall back to the tracker's file name, which was the
        subdirectory name in every earlier layout.
        """
        if note_info and isinstance(note_info.get("subdir"), str):
            return note_info["subdir"]
        return _tracker_stem(json_file)

    def tracker_subdir(self, json_file, notebook_data: Optional[Dict[str, Any]] = None) -> str:
        """Subdirectory of a whole tracker (from any record that records it)."""
        if notebook_data is None:
            notebook_data = self.load_notebook_data(json_file)
        for info in notebook_data.values():
            if isinstance(info, dict) and isinstance(info.get("subdir"), str):
                return info["subdir"]
        return _tracker_stem(json_file)

    def load_notebook_data(self, json_file_path: str) -> Dict[str, Any]:
        """Load notebook data from JSON file"""
        try:
            with open(json_file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    
    def save_notebook_data(self, json_file_path: str, data: Dict[str, Any]):
        """Save notebook data to JSON file (atomically)"""
        try:
            from tracker_io import write_json_atomic
            write_json_atomic(Path(json_file_path), data)
        except Exception as e:
            print(f"Error saving notebook data to {json_file_path}: {e}")
    
    def get_notes_to_process(self, export_type: str) -> List[Dict[str, Any]]:
        """Get list of notes that need to be processed for the given export type"""
        notes_to_process = []
        last_exported_key = f'lastExportedTo{export_type.capitalize()}'
        
        # For image extraction, look for raw files, not html files
        source_folder = 'raw' if export_type == 'images' else 'html'
        source_extension = '.html'
        
        for json_file in self.get_all_data_files():
            notebook_data = self.load_notebook_data(json_file)

            for note_id, note_info in notebook_data.items():
                # Skip deleted notes
                if 'deletedDate' in note_info:
                    continue
                folder_name = self.subdir_for(json_file, note_info)
                
                # Check if export is needed
                last_exported = note_info.get('lastExported', '')
                last_exported_to_format = note_info.get(last_exported_key, '')
                
                if last_exported != last_exported_to_format:
                    filename = note_info.get('filename', f'note-{note_id}')
                    source_path = self._get_file_path(source_folder, folder_name, filename, source_extension)
                    
                    if source_path.exists():
                        notes_to_process.append({
                            'note_id': note_id,
                            'notebook': folder_name,
                            'tracker': json_file.stem,
                            'filename': filename,
                            'source_file': source_path,
                            'json_file': json_file,
                            'note_info': note_info,
                            'last_exported_key': last_exported_key
                        })
        
        return notes_to_process
    
    def _get_file_path(self, folder_type: str, folder_name: str, filename: str, extension: str) -> Path:
        """Helper to build file paths consistently"""
        if self._uses_subdirs():
            return Path(self.root_directory) / folder_type / folder_name / f"{filename}{extension}"
        else:
            return Path(self.root_directory) / folder_type / f"{filename}{extension}"
    
    def _uses_subdirs(self) -> bool:
        """Check if the export uses subdirectories"""
        return os.getenv('NOTES_EXPORT_USE_SUBDIRS', 'true').lower() == 'true'
    
    def mark_note_exported(self, json_file_path: str, note_id: str, export_type: str,
                           extra: Optional[Dict[str, Any]] = None):
        """Mark a note as exported to the specified format (plus optional extra fields)"""
        notebook_data = self.load_notebook_data(json_file_path)

        if note_id in notebook_data:
            last_exported_key = f'lastExportedTo{export_type.capitalize()}'
            last_exported = notebook_data[note_id].get('lastExported', '')
            notebook_data[note_id][last_exported_key] = last_exported
            if extra:
                notebook_data[note_id].update(extra)

            self.save_notebook_data(json_file_path, notebook_data)
    
    def get_output_path(self, export_type: str, folder_name: str, filename: str, extension: str) -> Path:
        """Get the output path for a converted file"""
        output_folder = os.path.join(self.root_directory, export_type)
        
        if self._uses_subdirs():
            output_path = Path(output_folder) / folder_name / f"{filename}{extension}"
        else:
            output_path = Path(output_folder) / f"{filename}{extension}"
        
        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        return output_path
    
    def copy_attachments(self, source_file: Path, output_file: Path):
        """Copy attachments folder from source to output location"""
        import shutil
        
        source_attachments = source_file.parent / 'attachments'
        if source_attachments.exists():
            output_attachments = output_file.parent / 'attachments'
            if output_attachments.exists():
                shutil.rmtree(output_attachments)
            shutil.copytree(source_attachments, output_attachments)
            print(f"Copied attachments from {source_attachments} to {output_attachments}")

    def get_sync_status(self, note_info: Dict[str, Any], md_file_path) -> Dict[str, Any]:
        """Get sync status for a note by comparing local hash and remote modification date.

        Returns dict with 'local_changed' and 'remote_changed' booleans.
        """
        import hashlib
        from pathlib import Path

        md_path = Path(md_file_path)

        # Local change detection
        local_changed = False
        # Baselines: the last sync, else the Markdown export (#31)
        last_hash = (note_info.get("localFileHashAtLastSync")
                     or note_info.get("markdownHash", ""))
        if md_path.exists() and last_hash:
            h = hashlib.sha256()
            with open(md_path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            current_hash = h.hexdigest()
            local_changed = current_hash != last_hash

        # Remote change detection
        last_remote_mod = (note_info.get("appleNotesModifiedAtLastSync")
                           or note_info.get("modifiedAtMarkdownExport", ""))
        current_remote_mod = note_info.get("modified", "")
        remote_changed = bool(last_remote_mod and current_remote_mod
                              and current_remote_mod != last_remote_mod)

        return {"local_changed": local_changed, "remote_changed": remote_changed}

    def mark_note_synced(self, json_file_path: str, note_id: str,
                         md_file_path, new_mod_date: str, sync_source: str = "markdown"):
        """Mark a note as synced back to Apple Notes."""
        import hashlib
        from datetime import datetime
        from pathlib import Path

        notebook_data = self.load_notebook_data(json_file_path)

        if note_id in notebook_data:
            md_path = Path(md_file_path)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Compute current file hash
            file_hash = ""
            if md_path.exists():
                h = hashlib.sha256()
                with open(md_path, "rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        h.update(chunk)
                file_hash = h.hexdigest()

            notebook_data[note_id]["lastSyncedToNotes"] = now
            notebook_data[note_id]["localFileHashAtLastSync"] = file_hash
            notebook_data[note_id]["appleNotesModifiedAtLastSync"] = new_mod_date
            notebook_data[note_id]["syncCount"] = notebook_data[note_id].get("syncCount", 0) + 1
            notebook_data[note_id]["syncSource"] = sync_source

            self.save_notebook_data(json_file_path, notebook_data)

    def find_new_local_files(self, format_dir: str = "md") -> List[Dict[str, Any]]:
        """Find files in the format directory that don't match any tracked note."""
        from pathlib import Path

        new_files = []
        format_root = Path(self.root_directory) / format_dir

        if not format_root.exists():
            return new_files

        for json_file in self.get_all_data_files():
            notebook_data = self.load_notebook_data(json_file)
            folder_name = self.tracker_subdir(json_file, notebook_data)

            known_filenames = {info.get("filename", "") for info in notebook_data.values()}

            if self._uses_subdirs():
                scan_dir = format_root / folder_name
            else:
                scan_dir = format_root

            if not scan_dir.exists():
                continue

            for f in scan_dir.glob("*.md"):
                if not f.name.endswith(".conflict.md") and f.stem not in known_filenames:
                    new_files.append({
                        "file_path": f,
                        "filename": f.stem,
                        "notebook": folder_name,
                        "json_file": json_file,
                    })

        return new_files


def file_sha256(path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def get_tracker() -> NotesExportTracker:
    """Convenience function to get a tracker instance"""
    return NotesExportTracker()

def run_for_notes(stage: str, notes: List[Dict[str, Any]], handle) -> int:
    """Run ``handle(note)`` for each note with progress events and error counting.

    ``handle`` returns True (done), False (failed) or None (skipped). Exceptions
    count as failures. Returns the process exit code: 0, or 1 if any failed.
    """
    import events
    total = len(notes)
    failures = 0
    events.progress(stage, 0, total, force=True, unit="notes")
    for i, note in enumerate(notes, 1):
        try:
            ok = handle(note)
        except Exception as e:  # keep going; report at the end
            print(f"Error in {stage} for {note.get('filename')}: {e}")
            ok = False
        if ok is False:
            failures += 1
            events.emit("note_error", stage=stage, note_id=note.get("note_id"),
                        filename=note.get("filename"))
        events.progress(stage, i, total, unit="notes", failed=failures)
    if total:
        events.progress(stage, total, total, force=True, unit="notes", failed=failures)
    if failures:
        print(f"{stage}: {failures} of {total} notes failed")
    return 1 if failures else 0
