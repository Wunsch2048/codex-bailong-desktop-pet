"""The CLI may live inside CODEX_HOME, which the sandbox deliberately hides."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class ReadonlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('bwrap'):
            raise unittest.SkipTest('bubblewrap is not installed')
        probe = subprocess.run(['bwrap', '--ro-bind', '/', '/', '/bin/true'], capture_output=True, timeout=5)
        if probe.returncode:
            raise unittest.SkipTest('host does not permit bubblewrap user namespaces')

    def check_installation(self, home, installation):
        home.mkdir(parents=True, exist_ok=True)
        config = home / 'config.toml'
        auth = home / 'auth.json'
        config.write_text('synthetic-test-config\n')
        auth.write_text('synthetic-test-auth\n')
        binary = installation / 'bin/codex'
        binary.parent.mkdir(parents=True)
        (installation / 'lib').mkdir()
        (installation / 'bin/helper').write_text('''#!/bin/sh
exec "$(dirname "$0")/../lib/helper"
''')
        (installation / 'bin/helper').chmod(0o755)
        (installation / 'lib/helper').write_text('''#!/bin/sh
set -eu
test "$(cat "$(dirname "$0")/resource")" = synthetic-resource
echo sandbox-ok
''')
        (installation / 'lib/helper').chmod(0o755)
        (installation / 'lib/resource').write_text('synthetic-resource\n')
        binary.write_text('''#!/bin/sh
set -eu
test "$0" = "$BAILONG_NATIVE_CODEX"
test "$1" = -c
test "$3" = app-server
test "$(cat "$CODEX_HOME/config.toml")" = synthetic-test-config
test "$(cat "$CODEX_HOME/auth.json")" = synthetic-test-auth
if (echo changed > "$CODEX_HOME/config.toml") 2>/dev/null; then exit 23; fi
if (echo changed > "$CODEX_HOME/auth.json") 2>/dev/null; then exit 24; fi
if (echo changed > "$(dirname "$0")/../lib/resource") 2>/dev/null; then exit 25; fi
echo runtime > "$CODEX_HOME/runtime-test"
exec "$(dirname "$0")/helper"
''')
        binary.chmod(0o755)
        result = self.run_wrapper(home, binary)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'sandbox-ok')
        self.assertEqual(config.read_text(), 'synthetic-test-config\n')
        self.assertEqual(auth.read_text(), 'synthetic-test-auth\n')
        self.assertEqual((installation / 'lib/resource').read_text(), 'synthetic-resource\n')
        self.assertFalse((home / 'runtime-test').exists())

    def run_wrapper(self, home, binary):
        wrapper = Path(__file__).resolve().parents[1] / 'linux_app/codex_readonly'
        env = dict(os.environ, CODEX_HOME=str(home), BAILONG_NATIVE_CODEX=str(binary), BAILONG_FROZEN='0')
        return subprocess.run([str(wrapper), 'app-server'], env=env, capture_output=True, text=True, timeout=10)

    def test_external_launcher_keeps_original_path_and_neighbor_resources(self):
        with tempfile.TemporaryDirectory(prefix='bailong-sandbox-test-', dir=Path.home()) as folder:
            root = Path(folder)
            self.check_installation(root / 'home', root / 'installation with spaces')

    def test_hidden_home_preserves_complete_installation_subtree(self):
        with tempfile.TemporaryDirectory(prefix='bailong-sandbox-test-', dir=Path.home()) as folder:
            home = Path(folder) / 'home'
            self.check_installation(home, home / 'packages/standalone/version')

    def test_temporary_installation_keeps_original_path(self):
        with tempfile.TemporaryDirectory(prefix='bailong-sandbox-test-') as folder:
            root = Path(folder)
            self.check_installation(root / 'home', root / 'installation')

    def test_home_root_launcher_is_rejected_without_running_it(self):
        with tempfile.TemporaryDirectory(prefix='bailong-sandbox-test-', dir=Path.home()) as folder:
            home = Path(folder)
            binary = home / 'codex'
            binary.write_text('#!/bin/sh\necho should-not-run\n')
            binary.chmod(0o755)
            result = self.run_wrapper(home, binary)
            self.assertEqual(result.returncode, 2)
            self.assertIn('完整 CLI 安装目录', result.stderr)
            self.assertEqual(result.stdout, '')
