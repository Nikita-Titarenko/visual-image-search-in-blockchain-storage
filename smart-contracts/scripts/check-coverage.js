const fs = require("fs");
const path = require("path");

const COVERAGE_THRESHOLD = 85;
const coveragePath = path.resolve(__dirname, "..", "coverage.json");

function percentage(covered, total) {
  if (total === 0) {
    return 100;
  }
  return Math.round((covered / total) * 10000) / 100;
}

function accumulateTotals(coverageData) {
  const totals = {
    statements: { covered: 0, total: 0 },
    functions: { covered: 0, total: 0 },
    branches: { covered: 0, total: 0 },
    lines: { covered: 0, total: 0 }
  };

  for (const fileCoverage of Object.values(coverageData)) {
    for (const hits of Object.values(fileCoverage.s || {})) {
      totals.statements.total += 1;
      if (hits > 0) {
        totals.statements.covered += 1;
      }
    }

    for (const hits of Object.values(fileCoverage.f || {})) {
      totals.functions.total += 1;
      if (hits > 0) {
        totals.functions.covered += 1;
      }
    }

    for (const branchHits of Object.values(fileCoverage.b || {})) {
      for (const hits of branchHits) {
        totals.branches.total += 1;
        if (hits > 0) {
          totals.branches.covered += 1;
        }
      }
    }

    for (const hits of Object.values(fileCoverage.l || {})) {
      totals.lines.total += 1;
      if (hits > 0) {
        totals.lines.covered += 1;
      }
    }
  }

  return totals;
}

function main() {
  if (!fs.existsSync(coveragePath)) {
    throw new Error("coverage.json was not generated. Run the coverage task first.");
  }

  const coverageData = JSON.parse(fs.readFileSync(coveragePath, "utf8"));
  const totals = accumulateTotals(coverageData);
  const metrics = {
    statements: percentage(totals.statements.covered, totals.statements.total),
    functions: percentage(totals.functions.covered, totals.functions.total),
    branches: percentage(totals.branches.covered, totals.branches.total),
    lines: percentage(totals.lines.covered, totals.lines.total)
  };

  console.log("Coverage summary:");
  for (const [name, value] of Object.entries(metrics)) {
    console.log(`- ${name}: ${value.toFixed(2)}%`);
  }

  const failedMetrics = Object.entries(metrics).filter(([, value]) => value < COVERAGE_THRESHOLD);
  if (failedMetrics.length > 0) {
    const failedNames = failedMetrics.map(([name, value]) => `${name}=${value.toFixed(2)}%`).join(", ");
    throw new Error(`Coverage threshold of ${COVERAGE_THRESHOLD}% not met: ${failedNames}`);
  }

  console.log(`Coverage threshold satisfied: all metrics >= ${COVERAGE_THRESHOLD}%.`);
}

try {
  main();
} catch (error) {
  console.error(error.message);
  process.exit(1);
}