# Assets

There are no binary assets in this directory, and none are needed.

Every piece of artwork in Commit Rider (the bicycle, the rider, the mountains, trees, clouds,
sun and moon, particles) is **drawn procedurally by the code** in `src/commit_rider/rendering/`
and `src/commit_rider/animation/`, from original geometry. Nothing was traced, copied or
downloaded from another creator's artwork, and the project reproduces none of the source code,
artwork or proprietary assets of the animation that inspired it.

Fonts are not bundled. The optional statistics overlay uses DejaVu Sans if it is installed
(it is on GitHub's Ubuntu runners) and otherwise falls back to Pillow's built-in font.

Everything in this repository, including the images in `examples/`, is covered by the MIT licence
in the root `LICENSE`. The example images are generated from *synthetic* data
(`examples/sample-contributions.json`), not from anyone's real contribution history.
