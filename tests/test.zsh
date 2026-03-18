#!/bin/zsh

SCRIPT_DIR="$(dirname ${0:A})"
PROJECT_DIR="$(dirname ${SCRIPT_DIR})"
OUTPUT_FILE="${SCRIPT_DIR}/test_results.txt"

echo "Running tests in: ${SCRIPT_DIR}"
echo "Outputting results to: ${OUTPUT_FILE}"
echo "---------------------------------------------------"
echo ""
echo "Usage:"
echo "  tests/test.zsh                    # Run all tests"
echo "  tests/test.zsh unit               # Unit tests only"
echo "  tests/test.zsh integration        # Integration tests only"
echo "  tests/test.zsh search             # Search feature tests"
echo "  tests/test.zsh sync               # Sync feature tests"
echo "  tests/test.zsh qdrant             # Qdrant feature tests"
echo "  tests/test.zsh reconcile          # Reconciliation tests"
echo "  tests/test.zsh export             # Export feature tests"
echo "  tests/test.zsh settings           # Settings tests"
echo "  tests/test.zsh json_output        # JSON output tests"
echo ""
echo "Environment variables:"
echo "  NOTES_TEST_LIMIT=10               # Limit items per test (default: 10, 0=unlimited)"
echo "---------------------------------------------------"

pushd "${PROJECT_DIR}" > /dev/null

if [[ -n "$1" ]]; then
    echo "Running: pytest -m $1 -v"
    pytest -m "$1" -v > "${OUTPUT_FILE}" 2>&1
else
    echo "Running: pytest -v (all tests)"
    pytest -v > "${OUTPUT_FILE}" 2>&1
fi

EXIT_CODE=$?

popd > /dev/null

echo "---------------------------------------------------"
# Show summary line from results
tail -1 "${OUTPUT_FILE}"
echo "Test run complete. Results written to ${OUTPUT_FILE}"
exit $EXIT_CODE
