from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError


class SolverConfigLoader:
    """Load and validate solver config YAML files."""

    _ALLOWED_STOP_TYPES = {"max_iterations", "max_seconds"}

    def __init__(self, config_root: Path | str = Path("configs/solvers")) -> None:
        self._config_root = Path(config_root)
        self._yaml = YAML(typ="safe")
        self._yaml_parse_lock = threading.Lock()

    def load(self, solver_id: str, *, param_set_index: int) -> dict[str, Any]:
        if param_set_index < 0:
            raise ValueError("param_set_index must be >= 0")
        config_path = self._config_root / f"{solver_id}.yaml"
        if not config_path.exists():
            raise FileNotFoundError(f"Solver config YAML not found: {config_path}")

        data = self._read_yaml(config_path)
        self._validate_schema(data, solver_id=solver_id, file_path=config_path)
        return self._normalize_config(data, param_set_index=param_set_index, file_path=config_path)

    def load_all(self, solver_id: str) -> tuple[dict[str, Any], ...]:
        config_path = self._config_root / f"{solver_id}.yaml"
        if not config_path.exists():
            raise FileNotFoundError(f"Solver config YAML not found: {config_path}")

        data = self._read_yaml(config_path)
        self._validate_schema(data, solver_id=solver_id, file_path=config_path)
        return tuple(
            self._normalize_config(data, param_set_index=index, file_path=config_path)
            for index in range(len(self._parameter_entries(data)))
        )

    def load_group(self, solver_id: str, *, group_key: str) -> dict[str, Any]:
        """Load a managed parameter group by its stable, source-defined key."""
        if not isinstance(group_key, str) or not group_key.strip():
            raise ValueError("group_key must be a non-empty string")

        config_path = self._config_root / f"{solver_id}.yaml"
        if not config_path.exists():
            raise FileNotFoundError(f"Solver config YAML not found: {config_path}")

        data = self._read_yaml(config_path)
        self._validate_schema(data, solver_id=solver_id, file_path=config_path)
        if "parameter_groups" not in data:
            raise ValueError(
                f"managed group lookup requires parameter_groups in {config_path}"
            )

        for index, (stored_key, _) in enumerate(self._parameter_entries(data)):
            if stored_key == group_key:
                return self._normalize_config(
                    data,
                    param_set_index=index,
                    file_path=config_path,
                )
        raise ValueError(f"unknown parameter group key {group_key!r} in {config_path}")

    def _read_yaml(self, path: Path) -> dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as fh:
                with self._yaml_parse_lock:
                    loaded = self._yaml.load(fh)
        except YAMLError as exc:
            raise ValueError(f"Invalid YAML format in {path}: {exc}") from exc

        if not isinstance(loaded, dict):
            raise ValueError(f"Solver config must be a mapping: {path}")
        return loaded

    def _validate_schema(self, data: dict[str, Any], *, solver_id: str, file_path: Path) -> None:
        required_fields = ("solver_id", "solver_class", "stop_condition", "capabilities")
        missing = [field for field in required_fields if field not in data]
        if missing:
            raise ValueError(f"Missing required field(s) {missing} in {file_path}")

        has_legacy_params = "params" in data
        has_parameter_groups = "parameter_groups" in data
        if has_legacy_params == has_parameter_groups:
            raise ValueError(
                f"solver config must define exactly one of params or parameter_groups in {file_path}"
            )

        yaml_solver_id = str(data["solver_id"])
        if yaml_solver_id != solver_id:
            raise ValueError(
                f"solver_id mismatch in {file_path}: expected {solver_id}, got {yaml_solver_id}"
            )

        if not str(data["solver_class"]).strip():
            raise ValueError(f"solver_class cannot be empty in {file_path}")

        stop_condition = data["stop_condition"]
        if not isinstance(stop_condition, dict):
            raise ValueError(f"stop_condition must be a mapping in {file_path}")

        stop_type = stop_condition.get("type")
        if stop_type not in self._ALLOWED_STOP_TYPES:
            raise ValueError(
                f"stop_condition.type must be one of {sorted(self._ALLOWED_STOP_TYPES)} in {file_path}"
            )

        if stop_type == "max_iterations":
            value = stop_condition.get("max_iterations")
            if value is None or int(value) <= 0:
                raise ValueError(f"max_iterations must be > 0 in {file_path}")
        elif stop_type == "max_seconds":
            value = stop_condition.get("max_seconds")
            if value is None or float(value) <= 0:
                raise ValueError(f"max_seconds must be > 0 in {file_path}")

        if has_legacy_params:
            params = data["params"]
            if not isinstance(params, list) or not params:
                raise ValueError(f"params must be a non-empty list in {file_path}")
            for index, param_set in enumerate(params):
                if not isinstance(param_set, dict):
                    raise ValueError(f"params[{index}] must be a mapping in {file_path}")
        else:
            groups = data["parameter_groups"]
            if not isinstance(groups, list) or not groups:
                raise ValueError(f"parameter_groups must be a non-empty list in {file_path}")
            seen_keys: set[str] = set()
            for index, group in enumerate(groups):
                if not isinstance(group, dict):
                    raise ValueError(
                        f"parameter_groups[{index}] must be a mapping in {file_path}"
                    )
                key = group.get("key")
                if not isinstance(key, str) or not key.strip() or key != key.strip():
                    raise ValueError(
                        f"parameter_groups[{index}].key must be a non-empty trimmed string "
                        f"in {file_path}"
                    )
                if key in seen_keys:
                    raise ValueError(f"duplicate parameter group key {key!r} in {file_path}")
                seen_keys.add(key)
                if not isinstance(group.get("params"), dict):
                    raise ValueError(
                        f"parameter_groups[{index}].params must be a mapping in {file_path}"
                    )

        capabilities = data["capabilities"]
        if not isinstance(capabilities, dict):
            raise ValueError(f"capabilities must be a mapping in {file_path}")
        for field in ("problem_types", "encodings", "directions"):
            values = capabilities.get(field)
            if not isinstance(values, list) or not values or any(not str(v).strip() for v in values):
                raise ValueError(f"capabilities.{field} must be a non-empty list in {file_path}")
        directions = {str(v) for v in capabilities["directions"]}
        if not directions.issubset({"max", "min"}):
            raise ValueError(f"capabilities.directions must contain only 'max' or 'min' in {file_path}")

    def _normalize_config(
        self,
        data: dict[str, Any],
        *,
        param_set_index: int,
        file_path: Path,
    ) -> dict[str, Any]:
        parameter_entries = self._parameter_entries(data)
        if param_set_index >= len(parameter_entries):
            raise ValueError(
                f"param_set_index out of range in {file_path}: "
                f"got {param_set_index}, available indices are 0..{len(parameter_entries) - 1}"
            )

        normalized = copy.deepcopy(data)
        group_key, params = parameter_entries[param_set_index]
        normalized.pop("parameter_groups", None)
        normalized["params"] = copy.deepcopy(params)
        normalized["param_set_index"] = param_set_index
        if group_key is not None:
            normalized["group_key"] = group_key
        return normalized

    @staticmethod
    def _parameter_entries(data: dict[str, Any]) -> tuple[tuple[str | None, dict[str, Any]], ...]:
        if "parameter_groups" in data:
            return tuple((str(group["key"]), group["params"]) for group in data["parameter_groups"])
        return tuple((None, params) for params in data["params"])
