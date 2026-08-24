import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PluginCompatibilityTests(unittest.TestCase):
    def test_plata_exports_legacy_and_current_api(self):
        tree = ast.parse((ROOT / "plata.py").read_text(encoding="utf-8"))
        exported = next(
            node.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
        )
        names = {item.value for item in exported.elts}
        self.assertTrue({"Plata", "get_plata", "Cardinal", "get_cardinal", "PluginData"} <= names)

    def test_cardinal_and_plata_are_exact_aliases(self):
        tree = ast.parse((ROOT / "compatibility" / "cardinal.py").read_text(encoding="utf-8"))
        aliases = {
            target.id: node.value.id
            for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        self.assertEqual(aliases.get("Plata"), "Cardinal")
        self.assertEqual(aliases.get("get_cardinal"), "get_plata")

    def test_all_cardinal_bind_names_remain_available(self):
        source = (ROOT / "plata_core.py").read_text(encoding="utf-8")
        expected = {
            "BIND_TO_PRE_INIT", "BIND_TO_POST_INIT", "BIND_TO_PRE_START",
            "BIND_TO_POST_START", "BIND_TO_PRE_STOP", "BIND_TO_POST_STOP",
            "BIND_TO_INIT_MESSAGE", "BIND_TO_MESSAGES_LIST_CHANGED",
            "BIND_TO_LAST_CHAT_MESSAGE_CHANGED", "BIND_TO_NEW_MESSAGE",
            "BIND_TO_INIT_ORDER", "BIND_TO_NEW_ORDER",
            "BIND_TO_ORDERS_LIST_CHANGED", "BIND_TO_ORDER_STATUS_CHANGED",
            "BIND_TO_PRE_DELIVERY", "BIND_TO_POST_DELIVERY",
            "BIND_TO_PRE_LOTS_RAISE", "BIND_TO_POST_LOTS_RAISE",
        }
        mapping = next(
            node.value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Attribute) and target.attr == "handler_bind_var_names"
                    for target in node.targets)
        )
        bind_names = {key.value for key in mapping.keys if isinstance(key, ast.Constant)}
        self.assertFalse(expected - bind_names)


if __name__ == "__main__":
    unittest.main()
