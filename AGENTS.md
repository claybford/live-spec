READ THIS FIRST, BEFORE ANYTHING ELSE, DO NOT SKIP:
run `python3 lspec.py start live-spec.html` and read everything it prints, every line, from the opening header line beginning `==== live-spec.html —` through the closing line `==== end live-spec.html ====`. If either line is missing from what you received, or the tool reported any truncation, the delivery was cut: read live-spec.html in full another way before doing anything else. No ranged views, no search instead of reading.
This gates every request in this repo — questions and read-only tasks included. If the request looks answerable without the load, run it anyway; search and partial reads are not a substitute.
Before committing, stage the intended changes, then run `python3 lspec.py finish live-spec.html`; changes afterward require another run. Before handing work back, run it again after the last commit or edit, address its findings, and report any blocker or unfinished work. It supplies checks, evidence, a review prompt, and a local state-bound commit receipt; it does not certify that semantic review was performed.

This repo lives to serve the development of ./live-spec.html
./live-spec.html has a friend, lspec.py, the companion tool (verbs listed in `python3 lspec.py start`'s output); the hooks in ./hooks run `check --staged --finish-receipt` on every commit (pre-commit: structure + seal gate; commit-msg: review + vocabulary gates; both require a matching receipt), and `check --clean` is the post-commit completion check.
Only in this repo do you have the authority to move outside the premise and rules of ./live-spec.html a little bit with your proposed edits.
Don't fall into its depths when working on it - that's how you eff it up. Stay grounded, stay cool.
Just keep in mind what I told you.
It's dangerous to go alone, take this, etc.
:)
