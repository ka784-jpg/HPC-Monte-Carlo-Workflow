"""Refresh documentation assets only from the repository's public demo configuration."""

import argparse
import hashlib
from pathlib import Path
import shutil

from mcflow.manifest import load_manifest, make_manifest
from mcflow.plotting import plot
from mcflow.storage import WorkflowError, digest, read_json, write_record


def export(run):
    import matplotlib

    root = Path(__file__).resolve().parents[1]
    manifest = load_manifest(run)
    if manifest != make_manifest(read_json(root / "configs" / "gallery.json")):
        raise WorkflowError("Only the public gallery configuration may be exported")
    plot(run)
    output = root / "docs" / "assets"
    output.mkdir(exist_ok=True)
    hashes = {}
    for name in ("convergence.png", "convergence.pdf", "tasks.csv", "summary.json"):
        source = Path(run) / "analysis" / name
        shutil.copyfile(source, output / name)
        hashes[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    write_record(output / "provenance.json", {
        "source": "Public quarter-circle Monte Carlo example in this repository",
        "config": "configs/gallery.json", "manifest_sha256": digest(manifest),
        "matplotlib": matplotlib.__version__, "files_sha256": hashes})
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    print(export(parser.parse_args().run))
