'use strict';
// notes-exporter's test tiers, for the common ikt runner (@storizzi/ikt/runtime/tiers in the
// sibling apps/server/ikt repo). Nothing but the opt-in `live` tier reaches Apple Notes, launchd or a real export:
// every exporter run uses tests/fake_osascript.py or tests/service/fake_exporter.py, and every
// test works in its own temporary HOME and export folder.
//
//   node scripts/test-all.js [tier…|--list]        # or, from anywhere:  ikt test notes-exporter [tier…]
//
// Python: NOTES_EXPORTER_TEST_PYTHON, else the repo's .venv (python3 -m venv .venv &&
// .venv/bin/pip install -r requirements.txt).

const fs = require('fs');
const path = require('path');

module.exports = (ikt) => {
  const python = process.env.NOTES_EXPORTER_TEST_PYTHON || path.join(ikt.root, '.venv/bin/python');
  const noPython = () => (!fs.existsSync(python) ? `no ${python} (python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)` : null);
  const noService = () => noPython() || (!ikt.ok(`"${python}" -c "import fastapi, uvicorn, bcrypt, jwt, httpx"`)
    ? 'the service dependencies are not installed (.venv/bin/pip install -r requirements.txt)' : null);
  const pytest = (args, junit) => ikt.cmd(python, ['-m', 'pytest', '-q', '-p', 'no:cacheprovider', ...args,
    `--junitxml=${path.join(ikt.root, 'test-results', junit)}`]);
  return {
    name: 'notes-exporter',
    description: 'notes-exporter — Apple Notes exporter (zsh + AppleScript + Python) and its HTTP service',
    required: ['unit', 'service', 'e2e'],
    tiers: [
      {
        id: 'unit', label: 'Exporter tests (pytest; exportnotes.zsh end to end with the fake osascript)',
        skip: noPython,
        run: pytest(['tests', '--ignore=tests/service', '--ignore=tests/e2e'], 'pytest-unit.xml'),
        junit: ['test-results/pytest-unit.xml'],
      },
      {
        id: 'service', label: 'Service API tests (FastAPI TestClient, fake exporter, fake launchctl)',
        skip: noService,
        run: pytest(['tests/service'], 'pytest-service.xml'),
        junit: ['test-results/pytest-service.xml'],
      },
      {
        id: 'e2e', label: 'Service end to end (real server on a free port, driven over HTTP with an API key)',
        skip: noService,
        run: pytest(['tests/e2e'], 'pytest-e2e.xml'),
        junit: ['test-results/pytest-e2e.xml'],
      },
      {
        id: 'epubcheck', label: 'EPUB validation with epubcheck (optional: brew install epubcheck)',
        skip: () => noPython() || (!ikt.ok('command -v epubcheck') ? 'epubcheck not installed' : null),
        run: pytest(['tests/test_epub.py', '-k', 'epubcheck'], 'pytest-epubcheck.xml'),
        junit: ['test-results/pytest-epubcheck.xml'],
      },
      {
        // Opt in: this one DOES read the real Apple Notes, through the running service.
        id: 'live', label: 'Live export through the running service (opt in: NOTES_EXPORTER_LIVE=1; prints counts only)',
        skip: () => noService() || (process.env.NOTES_EXPORTER_LIVE !== '1'
          ? 'opt in with NOTES_EXPORTER_LIVE=1 (reads the real Notes through the running service)' : null),
        run: ikt.cmd(python, [path.join(ikt.root, 'scripts', 'live_check.py')]),
      },
    ],
  };
};
