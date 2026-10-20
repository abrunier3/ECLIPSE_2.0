import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("git"), "Git is required")
class GraphWorkflowGitTests(unittest.TestCase):
    def test_graph_push_handles_unstaged_install_metadata_and_remote_updates(self):
        workflow = (ROOT / ".github/workflows/run_graph.yml").read_text()
        step = workflow.split("      - name: Commit parsed JSON + graph output", 1)[1]
        commit_script = textwrap.dedent(step.split("        run: |\n", 1)[1])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "remote.git"
            worker = root / "worker"
            contributor = root / "contributor"
            environment = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1",
                           "GIT_CONFIG_GLOBAL": os.devnull,
                           "BRANCH_NAME": "main", "SCENARIO_NAME": "Demo"}

            def git(*arguments, cwd=root):
                return subprocess.run(
                    ["git", *arguments], cwd=cwd, env=environment,
                    check=True, capture_output=True, text=True,
                ).stdout.strip()

            git("init", "--bare", "--initial-branch=main", str(remote))
            git("clone", str(remote), str(worker))
            git("config", "user.name", "Test", cwd=worker)
            git("config", "user.email", "test@example.invalid", cwd=worker)
            for path in ("outputs/graph.json", "outputs/scenarios/Demo/graph.json",
                         "clean_database/json/Demo/Demo.json", "S24.egg-info/SOURCES.txt"):
                file = worker / path
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text("baseline\n")
            git("add", ".", cwd=worker)
            git("commit", "-m", "baseline", cwd=worker)
            git("push", "origin", "main", cwd=worker)

            # Another user pushes after the workflow has checked out the branch.
            git("clone", str(remote), str(contributor))
            git("config", "user.name", "Contributor", cwd=contributor)
            git("config", "user.email", "contributor@example.invalid", cwd=contributor)
            (contributor / "README.md").write_text("Concurrent update\n")
            git("add", "README.md", cwd=contributor)
            git("commit", "-m", "concurrent update", cwd=contributor)
            git("push", "origin", "main", cwd=contributor)

            # Reproduce graph generation plus pip's unstaged packaging changes.
            for path in ("outputs/graph.json", "outputs/scenarios/Demo/graph.json",
                         "clean_database/json/Demo/Demo.json"):
                (worker / path).write_text("generated\n")
            (worker / "S24.egg-info/SOURCES.txt").write_text("installed metadata\n")
            subprocess.run(
                ["bash", "-e", "-o", "pipefail", "-c", commit_script],
                cwd=worker, env=environment, check=True, capture_output=True, text=True,
            )

            # Only graph outputs were pushed; both the remote update and local
            # install metadata survive the actual workflow's commit/rebase step.
            self.assertEqual(git("show", "main:outputs/graph.json", cwd=remote), "generated")
            self.assertEqual(git("show", "main:outputs/scenarios/Demo/graph.json", cwd=remote), "generated")
            self.assertEqual(git("show", "main:clean_database/json/Demo/Demo.json", cwd=remote), "generated")
            self.assertEqual(git("show", "main:README.md", cwd=remote), "Concurrent update")
            self.assertEqual(git("show", "main:S24.egg-info/SOURCES.txt", cwd=remote), "baseline")
            self.assertEqual((worker / "S24.egg-info/SOURCES.txt").read_text(), "installed metadata\n")
            self.assertEqual(git("stash", "list", cwd=worker), "")


if __name__ == "__main__":
    unittest.main()
