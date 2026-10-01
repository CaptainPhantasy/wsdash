import tempfile, subprocess, unittest
from pathlib import Path
from wsdash.discover import find_workspaces
class RootDiscoveryTests(unittest.TestCase):
 def test_repo_root_itself_is_discovered(self):
  with tempfile.TemporaryDirectory() as td:
   subprocess.run(["git","init","-q",td],check=True)
   found=find_workspaces({"roots":[td],"editor_workspace_globs":[]})
   self.assertTrue(any(w["path"]==str(Path(td).resolve()) and w["kind"]=="repo" for w in found.values()))
