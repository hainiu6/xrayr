"""Isolated installer flow tests: only fixture files and substitute commands are used."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]

MOCK = r'''#!/usr/bin/python3
import json, os, pathlib, shutil, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
root = pathlib.Path(os.environ['QA_ROOT'])
statefile = root / 'state.json'
s = json.loads(statefile.read_text())
code = 0
if name == 'uname':
    print(os.environ.get('QA_ARCH', 'x86_64'))
elif name == 'curl':
    url = next(a for a in args if a.startswith('https://'))
    s.setdefault('download_urls', []).append(url)
    target = pathlib.Path(args[args.index('--output') + 1])
    src = root / 'fixtures' / url.rsplit('/', 1)[1]
    if not src.exists(): sys.exit(22)
    shutil.copyfile(src, target)
elif name == 'sha256sum':
    import hashlib
    expected, target = sys.stdin.read().strip().split(None, 1)
    code = int(hashlib.sha256(pathlib.Path(target.strip()).read_bytes()).hexdigest() != expected)
elif name == 'systemctl':
    cmd = args[0]
    if cmd == 'is-enabled':
        print(s['enabled']); code = int(s['enabled'] != 'enabled')
    elif cmd == 'is-active': code = int(not s['active'])
    elif cmd == 'show': print(42 if s['active'] else 0)
    elif cmd == 'enable': s['enabled'] = 'enabled'
    elif cmd == 'disable': s['enabled'] = 'disabled'
    elif cmd == 'stop': s['active'] = False
    elif cmd == 'start': s['active'] = True
    elif cmd == 'restart':
        s['active'] = not s['fail_once']
        s['fail_once'] = False
elif name == 'docker':
    if args[:2] == ['container', 'inspect']: code = int(not s['docker_exists'])
    elif args[0] == 'inspect':
        field = args[args.index('--format') + 1]
        if 'Running' in field: print(str(s['docker_active']).lower())
        elif 'MaximumRetryCount' in field: print(3)
        else: print(s['docker_policy'])
    elif args[0] == 'update': s['docker_policy'] = args[1].split('=', 1)[1]
    elif args[0] == 'stop': s['docker_active'] = False
    elif args[0] == 'start': s['docker_active'] = True
elif name == 'journalctl': print('QA: simulated startup failure')
statefile.write_text(json.dumps(s))
sys.exit(code)
'''


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='xrayr-qa-')
        self.root = Path(self.tmp.name)
        self.fixture = self.root / 'fixtures'
        self.fixture.mkdir()
        self.mockbin = self.root / 'mockbin'
        self.mockbin.mkdir()
        for cmd in ['curl', 'sha256sum', 'systemctl', 'docker', 'uname', 'apt-get', 'flock', 'sleep', 'journalctl']:
            p = self.mockbin / cmd
            p.write_text(MOCK)
            p.chmod(0o755)
        # Deliberately invalid, unrelated contents: installer only checks existence.
        (self.fixture / 'test.haima.us.pem').write_text('unvalidated certificate fixture\n')
        (self.fixture / 'test.haima.us.key').write_text('unvalidated private key fixture\n')
        (self.fixture / 'config.yml').write_text('Log:\n  Level: warning\nNodes: []\n')
        self.programzip = self.root / 'XrayR-linux-64.zip'
        with zipfile.ZipFile(self.programzip, 'w') as z:
            z.writestr('XrayR', '#!/bin/sh\nexit 0\n')
            for f in ['geoip.dat', 'geosite.dat', 'LICENSE', 'custom_inbound.json', 'custom_outbound.json']:
                z.writestr(f, '{}\n')
        shutil.copyfile(self.programzip, self.root / 'XrayR-linux-arm64-v8a.zip')
        sha = hashlib.sha256(self.programzip.read_bytes()).hexdigest()
        script = (ROOT / 'install-xrayr.sh').read_text()
        self.cfg = self.root / 'etc/XrayR'
        self.bin = self.root / 'usr/local/XrayR'
        self.unit = self.root / 'etc/systemd/system/XrayR.service'
        self.unit.parent.mkdir(parents=True)
        self.backups = self.root / 'backups'
        for before, after in [('/etc/XrayR', str(self.cfg)),
                              ('/usr/local/XrayR', str(self.bin)),
                              ('/etc/systemd/system/XrayR.service', str(self.unit)),
                              ('/var/backups/XrayR-native', str(self.backups)),
                              ('/run/lock/xrayr-native-install.lock', str(self.root / 'install.lock')),
                              ('/run/systemd/system', str(self.unit.parent)),
                              ('/etc/os-release', str(self.root / 'os-release'))]:
            script = script.replace(before, after)
        script = script.replace('[[ "$EUID" -eq 0 ]]', 'true')
        script = script.replace('ad06efe7ca3c19ea20817fb2aa163185f012433d97f8d4cc30eff30ca02bc5b4', sha)
        script = script.replace('2c2fa9dbc282f30caecaa026319927f6f0a4492f576239fa59c490abd2076558', sha)
        self.script = self.root / 'install-xrayr.sh'
        self.script.write_text(script)
        (self.root / 'os-release').write_text(
            'PRETTY_NAME="Debian GNU/Linux 12 (bookworm)"\n'
            'NAME="Debian GNU/Linux"\nVERSION_ID="12"\n'
            'VERSION="12 (bookworm)"\nVERSION_CODENAME=bookworm\nID=debian\n')
        self.statefile = self.root / 'state.json'
        self.statefile.write_text(json.dumps(dict(active=False, enabled='disabled', fail_once=False,
                                                  docker_exists=False, docker_active=False, docker_policy='always')))
        self.env = dict(os.environ, PATH=str(self.mockbin) + ':' + os.environ['PATH'], QA_ROOT=str(self.root))

    def tearDown(self):
        self.tmp.cleanup()

    def state(self, **update):
        data = json.loads(self.statefile.read_text())
        data.update(update)
        self.statefile.write_text(json.dumps(data))
        return data

    def run_installer(self, *args):
        return subprocess.run(['/bin/bash', str(self.script), *args], env=self.env,
                              capture_output=True, text=True, errors='replace')

    def old_install(self):
        (self.cfg / 'cert').mkdir(parents=True)
        for name in ['test.haima.us.pem', 'test.haima.us.key']:
            shutil.copyfile(self.fixture / name, self.cfg / 'cert' / name)
        (self.cfg / 'config.yml').write_text('Nodes: []\n# old customized configuration\n')
        (self.cfg / 'dns.json').write_text('{"custom":true}\n')
        self.bin.mkdir(parents=True)
        (self.bin / 'XrayR').write_text('old-binary')
        self.unit.write_text('old-unit')
        self.state(active=True, enabled='enabled')

    def test_fresh_install(self):
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.state()['active'])
        self.assertEqual(self.state()['enabled'], 'enabled')
        self.assertEqual((self.cfg / 'config.yml').stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.cfg / 'cert/test.haima.us.key').stat().st_mode & 0o777, 0o600)
        self.assertIn('ExecStart=' + str(self.bin / 'XrayR') + ' --config ' + str(self.cfg / 'config.yml'),
                      self.unit.read_text())

    def test_reinstall_preserves_custom_config_and_auxiliary(self):
        self.old_install()
        old = (self.cfg / 'config.yml').read_bytes()
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.cfg / 'config.yml').read_bytes(), old)
        self.assertEqual((self.cfg / 'dns.json').read_text(), '{"custom":true}\n')
        self.assertEqual(next(self.backups.glob('*/bin/XrayR')).read_text(), 'old-binary')

    def test_failed_refresh_restores_original_files_and_service(self):
        self.old_install()
        old = (self.cfg / 'config.yml').read_bytes()
        self.state(fail_once=True)
        result = self.run_installer('--refresh')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.cfg / 'config.yml').read_bytes(), old)
        self.assertEqual((self.bin / 'XrayR').read_text(), 'old-binary')
        self.assertEqual(self.unit.read_text(), 'old-unit')
        self.assertTrue(self.state()['active'])
        self.assertEqual(self.state()['enabled'], 'enabled')

    def test_failed_first_install_removes_new_files(self):
        self.state(fail_once=True)
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.cfg.exists())
        self.assertFalse(self.bin.exists())
        self.assertFalse(self.unit.exists())
        self.assertEqual(self.state()['enabled'], 'disabled')

    def test_checksum_failure_keeps_old_install_untouched(self):
        self.old_install()
        self.programzip.write_bytes(b'bad archive')
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.state()['active'])
        self.assertEqual((self.bin / 'XrayR').read_text(), 'old-binary')
        self.assertFalse(self.backups.exists())

    def test_docker_requires_explicit_migration(self):
        self.state(docker_exists=True, docker_active=True)
        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--migrate-docker', result.stderr)
        self.assertTrue(self.state()['docker_active'])

    def test_failed_migration_restores_container_and_policy(self):
        self.state(docker_exists=True, docker_active=True, docker_policy='on-failure', fail_once=True)
        result = self.run_installer('--migrate-docker')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.state()['docker_active'])
        self.assertEqual(self.state()['docker_policy'], 'on-failure:3')

    def test_arm64_install(self):
        self.env['QA_ARCH'] = 'aarch64'
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('XrayR-linux-arm64-v8a.zip', result.stdout)

    def test_ubuntu_os_release_does_not_overwrite_installer_version(self):
        (self.root / 'os-release').write_text(
            'NAME="Ubuntu"\nVERSION="24.04.3 LTS (Noble Numbat)"\n'
            'ID=ubuntu\nID_LIKE=debian\nVERSION_ID="24.04"\n'
            'VERSION_CODENAME=noble\nUBUNTU_CODENAME=noble\n')
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('原生 XrayR v0.9.4', result.stdout)
        self.assertTrue(self.state()['active'])

    def test_empty_certificate_files_are_accepted_by_installer(self):
        (self.fixture / 'test.haima.us.pem').write_bytes(b'')
        (self.fixture / 'test.haima.us.key').write_bytes(b'')
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.cfg / 'cert/test.haima.us.pem').is_file())
        self.assertEqual((self.cfg / 'cert/test.haima.us.key').read_bytes(), b'')

    def test_missing_certificate_stops_before_modifying_existing_install(self):
        self.old_install()
        (self.fixture / 'test.haima.us.pem').unlink()
        result = self.run_installer('--refresh')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.bin / 'XrayR').read_text(), 'old-binary')
        self.assertTrue(self.state()['active'])
        self.assertFalse(self.backups.exists())

    def test_custom_download_urls_are_used(self):
        urls = {
            'XRAYR_CONFIG_URL': 'https://custom.example/config.yml',
            'XRAYR_CERT_URL': 'https://custom.example/test.haima.us.pem',
            'XRAYR_KEY_URL': 'https://custom.example/test.haima.us.key',
        }
        self.env.update(urls)
        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.state()['download_urls'], list(urls.values()))


if __name__ == '__main__':
    unittest.main(verbosity=2)
