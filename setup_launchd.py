#!/usr/bin/env python3

import os
import getpass
from pathlib import Path
import argparse
from datetime import datetime

def get_user_info():
    """Get current user information"""
    username = getpass.getuser()
    home_dir = Path.home()
    return username, home_dir

def create_wrapper_script(script_dir, home_dir):
    """Create the wrapper script that sources environment and runs the main script"""
    wrapper_content = f"""#!/bin/zsh

# Get the directory where this wrapper script is located
WRAPPER_DIR=$(dirname "$0")

# Source shell environment files if they exist
[[ -f "{home_dir}/.zshrc" ]] && source "{home_dir}/.zshrc"
[[ -f "{home_dir}/.zshenv" ]] && source "{home_dir}/.zshenv"
[[ -f "{home_dir}/.profile" ]] && source "{home_dir}/.profile"

# Source .env file if it exists in the script directory
[[ -f "$WRAPPER_DIR/.env" ]] && source "$WRAPPER_DIR/.env"

# Change to the script directory
cd "$WRAPPER_DIR"

# Ensure conda is available if it exists
if [[ -f "{home_dir}/miniconda3/etc/profile.d/conda.sh" ]]; then
    source "{home_dir}/miniconda3/etc/profile.d/conda.sh"
elif [[ -f "{home_dir}/anaconda3/etc/profile.d/conda.sh" ]]; then
    source "{home_dir}/anaconda3/etc/profile.d/conda.sh"
elif [[ -f "/opt/homebrew/Caskroom/miniconda/base/etc/profile.d/conda.sh" ]]; then
    source "/opt/homebrew/Caskroom/miniconda/base/etc/profile.d/conda.sh"
fi

# Log environment for debugging
echo "--- Environment Debug Info ---" >> logs/debug.log
echo "DATE: $(date)" >> logs/debug.log
echo "USER: $(whoami)" >> logs/debug.log
echo "HOME: $HOME" >> logs/debug.log
echo "PATH: $PATH" >> logs/debug.log
echo "PWD: $(pwd)" >> logs/debug.log
echo "CONDA available: $(which conda 2>/dev/null || echo 'not found')" >> logs/debug.log
echo "------------------------------" >> logs/debug.log

# Run the actual export script
./exportnotes.zsh "$@"
"""
    
    wrapper_path = script_dir / "exportnotes-wrapper.zsh"
    with open(wrapper_path, 'w') as f:
        f.write(wrapper_content)
    
    # Make executable
    os.chmod(wrapper_path, 0o755)
    return wrapper_path

def create_plist_file(username, home_dir, script_dir, schedule_hour=9, schedule_minute=0, interval_minutes=None):
    """Create the launchd plist file"""
    
    # Create logs directory if it doesn't exist
    logs_dir = script_dir / "logs"
    logs_dir.mkdir(exist_ok=True)
    os.chmod(logs_dir, 0o755)
    
    # Determine schedule type
    if interval_minutes:
        schedule_section = f"""    <key>StartInterval</key>
    <integer>{interval_minutes * 60}</integer>"""
    else:
        schedule_section = f"""    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>{schedule_hour}</integer>
        <key>Minute</key>
        <integer>{schedule_minute}</integer>
    </dict>"""
    
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.{username}.notes-exporter</string>
    
    <key>ProgramArguments</key>
    <array>
        <string>/bin/zsh</string>
        <string>{script_dir}/exportnotes-wrapper.zsh</string>
    </array>
    
    <key>WorkingDirectory</key>
    <string>{script_dir}</string>
    
    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>{home_dir}</string>
        <key>USER</key>
        <string>{username}</string>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin:/opt/homebrew/Caskroom/miniconda/base/bin</string>
    </dict>
    
