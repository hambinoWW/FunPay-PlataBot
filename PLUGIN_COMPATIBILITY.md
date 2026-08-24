# PLATA plugin compatibility

PLATA runs plugins written for FunPay Cardinal without source changes.

The following legacy contracts are intentionally stable:

- `from cardinal import Cardinal` and `get_cardinal`
- `Cardinal` class methods and attributes used by plugins
- all `BIND_TO_*` handler variables
- the `plugins/` directory and `plugins.<module>` import path
- legacy plugin metadata: `NAME`, `VERSION`, `DESCRIPTION`, `CREDITS`,
  `SETTINGS_PAGE`, `UUID`, and `BIND_TO_DELETE`
- Telegram control-panel modules under `tg_bot`

New plugins may use `from plata import Plata, get_plata`. `Plata` and
`Cardinal` are the exact same class object, so type and identity checks remain
compatible in both directions.

The legacy top-level module `cardinal` is registered from the hidden
`compatibility/cardinal.py` shim before plugins are loaded.
