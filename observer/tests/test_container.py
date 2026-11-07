import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


class ContainerContractTests(unittest.TestCase):
    def test_image_installs_locked_dependencies_before_wheel_and_serves_one_worker(
        self,
    ) -> None:
        dockerfile = (ROOT / "Dockerfile").read_text()

        locked = "pip install --no-cache-dir --no-deps -r /tmp/observer/requirements.txt"
        wheel = "pip install --no-cache-dir --no-deps /tmp/*.whl"
        self.assertIn(locked, dockerfile)
        self.assertIn(wheel, dockerfile)
        self.assertLess(dockerfile.index(locked), dockerfile.index(wheel))
        self.assertIn('"observer.app:app"', dockerfile)
        self.assertIn('"--port", "8080"', dockerfile)
        self.assertIn('"--workers", "1"', dockerfile)

    def test_build_is_local_only_and_context_is_whitelisted(self) -> None:
        build = (ROOT / "build.sh").read_text()
        ignore = (ROOT / ".dockerignore").read_text()

        self.assertIn("uv build", build)
        self.assertIn("uv export --frozen --no-dev --no-emit-project", build)
        self.assertIn("docker build --platform linux/amd64", build)
        self.assertIn("--network none", build)
        self.assertIn("import observer.app", build)
        self.assertNotIn("docker push", build)
        self.assertEqual(
            ignore.split(), ["*", "!Dockerfile", "!dist/*.whl", "!.build/requirements.txt"]
        )
