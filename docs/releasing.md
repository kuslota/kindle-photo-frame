# First release

The release workflow builds the plugin, Windows x64 Photo Prep, and macOS Apple
Silicon Photo Prep. Pushing a `v*` tag creates a **draft** release after all builds
and checks pass. You publish that draft after testing the downloaded packages.

## Prepare the public repository

- The project code uses the MIT license; retain `LICENSE` in source and release packages.
- Review both the current files and Git history. Deleted files remain downloadable
  from old commits. For the initial public release, use the cleaned, squashed `main`
  history and remove remote branches or tags that still expose development history.
  Keep any backup of the original history private and outside the repository.
- Confirm you have permission to distribute the documentation images. Metadata
  cleanup affects current images only; older versions remain in existing history.
- Keep local input photos, presets, `.env` files, virtual environments and build
  output out of Git. Inspect `git status --short` and the staged diff before committing.
- In GitHub **Settings → Actions → General**, allow the actions used by the workflows.
  The workflow requests release write permission for its release job; no personal
  access token or signing secret is needed.
- Once the intended files and history are on GitHub, use **Settings → General →
  Danger Zone → Change repository visibility → Make public** when ready. This exposes
  the repository's history, not just its latest files. Review branches and tags too.

## Verify before tagging

Run from the repository root with Python 3.12:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r tools/requirements.txt
.venv/bin/python -m unittest discover -s tests
.venv/bin/python tools/package_plugin.py
```

On Windows use `.venv\Scripts\python.exe`. Commit the reviewed cleanup and push
`main`. Wait for **Tests** in the Actions tab to pass on all three operating systems.
Optionally run **Build release packages → Run workflow** first and test its artifacts.
GitHub wraps each ZIP in an artifact download; extract that outer wrapper first.

## Create version 1.0.0

The macOS app metadata currently uses `1.0.0` in
`packaging/KindlePhotoPrep.spec`. For later releases update that version before tagging.
From the reviewed, committed `main` branch:

```sh
git status --short
# The output above should be empty.
git push origin main
git tag -a v1.0.0 -m "Kindle Photo Frame 1.0.0"
git push origin v1.0.0
```

In **Actions → Build release packages**, wait for `prep`, `plugin`, and `release`
to finish successfully. Open **Releases** and edit the `v1.0.0` draft. It should contain:

- `Kindle-Photo-Frame-Plugin.zip`
- `Kindle-Photo-Prep-Windows-x64.zip`
- `Kindle-Photo-Prep-macOS-Apple-Silicon.zip`
- `SHA256SUMS.txt`

GitHub also adds source archives; those are not the ready-to-install packages.
Download the release assets and complete the
[release verification checklist](development.md#release-verification-checklist).
Record the actual OS, Kindle firmware, and KOReader versions tested. Do not claim
Windows, macOS, or hardware verification you have not performed.

Optional checksum verification, from the folder containing all three ZIPs:

```sh
# macOS
shasum -a 256 -c SHA256SUMS.txt
# Linux
sha256sum -c SHA256SUMS.txt
```

On Windows, use `Get-FileHash .\Kindle-Photo-Prep-Windows-x64.zip -Algorithm SHA256`
and compare with the matching entry in `SHA256SUMS.txt`.

## Release notes and publishing

Use this as a starting point, adding your actual test results:

> First release of Kindle Photo Frame for jailbroken Kindles running KOReader.
>
> Install `Kindle-Photo-Frame-Plugin.zip` on the Kindle. Optional Photo Prep packages
> are available for Windows x64 and Apple Silicon Macs; they crop, resize, and adjust
> local photos for e-ink. See the README for installation and supported image formats.
>
> Photo Prep packages are unsigned and the macOS app is not notarized. Follow the
> linked OS guidance in the README; do not disable system security protections.
>
> Tested configurations: add the actual operating systems, Kindle models, firmware,
> and KOReader versions verified for this release.

Review the assets and notes, then click **Publish release**. For a trial release,
select **Set as a pre-release** first. Keep the draft until verification is complete.

If a build fails, inspect the failing Actions step. A transient failure can be
rerun. If source changes are needed, commit the fix and use a new version tag.
The workflow can replace assets on an existing draft, but refuses to overwrite
an already published release. Never move a published tag to different code.

GitHub references: [managing releases](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)
and [changing visibility](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility).
