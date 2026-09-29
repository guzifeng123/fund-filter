const fs = require("node:fs");
const path = require("node:path");

function parseArgs(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 2) values[argv[index]] = argv[index + 1];
  for (const required of ["--after", "--diff", "--summary"]) {
    if (!values[required]) throw new Error(`Missing required argument ${required}`);
  }
  return values;
}

function readJson(filePath) {
  if (!filePath || !fs.existsSync(filePath)) return null;
  const content = fs.readFileSync(filePath, "utf8").replace(/^\uFEFF/, "").trim();
  return content ? JSON.parse(content) : null;
}

function compareSets(before, after) {
  const beforeSet = new Set(before);
  const afterSet = new Set(after);
  return {
    added: [...afterSet].filter((value) => !beforeSet.has(value)).sort(),
    removed: [...beforeSet].filter((value) => !afterSet.has(value)).sort()
  };
}

function operations(openapi) {
  const map = new Map();
  const methods = new Set(["get", "put", "post", "delete", "options", "head", "patch", "trace"]);
  for (const [route, pathItem] of Object.entries(openapi?.paths ?? {})) {
    for (const [method, operation] of Object.entries(pathItem ?? {})) {
      if (methods.has(method.toLowerCase())) {
        map.set(`${method.toUpperCase()} ${route}`, { operation, pathItem });
      }
    }
  }
  return map;
}

function schemas(openapi) {
  return openapi?.components?.schemas ?? {};
}

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function tightenedSchemaConstraints(beforeField, afterField) {
  const changes = [];
  if (stableJson(beforeField?.type) !== stableJson(afterField?.type)) {
    changes.push(`type changed from ${stableJson(beforeField?.type)} to ${stableJson(afterField?.type)}`);
  }

  for (const key of ["minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties"]) {
    const beforeValue = beforeField?.[key];
    const afterValue = afterField?.[key];
    if (typeof afterValue === "number" && (typeof beforeValue !== "number" || afterValue > beforeValue)) {
      changes.push(`${key} increased from ${beforeValue ?? "unset"} to ${afterValue}`);
    }
  }
  for (const key of ["maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties"]) {
    const beforeValue = beforeField?.[key];
    const afterValue = afterField?.[key];
    if (typeof afterValue === "number" && (typeof beforeValue !== "number" || afterValue < beforeValue)) {
      changes.push(`${key} decreased from ${beforeValue ?? "unset"} to ${afterValue}`);
    }
  }

  if (Array.isArray(afterField?.enum)) {
    if (!Array.isArray(beforeField?.enum)) changes.push("enum restriction added");
    else {
      const removedValues = beforeField.enum.filter((value) => !afterField.enum.some((candidate) => stableJson(candidate) === stableJson(value)));
      if (removedValues.length) changes.push(`enum values removed: ${removedValues.map(stableJson).join(", ")}`);
    }
  }
  for (const key of ["pattern", "format", "const"]) {
    if (afterField?.[key] !== undefined && stableJson(beforeField?.[key]) !== stableJson(afterField[key])) {
      changes.push(`${key} added or changed`);
    }
  }
  if (afterField?.additionalProperties === false && beforeField?.additionalProperties !== false) {
    changes.push("additionalProperties changed to false");
  }
  return changes;
}

function requiredParameters(entry) {
  const parameters = [...(entry?.pathItem?.parameters ?? []), ...(entry?.operation?.parameters ?? [])];
  const required = parameters
    .filter((parameter) => parameter?.required === true)
    .map((parameter) => parameter.$ref ? `ref ${parameter.$ref}` : `${parameter.in ?? "unknown"} ${parameter.name ?? "unnamed"}`);
  if (entry?.operation?.requestBody?.required === true) required.push("body requestBody");
  return [...new Set(required)].sort();
}

function list(lines, items, empty = "None.") {
  if (!items.length) lines.push(`- ${empty}`);
  else for (const item of items) lines.push(`- \`${item}\``);
}

