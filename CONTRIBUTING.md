# Contributing

Thanks for taking a look at Parrot Uptime Dashboard. This is a small,
offline desktop utility, so contributions are intentionally lightweight.

## Ground rules

* The application must stay **fully offline**: no network calls, telemetry,
  or remote assets.
* Keep the runtime dependency list at **matplotlib** plus the standard
  library (Tkinter, SQLite). New third-party packages need a good reason.
* Uptime numbers must never be invented. Days without data stay marked as
  *no data*, not zero.

## Development setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt      # matplotlib only
python3 app.py                       # run the GUI
```

On Debian/Parrot, Tkinter comes from the `python3-tk` package:

```bash
sudo apt install python3-tk python3-matplotlib
```

## Tests

The suite uses only `unittest`, so it runs with no extra dependencies:

```bash
python3 -m unittest discover -s tests -t . -v
```

CI runs the same command on Python 3.9–3.13, plus a shell syntax check.

## Code style

* Match the surrounding code: comments explain *why*, not *what*.
* Keep functions small and side-effect-free where practical.
* Format with `black` (88 columns) if you have it; it is not enforced.

## Submitting changes

1. Fork or branch from `main`.
2. Make the change and add or update tests where it makes sense.
3. Run the test suite and `python3 -m compileall -q .`.
4. Open a pull request describing the problem and the fix.

Bug reports are welcome too — please include your Parrot/Python versions
and what `journalctl --list-boots` and `last reboot` return on your system,
since history reconstruction depends on them.
