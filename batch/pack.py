"""Produce a portable package from the explicit application and dependency lists."""
import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

HERE = Path(__file__).resolve().parent
FILES = (
    "README.md","WINDOWS.md","batch.sh","batch.py","batch_engine.py","batch_state.py","acceptance.py","pack.py",
    "vendor.sha256","vendor-files.txt","examples/jobs.json","examples/quickstart.json","examples/sources.md",
    "examples/data/cowell.png","examples/data/griffith.png","examples/data/younger-original.pdf","examples/data/segal.png",
)


def package(destination):
    dependencies = (HERE/"vendor-files.txt").read_text().splitlines()
    plan = [*FILES,*("vendor/"+path for path in dependencies)]
    with ZipFile(destination,"x",compression=ZIP_DEFLATED,compresslevel=6) as release:
        for member in plan:
            release.write(HERE/member,"visual-search-batch/"+member)
    print(f"{len(plan)} files: {destination}")


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output",type=Path)
    package(parser.parse_args().output)
