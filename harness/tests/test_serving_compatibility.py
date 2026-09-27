import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class A2ACompatibilityTests(unittest.TestCase):
    def test_missing_version_uses_method_shape_and_preserves_explicit_version(self):
        from a2a.server.routes.common import DefaultServerCallContextBuilder

        from chrysopoeia.app_utils.a2a import _A2AServerCallContextBuilder

        cases = (("message/send", "0.3"), ("SendMessage", "1.0"))
        for method, expected in cases:
            context = SimpleNamespace(state={})
            request = SimpleNamespace(_json={"method": method})
            with patch.object(
                DefaultServerCallContextBuilder, "build", return_value=context
            ):
                result = _A2AServerCallContextBuilder().build(request)
            self.assertEqual(result.state["headers"]["A2A-Version"], expected)

        context = SimpleNamespace(state={"headers": {"x-a2a-version": "0.3"}})
        with patch.object(
            DefaultServerCallContextBuilder, "build", return_value=context
        ):
            result = _A2AServerCallContextBuilder().build(SimpleNamespace(_json={}))
        self.assertEqual(result.state["headers"]["A2A-Version"], "0.3")

    def test_agent_card_advertises_v0_3_compatibility(self):
        from chrysopoeia.app_utils.a2a import _add_v0_3_compat_interface

        card = SimpleNamespace(
            supported_interfaces=[SimpleNamespace(url="http://test/a2a/chrysopoeia")]
        )
        result = asyncio.run(_add_v0_3_compat_interface(card))

        self.assertIs(result, card)
        self.assertEqual(result.supported_interfaces[-1].protocol_version, "0.3")
        self.assertEqual(result.supported_interfaces[-1].protocol_binding, "JSONRPC")
        self.assertEqual(
            result.supported_interfaces[-1].url, "http://test/a2a/chrysopoeia"
        )

    def test_fastapi_app_has_no_feedback_route(self):
        from fastapi.testclient import TestClient

        from chrysopoeia.fast_api_app import app

        self.assertNotIn("/feedback", {route.path for route in app.routes})
        with TestClient(app) as client:
            response = client.get("/a2a/chrysopoeia/.well-known/agent-card.json")

        self.assertEqual(response.status_code, 200)
        interfaces = response.json()["supportedInterfaces"]
        self.assertEqual(
            {interface["protocolVersion"] for interface in interfaces},
            {"0.3", "1.0"},
        )

    def test_v0_3_jsonrpc_route_returns_compatible_error_without_agent_call(self):
        from fastapi.testclient import TestClient
        from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor

        from chrysopoeia.fast_api_app import app

        request = {
            "jsonrpc": "2.0",
            "id": "compat-03",
            "method": "tasks/get",
            "params": {"id": "missing-task"},
        }
        with patch.object(
            A2aAgentExecutor,
            "execute",
            side_effect=AssertionError("agent executor must not run"),
        ) as execute:
            with TestClient(app) as client:
                response = client.post(
                    "/a2a/chrysopoeia",
                    headers={"A2A-Version": "0.3"},
                    json=request,
                )

        execute.assert_not_called()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["jsonrpc"], "2.0")
        self.assertEqual(body["id"], request["id"])
        self.assertEqual(body["error"]["code"], -32603)
        self.assertEqual(body["error"]["message"], "Task not found")
        self.assertNotIn("result", body)


if __name__ == "__main__":
    unittest.main()
