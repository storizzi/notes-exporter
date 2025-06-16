#!/bin/zsh

SCRIPT_DIR="$(dirname ${0:A})"
OUTPUT_FILE="${SCRIPT_DIR}/test_results.txt"

echo "Running tests in: ${SCRIPT_DIR}"
echo "Outputting results to: ${OUTPUT_FILE}"
echo "---------------------------------------------------"

pushd "${SCRIPT_DIR}" > /dev/null

pytest -v > "${OUTPUT_FILE}" 2>&1

popd > /dev/null

echo "---------------------------------------------------"
echo "Test run complete. Results written to ${OUTPUT_FILE}"
