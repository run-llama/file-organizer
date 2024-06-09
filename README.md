# File Organizer

A command-line utility that organizes files into folders based on descriptions of their content, while ensuring that no folder is unhelpfully vague or overly specific. Very obviously inspired by [llama-fs](https://github.com/iyaja/llama-fs), the main differences being:
* It never renames any files, it just puts them into folders, file names are generally pretty helpful.
* The organization is hopefully much smarter, helping you locate groups of files regardless of their names

## Usage

At the moment the tool has to be run manually in separate stages (see Further Work below).

```bash
python organize.py --describe path_to_folder
```

Reads all the files in `path_to_folder` and gets an LLM to describe them in detail. These descriptions are cached in a folder called `db` as JSON files based on the `inode` ID of the file, so even if they move around the filesystem, the cache will still be valid.

```bash
python organize.py --categorize path_to_folder
```

Reads all the files in `path_to_folder` that have a cached description from the previous step. It then comes up with a proposed category for each one and writes these categories into a file called `db/categorized_paths.json`. **It ignores folders**, assuming if you put something in a folder that's already a pretty good category. It will however re-organize files that are in folders it previously created.

```bash
python organize.py --recategorize path_to_folder
```

Reads all the files in `db/categorized_paths.json` and makes sure none of the categories are either too vague or too specific:
* If a category has 3 or fewer files, it will attempt to merge them into larger existing categories
* If a single category accounts for 20% or more of the files, it will attempt to split them into more specific categories
* It will make up to 5 passes over the data to try and get this right (since the first pass might create too many small categories, or another big category).

```bash
python organize.py --move path_to_folder
```

Takes the files described in `db/categorized_paths.json` and moves them into folders named after their categories with the suffix "(Auto)". It will record which folders it generated in a file called `db/auto_generated_folders.json`; if you run it multiple times and it ends up emptying out an auto-generated folder that folder will be deleted.

## Further work

Getting organization to work was the fun part, there's a bunch of grunt work to do:

* Obviously the whole thing runs in stages right now; the expectation is that some higher-level process will be taking care of deciding when to describe files, when to categorize, when to re-categorize, and when to move. I would expect this to be a cute little Electron desktop app or something.
* `categorized_paths.json` does not account for you ever running this on more than one folder! The whole thing needs to be refactored so that `categorized_paths` and `auto_generated_folders` take into account that not every file lives in one folder.
* Not all the files are usefully described. At the moment it can't read WEBP files, so it tends to sort them into a category called "webp files" which isn't very helpful. It also has trouble with some audio and video files.
