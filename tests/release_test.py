"""scripts/release.py in a throwaway repository: the release commit, its tag and the hyprpm pin, or nothing."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/release.py'
PIN = '["efb50993780079460b0cbed1363e2166a2de1d9f", "{}"],'
FILES = {
    'CHANGELOG.md': '# Changelog\n\n## Unreleased\n\n- Cards say who manages them.\n\n## 0.3.0-rc.26 — 2026-11-18\n\n- Before.\n',
    'README.md': 'Native dwindle cards are available in the **0.3.0-rc.26 preview**. The five-app\n',
    'docs/BETA.md': 'try [Hyprflip 0.3.0-rc.26](https://github.com/nocstah/hyprflip/releases/tag/v0.3.0-rc.26).\n'
                    'git clone --branch v0.3.0-rc.26 https://github.com/nocstah/hyprflip.git\n',
    'TESTING.md': '# Validation\n\n## Card owners; release checks for 0.3.0-rc.27 (2026-11-18)\n\nChecked.\n\n'
                  '## Release checks for 0.3.0-rc.26 (2026-11-18)\n\nBefore.\n',
    'CMakeLists.txt': 'pkg_check_modules(HYPRLAND REQUIRED IMPORTED_TARGET hyprland=0.56.2)\n',
}


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / 'scripts').mkdir()
        shutil.copyfile(SCRIPT, self.root / 'scripts/release.py')
        for name, text in FILES.items():
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_text(text)
        self.git('init', '--quiet', '--initial-branch', 'main')
        self.git('config', 'user.name', 'Release Test')
        self.git('config', 'user.email', 'release@example.invalid')
        self.git('add', '.')
        self.git('commit', '--quiet', '-m', 'rc.26')
        self.git('tag', 'v0.3.0-rc.26')
        (self.root / 'hyprpm.toml').write_text(f'[repository]\ncommit_pins = [\n    {PIN.format(self.head())}\n]\n')
        self.git('add', 'hyprpm.toml')
        self.git('commit', '--quiet', '-m', 'Pin Hyprland 0.56.2 to 0.3.0-rc.26')
        self.before = self.head()

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True, text=True).stdout.strip()

    def head(self): return self.git('rev-parse', 'HEAD')

    def release(self, *args):
        return subprocess.run([sys.executable, str(self.root / 'scripts/release.py'), *args],
                              capture_output=True, text=True)

    def test_a_release_commits_tags_and_pins_hyprpm_to_the_tag(self):
        body = self.root.parent / (self.root.name + '-body')
        body.write_text('Cards say who manages them.\n\nCo-Authored-By: Someone <someone@example.invalid>\n')
        self.addCleanup(body.unlink)
        result = self.release('0.3.0-rc.27', '--date', '2026-11-19', '--body', str(body), '--no-test')
        self.assertEqual(result.returncode, 0, result.stderr)
        tagged = self.git('rev-parse', 'v0.3.0-rc.27^{commit}')
        self.assertEqual(self.git('log', '--format=%s', '-2').splitlines(),
                         ['Pin Hyprland 0.56.2 to 0.3.0-rc.27', 'Release Hyprflip 0.3.0-rc.27'])
        self.assertEqual(self.git('rev-parse', 'HEAD~1'), tagged)
        self.assertIn('Co-Authored-By: Someone', self.git('log', '-1', '--format=%b', tagged))
        self.assertIn(PIN.format(tagged), (self.root / 'hyprpm.toml').read_text())
        self.assertIn('## 0.3.0-rc.27 — 2026-11-19\n\n- Cards say who manages them.', (self.root / 'CHANGELOG.md').read_text())
        self.assertIn('**0.3.0-rc.27 preview**', (self.root / 'README.md').read_text())
        # The checks' section says which commit was released, ahead of the next section.
        self.assertIn(f'Checked.\n\nReleased from {self.before[:7]}. The release commit changes only the changelog, '
                      'the\nREADME, the beta guide and this note.\n\n## Release checks for 0.3.0-rc.26',
                      (self.root / 'TESTING.md').read_text())
        beta = (self.root / 'docs/BETA.md').read_text()
        self.assertNotIn('rc.26', beta)
        self.assertEqual(beta.count('0.3.0-rc.27'), 3)
        # Nothing is pushed: it says how.
        self.assertIn('git push origin HEAD:main && git push origin v0.3.0-rc.27', result.stdout)
        self.assertIn('gh release create v0.3.0-rc.27 --prerelease --verify-tag', result.stdout)
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_a_dry_run_shows_the_changes_and_makes_none(self):
        result = self.release('0.3.0-rc.27', '--date', '2026-11-19', '--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('+## 0.3.0-rc.27 — 2026-11-19', result.stdout)
        self.assertIn('+Native dwindle cards are available in the **0.3.0-rc.27 preview**', result.stdout)
        self.assertEqual((self.head(), self.git('status', '--porcelain'), self.git('tag')), (self.before, '', 'v0.3.0-rc.26'))

    def test_it_refuses_and_changes_nothing_until_the_release_is_ready(self):
        def refused(*args, why):
            result = self.release(*args, '--no-test')
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn(why, result.stderr)
            self.assertEqual((self.head(), self.git('tag')), (self.before, 'v0.3.0-rc.26'))
        refused('0.3.0-rc.28', why='TESTING.md has no heading naming 0.3.0-rc.28')
        refused('0.3.0-rc.26', why='the tag v0.3.0-rc.26 exists already')
        refused('rc.27', why='is not a version')
        (self.root / 'README.md').write_text('changed\n')
        refused('0.3.0-rc.27', why='commit or stash the changes to tracked files first')
        self.git('checkout', '--', 'README.md')
        (self.root / 'CHANGELOG.md').write_text('# Changelog\n\n## Unreleased\n\n## 0.3.0-rc.26 — 2026-11-18\n')
        self.git('commit', '--quiet', '-am', 'empty')
        self.before = self.head()
        refused('0.3.0-rc.27', why='no "## Unreleased" section with entries')
        self.assertEqual(self.git('status', '--porcelain'), '')


if __name__ == '__main__':
    unittest.main()