function buildSummary(before, after, diffPath) {
  const beforeOperations = operations(before);
  const afterOperations = operations(after);
  const operationDiff = compareSets([...beforeOperations.keys()], [...afterOperations.keys()]);
  const beforeSchemas = schemas(before);
  const afterSchemas = schemas(after);
  const schemaDiff = compareSets(Object.keys(beforeSchemas), Object.keys(afterSchemas));
  const responseCodesAdded = [];
  const responseCodesRemoved = [];
  const requiredParametersAdded = [];
  const requiredParametersRemoved = [];
  const schemaFieldsAdded = [];
  const schemaFieldsRemoved = [];
  const schemaFieldsChanged = [];
  const schemaConstraintsTightened = [];
  const requiredFieldsAdded = [];
  const requiredFieldsRemoved = [];

  for (const operationName of [...beforeOperations.keys()].filter((name) => afterOperations.has(name)).sort()) {
    const beforeEntry = beforeOperations.get(operationName);
    const afterEntry = afterOperations.get(operationName);
    const responseDiff = compareSets(
      Object.keys(beforeEntry.operation.responses ?? {}),
      Object.keys(afterEntry.operation.responses ?? {})
    );
    responseCodesAdded.push(...responseDiff.added.map((code) => `${operationName} -> ${code}`));
    responseCodesRemoved.push(...responseDiff.removed.map((code) => `${operationName} -> ${code}`));
    const parameterDiff = compareSets(requiredParameters(beforeEntry), requiredParameters(afterEntry));
    requiredParametersAdded.push(...parameterDiff.added.map((parameter) => `${operationName} -> ${parameter}`));
    requiredParametersRemoved.push(...parameterDiff.removed.map((parameter) => `${operationName} -> ${parameter}`));
  }

  for (const schemaName of Object.keys(beforeSchemas).filter((name) => afterSchemas[name]).sort()) {
    const beforeSchema = beforeSchemas[schemaName] ?? {};
    const afterSchema = afterSchemas[schemaName] ?? {};
    const beforeProperties = beforeSchema.properties ?? {};
    const afterProperties = afterSchema.properties ?? {};
    const fieldDiff = compareSets(Object.keys(beforeProperties), Object.keys(afterProperties));
    schemaFieldsAdded.push(...fieldDiff.added.map((field) => `${schemaName}.${field}`));
    schemaFieldsRemoved.push(...fieldDiff.removed.map((field) => `${schemaName}.${field}`));
    for (const field of Object.keys(beforeProperties).filter((name) => afterProperties[name]).sort()) {
      if (stableJson(beforeProperties[field]) !== stableJson(afterProperties[field])) {
        schemaFieldsChanged.push(`${schemaName}.${field}`);
        schemaConstraintsTightened.push(
          ...tightenedSchemaConstraints(beforeProperties[field], afterProperties[field])
            .map((change) => `${schemaName}.${field}: ${change}`)
        );
      }
    }
    const requiredDiff = compareSets(beforeSchema.required ?? [], afterSchema.required ?? []);
    requiredFieldsAdded.push(...requiredDiff.added.map((field) => `${schemaName}.${field}`));
    requiredFieldsRemoved.push(...requiredDiff.removed.map((field) => `${schemaName}.${field}`));
  }

  const breakingHints = [
    ...operationDiff.removed.map((value) => `Removed operation may break API clients: ${value}`),
    ...schemaDiff.removed.map((value) => `Removed schema may break generated clients or docs: ${value}`),
    ...schemaFieldsRemoved.map((value) => `Removed schema field may break clients: ${value}`),
    ...schemaConstraintsTightened.map((value) => `Tightened schema constraint may reject existing requests: ${value}`),
    ...requiredFieldsAdded.map((value) => `New required schema field may break existing requests: ${value}`),
    ...requiredParametersAdded.map((value) => `New required parameter may break existing requests: ${value}`),
    ...responseCodesRemoved.map((value) => `Removed documented response may break client handling: ${value}`)
  ];
  const sections = [
    ["Added Operations", operationDiff.added],
    ["Removed Operations", operationDiff.removed],
    ["Added Schemas", schemaDiff.added],
    ["Removed Schemas", schemaDiff.removed],
    ["Added Response Codes", responseCodesAdded],
    ["Removed Response Codes", responseCodesRemoved],
    ["Added Required Parameters", requiredParametersAdded],
    ["Removed Required Parameters", requiredParametersRemoved],
    ["Added Schema Fields", schemaFieldsAdded],
    ["Removed Schema Fields", schemaFieldsRemoved],
    ["Changed Schema Field Definitions", schemaFieldsChanged],
    ["Tightened Schema Constraints", schemaConstraintsTightened],
    ["Newly Required Schema Fields", requiredFieldsAdded],
    ["No Longer Required Schema Fields", requiredFieldsRemoved]
  ];
  const lines = [
    "# OpenAPI Drift Summary",
    "",
    `- Raw diff: \`${diffPath.replaceAll("\\", "/")}\``,
    `- Operations before: ${beforeOperations.size}`,
    `- Operations after: ${afterOperations.size}`,
    `- Schemas before: ${Object.keys(beforeSchemas).length}`,
    `- Schemas after: ${Object.keys(afterSchemas).length}`,
    `- Potential breaking changes: ${breakingHints.length ? "yes" : "none detected"}`
  ];
  for (const [heading, items] of sections) {
    lines.push("", `## ${heading}`, "");
    list(lines, items);
  }
  lines.push("", "## Breaking Change Hints", "");
  if (breakingHints.length) list(lines, breakingHints);
  else lines.push("- No operation, schema, field, constraint, response-code, or required-parameter breaking hints detected.");
  return `${lines.join("\n")}\n`;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const before = readJson(args["--before"]);
  const after = readJson(args["--after"]);
  const summary = buildSummary(before, after, args["--diff"]);
  fs.mkdirSync(path.dirname(args["--summary"]), { recursive: true });
  fs.writeFileSync(args["--summary"], summary, "utf8");
}

main();
