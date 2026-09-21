# Contributing

For bugs, open a GitHub issue with the steps to reproduce, expected and actual
behavior, and your operating system or Kindle model, firmware and KOReader version.
For Photo Prep, include the input format and selected preset. Use a non-private
sample image if one is needed. Remove personal paths and photo filenames from logs.

Discuss substantial changes in an issue before implementing them. Keep changes
focused and explain how you verified them in the pull request.

Follow [the development guide](docs/development.md) to run from source. Before
submitting Python changes, run:

```sh
python -m pip install -r tools/requirements.txt
python -m unittest discover -s tests
python tools/package_plugin.py
```

Plugin changes also need the relevant [Kindle bench tests](notes/design.md).
State which hardware you tested; automated tests cannot verify Kindle sleep behavior.
Do not commit personal photos, local presets, credentials, or generated builds.
