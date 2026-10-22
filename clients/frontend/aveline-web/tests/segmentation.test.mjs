import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { smartSegmentText } from "../src/utils/text.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
// 从 clients/frontend/aveline-web/tests 到仓库根要上溯四级
const corpusPath = path.resolve(
  here,
  "../../../../tests/scripts/android_frontend/segmentation_cases.json",
);
const corpus = JSON.parse(await readFile(corpusPath, "utf8"));
const cases = corpus.web_smart_segment;

assert.ok(Array.isArray(cases) && cases.length > 0, "web_smart_segment corpus is missing");
for (const { name, input, expected } of cases) {
  const actual = smartSegmentText(input, false);
  assert.deepEqual(actual, expected, `${name}\ninput: ${JSON.stringify(input)}`);
}

console.log(`PASS: ${cases.length} Web smartSegmentText golden cases`);
