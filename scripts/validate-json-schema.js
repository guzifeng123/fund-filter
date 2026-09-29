const fs = require("fs");
const path = require("path");
const Ajv = require("ajv");

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function formatAjvError(error) {
  const location = error.dataPath || error.instancePath || "<root>";
  return `${location} ${error.message}`;
}

const [, , schemaArg, ...documentArgs] = process.argv;

if (!schemaArg || documentArgs.length === 0) {
  console.error("Usage: node scripts/validate-json-schema.js <schema.json> <document.json> [document.json ...]");
  process.exit(2);
}

const workspaceRoot = path.resolve(__dirname, "..");
const schemaPath = path.resolve(workspaceRoot, schemaArg);
const schema = readJson(schemaPath);
const ajv = new Ajv({
  allErrors: true,
  strict: false
});
const validate = ajv.compile(schema);
let hasError = false;

for (const documentArg of documentArgs) {
  const documentPath = path.resolve(workspaceRoot, documentArg);
  const document = readJson(documentPath);
  const ok = validate(document);
  if (!ok) {
    hasError = true;
    console.error(`JSON Schema validation failed: ${documentArg}`);
    for (const error of validate.errors || []) {
      console.error(`- ${formatAjvError(error)}`);
    }
  }
}

if (hasError) {
  process.exit(1);
}

console.log("JSON Schema validation passed.");
