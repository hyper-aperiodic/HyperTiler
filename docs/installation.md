# Installation

Pick whichever fits how you like to work. Every method below needs Python
3.12+ installed, except the standalone executable.

## Standalone executables

Packaged executables - no Python install required at all. Download, unzip, and run in folder!

[Available for Windows, with Linux and macOS.](https://github.com/hyper-aperiodic/HyperTiler/releases)


## PyPI package

```bash
pip install hypertiler
```

Then launch the desktop app with (from that same environment - activate it
first if you used a virtualenv):

```bash
hypertiler
```

Or use it as a library without launching the GUI at all - see
{doc}`quickstart`.

## Git clone

Clone the repo, then run `scripts/setup.sh` or `setup.bat` to create a
`.venv` and install dependencies, then `scripts/run.sh` or `run.bat` to
launch. Assumes familiarity with git and a terminal (`.sh` for Linux/macOS,
`.bat` for Windows).

## Download + double-click (no terminal needed)

Download the repo as a zip - no git required. On Windows, double-click
`scripts/setup.bat` once, then `scripts/run.bat` each time after (Mac/Linux:
`setup.sh`/`run.sh`).

