#!/usr/bin/env python3
"""
VMUPro Save Converter - Bulk VM2 to VMUPro format converter
A Windows tool for converting Dreamcast VM2 save files (.vmu) to VMUPro format

Credits:
- VM2 Hardware: Created by DreamMods (modern VMU memory card device)
- VMUPro Hardware: Created by 8bitmods (modern VMU memory card device)
- Game Database: K3zter/vmu-save-splitter (https://github.com/K3zter/vmu-save-splitter)
"""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, scrolledtext, simpledialog
import os
import shutil
import re
import json
import csv
import threading
from pathlib import Path
from datetime import datetime
import urllib.request
import ssl
import base64
from io import BytesIO, StringIO

# Embedded logo data (will be replaced with actual base64 encoded image)
LOGO_BASE64 = ""

class GitHubCSVDownloader:
    def __init__(self, progress_callback=None, status_callback=None):
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.games = {}

    def log(self, msg):
        if self.status_callback:
            self.status_callback(msg)
        print(msg)

    def download_csv_from_github(self):
        """Download the CSV database from K3zter's vmu-save-splitter repository"""
        url = "https://raw.githubusercontent.com/K3zter/vmu-save-splitter/main/game-db.csv"

        self.log("=" * 60)
        self.log("Downloading VMUPro Game Database from GitHub...")
        self.log(f"Source: K3zter/vmu-save-splitter")
        self.log(f"URL: {url}")
        self.log("=" * 60)

        try:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'text/plain, text/csv, */*',
                }
            )

            self.log("Connecting to GitHub...")
            with urllib.request.urlopen(req, context=ssl_context, timeout=30) as response:
                raw_content = response.read()
                self.log(f"Downloaded {len(raw_content)} bytes")

                # Try multiple encodings - the CSV file may not be UTF-8
                encodings = ['utf-8', 'utf-8-sig', 'windows-1252', 'latin-1', 'iso-8859-1']
                content = None

                for encoding in encodings:
                    try:
                        content = raw_content.decode(encoding)
                        self.log(f"Successfully decoded using {encoding} encoding")
                        return content
                    except UnicodeDecodeError:
                        continue

                # If all encodings fail, use latin-1 with errors='replace'
                if content is None:
                    content = raw_content.decode('latin-1', errors='replace')
                    self.log("Using fallback Latin-1 encoding with error replacement")
                    return content

        except Exception as e:
            self.log(f"Error downloading from GitHub: {e}")
            import traceback
            self.log(traceback.format_exc())
            return None

    def parse_csv_content(self, csv_content):
        """Parse CSV file content and extract game information"""
        try:
            self.log("\nParsing CSV database...")

            # Skip the 'sep=;' line if present
            lines = csv_content.strip().split('\n')
            if lines[0].startswith('sep='):
                lines = lines[1:]

            csv_data = '\n'.join(lines)
            reader = csv.DictReader(StringIO(csv_data), delimiter=';')

            count = 0
            for row in reader:
                game_id = row.get('GameID', '').strip()
                title = row.get('Title', '').strip()
                region = row.get('Region', '').strip()
                version = row.get('Version', '').strip()
                languages = row.get('Languages', '').strip()

                if game_id and title:
                    # Remove trailing tildes used for padding in the CSV
                    game_id_clean = game_id.rstrip('~')

                    # Store with clean ID as key
                    if game_id_clean not in self.games:
                        self.games[game_id_clean] = {
                            'gameid': game_id_clean,
                            'title': title,
                            'region': region,
                            'version': version,
                            'languages': languages
                        }
                        count += 1

                    if count % 100 == 0:
                        self.log(f"Parsed {count} unique games...")
                        if self.progress_callback:
                            self.progress_callback(count)

            self.log(f"Total unique games parsed: {count}")
            return count

        except Exception as e:
            self.log(f"Parse error: {e}")
            import traceback
            self.log(traceback.format_exc())
            return 0

    def download_and_parse(self):
        """Download CSV from GitHub and parse it"""
        csv_content = self.download_csv_from_github()

        if not csv_content:
            self.log("\nFailed to download CSV file from GitHub")
            return 0

        count = self.parse_csv_content(csv_content)
        return count

    def save(self, filename='vmupro_gamedb.json'):
        if not self.games:
            return False

        database = {
            'version': 3,
            'last_updated': datetime.now().isoformat(),
            'total_games': len(self.games),
            'games': self.games,
            'source': 'K3zter/vmu-save-splitter'
        }

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(database, f, indent=2, ensure_ascii=False)

        self.log(f"Database saved: {filename}")
        return True

