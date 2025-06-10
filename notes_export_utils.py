import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any

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
                    json_files = list(Path(data_dir).glob("*.json"))
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
        return list(data_path.glob("*.json"))
    
    def load_notebook_data(self, json_file_path: str) -> Dict[str, Any]:
        """Load notebook data from JSON file"""
        try:
            with open(json_file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    
    def save_notebook_data(self, json_file_path: str, data: Dict[str, Any]):
        """Save notebook data to JSON file"""
        try:
            with open(json_file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, sort_keys=True)
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
            folder_name = json_file.stem
            
            for note_id, note_info in notebook_data.items():
                # Skip deleted notes
                if 'deletedDate' in note_info:
                    continue
                
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
    
    def mark_note_exported(self, json_file_path: str, note_id: str, export_type: str):
        """Mark a note as exported to the specified format"""
        notebook_data = self.load_notebook_data(json_file_path)
        
        if note_id in notebook_data:
            last_exported_key = f'lastExportedTo{export_type.capitalize()}'
            last_exported = notebook_data[note_id].get('lastExported', '')
            notebook_data[note_id][last_exported_key] = last_exported
            
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

def get_tracker() -> NotesExportTracker:
    """Convenience function to get a tracker instance"""
    return NotesExportTracker()