import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / ".agents" / "skills"


class DeliverySkillContractTest(unittest.TestCase):
    skill_names = {
        "itom-task-routing",
        "itom-fix-delivery",
        "itom-feature-delivery",
        "itom-code-candidate-delivery",
    }

    def read_skill(self, name: str) -> str:
        return (SKILL_ROOT / name / "SKILL.md").read_text(encoding="utf-8")

    def test_repository_skills_use_auto_discovery_layout(self):
        for name in self.skill_names:
            skill = SKILL_ROOT / name / "SKILL.md"
            metadata = SKILL_ROOT / name / "agents" / "openai.yaml"
            self.assertTrue(skill.is_file(), name)
            self.assertTrue(metadata.is_file(), name)
            self.assertIn(f"name: {name}", skill.read_text(encoding="utf-8"))
            self.assertIn(f"${name}", metadata.read_text(encoding="utf-8"))

        self.assertFalse((ROOT / "skills" / "itom-fix-delivery" / "SKILL.md").exists())
        self.assertFalse((ROOT / "skills" / "itom-feature-delivery" / "SKILL.md").exists())

    def test_router_requires_exactly_three_routes_before_mutation(self):
        router = self.read_skill("itom-task-routing")
        numbered = re.findall(
            r"^\d\. `(production-fix|feature-local|code-candidate)`:",
            router,
            flags=re.MULTILINE,
        )
        self.assertEqual(numbered, ["production-fix", "feature-local", "code-candidate"])
        self.assertIn("Wait for an explicit selection", router)
        self.assertIn("Do not edit, start or stop an environment", router)

    def test_feature_route_holds_runtime_for_user_uat(self):
        feature = self.read_skill("itom-feature-delivery")
        normalized = " ".join(feature.split())
        for contract in (
            "Treat `local-candidate-ready` as the start of the user's acceptance window",
            "Keep the application containers, database, volumes",
            "do not run `docker compose stop` or `down`",
            "local acceptance still does not authorize IDC",
            "Preserve volumes and acceptance data",
        ):
            self.assertIn(contract, normalized)

    def test_production_and_code_candidate_boundaries(self):
        production = self.read_skill("itom-fix-delivery")
        candidate = self.read_skill("itom-code-candidate-delivery")
        self.assertIn("completion target is the repaired real IDC workflow", production)
        self.assertIn("explicit authorization with `approve-idc`", production)
        self.assertIn("Do not start, stop, restart", candidate)
        self.assertIn("cannot call `approve-idc`", candidate)

    def test_agents_references_discoverable_skills(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertNotIn("`skills/itom-", agents)
        for name in self.skill_names:
            self.assertIn(f".agents/skills/{name}/SKILL.md", agents)

    def test_quality_gate_discovers_every_repository_contract_test(self):
        workflow = (ROOT / ".github" / "workflows" / "quality-gate.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "python -m unittest discover -s scripts/tests -p 'test_*.py'",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
