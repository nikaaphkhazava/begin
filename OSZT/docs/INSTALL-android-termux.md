# Running OSZT on an Android Phone (Xiaomi POCO X3 Pro / Termux)

This guide walks you through setting up the OSZT (Hermes) AI agent on an Android phone, such as the **Xiaomi POCO X3 Pro**. This phone features a powerful Snapdragon 860 chipset and up to 8GB of RAM, making it a capable environment for executing file management and preferences synchronization tasks locally within Termux.

By the end of this guide, your AI assistant will be able to **search**, **download**, and **rearrange** files directly on your phone's storage, while keeping your user preferences and action history synchronized with a secure cloud backup that you can **delete at any time**.

---

## Prerequisites

1. **Termux (F-Droid version)**: Install Termux from F-Droid (do not use the Google Play Store version as it is deprecated and no longer receives updates).
2. **Termux:API (Optional)**: Provides shell-level integrations with Android system APIs (optional but highly recommended).

---

## Step 1: Setting Up Termux and Package Installation

Open Termux on your phone and run the following commands to update the system packages and install Python, SQLite, curl, and other dependencies:

```bash
# Update and upgrade existing packages
pkg update && pkg upgrade -y

# Install Python, build dependencies, sqlite, curl, and Git
pkg install git python python-tkinter ndk-sysroot clang make libjpeg-turbo sqlite curl -y
```

---

## Step 2: Granting Storage Access (To Search and Rearrange Files)

To allow the AI agent to search, move, rename, and copy files on your phone's internal storage, you must grant Termux storage permissions:

```bash
termux-setup-storage
```

This creates a directory at `~/storage` which links directly to your phone's internal storage directory (shared directories like `/sdcard` containing `Downloads`, `DCIM`, `Documents`, etc.).

### Setting up the Policy for Storage Management
To allow the agent to manage these files, configure your policy (`~/.config/oszt/policy.json`) with the correct roots:

```json
{
  "allowed_capabilities": [
    "list_files",
    "find_files",
    "write_text",
    "make_dir",
    "move_path",
    "copy_path",
    "delete_path",
    "restore_path",
    "list_trash",
    "download_file",
    "sync_preferences_to_cloud",
    "fetch_preferences_from_cloud",
    "delete_cloud_history"
  ],
  "file_roots": ["~/storage/shared"],
  "write_roots": ["~/storage/shared/Documents", "~/storage/shared/Downloads"],
  "allowed_hosts": ["yourcloud.com", "flathub.org", "download.mozilla.org", "github.com"]
}
```

- **Search files**: Using the `find_files` capability, the agent can recursively search files inside `~/storage/shared` matching glob patterns.
- **Rearrange files**: Using the `move_path` and `copy_path` capabilities, the agent can organize and rearrange documents or downloads easily.

---

## Step 3: Setting up the Local AI (Ollama or Remote API)

Running models directly on a smartphone GPU requires specific acceleration (like Termux-PRoot or native builds). For the POCO X3 Pro, you can run Ollama natively in Termux (CPU-only, slightly slower) or configure the agent to point to an Ollama server running on your local network (preferred for maximum speed).

### Option A: Running Ollama locally in Termux (CPU-only)
See the Ollama documentation for running under Termux, or install and pull the `qwen2.5:3b` model:
```bash
# If Ollama is running inside Termux
ollama serve &
ollama pull qwen2.5:3b
```

### Option B: Pointing to a local network server
If your PC runs Ollama, find your PC's IP (e.g. `192.168.1.100`) and pass it to the agent command:
```bash
oszt agent "Organize my PDF files in Downloads" --ollama-url http://192.168.1.100:11434
```

---

## Step 4: Cloud Preferences and History Synchronization (Deletable at any time)

To preserve your preferences (facts) and action history across devices and reinstalls, OSZT provides three built-in capabilities:
1. `sync_preferences_to_cloud` (POST)
2. `fetch_preferences_from_cloud` (GET)
3. `delete_cloud_history` (DELETE)

This is designed to use any standard REST endpoint (such as a private KV storage, custom webhook, Nextcloud, or a custom REST API).

### How to configure Cloud Sync

1. **Add the cloud hostname to policy allowed hosts**:
   Open `~/.config/oszt/policy.json` and ensure your cloud endpoint domain (e.g. `cloud.yourdomain.com`) is in the `"allowed_hosts"` list.

2. **Synchronize preferences & history to the cloud**:
   ```bash
   oszt --policy ~/.config/oszt/policy.json call sync_preferences_to_cloud endpoint_url=https://cloud.yourdomain.com/user123/backup
   ```
   *This POSTs a JSON payload containing all your facts (preferences) and recent actions.*

3. **Fetch (Restore) preferences from the cloud**:
   ```bash
   oszt --policy ~/.config/oszt/policy.json call fetch_preferences_from_cloud endpoint_url=https://cloud.yourdomain.com/user123/backup
   ```
   *This GETs the saved payload and updates your phone's local database.*

4. **Delete cloud history at any time**:
   If you ever want to completely remove your history and preferences from the cloud, invoke the delete capability:
   ```bash
   oszt --policy ~/.config/oszt/policy.json call delete_cloud_history endpoint_url=https://cloud.yourdomain.com/user123/backup
   ```
   *This sends a standard HTTP DELETE request to the server, telling it to purge all your data instantly.*

---

## Step 5: Testing and Running OSZT inside Termux

Clone and check that the entire logic is running perfectly on your phone:

```bash
# Clone the repository (if you haven't already)
git clone https://github.com/nikaaphkhazava/begin.git
cd begin/OSZT

# Run the unit tests to confirm stability
PYTHONPATH=. pytest

# Run doctor to see what is missing on your Android system
python3 -m oszt doctor
```

Once you've verified the actions in dry run, you can set `"dry_run": false` in your `~/.config/oszt/policy.json` to enable active rearrangement, downloads, and cloud syncing!
