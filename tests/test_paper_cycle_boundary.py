import json
import subprocess
import sys
import unittest


class PaperCycleBoundaryTests(unittest.TestCase):
    def test_import_does_not_load_adk(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json, sys; import chrysopoeia.paper_cycle; "
                "print(json.dumps(sorted(name for name in sys.modules if name == 'google.adk' or name.startswith('google.adk.'))))",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(json.loads(result.stdout), [])

    def test_agent_edge_uses_paper_cycle_contracts_without_reexporting_them(
        self,
    ) -> None:
        from chrysopoeia import agent, paper_cycle

        self.assertIs(agent.trader_agent.output_schema, paper_cycle.ProposalOutput)
        self.assertIs(agent.reviewer_agent.output_schema, paper_cycle.ReviewOutput)
        for moved_name in (
            "ProposalOutput",
            "ReviewOutput",
            "PaperCycleRequest",
            "finalize_paper_cycle",
        ):
            self.assertFalse(hasattr(agent, moved_name))


if __name__ == "__main__":
    unittest.main()
