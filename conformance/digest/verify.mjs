#!/usr/bin/env node
/**
 * Independent RFC 8785 / JCS verifier for the committed digest corpus.
 *
 * This program must not call Python and must not use npm packages.
 * Number and string serialization come from ECMAScript JSON.stringify;
 * object keys are sorted recursively by UTF-16 code units via Object.keys().sort().
 */

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const ALGORITHM = "jcs-sha256";
export const PREFIX = "jcs-sha256:";

const CORPUS_FILE = "rfc8785-v1.json";

export function canonicalize(value) {
  if (value === null) {
    return "null";
  }
  const valueType = typeof value;
  if (valueType === "boolean") {
    return value ? "true" : "false";
  }
  if (valueType === "number") {
    if (!Number.isFinite(value)) {
      throw new Error("JCS numbers must be finite");
    }
    return JSON.stringify(value);
  }
  if (valueType === "string") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalize(item)).join(",")}]`;
  }
  if (valueType === "object") {
    const keys = Object.keys(value).sort();
    const members = keys.map((key) => `${JSON.stringify(key)}:${canonicalize(value[key])}`);
    return `{${members.join(",")}}`;
  }
  throw new Error(`JCS value has unsupported type: ${valueType}`);
}

export function contentDigest(value) {
  const canonicalUtf8 = canonicalize(value);
  const digest = `${PREFIX}${createHash("sha256").update(canonicalUtf8, "utf8").digest("hex")}`;
  return { canonicalUtf8, digest };
}

export function loadCorpus(corpusPath) {
  const document = JSON.parse(readFileSync(corpusPath, "utf8"));
  if (document.algorithm !== ALGORITHM) {
    throw new Error(`unexpected algorithm: ${document.algorithm}`);
  }
  if (document.prefix !== PREFIX) {
    throw new Error(`unexpected prefix: ${document.prefix}`);
  }
  if (!Array.isArray(document.vectors) || document.vectors.length === 0) {
    throw new Error("corpus has no vectors");
  }
  return document;
}

export function verifyCorpus(corpusPath) {
  const document = loadCorpus(corpusPath);
  const failures = [];
  for (const vector of document.vectors) {
    const { canonicalUtf8, digest } = contentDigest(vector.input);
    if (canonicalUtf8 !== vector.canonicalUtf8) {
      failures.push(
        `${vector.id}: canonical mismatch\n  expected: ${vector.canonicalUtf8}\n  actual:   ${canonicalUtf8}`,
      );
    }
    if (digest !== vector.digest) {
      failures.push(
        `${vector.id}: digest mismatch\n  expected: ${vector.digest}\n  actual:   ${digest}`,
      );
    }
    if (!digest.startsWith(PREFIX) || !/^[0-9a-f]{64}$/.test(digest.slice(PREFIX.length))) {
      failures.push(`${vector.id}: digest is not ${PREFIX}<64 lowercase hex>`);
    }
  }
  return { vectorCount: document.vectors.length, failures };
}

function main() {
  const corpusPath = join(dirname(fileURLToPath(import.meta.url)), CORPUS_FILE);
  const { vectorCount, failures } = verifyCorpus(corpusPath);
  if (failures.length > 0) {
    console.error(`JCS conformance failed for ${failures.length} of ${vectorCount} vectors:`);
    for (const failure of failures) {
      console.error(failure);
    }
    process.exit(1);
  }
  console.log(`JCS conformance passed: ${vectorCount} vectors in ${CORPUS_FILE}`);
}

const entryPath = process.argv[1];
if (entryPath !== undefined && import.meta.url === pathToFileURL(entryPath).href) {
  main();
}