{schedule_section}
    
    <key>RunAtLoad</key>
    <false/>
    
    <key>StandardOutPath</key>
    <string>{logs_dir}/stdout.log</string>
    
    <key>StandardErrorPath</key>
    <string>{logs_dir}/stderr.log</string>
    
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>"""
    
    # Write to LaunchAgents directory
    launch_agents_dir = home_dir / "Library" / "LaunchAgents"
    launch_agents_dir.mkdir(exist_ok=True)
    
    plist_path = launch_agents_dir / f"com.{username}.notes-exporter.plist"
    with open(plist_path, 'w') as f:
        f.write(plist_content)
    
    # Set correct permissions for plist file
    os.chmod(plist_path, 0o644)
    
    return plist_path

def create_env_file(script_dir):
    """Create a sample .env file"""
    env_content = """# Environment variables for notes export
# Uncomment and modify as needed

# Export settings
# export NOTES_EXPORT_ROOT_DIR="$HOME/Downloads/AppleNotesExport"
# export NOTES_EXPORT_CONVERT_TO_MARKDOWN="true"
# export NOTES_EXPORT_CONVERT_TO_PDF="false"
# export NOTES_EXPORT_EXTRACT_IMAGES="true"

# Conda settings
# export NOTES_EXPORT_CONDA_ENV="notes-export"

# Custom PATH additions
# export PATH="/opt/homebrew/bin:$PATH"

