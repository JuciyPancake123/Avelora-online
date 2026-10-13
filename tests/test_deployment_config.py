"""Guard against deployment variable typos and wrong port defaults."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1]

class DeploymentConfigurationTests(unittest.TestCase):
    def test_docker_defaults_match_server(self):
        docker=(BASE/'Dockerfile').read_text()
        server=(BASE/'server.py').read_text()
        for var in ('AVELORA_ONLINE','AVELORA_DATA_DIR','AVELORA_DM_PASSWORD'):
            self.assertIn(var,server)
        self.assertIn('AVELORA_ONLINE=1',docker)
        self.assertIn('AVELORA_DATA_DIR=/data',docker)
        self.assertIn('PORT=8080',docker)
        self.assertNotIn('AVALORA_',docker)
        self.assertNotIn('AVALORA_',server)

    def test_missing_password_explains_correct_name(self):
        with tempfile.TemporaryDirectory() as td:
            env={**os.environ,'AVELORA_ONLINE':'1','AVELORA_DATA_DIR':td}
            env.pop('AVELORA_DM_PASSWORD',None)
            proc=subprocess.run(['python3','server.py','--no-browser'],cwd=BASE,env=env,capture_output=True,text=True,timeout=8)
            self.assertNotEqual(proc.returncode,0)
            self.assertIn('AVELORA_DM_PASSWORD',proc.stderr)
            self.assertNotIn('AVALORA_DM_PASSWORD',proc.stderr)

if __name__=='__main__':unittest.main()
