"use strict";

// Read JSON lines so one model instance can serve all paid views in a run.
const { createWorker, OEM, PSM } = require("tesseract.js");
const fs = require("node:fs");
const path = require("node:path");
const readline = require("node:readline");

const model = process.argv[2];
const emit = (value) => process.stdout.write(JSON.stringify(value) + "\n");

function convert(blocks, width, height) {
  const normalized = ({ x0, y0, x1, y1 }) => [x0 / width, y0 / height, x1 / width, y1 / height];
  return (blocks || []).flatMap((block) => block.paragraphs || [])
    .flatMap((paragraph) => paragraph.lines || [])
    .map((line) => ({
      text: line.text.trim(),
      box: normalized(line.bbox),
      confidence: Math.max(0, line.confidence) / 100,
      raw_words: (line.words || []).map((word) => ({ text: word.text, box: normalized(word.bbox) })),
      words: (line.words || []).flatMap((word) => {
        const box = normalized(word.bbox);
        const dx = (box[2] - box[0]) / Math.max(1, word.text.length);
        return Array.from(word.text.matchAll(/[A-Za-z0-9]+/g), (match) => ({
          text: match[0],
          box: [box[0] + dx * match.index, box[1], box[0] + dx * (match.index + match[0].length), box[3]],
        }));
      }),
    }));
}

async function main() {
  if (!model || path.basename(model) !== "eng.traineddata" || !fs.existsSync(model)) {
    throw new Error("Missing local eng.traineddata");
  }
  const worker = await createWorker("eng", OEM.LSTM_ONLY, {
    langPath: path.dirname(fs.realpathSync(model)),
    cacheMethod: "none",
    gzip: false,
  });
  try {
    await worker.setParameters({
      tessedit_pageseg_mode: PSM.SPARSE_TEXT,
      user_defined_dpi: "150",
      classify_enable_learning: "0",
      tessedit_do_invert: "0",
    });
    for await (const line of readline.createInterface({ input: process.stdin, crlfDelay: Infinity })) {
      try {
        const { image, size, mode } = JSON.parse(line);
        const psm = mode === "line" ? PSM.SINGLE_LINE : PSM.SPARSE_TEXT;
        const result = await worker.recognize(Buffer.from(image, "base64"), { tessedit_pageseg_mode: psm }, { blocks: true });
        emit({ lines: convert(result.data.blocks, ...size) });
      } catch (error) {
        emit({ error: String(error) });
      }
    }
  } finally {
    await worker.terminate();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