# Other custom environment variables
# export MY_CUSTOM_VAR="value"
"""
    
    env_path = script_dir / ".env"
    if not env_path.exists():
        with open(env_path, 'w') as f:
            f.write(env_content)
        print(f"Created sample .env file at: {env_path}")
    else:
        print(f".env file already exists at: {env_path}")
    
    return env_path

def remove_launchd_setup(username, home_dir, script_dir):
    """Remove the launchd setup (unload and delete files)"""
    launch_agents_dir = home_dir / "Library" / "LaunchAgents"
    plist_path = launch_agents_dir / f"com.{username}.notes-exporter.plist"
    wrapper_path = script_dir / "exportnotes-wrapper.zsh"
    
    print(f"Removing launchd setup for user: {username}")
    
    # First unload the job if it's loaded
    unload_job(username, home_dir)
    
    # Remove the plist file
    if plist_path.exists():
        plist_path.unlink()
        print(f"✓ Removed plist file: {plist_path}")
    else:
        print(f"Plist file not found: {plist_path}")
    
    # Remove the wrapper script
    if wrapper_path.exists():
        wrapper_path.unlink()
        print(f"✓ Removed wrapper script: {wrapper_path}")
    else:
        print(f"Wrapper script not found: {wrapper_path}")
    
    print("✓ LaunchD setup removed successfully!")
    print("Note: The main exportnotes.zsh script and .env file were left untouched.")

def is_job_loaded(username):
    """Check if the job is currently loaded (returns True/False)"""
    result = os.system(f"launchctl list | grep -q notes-exporter")
    return result == 0

def load_job(username, home_dir):
    """Load the launchd job"""
    plist_path = home_dir / "Library" / "LaunchAgents" / f"com.{username}.notes-exporter.plist"
    
    if not plist_path.exists():
        print(f"Error: Plist file not found at {plist_path}")
        print("Run the script without --load first to create the files.")
        return False
    
    # Check if job is already loaded and unload it first
    if is_job_loaded(username):
        print("Job is already loaded. Unloading first...")
        unload_job(username, home_dir)
        # Give it a moment to complete
        import time
        time.sleep(1)
    
    print(f"Loading launchd job from: {plist_path}")
    result = os.system(f"launchctl load '{plist_path}'")
    if result == 0:
        print("✓ Job loaded successfully!")
        return True
    else:
        print(f"✗ Failed to load job (exit code: {result})")
        print("Common solutions:")
        print("1. Try unloading first: python3 setup_launchd.py --unload")
        print("2. Check plist syntax: plutil -lint '{}'".format(plist_path))
        print("3. Try manual load: launchctl load '{}'".format(plist_path))
        return False

def unload_job(username, home_dir):
    """Unload the launchd job"""
    plist_path = home_dir / "Library" / "LaunchAgents" / f"com.{username}.notes-exporter.plist"
    
    print(f"Unloading launchd job from: {plist_path}")
    result = os.system(f"launchctl unload '{plist_path}' 2>/dev/null")
    if result == 0:
        print("✓ Job unloaded successfully!")
        return True
    else:
        print("✓ Job was not loaded (or already unloaded)")
        return True

def test_job(username):
    """Test run the launchd job manually"""
    print(f"Starting manual test run of job: com.{username}.notes-exporter")
    result = os.system(f"launchctl start com.{username}.notes-exporter")
    if result == 0:
        print("✓ Test job started!")
        print("Check the logs to see if it ran successfully:")
        print("  tail -f logs/stdout.log")
        print("  tail -f logs/stderr.log")
    else:
        print("✗ Failed to start test job")
        print("Make sure the job is loaded first with --load")

def check_job_status(username):
    """Check if the job is currently loaded"""
    print("Checking job status...")
    if is_job_loaded(username):
        # Show detailed status
        os.system(f"launchctl list | grep notes-exporter")
        return True
    else:
        print("✗ Job is not loaded")
        return False

def debug_plist(username, home_dir, script_dir):
    """Debug the plist file and related paths"""
    plist_path = home_dir / "Library" / "LaunchAgents" / f"com.{username}.notes-exporter.plist"
    wrapper_path = script_dir / "exportnotes-wrapper.zsh"
    main_script = script_dir / "exportnotes.zsh"
    
    print("=== DEBUGGING PLIST SETUP ===")
    print(f"User: {username}")
    print(f"Home: {home_dir}")
    print(f"Script dir: {script_dir}")
    print()
    
    # Check plist file
    print("1. Plist file:")
    if plist_path.exists():
        print(f"   ✓ Exists: {plist_path}")
        print(f"   Permissions: {oct(plist_path.stat().st_mode)[-3:]}")
        
        # Check syntax
        print("   Checking syntax...")
        result = os.system(f"plutil -lint '{plist_path}' 2>/dev/null")
        if result == 0:
            print("   ✓ Valid XML syntax")
        else:
            print("   ✗ Invalid XML syntax!")
            os.system(f"plutil -lint '{plist_path}'")
    else:
        print(f"   ✗ Missing: {plist_path}")
    print()
    
    # Check wrapper script
    print("2. Wrapper script:")
    if wrapper_path.exists():
        print(f"   ✓ Exists: {wrapper_path}")
        print(f"   Permissions: {oct(wrapper_path.stat().st_mode)[-3:]}")
        if wrapper_path.stat().st_mode & 0o111:
            print("   ✓ Executable")
        else:
            print("   ✗ Not executable!")
    else:
        print(f"   ✗ Missing: {wrapper_path}")
    print()
    
    # Check main script
    print("3. Main script:")
    if main_script.exists():
        print(f"   ✓ Exists: {main_script}")
        print(f"   Permissions: {oct(main_script.stat().st_mode)[-3:]}")
        if main_script.stat().st_mode & 0o111:
            print("   ✓ Executable")
        else:
            print("   ✗ Not executable!")
    else:
        print(f"   ✗ Missing: {main_script}")
    print()
    
    # Check if job is already loaded
    print("4. Current job status:")
    if is_job_loaded(username):
        print("   Job is currently loaded:")
        os.system(f"launchctl list | grep notes-exporter")
    else:
        print("   Job is not loaded")
    print()
    
    # Check for any launchd errors
    print("5. Recent launchd errors:")
    os.system("log show --predicate 'subsystem == \"com.apple.launchd\"' --last 5m | grep -i error | tail -5")
    print()
    
    # Show plist content
    if plist_path.exists():
        print("6. Plist content (first 20 lines):")
        os.system(f"head -20 '{plist_path}'")

def main():
    parser = argparse.ArgumentParser(description='Manage launchd setup for notes export scheduling')
    
    # Action arguments (mutually exclusive)
    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument('--remove', action='store_true',
                        help='Remove the launchd setup (unload and delete files)')
    action_group.add_argument('--load', action='store_true',
                        help='Load the launchd job (start scheduling)')
    action_group.add_argument('--unload', action='store_true',
                        help='Unload the launchd job (stop scheduling)')
    action_group.add_argument('--test', action='store_true',
                        help='Run the job manually for testing')
    action_group.add_argument('--status', action='store_true',
                        help='Check if the job is currently loaded')
    action_group.add_argument('--debug', action='store_true',
                        help='Debug the plist setup and check for issues')
    
    # Configuration arguments
    parser.add_argument('--script-dir', type=str, default='.', 
                        help='Directory containing the exportnotes.zsh script (default: current directory)')
    parser.add_argument('--hour', type=int, default=9, 
                        help='Hour to run daily (0-23, default: 9)')
    parser.add_argument('--minute', type=int, default=0, 
                        help='Minute to run (0-59, default: 0)')
    parser.add_argument('--interval', type=int, 
                        help='Run every N minutes instead of daily schedule')
    
    args = parser.parse_args()
    
    # Get user info
    username, home_dir = get_user_info()
    script_dir = Path(args.script_dir).resolve()
    
    # Handle different actions
    if args.remove:
        remove_launchd_setup(username, home_dir, script_dir)
        return
    elif args.load:
        if load_job(username, home_dir):
            check_job_status(username)
        else:
            print("\nTroubleshooting steps:")
            print("1. Check if job already loaded: python3 setup_launchd.py --status")
            print("2. Unload first: python3 setup_launchd.py --unload")
            print("3. Recreate setup: python3 setup_launchd.py")
        return
    elif args.unload:
        unload_job(username, home_dir)
        return
    elif args.test:
        test_job(username)
        return
    elif args.status:
        if check_job_status(username):
            print("✓ Job is currently loaded and scheduled")
        else:
            print("✗ Job is not loaded")
        return
    elif args.debug:
        debug_plist(username, home_dir, script_dir)
        return
    
    print(f"Setting up launchd for user: {username}")
    print(f"Home directory: {home_dir}")
    print(f"Script directory: {script_dir}")
    
    # Check if exportnotes.zsh exists
    main_script = script_dir / "exportnotes.zsh"
    if not main_script.exists():
        print(f"Warning: {main_script} not found!")
        print("Make sure you're running this from the correct directory.")
    else:
        # Set correct permissions for main script
        os.chmod(main_script, 0o755)
        print(f"Set permissions for: {main_script}")
    
    # Ensure script directory has correct permissions
    os.chmod(script_dir, 0o755)
    
    # Ensure LaunchAgents directory has correct permissions
    launch_agents_dir = home_dir / "Library" / "LaunchAgents"
    if launch_agents_dir.exists():
        os.chmod(launch_agents_dir, 0o755)
    
    # Create wrapper script
    wrapper_path = create_wrapper_script(script_dir, home_dir)
    print(f"Created wrapper script: {wrapper_path}")
    
    # Create plist file
    plist_path = create_plist_file(username, home_dir, script_dir, 
                                   args.hour, args.minute, args.interval)
    print(f"✓ Created plist file: {plist_path}")
    
    # Create sample .env file
    env_path = create_env_file(script_dir)
    
    # Print schedule info
    if args.interval:
        print(f"Scheduled to run every {args.interval} minutes")
    else:
        print(f"Scheduled to run daily at {args.hour:02d}:{args.minute:02d}")
    
    print("Setup complete! Use these commands to manage your scheduled job:")
    print(f"  python3 {Path(__file__).name} --load     # Start scheduling")
    print(f"  python3 {Path(__file__).name} --test     # Test run manually")
    print(f"  python3 {Path(__file__).name} --status   # Check if loaded")
    print(f"  python3 {Path(__file__).name} --unload   # Stop scheduling")
    print(f"  python3 {Path(__file__).name} --remove   # Remove everything")
    print(f"  python3 {Path(__file__).name} --debug    # Debug any issues")
    print("\nOr view logs directly:")
    print(f"  tail -f '{script_dir}/logs/stdout.log'")
    print(f"  tail -f '{script_dir}/logs/stderr.log'")

if __name__ == "__main__":
    main()