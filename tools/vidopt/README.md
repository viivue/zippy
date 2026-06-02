# vidopt

Python command-line tool for optimising MP4 and MOV videos for web delivery.
Produces streaming-ready H.264 MP4 files sized for the web without sacrificing
noticeable quality. Source files are never modified or deleted.

## Requirements

- Python 3.10 or later
- ffmpeg (auto-downloaded on Windows; see below for other platforms)

## Install

### Step 1 - Python 3.10 or later

Check if Python is already installed:

```sh
python --version
```

If it is missing or older than 3.10, download it from
[python.org/downloads](https://www.python.org/downloads/).

> **Windows tip:** In the installer check "Add Python to PATH" before clicking
> Install Now.

### Step 2 - install uv or pipx

#### uv (recommended)

##### Windows

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

After the script completes, close and reopen your terminal.

##### macOS / Linux

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### pipx (alternative)

```sh
pip install --user pipx
pipx ensurepath
```

Close and reopen your terminal after `ensurepath`.

### Step 3 - install vidopt

From the repo root:

```sh
uv tool install ./tools/vidopt
# or
pipx install ./tools/vidopt
```

## Updating

Pull the latest code, then reinstall:

```sh
uv tool install --reinstall ./tools/vidopt
# or
pipx install --force ./tools/vidopt
```

## ffmpeg

vidopt looks for ffmpeg and ffprobe in this order:

1. `~/.vidopt/bin/`
2. System PATH

**Windows:** vidopt auto-downloads a static build from
[gyan.dev](https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip)
on first run and places the binaries in `~\.vidopt\bin\`.

> **Offline networks:** Download the zip manually, extract it, and copy
> `ffmpeg.exe` + `ffprobe.exe` into `%USERPROFILE%\.vidopt\bin\`.
> Then pass `--skip-download` to prevent any network access.

**macOS**

```sh
brew install ffmpeg
```

**Linux**

```sh
sudo apt install ffmpeg   # Debian / Ubuntu
sudo dnf install ffmpeg   # Fedora / RHEL
```

## Usage

```sh
vidopt video.mp4
vidopt clip.mov --output ./web-exports
vidopt ./raw-footage --recursive
vidopt video.mp4 --quality 5          # best quality
vidopt video.mp4 --quality 2          # smallest file
vidopt video.mp4 --h265 --quality 4
vidopt video.mp4 --speed thorough     # best compression, slower encode
vidopt video.mp4 --max-width 1280
vidopt ./raw-footage --dry-run
vidopt ./raw-footage --recursive --overwrite
```

## All flags

| Flag | Default | Description |
|------|---------|-------------|
| `--output DIR` | `<input>/optimized` | Destination folder |
| `--quality 1-5` | `4` | Output quality (see below) |
| `--speed fast\|balanced\|slow\|thorough` | `slow` | Encoding speed |
| `--max-width PX` | off | Scale down if wider than PX |
| `--h265` | off | Use H.265/HEVC codec (modern browsers only) |
| `--recursive` / `-r` | off | Include subfolders |
| `--overwrite` | off | Replace existing outputs |
| `--dry-run` | off | Print commands, do not encode |
| `--skip-download` | off | Never auto-download ffmpeg |

## Quality (`--quality`)

| Value | Result |
|-------|--------|
| `5` | Near-lossless, largest files |
| `4` | **Default** - high quality, good compression |
| `3` | Balanced, noticeably smaller |
| `2` | Small file priority |
| `1` | Aggressive compression, smallest files |

## Speed (`--speed`)

Slower encodes produce smaller files at the same quality level.

| Value | Encode time | File size |
|-------|-------------|-----------|
| `fast` | Fastest | Largest |
| `balanced` | Moderate | Moderate |
| `slow` | **Default** | Smaller |
| `thorough` | Slowest | Smallest |

## End-of-run report

```
================================================================================
SUMMARY
================================================================================
File                            Original     Output   Saved  Resolution  Status
--------------------------------------------------------------------------------
interview.mp4                    142.3 MB    38.1 MB  73.2%    1920x1080  OK
b-roll.mov                        89.4 MB    91.2 MB  -2.0%    3840x2160  LARGER  <<<
demo.mp4                          12.0 MB     3.9 MB  67.5%    1280x720   OK
--------------------------------------------------------------------------------
Net saved: 98.44 MB
```

Files marked `LARGER` are kept but flagged. This sometimes happens when the
source was already well-compressed or encoded with a modern codec at low bitrate.

Files marked `SKIPPED` already have an output in place — pass `--overwrite` to
re-encode them.

When batch-processing more than one file, a progress bar tracks overall progress.

## Development

```sh
cd tools/vidopt
uv venv && uv pip install -e .
vidopt --help
```

The `-e` flag installs in editable mode — source changes take effect immediately
without reinstalling.

If you add or change dependencies in `pyproject.toml`, re-run:

```sh
uv pip install -e .
```