class VMUProApp:
    def __init__(self, root):
        self.root = root
        self.root.title("VMUPro Save Converter v1.0")
        self.root.geometry("1400x800")
        
        # Set window icon if available
        try:
            if os.path.exists('icon.ico'):
                self.root.iconbitmap('icon.ico')
        except:
            pass
        
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        self.redump_db = {}
        self.gid_to_traditional = {}  # Maps GID### to traditional game IDs
        self.source_files = []
        self.dest_files = []
        self.source_folder = tk.StringVar()
        self.output_folder = tk.StringVar()
        self.manual_mappings = {}
        self.hide_unknown = tk.BooleanVar(value=False)
        self.unknown_games = []
        self.reconcile_btn = None
        
        self.load_database()
        self.load_manual_mappings()
        self.create_ui()
    
    def load_database(self):
        # Try local pipe-delimited database first
        if Path('vmupro_gamedb.txt').exists():
            try:
                self.redump_db, self.gid_to_traditional = self.load_pipe_delimited_db('vmupro_gamedb.txt')
                print(f"Loaded {len(self.redump_db)} games from vmupro_gamedb.txt")
                print(f"Created {len(self.gid_to_traditional)} GID mappings")
                return
            except Exception as e:
                print(f"Error loading vmupro_gamedb.txt: {e}")

        # Fall back to JSON databases for compatibility
        db_files = ['vmupro_gamedb.json', 'redump_dreamcast.json']
        for db_file in db_files:
            if Path(db_file).exists():
                try:
                    with open(db_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        self.redump_db = data.get('games', {})
                        self.gid_to_traditional = {}
                        print(f"Loaded {len(self.redump_db)} games from {db_file}")
                        return
                except Exception as e:
                    print(f"Error loading database {db_file}: {e}")

        print("No database file found")
        self.gid_to_traditional = {}

    def load_pipe_delimited_db(self, filename):
        """Load pipe-delimited database and create GID→Traditional ID mappings"""
        games = {}
        gid_map = {}

        with open(filename, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()

                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue

                # Parse: |Region|Title|GameID|Optional|
                parts = line.split('|')
                if len(parts) < 4:
                    continue

                region = parts[1].strip()
                title = parts[2].strip()
                game_id = parts[3].strip()

                if not game_id or not title:
                    continue

                # Store game with all possible IDs
                # For GID entries, we'll map them to traditional IDs later
                if game_id.startswith('GID'):
                    # This is a GID entry - we need to find the corresponding traditional ID
                    # For now, store it with GID as key
                    if game_id not in games:
                        games[game_id] = {
                            'gameid': game_id,
                            'title': title,
                            'region': region
                        }
                else:
                    # This is a traditional game ID - store it normally
                    # Also check if there's a GID entry for this game
                    if game_id not in games:
                        games[game_id] = {
                            'gameid': game_id,
                            'title': title,
                            'region': region
                        }

                    # Check if we have a GID entry with the same title
                    # Create mapping from GID to traditional ID
                    for gid_key, gid_data in list(games.items()):
                        if gid_key.startswith('GID') and gid_data['title'] == title:
                            # Found a match! Map this GID to the traditional ID
                            gid_map[gid_key] = game_id
                            # Also add traditional ID as an alias
                            games[game_id] = {
                                'gameid': game_id,
                                'title': title,
                                'region': region,
                                'gid': gid_key
                            }

        return games, gid_map
    
    def load_manual_mappings(self):
        """Load saved manual game ID mappings"""
        mappings_file = 'manual_mappings.json'
        if Path(mappings_file).exists():
            try:
                with open(mappings_file, 'r', encoding='utf-8') as f:
                    self.manual_mappings = json.load(f)
                    print(f"Loaded {len(self.manual_mappings)} manual mappings")
            except Exception as e:
                print(f"Error loading manual mappings: {e}")
    
    def save_manual_mappings(self):
        """Save manual game ID mappings for future use"""
        mappings_file = 'manual_mappings.json'
        try:
            with open(mappings_file, 'w', encoding='utf-8') as f:
                json.dump(self.manual_mappings, f, indent=2, ensure_ascii=False)
            print(f"Saved {len(self.manual_mappings)} manual mappings")
        except Exception as e:
            print(f"Error saving manual mappings: {e}")
    
    def show_about(self):
        """Show about dialog with credits"""
        about_window = tk.Toplevel(self.root)
        about_window.title("About VMUPro Save Converter")
        about_window.geometry("500x400")
        about_window.resizable(False, False)
        
        frame = ttk.Frame(about_window, padding=20)
        frame.pack(fill='both', expand=True)
        
        ttk.Label(frame, text="VMUPro Save Converter", font=('Arial', 14, 'bold')).pack(pady=10)
        ttk.Label(frame, text="Version 1.0", font=('Arial', 10)).pack(pady=5)
        
        ttk.Separator(frame, orient='horizontal').pack(fill='x', pady=10)
        
        credits_text = """
A Windows tool for bulk converting Dreamcast VM2
save files to VMUPro format with intelligent
game identification.

CREDITS:

• VM2 Hardware: Created by DreamMods
  Modern VMU memory card device for Dreamcast

• VMUPro Hardware: Created by 8bitmods
  Modern VMU memory card device for Dreamcast

• Game Database: K3zter/vmu-save-splitter
  VMUPro-compatible game database
  GitHub: github.com/K3zter/vmu-save-splitter

LICENSE: MIT License

GAME ID DETECTION:

This tool automatically detects game IDs using:
• Folder and file name patterns
• Metadata files (title.txt, etc.)
• Smart hyphen insertion for incomplete IDs
  Examples:
  - T1201N → T-1201N
  - HDR0178 → HDR-0178
  - MK511905 → MK-51190-50
  - 6107390 → 610-7390
        """
        
        text_widget = tk.Text(frame, height=15, width=50, wrap='word', font=('Arial', 9))
        text_widget.insert('1.0', credits_text)
        text_widget.config(state='disabled')
        text_widget.pack(pady=10)
        
        ttk.Button(frame, text="Close", command=about_window.destroy).pack(pady=10)
    
    def create_ui(self):
        # Menu bar
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self.show_about)
        
        main_container = ttk.Frame(self.root)
        main_container.pack(fill='both', expand=True, padx=0, pady=0)
        main_container.columnconfigure(0, weight=1)
        main_container.rowconfigure(0, weight=1)
        
        notebook = ttk.Notebook(main_container)
        notebook.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
        
        self.download_tab = ttk.Frame(notebook)
        notebook.add(self.download_tab, text='Download Database')
        self.download_tab.columnconfigure(0, weight=1)
        self.download_tab.rowconfigure(0, weight=1)
        self.create_download_ui()
        
        self.converter_tab = ttk.Frame(notebook)
        notebook.add(self.converter_tab, text='Convert Saves')
        self.converter_tab.columnconfigure(0, weight=1)
        self.converter_tab.rowconfigure(0, weight=1)
        self.create_converter_ui()
        
        self.browser_tab = ttk.Frame(notebook)
        notebook.add(self.browser_tab, text='Game Browser')
        self.browser_tab.columnconfigure(0, weight=1)
        self.browser_tab.rowconfigure(2, weight=1)
        self.create_browser_ui()
    
    def create_download_ui(self):
        frame = ttk.Frame(self.download_tab)
        frame.grid(row=0, column=0, sticky='nsew', padx=15, pady=15)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(5, weight=1)
        
        title = ttk.Label(frame, text="Download VMUPro Game Database from GitHub", font=('Arial', 12, 'bold'))
        title.grid(row=0, column=0, sticky='w', pady=(0, 5))

        info = ttk.Label(frame, text="Downloads the latest VMUPro-compatible game database from K3zter/vmu-save-splitter")
        info.grid(row=1, column=0, sticky='w', pady=(0, 15))
        
        self.db_status = ttk.Label(frame, text=self.get_db_status())
        self.db_status.grid(row=2, column=0, sticky='w', pady=(0, 15))
        
        button_frame = ttk.Frame(frame)
        button_frame.grid(row=3, column=0, sticky='w', pady=10)
        self.download_btn = ttk.Button(button_frame, text="Download from GitHub", command=self.start_download, width=25)
        self.download_btn.pack(side='left')
        
        self.download_progress = ttk.Progressbar(frame, mode='determinate', maximum=100)
        self.download_progress.grid(row=4, column=0, sticky='ew', pady=10)
        
        text_frame = ttk.LabelFrame(frame, text="Download Log", padding=5)
        text_frame.grid(row=5, column=0, sticky='nsew', pady=10)
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        
        self.download_status_text = scrolledtext.ScrolledText(text_frame, height=15, width=100, font=('Courier', 9))
        self.download_status_text.grid(row=0, column=0, sticky='nsew')
    
    def get_db_status(self):
        if self.redump_db:
            return f"Database loaded: {len(self.redump_db)} games"
        return "No database loaded - Click 'Download from GitHub' to fetch the latest database"
    
    def start_download(self):
        self.download_btn.config(state='disabled')
        self.download_status_text.config(state='normal')
        self.download_status_text.delete('1.0', tk.END)
        self.download_progress.config(value=0)
        
        thread = threading.Thread(target=self.download_worker, daemon=True)
        thread.start()
    
    def download_worker(self):
        downloader = GitHubCSVDownloader(
            progress_callback=self.update_download_progress,
            status_callback=self.append_download_status
        )

        try:
            count = downloader.download_and_parse()
            if count > 0:
                downloader.save('vmupro_gamedb.json')
                self.redump_db = downloader.games
                self.root.after(0, lambda: self.finalize_download(True, count))
            else:
                self.root.after(0, lambda: self.finalize_download(False, 0))
        except Exception as e:
            self.append_download_status(f"Error: {e}")
            import traceback
            self.append_download_status(traceback.format_exc())
            self.root.after(0, lambda: self.finalize_download(False, 0))
    
    def update_download_progress(self, value):
        progress = min((value / 10), 100)
        self.root.after(0, lambda: self.download_progress.config(value=progress))
    
    def append_download_status(self, text):
        def _append():
            self.download_status_text.config(state='normal')
            self.download_status_text.insert(tk.END, text + '\n')
            self.download_status_text.see(tk.END)
            self.download_status_text.update()
        self.root.after(0, _append)
    
    def finalize_download(self, success, count):
        self.download_btn.config(state='normal')
        self.download_progress.config(value=100 if success else 0)
        self.db_status.config(text=self.get_db_status())
        if success:
            messagebox.showinfo("Success", f"Downloaded and parsed {count} games from GitHub!")
            self.refresh_browser()
        else:
            messagebox.showerror("Error", "Failed to download database from GitHub.\n\nCheck your internet connection and try again.")
    
    def create_converter_ui(self):
        main_frame = ttk.Frame(self.converter_tab)
        main_frame.grid(row=0, column=0, sticky='nsew', padx=10, pady=10)
        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(3, weight=1)
        
        title = ttk.Label(main_frame, text="Bulk VM2 to VMUPro Save Converter", font=('Arial', 12, 'bold'))
        title.grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 0))
        
        info = ttk.Label(main_frame, text="Converts .vmu files only (ignores .bin and other files)", foreground='gray', font=('Arial', 9))
        info.grid(row=1, column=0, columnspan=2, sticky='w', pady=(2, 10))
        
        folder_frame = ttk.Frame(main_frame)
        folder_frame.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(0, 10))
        folder_frame.columnconfigure(1, weight=1)
        
        ttk.Label(folder_frame, text="Source:", font=('Arial', 10, 'bold')).grid(row=0, column=0, sticky='w', padx=(0, 5))
        self.source_display = ttk.Label(folder_frame, text="No folder selected", foreground='orange')
        self.source_display.grid(row=0, column=1, sticky='w', padx=(0, 10))
        ttk.Button(folder_frame, text="Browse Source", command=self.select_source).grid(row=0, column=2, padx=5)
        
        ttk.Label(folder_frame, text="Output:", font=('Arial', 10, 'bold')).grid(row=1, column=0, sticky='w', padx=(0, 5), pady=(5, 0))
        self.output_display = ttk.Label(folder_frame, text="No folder selected", foreground='orange')
        self.output_display.grid(row=1, column=1, sticky='w', padx=(0, 10), pady=(5, 0))
        ttk.Button(folder_frame, text="Browse Output", command=self.select_output).grid(row=1, column=2, padx=5, pady=(5, 0))
        
        source_frame = ttk.LabelFrame(main_frame, text="Source Files (VM2 .vmu files only)", padding=5)
        source_frame.grid(row=3, column=0, sticky='nsew', padx=(0, 5))
        source_frame.columnconfigure(0, weight=1)
        source_frame.rowconfigure(1, weight=1)
        
        source_btn_frame = ttk.Frame(source_frame)
        source_btn_frame.grid(row=0, column=0, sticky='ew', pady=(0, 5))
        ttk.Button(source_btn_frame, text="Refresh", command=self.scan_source_files).pack(side='left', padx=(0, 5))
        ttk.Button(source_btn_frame, text="Select All", command=self.select_all_source).pack(side='left', padx=(0, 5))
        ttk.Button(source_btn_frame, text="Deselect All", command=self.deselect_all_source).pack(side='left', padx=(0, 5))
        self.reconcile_btn = ttk.Button(source_btn_frame, text="Reconcile Unknown Games", 
                                       command=self.start_batch_reconciliation, state='disabled')
        self.reconcile_btn.pack(side='left', padx=(5, 0))
        ttk.Checkbutton(source_btn_frame, text="Hide Unknown", variable=self.hide_unknown, 
                       command=self.toggle_hide_unknown).pack(side='left', padx=(5, 0))
        
        source_tree_frame = ttk.Frame(source_frame)
        source_tree_frame.grid(row=1, column=0, sticky='nsew')
        source_tree_frame.columnconfigure(0, weight=1)
        source_tree_frame.rowconfigure(0, weight=1)
        
        self.source_tree = ttk.Treeview(source_tree_frame, columns=('Game', 'Region', 'Files', 'Status'), 
                                       show='tree headings', selectmode='extended')
        self.source_tree.heading('#0', text='Game ID / File')
        self.source_tree.heading('Game', text='Game Title')
        self.source_tree.heading('Region', text='Region')
        self.source_tree.heading('Files', text='Info')
        self.source_tree.heading('Status', text='Status')
        self.source_tree.column('#0', width=180)
        self.source_tree.column('Game', width=220)
        self.source_tree.column('Region', width=70)
        self.source_tree.column('Files', width=80)
        self.source_tree.column('Status', width=100)
        
        self.source_tree.bind('<Button-3>', self.show_context_menu)
        self.source_tree.bind('<Double-1>', self.on_double_click)
        
        source_scroll = ttk.Scrollbar(source_tree_frame, orient='vertical', command=self.source_tree.yview)
        self.source_tree.configure(yscrollcommand=source_scroll.set)
        self.source_tree.grid(row=0, column=0, sticky='nsew')
        source_scroll.grid(row=0, column=1, sticky='ns')
        
        dest_frame = ttk.LabelFrame(main_frame, text="Destination Files (VMUPro)", padding=5)
        dest_frame.grid(row=3, column=1, sticky='nsew', padx=(5, 0))
        dest_frame.columnconfigure(0, weight=1)
        dest_frame.rowconfigure(1, weight=1)
        
        dest_btn_frame = ttk.Frame(dest_frame)
        dest_btn_frame.grid(row=0, column=0, sticky='ew', pady=(0, 5))
        ttk.Button(dest_btn_frame, text="Refresh", command=self.scan_dest_files).pack(side='left', padx=(0, 5))
        ttk.Button(dest_btn_frame, text="Open Folder", command=self.open_dest_folder).pack(side='left')
        
        dest_tree_frame = ttk.Frame(dest_frame)
        dest_tree_frame.grid(row=1, column=0, sticky='nsew')
        dest_tree_frame.columnconfigure(0, weight=1)
        dest_tree_frame.rowconfigure(0, weight=1)
        
        self.dest_tree = ttk.Treeview(dest_tree_frame, columns=('Game', 'Region', 'Files'), show='tree headings')
        self.dest_tree.heading('#0', text='Game ID / File')
        self.dest_tree.heading('Game', text='Game Title')
        self.dest_tree.heading('Region', text='Region')
        self.dest_tree.heading('Files', text='Size')
        self.dest_tree.column('#0', width=200)
        self.dest_tree.column('Game', width=250)
        self.dest_tree.column('Region', width=80)
        self.dest_tree.column('Files', width=80)
        
        dest_scroll = ttk.Scrollbar(dest_tree_frame, orient='vertical', command=self.dest_tree.yview)
        self.dest_tree.configure(yscrollcommand=dest_scroll.set)
        self.dest_tree.grid(row=0, column=0, sticky='nsew')
        dest_scroll.grid(row=0, column=1, sticky='ns')
        
        convert_frame = ttk.Frame(main_frame)
        convert_frame.grid(row=4, column=0, columnspan=2, sticky='ew', pady=(10, 0))
        self.convert_btn = ttk.Button(convert_frame, text="Convert Selected Files", command=self.start_conversion)
        self.convert_btn.pack(side='left', padx=(0, 10))
        self.status_label = ttk.Label(convert_frame, text="Ready")
        self.status_label.pack(side='left')
    
    def on_double_click(self, event):
        """Handle double-click to manually set game ID"""
        item = self.source_tree.identify_row(event.y)
        if not item:
            return
        
        tags = self.source_tree.item(item, 'tags')
        if 'game' in tags:
            game_id = self.source_tree.item(item, 'text')
            if game_id == 'UNKNOWN' or 'unknown_' in game_id:
                self.manual_set_game_id_with_search(item, game_id)
    
    def show_context_menu(self, event):
        item = self.source_tree.identify_row(event.y)
        if not item:
            return
        
        tags = self.source_tree.item(item, 'tags')
        if 'game' not in tags:
            return
        
        game_id = self.source_tree.item(item, 'text')
        
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Manually Set Game ID", command=lambda: self.manual_set_game_id_with_search(item, game_id))
        menu.add_command(label="Search Database", command=lambda: self.search_similar_games(item, game_id))
        menu.post(event.x_root, event.y_root)
    
    def start_batch_reconciliation(self):
        """Start batch reconciliation wizard for all unknown games"""
        if not hasattr(self, 'unknown_games') or not self.unknown_games:
            messagebox.showinfo("No Unknown Games", "All games have been identified!")
            return
        
        dialog = tk.Toplevel(self.root)
        dialog.title("Batch Game Reconciliation Wizard")
        dialog.geometry("900x700")
        dialog.resizable(True, True)
        
        # Make dialog modal
        dialog.transient(self.root)
        dialog.grab_set()
        
        # State variables
        current_index = [0]  # Use list to make it mutable in nested functions
        mappings = {}  # Store all mappings
        
        main_frame = ttk.Frame(dialog, padding=10)
        main_frame.pack(fill='both', expand=True)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(2, weight=1)
        
        # Progress header
        progress_frame = ttk.Frame(main_frame)
        progress_frame.grid(row=0, column=0, sticky='ew', pady=(0, 10))
        
        progress_label = ttk.Label(progress_frame, text="", font=('Arial', 11, 'bold'))
        progress_label.pack(side='left')
        
        progress_bar = ttk.Progressbar(progress_frame, mode='determinate', maximum=len(self.unknown_games))
        progress_bar.pack(side='right', fill='x', expand=True, padx=(10, 0))
        
        # Info frame - shows current unknown game info
        info_frame = ttk.LabelFrame(main_frame, text="Current Unknown Game", padding=10)
        info_frame.grid(row=1, column=0, sticky='ew', pady=(0, 10))
        info_frame.columnconfigure(1, weight=1)
        
        folder_label = ttk.Label(info_frame, text="Folder:", font=('Arial', 9, 'bold'))
        folder_label.grid(row=0, column=0, sticky='w', padx=(0, 10))
        folder_value = ttk.Label(info_frame, text="", foreground='blue')
        folder_value.grid(row=0, column=1, sticky='w')
        
        files_label = ttk.Label(info_frame, text="Files:", font=('Arial', 9, 'bold'))
        files_label.grid(row=1, column=0, sticky='w', padx=(0, 10), pady=(5, 0))
        files_value = ttk.Label(info_frame, text="")
        files_value.grid(row=1, column=1, sticky='w', pady=(5, 0))
        
        path_label = ttk.Label(info_frame, text="Location:", font=('Arial', 9, 'bold'))
        path_label.grid(row=2, column=0, sticky='w', padx=(0, 10), pady=(5, 0))
        path_value = ttk.Label(info_frame, text="", foreground='gray')
        path_value.grid(row=2, column=1, sticky='w', pady=(5, 0))
        
        # Auto-suggest frame
        suggest_frame = ttk.Frame(info_frame)
        suggest_frame.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(10, 0))
        
        suggest_label = ttk.Label(suggest_frame, text="Auto-suggestion:", font=('Arial', 9, 'bold'))
        suggest_label.pack(side='left', padx=(0, 10))
        
        suggest_button = ttk.Button(suggest_frame, text="Search based on folder name", 
                                    command=lambda: auto_search_folder())
        suggest_button.pack(side='left')
        
        # Search and select frame
        select_frame = ttk.LabelFrame(main_frame, text="Select Correct Game from Database", padding=10)
        select_frame.grid(row=2, column=0, sticky='nsew', pady=(0, 10))
        select_frame.columnconfigure(0, weight=1)
        select_frame.rowconfigure(1, weight=1)
        
        # Search box
        search_frame = ttk.Frame(select_frame)
        search_frame.grid(row=0, column=0, sticky='ew', pady=(0, 10))
        search_frame.columnconfigure(1, weight=1)
        
        ttk.Label(search_frame, text="Search:", font=('Arial', 9, 'bold')).grid(row=0, column=0, padx=(0, 10))
        search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=search_var, font=('Arial', 10))
        search_entry.grid(row=0, column=1, sticky='ew', padx=(0, 10))
        
        clear_btn = ttk.Button(search_frame, text="Clear", width=8, 
                              command=lambda: search_var.set(''))
        clear_btn.grid(row=0, column=2)
        
        # Game list
        list_frame = ttk.Frame(select_frame)
        list_frame.grid(row=1, column=0, sticky='nsew')
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side='right', fill='y')
        
        game_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, 
                                  font=('Courier', 9), height=15)
        game_listbox.pack(side='left', fill='both', expand=True)
        scrollbar.config(command=game_listbox.yview)
        
        # Store all games for filtering
        all_games = []
        for game_id, info in sorted(self.redump_db.items()):
            all_games.append((game_id, info['title'], info['region']))
            game_listbox.insert(tk.END, f"{game_id:<15} | {info['title']:<50} | {info['region']}")
        
        def calculate_match_score(search_terms, game_id, title, region):
            """Calculate relevance score for fuzzy matching with better prioritization"""
            score = 0
            search_lower = search_terms.lower().strip()
            game_id_lower = game_id.lower()
            title_lower = title.lower()
            region_lower = region.lower()
            
            # Exact matches get highest score
            if search_lower == game_id_lower:
                return 10000
            if search_lower == title_lower:
                return 9000
            
            # Game ID starts with search (very high priority)
            if game_id_lower.startswith(search_lower):
                return 8000
            
            # Title starts with search (very high priority)
            if title_lower.startswith(search_lower):
                return 7000
            
            # Search is contained in game ID (high priority)
            if search_lower in game_id_lower:
                score += 5000
            
            # Search is contained in title (high priority)
            if search_lower in title_lower:
                score += 4000
            
            # Region exact match
            if search_lower == region_lower:
                score += 3000
            
            # Word-by-word matching
            search_words = [w for w in search_lower.split() if len(w) > 2]
            title_words = title_lower.split()
            
            if search_words:
                # Count exact word matches
                exact_word_matches = 0
                for search_word in search_words:
                    if search_word in title_words:
                        exact_word_matches += 1
                        score += 500
                
                # Bonus if ALL search words are found
                if exact_word_matches == len(search_words):
                    score += 2000
                
                # Partial word matching
                for search_word in search_words:
                    for title_word in title_words:
                        if len(search_word) >= 3:
                            if title_word.startswith(search_word):
                                score += 200
                            elif search_word in title_word:
                                score += 100
            
            # Penalize very long titles if search is short (probably not what user wants)
            if len(search_lower) < 10 and len(title) > 50:
                score -= 500
            
            return max(0, score)
        
        def filter_games(*args):
            """Filter and sort game list based on search with fuzzy matching"""
            search = search_var.get().strip()
            game_listbox.delete(0, tk.END)
            
            if not search:
                # No search - show all games
                for game_id, title, region in all_games:
                    game_listbox.insert(tk.END, f"{game_id:<15} | {title:<50} | {region}")
                return
            
            # Calculate scores for all games
            scored_games = []
            
            for game_id, title, region in all_games:
                score = calculate_match_score(search, game_id, title, region)
                
                if score > 0:
                    scored_games.append((score, game_id, title, region))
            
            # Sort by score (highest first)
            scored_games.sort(reverse=True, key=lambda x: x[0])
            
            # Show top matches (limit to reasonable number for performance)
            for score, game_id, title, region in scored_games[:200]:
                game_listbox.insert(tk.END, f"{game_id:<15} | {title:<50} | {region}")
            
            if not scored_games:
                game_listbox.insert(tk.END, "No matches found - try different search terms")
        
        search_var.trace('w', filter_games)
        
        def auto_search_folder():
            """Auto-populate search based on folder name"""
            if current_index[0] < len(self.unknown_games):
                unknown_id = self.unknown_games[current_index[0]]
                # Extract folder name from unknown_id
                parts = unknown_id.split('_')
                if len(parts) >= 2:
                    folder_name = parts[1]
                    # Clean up folder name for better search
                    clean_name = re.sub(r'[^a-zA-Z0-9\s]', ' ', folder_name)
                    search_var.set(clean_name)
                    search_entry.focus()
        
        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=3, column=0, sticky='ew')
        
        skip_btn = ttk.Button(button_frame, text="Skip This Game", width=20)
        skip_btn.pack(side='left', padx=(0, 5))
        
        skip_all_btn = ttk.Button(button_frame, text="Skip All Remaining", width=20)
        skip_all_btn.pack(side='left', padx=(0, 5))
        
        confirm_btn = ttk.Button(button_frame, text="Confirm Selection", width=20)
        confirm_btn.pack(side='right', padx=(5, 0))
        
        finish_btn = ttk.Button(button_frame, text="Finish & Apply All", width=20)
        finish_btn.pack(side='right', padx=(5, 0))
        
        def update_display():
            """Update dialog to show current unknown game"""
            if current_index[0] >= len(self.unknown_games):
                # All done!
                apply_mappings()
                return
            
            unknown_id = self.unknown_games[current_index[0]]
            
            # Update progress
            progress_label.config(text=f"Game {current_index[0] + 1} of {len(self.unknown_games)}")
            progress_bar.config(value=current_index[0])
            
            # Find files for this unknown game
            files = [f for _, gid, f in self.source_files if gid == unknown_id]
            
            if files:
                folder_name = os.path.basename(files[0]['source_folder'])
                folder_value.config(text=folder_name)
                files_value.config(text=f"{len(files)} file(s): {', '.join([f['filename'] for f in files[:3]])}" + 
                                       ("..." if len(files) > 3 else ""))
                path_value.config(text=files[0]['source_folder'])
            
            # Clear search and selection
            search_var.set('')
            game_listbox.selection_clear(0, tk.END)
            search_entry.focus()
        
        def skip_current():
            """Skip current game and move to next"""
            current_index[0] += 1
            if current_index[0] >= len(self.unknown_games):
                apply_mappings()
            else:
                update_display()
        
        def skip_all_remaining():
            """Skip all remaining games"""
            result = messagebox.askyesno("Skip Remaining", 
                                        f"Skip the remaining {len(self.unknown_games) - current_index[0]} games?\n\n"
                                        "You can reconcile them later by clicking the 'Reconcile Unknown Games' button again.",
                                        parent=dialog)
            if result:
                apply_mappings()
        
        def confirm_selection():
            """Confirm the selected game for current unknown"""
            selection = game_listbox.curselection()
            if not selection:
                messagebox.showwarning("No Selection", "Please select a game from the list.", parent=dialog)
                return
            
            selected_text = game_listbox.get(selection[0])
            selected_id = selected_text.split('|')[0].strip()
            
            unknown_id = self.unknown_games[current_index[0]]
            mappings[unknown_id] = selected_id
            
            # Move to next
            current_index[0] += 1
            if current_index[0] >= len(self.unknown_games):
                apply_mappings()
            else:
                update_display()
        
        def apply_mappings():
            """Apply all mappings and close dialog"""
            if mappings:
                for unknown_id, game_id in mappings.items():
                    self.manual_mappings[unknown_id] = game_id
                
                self.save_manual_mappings()
                dialog.destroy()
                messagebox.showinfo("Success", 
                                   f"Reconciled {len(mappings)} game(s)!\n\n"
                                   "Refreshing file list...",
                                   parent=self.root)
                self.scan_source_files()
            else:
                dialog.destroy()
        
        def on_listbox_double_click(event):
            """Handle double-click on listbox"""
            confirm_selection()
        
        # Bind buttons
        skip_btn.config(command=skip_current)
        skip_all_btn.config(command=skip_all_remaining)
        confirm_btn.config(command=confirm_selection)
        finish_btn.config(command=apply_mappings)
        game_listbox.bind('<Double-Button-1>', on_listbox_double_click)
        
        # Handle dialog close
        def on_closing():
            if mappings:
                result = messagebox.askyesno("Unsaved Changes", 
                                           f"You have {len(mappings)} game(s) mapped.\n\n"
                                           "Apply these changes before closing?",
                                           parent=dialog)
                if result:
                    apply_mappings()
                    return
            dialog.destroy()
        
        dialog.protocol("WM_DELETE_WINDOW", on_closing)
        
        # Start with first unknown game
        update_display()
    
    def manual_set_game_id_with_search(self, tree_item, current_id):
        """Enhanced manual game ID setting with database browser"""
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Set Game ID for: {current_id}")
        dialog.geometry("800x600")
        
        frame = ttk.Frame(dialog, padding=10)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)
        
        ttk.Label(frame, text=f"Select game for: {current_id}", font=('Arial', 11, 'bold')).grid(row=0, column=0, sticky='w', pady=(0, 10))
        
        search_frame = ttk.Frame(frame)
        search_frame.grid(row=1, column=0, sticky='ew', pady=(0, 10))
        search_frame.columnconfigure(1, weight=1)
        
        ttk.Label(search_frame, text="Search:").grid(row=0, column=0, padx=(0, 5))
        search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=search_var)
        search_entry.grid(row=0, column=1, sticky='ew')
        
        list_frame = ttk.Frame(frame)
        list_frame.grid(row=2, column=0, sticky='nsew')
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side='right', fill='y')
        
        listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, font=('Courier', 9))
        listbox.pack(side='left', fill='both', expand=True)
        scrollbar.config(command=listbox.yview)
        
        games_list = []
        for game_id, info in sorted(self.redump_db.items()):
            games_list.append((game_id, info['title'], info['region']))
            listbox.insert(tk.END, f"{game_id}  |  {info['title']}  ({info['region']})")
        
        def calculate_match_score(search_terms, game_id, title, region):
            """Calculate relevance score for fuzzy matching"""
            score = 0
            search_lower = search_terms.lower().strip()
            game_id_lower = game_id.lower()
            title_lower = title.lower()
            region_lower = region.lower()
            
            if search_lower == game_id_lower:
                return 10000
            if search_lower == title_lower:
                return 9000
            
            if game_id_lower.startswith(search_lower):
                return 8000
            
            if title_lower.startswith(search_lower):
                return 7000
            
            if search_lower in game_id_lower:
                score += 5000
            
            if search_lower in title_lower:
                score += 4000
            
            if search_lower == region_lower:
                score += 3000
            
            search_words = [w for w in search_lower.split() if len(w) > 2]
            title_words = title_lower.split()
            
            if search_words:
                exact_word_matches = 0
                for search_word in search_words:
                    if search_word in title_words:
                        exact_word_matches += 1
                        score += 500
                
                if exact_word_matches == len(search_words):
                    score += 2000
                
                for search_word in search_words:
                    for title_word in title_words:
                        if len(search_word) >= 3:
                            if title_word.startswith(search_word):
                                score += 200
                            elif search_word in title_word:
                                score += 100
            
            if len(search_lower) < 10 and len(title) > 50:
                score -= 500
            
            return max(0, score)
        
        def filter_games(*args):
            search = search_var.get().strip()
            listbox.delete(0, tk.END)
            
            if not search:
                for game_id, title, region in games_list:
                    listbox.insert(tk.END, f"{game_id}  |  {title}  ({region})")
                return
            
            scored_games = []
            
            for game_id, title, region in games_list:
                score = calculate_match_score(search, game_id, title, region)
                
                if score > 0:
                    scored_games.append((score, game_id, title, region))
            
            scored_games.sort(reverse=True, key=lambda x: x[0])
            
            for score, game_id, title, region in scored_games[:200]:
                listbox.insert(tk.END, f"{game_id}  |  {title}  ({region})")
            
            if not scored_games:
                listbox.insert(tk.END, "No matches found - try different search terms")
        
        search_var.trace('w', filter_games)
        
        def on_select():
            selection = listbox.curselection()
            if selection:
                selected_text = listbox.get(selection[0])
                selected_id = selected_text.split('|')[0].strip()
                
                # Map all files from this source to the new game ID
                for i, (path, gid, finfo) in enumerate(self.source_files):
                    if gid == current_id:
                        self.manual_mappings[current_id] = selected_id
                
                self.save_manual_mappings()
                messagebox.showinfo("Success", f"Mapped '{current_id}' → '{selected_id}'")
                dialog.destroy()
                self.scan_source_files()
        
        button_frame = ttk.Frame(frame)
        button_frame.grid(row=3, column=0, sticky='ew', pady=(10, 0))
        ttk.Button(button_frame, text="Confirm Selection", command=on_select).pack(side='left', padx=(0, 5))
        ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side='left')
        
        search_entry.focus()
    
    def manual_set_game_id(self, tree_item, current_id):
        new_id = simpledialog.askstring("Manual Game ID", 
                                        f"Enter correct Game ID for '{current_id}':",
                                        initialvalue=current_id)
        if new_id and new_id != current_id:
            self.manual_mappings[current_id] = new_id
            self.save_manual_mappings()
            self.scan_source_files()
    
    def search_similar_games(self, tree_item, game_id):
        matches = []
        search_pattern = re.sub(r'[^A-Z0-9]', '', game_id.upper())
        
        for db_id, info in self.redump_db.items():
            db_pattern = re.sub(r'[^A-Z0-9]', '', db_id.upper())
            if search_pattern in db_pattern or db_pattern in search_pattern:
                matches.append((db_id, info['title'], info['region']))
        
        if not matches:
            messagebox.showinfo("No Matches", f"No similar games found for '{game_id}'")
            return
        
        dialog = tk.Toplevel(self.root)
        dialog.title("Select Matching Game")
        dialog.geometry("700x400")
        
        ttk.Label(dialog, text=f"Select the correct game for '{game_id}':", 
                 font=('Arial', 10, 'bold')).pack(pady=10, padx=10)
        
        listbox_frame = ttk.Frame(dialog)
        listbox_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        scrollbar = ttk.Scrollbar(listbox_frame)
        scrollbar.pack(side='right', fill='y')
        
        listbox = tk.Listbox(listbox_frame, yscrollcommand=scrollbar.set, font=('Courier', 9))
        listbox.pack(side='left', fill='both', expand=True)
        scrollbar.config(command=listbox.yview)
        
        for match_id, title, region in matches:
            listbox.insert(tk.END, f"{match_id}  |  {title}  ({region})")
        
        def on_select():
            selection = listbox.curselection()
            if selection:
                selected_id = matches[selection[0]][0]
                self.manual_mappings[game_id] = selected_id
                self.save_manual_mappings()
                messagebox.showinfo("Success", f"Mapped '{game_id}' → '{selected_id}'")
                dialog.destroy()
                self.scan_source_files()
        
        ttk.Button(dialog, text="Confirm Selection", command=on_select).pack(pady=10)
    
    def toggle_hide_unknown(self):
        self.scan_source_files()
    
    def select_source(self):
        folder = filedialog.askdirectory(title="Select VM2 Source Folder")
        if folder:
            self.source_folder.set(folder)
            self.source_display.config(text=f"Selected: {folder}", foreground='green')
            self.scan_source_files()
    
    def select_output(self):
        folder = filedialog.askdirectory(title="Select Output Folder")
        if folder:
            self.output_folder.set(folder)
            self.output_display.config(text=f"Selected: {folder}", foreground='green')
            self.scan_dest_files()
    
    def read_text_file(self, filepath):
        """Read text file with multiple encoding attempts and special handling for Dreamcast files"""
        # Try UTF-16 variants first (common in Dreamcast saves)
        utf16_encodings = [
            'utf-16-le',  # UTF-16 Little Endian (most common for Dreamcast)
            'utf-16-be',  # UTF-16 Big Endian
            'utf-16',     # UTF-16 with BOM detection
        ]
        
        # Then try other common encodings
        other_encodings = [
            'utf-8',
            'shift_jis',   # Japanese
            'euc-jp',      # Japanese
            'iso-2022-jp', # Japanese
            'cp932',       # Japanese Windows
            'latin1',
            'cp1252',      # Windows Western European
        ]
        
        all_encodings = utf16_encodings + other_encodings
        
        for encoding in all_encodings:
            try:
                with open(filepath, 'r', encoding=encoding, errors='ignore') as f:
                    content = f.read()
                    # Check if content is meaningful (has printable characters)
                    if content:
                        # Remove null bytes and control characters that might interfere
                        content = ''.join(char for char in content if char.isprintable() or char in '\n\r\t ')
                        content = content.strip()
                        
                        # Check if we have actual readable content
                        if len(content) > 0:
                            # For UTF-16, sometimes we get the BOM as first char, remove it
                            if content.startswith('\ufeff'):
                                content = content[1:]
                            
                            # Verify we have some alphanumeric content
                            if any(c.isalnum() for c in content):
                                return content, encoding
            except:
                continue
        
        # If all encoding attempts fail, try reading as raw bytes and look for patterns
        try:
            with open(filepath, 'rb') as f:
                raw_bytes = f.read()
                
                # Try to detect UTF-16 by looking for null bytes pattern
                if b'\x00' in raw_bytes:
                    # Likely UTF-16, try both byte orders
                    for encoding in ['utf-16-le', 'utf-16-be']:
                        try:
                            content = raw_bytes.decode(encoding, errors='ignore')
                            content = ''.join(char for char in content if char.isprintable() or char in '\n\r\t ')
                            content = content.strip()
                            if content and any(c.isalnum() for c in content):
                                return content, encoding
                        except:
                            continue
        except:
            pass
        
        return None, None
    
    def analyze_folder_metadata(self, folder_path):
        """Analyze folder for metadata files that might contain game information"""
        metadata = {
            'game_hints': [],
            'serial_hints': [],
            'title_hints': []
        }
        
        try:
            for file in os.listdir(folder_path):
                filepath = os.path.join(folder_path, file)
                if not os.path.isfile(filepath):
                    continue
                
                filename_lower = file.lower()
                
                # Check for title files (title.txt, TITLE.TXT, etc.)
                if filename_lower in ['title.txt', 'title', 'game.txt', 'gamename.txt']:
                    content, encoding = self.read_text_file(filepath)
                    if content:
                        # Clean up the content
                        lines = content.split('\n')
                        for line in lines:
                            clean_line = line.strip()
                            # Look for game title (usually first line or lines with substantial text)
                            if len(clean_line) >= 3 and len(clean_line) < 150:
                                # Remove common noise
                                clean_line = re.sub(r'[^\w\s\-:&!?\']', ' ', clean_line)
                                clean_line = ' '.join(clean_line.split())  # Normalize whitespace
                                
                                if clean_line:
                                    metadata['title_hints'].append(clean_line)
                        
                        # Also look for serial numbers in title file
                        serials = re.findall(r'\b([A-Z]{1,3}-\d{4,5}(?:-\d{2})?)\b', content)
                        metadata['serial_hints'].extend(serials)
                
                # Check for other text files that might have game info
                elif filename_lower.endswith('.txt'):
                    content, encoding = self.read_text_file(filepath)
                    if content:
                        # Look for serial numbers
                        serials = re.findall(r'\b([A-Z]{1,3}-\d{4,5}(?:-\d{2})?)\b', content)
                        metadata['serial_hints'].extend(serials)
                        
                        # Get first few meaningful lines as title hints
                        lines = content.split('\n')
                        for line in lines[:5]:
                            clean_line = line.strip()
                            if 5 < len(clean_line) < 100:
                                clean_line = re.sub(r'[^\w\s\-:&!?\']', ' ', clean_line)
                                clean_line = ' '.join(clean_line.split())
                                if clean_line:
                                    metadata['title_hints'].append(clean_line)
                
                # Check for .dat files
                elif filename_lower.endswith('.dat'):
                    content, encoding = self.read_text_file(filepath)
                    if content:
                        serials = re.findall(r'\b([A-Z]{1,3}-\d{4,5}(?:-\d{2})?)\b', content)
                        metadata['serial_hints'].extend(serials)
        
        except Exception as e:
            print(f"Error analyzing folder metadata: {e}")
        
        return metadata
    
    def intelligent_game_id_detection(self, folder_path, filename):
        """Intelligently detect game ID from multiple sources"""
        detected_id = None
        confidence = "LOW"
        source = ""
        
        # First try: Extract from path (folder names often have game IDs)
        path_id = self.extract_game_id(folder_path)
        if path_id != 'UNKNOWN':
            detected_id = path_id
            confidence = "HIGH"
            source = "Path"
            # Early return for high confidence matches
            if detected_id in self.manual_mappings:
                return self.manual_mappings[detected_id], "MANUAL", "User Confirmed"
            return detected_id, confidence, source
        
        # Second try: Extract from filename
        file_id = self.extract_game_id(filename)
        if file_id != 'UNKNOWN':
            detected_id = file_id
            confidence = "HIGH"
            source = "Filename"
            if detected_id in self.manual_mappings:
                return self.manual_mappings[detected_id], "MANUAL", "User Confirmed"
            return detected_id, confidence, source
        
        # Third try: Analyze metadata files in folder
        metadata = self.analyze_folder_metadata(folder_path)
        
        # Check serial hints from metadata
        if metadata['serial_hints']:
            for hint in metadata['serial_hints']:
                # Try the hint directly
                if hint in self.redump_db:
                    detected_id = hint
                    confidence = "HIGH"
                    source = "Metadata File"
                    if detected_id in self.manual_mappings:
                        return self.manual_mappings[detected_id], "MANUAL", "User Confirmed"
                    return detected_id, confidence, source
                
                # Try to normalize the hint (add/remove hyphens)
                normalized = self.extract_game_id(hint)
                if normalized != 'UNKNOWN' and normalized in self.redump_db:
                    detected_id = normalized
                    confidence = "HIGH"
                    source = "Metadata File"
                    if detected_id in self.manual_mappings:
                        return self.manual_mappings[detected_id], "MANUAL", "User Confirmed"
                    return detected_id, confidence, source
        
        # Fourth try: Match title hints against database
        if metadata['title_hints']:
            best_match_score = 0
            best_match_id = None
            
            for title_hint in metadata['title_hints']:
                # Search through database for title matches
                for game_id, game_info in self.redump_db.items():
                    db_title = game_info['title'].lower()
                    hint_lower = title_hint.lower()
                    
                    # Calculate similarity score
                    score = 0
                    
                    # Exact match
                    if hint_lower == db_title:
                        score = 1000
                    # Title hint is contained in database title
                    elif hint_lower in db_title:
                        score = 800
                    # Database title is contained in hint
                    elif db_title in hint_lower:
                        score = 700
                    else:
                        # Check for word matches
                        hint_words = set(hint_lower.split())
                        title_words = set(db_title.split())
                        common_words = hint_words & title_words
                        
                        # Remove common words that don't help
                        common_words = {w for w in common_words if len(w) > 3 and w not in ['the', 'and', 'for']}
                        
                        if len(common_words) > 0:
                            score = len(common_words) * 100
                    
                    if score > best_match_score:
                        best_match_score = score
                        best_match_id = game_id
            
            # If we found a decent match
            if best_match_score >= 500:  # Threshold for accepting title matches
                detected_id = best_match_id
                confidence = "MEDIUM"
                source = "Title Match"
                if detected_id in self.manual_mappings:
                    return self.manual_mappings[detected_id], "MANUAL", "User Confirmed"
                return detected_id, confidence, source
        
        # Check manual mappings one final time
        if detected_id and detected_id in self.manual_mappings:
            detected_id = self.manual_mappings[detected_id]
            confidence = "MANUAL"
            source = "User Confirmed"
        
        return detected_id if detected_id else 'UNKNOWN', confidence, source
    
    def scan_source_files(self):
        folder = self.source_folder.get()
        if not folder:
            messagebox.showwarning("No Folder", "Please select a source folder first")
            return
        
        for item in self.source_tree.get_children():
            self.source_tree.delete(item)
        
        self.source_files = []
        game_files = {}
        unknown_by_folder = {}
        
        for root, dirs, files in os.walk(folder):
            for file in files:
                # Only process .vmu files (VM2 format)
                # Ignore .bin, .dci and other files
                if not file.lower().endswith('.vmu'):
                    continue
                
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, folder)
                
                game_id, confidence, source = self.intelligent_game_id_detection(root, file)
                
                # For unknown files, group by source folder first
                if game_id == 'UNKNOWN':
                    folder_name = os.path.basename(root)
                    unique_key = f"unknown_{folder_name}_{root}"
                    game_id = unique_key
                    
                    if unique_key not in unknown_by_folder:
                        unknown_by_folder[unique_key] = {
                            'folder_name': folder_name,
                            'full_path': root,
                            'rel_path': os.path.relpath(root, folder)
                        }
                
                # NOW check manual mappings (after unique_key is created)
                if game_id in self.manual_mappings:
                    game_id = self.manual_mappings[game_id]
                    confidence = "MANUAL"
                    source = "User Set"
                
                file_size = os.path.getsize(full_path)
                
                file_info = {
                    'filename': file,
                    'full_path': full_path,
                    'rel_path': rel_path,
                    'size': file_size,
                    'game_id': game_id,
                    'confidence': confidence,
                    'detection_source': source,
                    'source_folder': root
                }
                
                self.source_files.append((full_path, game_id, file_info))
                
                if game_id not in game_files:
                    game_files[game_id] = []
                game_files[game_id].append(file_info)
        
        for game_id in sorted(game_files.keys()):
            if self.hide_unknown.get() and 'unknown_' in game_id:
                continue
            
            files = game_files[game_id]
            
            # Check if this is an unknown group
            if 'unknown_' in game_id:
                folder_info = unknown_by_folder.get(game_id, {})
                title = f"Unknown - {folder_info.get('folder_name', 'Unknown Folder')}"
                region = '?'
                status_text = f"UNMATCHED - {folder_info.get('rel_path', '')}"
            else:
                info = self.redump_db.get(game_id, {})
                title = info.get('title', 'Unknown Game')
                region = info.get('region', '?')
                
                confidence = files[0]['confidence'] if files else 'UNKNOWN'
                
                if confidence == 'MANUAL':
                    status_text = "User Set"
                elif confidence == 'HIGH':
                    status_text = "Verified"
                else:
                    status_text = f"{confidence}"
            
            game_node = self.source_tree.insert('', 'end', text=game_id, 
                                                values=(title, region, f"{len(files)} files", status_text),
                                                tags=('game',))
            
            for file_info in files:
                size_str = f"{file_info['size'] / 1024:.1f} KB"
                source_str = file_info['detection_source']
                self.source_tree.insert(game_node, 'end', text=file_info['filename'],
                                       values=('', '', size_str, source_str),
                                       tags=('file',))
        
        matched = len([g for g in game_files.keys() if 'unknown_' not in g])
        unmatched_groups = len([g for g in game_files.keys() if 'unknown_' in g])
        unmatched_files = sum(len(files) for gid, files in game_files.items() if 'unknown_' in gid)
        
        # Enable/disable reconcile button
        if unmatched_groups > 0:
            self.reconcile_btn.config(state='normal')
            self.unknown_games = [gid for gid in game_files.keys() if 'unknown_' in gid]
        else:
            self.reconcile_btn.config(state='disabled')
            self.unknown_games = []
        
        self.status_label.config(text=f"Found {len(self.source_files)} files: {matched} matched games, {unmatched_files} unmatched files in {unmatched_groups} folders")
    
    def fuzzy_match_game_id(self, potential_id):
        """
        Fuzzy match a potential game ID against the database.
        Tries multiple hyphen insertion patterns and variations.
        Also maps GID format to traditional game IDs.
        """
        if not potential_id:
            return None

        potential_id = potential_id.upper().strip()

        # Check if this is a GID and map to traditional ID
        if potential_id.startswith('GID') and potential_id in self.gid_to_traditional:
            traditional_id = self.gid_to_traditional[potential_id]
            print(f"Mapped {potential_id} → {traditional_id}")
            return traditional_id

        # Direct match first
        if potential_id in self.redump_db:
            return potential_id

        # Try without hyphens - compare stripped versions
        stripped_input = potential_id.replace('-', '').replace('_', '')

        # Check if stripped version is a GID
        if stripped_input.startswith('GID') and stripped_input in self.gid_to_traditional:
            traditional_id = self.gid_to_traditional[stripped_input]
            print(f"Mapped {stripped_input} → {traditional_id}")
            return traditional_id

        for db_id in self.redump_db.keys():
            stripped_db = db_id.replace('-', '').replace('_', '')
            if stripped_input == stripped_db:
                return db_id

        # Generate possible hyphen variations
        variations = self.generate_hyphen_variations(potential_id)

        for variation in variations:
            if variation in self.redump_db:
                return variation

        return None

    def generate_hyphen_variations(self, game_id):
        """Generate possible hyphen insertion variations for a game ID"""
        variations = set()
        clean_id = game_id.replace('-', '').replace('_', '')

        # Common Dreamcast game ID patterns:
        # T-1201N (1 letter, 4 digits, 1 letter)
        # HDR-0041 (3 letters, 4 digits)
        # MK-51190-50 (2 letters, 5 digits, 2 digits)
        # T-36803-N (1 letter, 5 digits, 1 letter)
        # 610-7390 (3 digits, 4 digits)

        patterns = [
            # Pattern: T1201N -> T-1201N
            (r'^([A-Z]{1})(\d{4})([A-Z]{1})$', ['{0}-{1}{2}']),
            # Pattern: T12015 -> T-1201-5 or T-12015
            (r'^([A-Z]{1})(\d{4})(\d{1})$', ['{0}-{1}-{2}', '{0}-{1}{2}']),
            # Pattern: T36803N -> T-36803-N or T-36803N
            (r'^([A-Z]{1})(\d{5})([A-Z]{1})$', ['{0}-{1}-{2}', '{0}-{1}{2}']),
            # Pattern: HDR0041 -> HDR-0041
            (r'^([A-Z]{2,3})(\d{4})$', ['{0}-{1}']),
            # Pattern: HDR00415 -> HDR-0041-5
            (r'^([A-Z]{2,3})(\d{4})(\d{1,2})$', ['{0}-{1}-{2}', '{0}-{1}{2}']),
            # Pattern: MK511905 -> MK-51190-5, MK-51190-50, MK-5119-05, etc.
            (r'^([A-Z]{2})(\d{5})(\d{1})$', ['{0}-{1}-{2}', '{0}-{1}{2}']),
            (r'^([A-Z]{2})(\d{5})(\d{2})$', ['{0}-{1}-{2}', '{0}-{1}{2}']),
            (r'^([A-Z]{2})(\d{4})(\d{2})$', ['{0}-{1}-{2}', '{0}-{1}{2}']),
            # Pattern: 6107390 -> 610-7390
            (r'^(\d{3})(\d{4})$', ['{0}-{1}']),
            # Pattern: T11001N -> T-11001-N or T-11001N
            (r'^([A-Z]{1})(\d{5})([A-Z]{1})$', ['{0}-{1}-{2}', '{0}-{1}{2}']),
            # Pattern: T13004N -> T-13004-N or T-13004N
            (r'^([A-Z]{1})(\d{5})([A-Z]{1})$', ['{0}-{1}-{2}', '{0}-{1}{2}']),
            # Pattern: longer codes like T15128N -> T-15128-N
            (r'^([A-Z]{1,2})(\d{5,6})([A-Z]?)$', ['{0}-{1}-{2}', '{0}-{1}{2}']),
            # Pattern: IND16963 -> IND-16963
            (r'^([A-Z]{3})(\d{5})$', ['{0}-{1}']),
            # Very flexible catchall: letters-digits-optional letters/digits
            (r'^([A-Z]+)(\d+)([A-Z]*)$', ['{0}-{1}{2}', '{0}-{1}-{2}']),
        ]

        for pattern_regex, format_strings in patterns:
            match = re.match(pattern_regex, clean_id)
            if match:
                groups = match.groups()
                for fmt in format_strings:
                    try:
                        variation = fmt.format(*groups)
                        # Remove trailing hyphens
                        variation = variation.rstrip('-')
                        if variation:
                            variations.add(variation)
                    except:
                        pass

        return variations

    def extract_game_id(self, path):
        """Extract and normalize game ID from path with intelligent fuzzy matching"""
        # Extract potential game ID patterns from path
        path_upper = path.upper()

        # Try to find game ID patterns in the path
        potential_patterns = [
            r'([A-Z]{1,3}-\d{4,6}(?:-[A-Z0-9]{1,2})?)',  # With hyphens: T-1201N, HDR-0178
            r'([A-Z]{1,3}\d{4,7}[A-Z]?)',                 # Without hyphens: T1201N, HDR0041
            r'(\d{3}-\d{4})',                              # Numeric: 610-7390
            r'(\d{7})',                                    # Numeric no hyphen: 6107390
            r'(GID\d{3})',                                 # GID format: GID028
            r'([A-Z]{3,10})',                             # Word-like: CLASCUBE, VMUGAMES
        ]

        candidates = []
        for pattern in potential_patterns:
            matches = re.findall(pattern, path_upper)
            candidates.extend(matches)

        # Try to fuzzy match each candidate
        for candidate in candidates:
            matched_id = self.fuzzy_match_game_id(candidate)
            if matched_id:
                return matched_id

        # If no fuzzy match, try extracting from folder/file name directly
        # Extract the last folder name or filename without extension
        parts = path.replace('\\', '/').split('/')
        for part in reversed(parts):
            if part:
                # Clean the part
                clean_part = part.split('.')[0].strip()
                matched_id = self.fuzzy_match_game_id(clean_part)
                if matched_id:
                    return matched_id

        return 'UNKNOWN'
    
    def scan_dest_files(self):
        folder = self.output_folder.get()
        if not folder:
            return
        
        for item in self.dest_tree.get_children():
            self.dest_tree.delete(item)
        
        self.dest_files = []
        dreamcast_folder = os.path.join(folder, 'Dreamcast')
        
        if not os.path.exists(dreamcast_folder):
            self.dest_tree.insert('', 'end', text='No Dreamcast folder yet', values=('', '', ''))
            return
        
        game_files = {}
        
        for game_id in os.listdir(dreamcast_folder):
            game_path = os.path.join(dreamcast_folder, game_id)
            if os.path.isdir(game_path):
                files = []
                for file in os.listdir(game_path):
                    if file.endswith('.vmu'):
                        full_path = os.path.join(game_path, file)
                        file_size = os.path.getsize(full_path)
                        files.append({
                            'filename': file,
                            'full_path': full_path,
                            'size': file_size
                        })
                        self.dest_files.append(full_path)
                
                if files:
                    game_files[game_id] = files
        
        for game_id in sorted(game_files.keys()):
            files = game_files[game_id]
            
            # Handle unknown folders
            if 'unknown_' in game_id or game_id.startswith('UNKNOWN'):
                title = "Unknown Game (requires manual mapping)"
                region = '?'
            else:
                info = self.redump_db.get(game_id, {})
                title = info.get('title', 'Unknown Game')
                region = info.get('region', '?')
            
            game_node = self.dest_tree.insert('', 'end', text=game_id,
                                             values=(title, region, f"{len(files)} files"))
            
            for file_info in files:
                size_str = f"{file_info['size'] / 1024:.1f} KB"
                self.dest_tree.insert(game_node, 'end', text=file_info['filename'],
                                     values=('', '', size_str))
    
    def select_all_source(self):
        for item in self.source_tree.get_children():
            self.source_tree.selection_add(item)
    
    def deselect_all_source(self):
        self.source_tree.selection_remove(self.source_tree.selection())
    
    def open_dest_folder(self):
        folder = self.output_folder.get()
        if folder:
            dreamcast_folder = os.path.join(folder, 'Dreamcast')
            if os.path.exists(dreamcast_folder):
                if os.name == 'nt':
                    os.startfile(dreamcast_folder)
                else:
                    os.system(f'open "{dreamcast_folder}"')
            else:
                if os.name == 'nt':
                    os.startfile(folder)
                else:
                    os.system(f'open "{folder}"')
    
    def start_conversion(self):
        if not self.source_folder.get() or not self.output_folder.get():
            messagebox.showerror("Error", "Select both source and output folders")
            return
        
        selected = self.source_tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select files or games to convert")
            return
        
        files_to_convert = []
        seen_paths = set()  # Track which files we've already added
        
        for item in selected:
            item_text = self.source_tree.item(item, 'text')
            tags = self.source_tree.item(item, 'tags')
            
            if 'game' in tags:
                # Selected a game node - add all its files
                for child in self.source_tree.get_children(item):
                    child_text = self.source_tree.item(child, 'text')
                    for full_path, game_id, file_info in self.source_files:
                        if file_info['filename'] == child_text and game_id == item_text:
                            if full_path not in seen_paths:  # Only add if not already added
                                files_to_convert.append((full_path, game_id, file_info))
                                seen_paths.add(full_path)
                            break
            else:
                # Selected a file node - add just that file
                parent = self.source_tree.parent(item)
                parent_text = self.source_tree.item(parent, 'text')
                for full_path, game_id, file_info in self.source_files:
                    if file_info['filename'] == item_text and game_id == parent_text:
                        if full_path not in seen_paths:  # Only add if not already added
                            files_to_convert.append((full_path, game_id, file_info))
                            seen_paths.add(full_path)
                        break
        
        if not files_to_convert:
            messagebox.showwarning("No Files", "No valid files found in selection")
            return

        # Check for unknown games and block conversion
        unknown_files = [(path, gid, info) for path, gid, info in files_to_convert if 'unknown_' in gid]
        if unknown_files:
            messagebox.showerror(
                "Cannot Convert Unknown Games",
                f"{len(unknown_files)} file(s) have unknown game IDs and cannot be converted.\n\n"
                "VMUPro requires valid game IDs for all saves.\n\n"
                "Please use 'Reconcile Unknown Games' to manually map them first,\n"
                "or deselect them before converting."
            )
            return
        
        self.convert_btn.config(state='disabled')
        self.status_label.config(text=f"Converting {len(files_to_convert)} files...")
        thread = threading.Thread(target=self.conversion_worker, args=(files_to_convert,), daemon=True)
        thread.start()
    
    def conversion_worker(self, files_to_convert):
        try:
            output_root = self.output_folder.get()
            dreamcast_folder = os.path.join(output_root, 'Dreamcast')
            os.makedirs(dreamcast_folder, exist_ok=True)
            
            converted = 0
            game_channel_counters = {}  # Track channel numbers per game
            
            for full_path, game_id, file_info in files_to_convert:
                # Initialize channel counter for this game if not exists
                if game_id not in game_channel_counters:
                    game_channel_counters[game_id] = 1
                
                # Get the next channel number for this game
                channel_no = str(game_channel_counters[game_id])

                game_folder = os.path.join(dreamcast_folder, game_id)
                os.makedirs(game_folder, exist_ok=True)

                dest_path = os.path.join(game_folder, f"{game_id}-{channel_no}.vmu")

                # Ensure unique filename
                while os.path.exists(dest_path):
                    game_channel_counters[game_id] += 1
                    channel_no = str(game_channel_counters[game_id])
                    dest_path = os.path.join(game_folder, f"{game_id}-{channel_no}.vmu")
                
                # Copy the file
                shutil.copy2(full_path, dest_path)
                
                # Increment counter for next file of this game
                game_channel_counters[game_id] += 1
                converted += 1
            
            self.root.after(0, lambda: self.finalize_conversion(converted))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", str(e)))
            self.root.after(0, lambda: self.convert_btn.config(state='normal'))
    
    def finalize_conversion(self, count):
        self.convert_btn.config(state='normal')
        self.status_label.config(text=f"Converted {count} files successfully!")
        messagebox.showinfo("Success", f"Converted {count} files to VMUPro format!")
        self.scan_dest_files()
    
    def create_browser_ui(self):
        frame = ttk.Frame(self.browser_tab)
        frame.grid(row=0, column=0, sticky='nsew', padx=15, pady=15)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)
        
        title = ttk.Label(frame, text="Dreamcast Game Browser", font=('Arial', 12, 'bold'))
        title.grid(row=0, column=0, sticky='w', pady=(0, 10))
        
        search_frame = ttk.Frame(frame)
        search_frame.grid(row=1, column=0, sticky='ew', pady=10)
        search_frame.columnconfigure(1, weight=1)
        
        ttk.Label(search_frame, text="Search:", font=('Arial', 10, 'bold')).pack(side='left', padx=(0, 10))
        self.search_var = tk.StringVar()
        self.search_var.trace('w', lambda *args: self.search_games())
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        search_entry.pack(side='left', fill='x', expand=True, padx=(0, 10))
        
        self.refresh_btn = ttk.Button(search_frame, text="Refresh Database", command=self.refresh_database)
        self.refresh_btn.pack(side='left')
        
        text_frame = ttk.LabelFrame(frame, text="Results", padding=5)
        text_frame.grid(row=2, column=0, sticky='nsew', pady=10)
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        
        self.browser_text = scrolledtext.ScrolledText(text_frame, height=20, width=100, font=('Courier', 9))
        self.browser_text.grid(row=0, column=0, sticky='nsew')
        
        self.refresh_browser()
    
    def refresh_database(self):
        self.load_database()
        self.refresh_browser()
        messagebox.showinfo("Refresh Complete", f"Database refreshed!\n\nLoaded {len(self.redump_db)} games.")
    
    def search_games(self):
        search = self.search_var.get().lower()
        
        self.browser_text.config(state='normal')
        self.browser_text.delete('1.0', tk.END)
        
        results = []
        for gameid, info in sorted(self.redump_db.items()):
            title = info.get('title', '')
            region = info.get('region', '')
            
            if search in gameid.lower() or search in title.lower() or search in region.lower():
                results.append((gameid, title, region))
        
        for gameid, title, region in results:
            self.browser_text.insert(tk.END, f"{gameid}  {title}  ({region})\n")
        
        if not results:
            self.browser_text.insert(tk.END, "No results found")
        
        self.browser_text.config(state='disabled')
    
    def refresh_browser(self):
        self.browser_text.config(state='normal')
        self.browser_text.delete('1.0', tk.END)
        
        if self.redump_db:
            for gameid, info in sorted(list(self.redump_db.items())[:100]):
                title = info.get('title', '')
                region = info.get('region', '')
                self.browser_text.insert(tk.END, f"{gameid}  {title}  ({region})\n")
            
            if len(self.redump_db) > 100:
                self.browser_text.insert(tk.END, f"\n... and {len(self.redump_db) - 100} more games (search to narrow results)")
        else:
            self.browser_text.insert(tk.END, "Download database first from the 'Download Database' tab!")
        
        self.browser_text.config(state='disabled')

if __name__ == "__main__":
    root = tk.Tk()
    app = VMUProApp(root)
    root.mainloop()