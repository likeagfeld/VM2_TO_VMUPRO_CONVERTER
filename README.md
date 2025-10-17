# Quick Start

## Using the Converter

1. Download `VMUPro_Converter.exe` from [Releases](../../releases)
2. Run it
3. Download Database tab - click "Download from GitHub" (first time only)
4. Convert Saves tab:
   - Browse Source - select your VM2 saves folder
   - Browse Output - select where you want converted files
   - Click "Convert Selected Files"

## If Games Don't Match

Click "Reconcile Unknown Games" to manually select the correct game for any unmatched saves. Your selections are saved for next time.

## Building from Source

```bash
pip install pyinstaller pillow
python convert_icon.py
pyinstaller VMUPro_Converter.spec
```

Done.
