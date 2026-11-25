"""Deterministic engineering fixtures. Optional generation dependency: reportlab."""

import json
from pathlib import Path
import random
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[1]


def build():
    directory = ROOT / "data/conflicts"
    directory.mkdir(exist_ok=True)
    rng = random.Random(61583)
    records = []
    for i in range(12):
        first, second = rng.sample(range(100, 900), 2)
        same = i % 3 == 0
        if same:
            second = first
        name = f"register-{i:02d}.pdf"
        canvas = Canvas(str(directory / name), pagesize=(612, 792), invariant=True)
        anchor = ("Relay output", "Reserve load", "Intake demand")[i % 3]
        for j, value in enumerate((first, second), 1):
            canvas.setFont("Helvetica-Bold", 21)
            canvas.drawString(55, 725, f"Inspection record {j}")
            canvas.setFont("Helvetica", 12)
            canvas.drawString(55, 685, "Values recorded in the weekly equipment review.")
            canvas.setFont("Helvetica" if i % 2 else "Courier", 16)
            canvas.drawString(65, 520 - i * 9, f"{anchor} {value} kW")
            canvas.showPage()
        canvas.save()
        records.append({"file": name, "anchor": anchor, "values": [str(first), str(second)],
                        "expected": "answered" if same else "conflict"})
    (directory / "manifest.json").write_text(json.dumps(records, indent=2) + "\n")


if __name__ == "__main__":
    build()
