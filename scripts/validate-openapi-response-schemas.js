const fs = require("node:fs");

const methods = new Set(["get", "put", "post", "delete", "options", "head", "patch", "trace"]);

function findEmptyJsonResponseSchemas(openapi) {
  const failures = [];
  for (const [route, pathItem] of Object.entries(openapi?.paths ?? {})) {
    for (const [method, operation] of Object.entries(pathItem ?? {})) {
      if (!methods.has(method.toLowerCase())) continue;
      for (const [statusCode, response] of Object.entries(operation?.responses ?? {})) {
        if (!/^2\d\d$/.test(statusCode)) continue;
        for (const [mediaType, media] of Object.entries(response?.content ?? {})) {
          if (mediaType !== "application/json" && !mediaType.endsWith("+json")) continue;
          const schema = media?.schema;
          if (!schema || typeof schema !== "object" || Object.keys(schema).length === 0) {
            failures.push(`${method.toUpperCase()} ${route} -> ${statusCode} ${mediaType}`);
          }
        }
      }
    }
  }
  return failures.sort();
}

function main() {
  const args = process.argv.slice(2);
  const expectInvalid = args.includes("--expect-invalid");
  const filePath = args.find((value) => value !== "--expect-invalid");
  if (!filePath) throw new Error("Usage: node validate-openapi-response-schemas.js <openapi.json> [--expect-invalid]");
  const openapi = JSON.parse(fs.readFileSync(filePath, "utf8").replace(/^\uFEFF/, ""));
  const failures = findEmptyJsonResponseSchemas(openapi);

  if (expectInvalid) {
    if (!failures.length) throw new Error("Expected fixture to contain an empty 2xx JSON response schema");
    process.stdout.write(`Expected invalid response schema detected: ${failures.join(", ")}\n`);
    return;
  }
  if (failures.length) {
    process.stderr.write("OpenAPI 2xx JSON responses must not use an empty schema:\n");
    for (const failure of failures) process.stderr.write(`- ${failure}\n`);
    process.exitCode = 1;
    return;
  }
  process.stdout.write("OpenAPI response schema validation passed.\n");
}

if (require.main === module) main();

module.exports = { findEmptyJsonResponseSchemas };
