"""Deterministic COMSOL .mph audit, diff, patch, verify, and smoke helper.

Run ``diff`` with normal Python. Run actions that touch a model through
``sim exec --file`` so COMSOL's ``ModelUtil`` is available. Configuration is
read from ``MPH_TOOL_CONFIG`` or from ``--config`` when run directly.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


TOOL_VERSION = "2.0.0"
DEFAULT_FEATURE_PROPERTIES = {
    "ElectrodeCurrent": ["ElectronicCurrentType", "TotalCurrentType", "Its", "IncludeContactResistance", "Rc"],
    "ParticleIntercalation": ["Ds", "Ds_mat"],
    "PorousElectrodeReaction": ["k", "i0refType", "HeatofReactionType"],
    "NormalCurrentDensity": ["nJ_type", "nJ", "J0"],
    "HeatSource": ["heatSourceType", "Q0_src", "Q0", "P0"],
    "HeatFluxBoundary": ["HeatFluxType", "h", "Text", "q0_input"],
    "GlobalEquations": ["name", "equation", "initialValueU", "CustomDependentVariableUnit", "CustomSourceTermUnit"],
    "ImplicitEvent": ["condition", "stopcond", "expr"],
}
RESULT_PROPERTIES = ["data", "solution", "expr", "unit", "descr", "probetag", "table"]
AUDIT_PRESETS = {
    "voltage": {
        "parameter_patterns": ["soc", "stoich", "ocv", "ocp", "volt", "v_min", "v_max", "cutoff"],
        "variable_patterns": ["soc", "stoich", "ocv", "ocp", "volt", "e_cell", "charge", "discharge"],
        "function_patterns": ["ocv", "ocp", "equilibrium", "lfp", "graphite", "gr_"],
        "feature_types": ["ElectrodeCurrent", "ElectrodePotential", "ImplicitEvent", "ExplicitEvent", "GlobalEquations"],
        "sections": ["functions", "studies", "results", "probes"],
    },
    "capacity": {
        "parameter_patterns": ["capacity", "cap", "q_cell", "soc", "stoich", "csmax"],
        "variable_patterns": ["capacity", "cap", "q1", "q2", "soc", "stoich", "ah_"],
        "function_patterns": ["ocv", "ocp"],
        "feature_types": ["GlobalEquations", "ImplicitEvent", "ExplicitEvent"],
        "sections": ["functions", "studies", "results", "probes"],
    },
    "heat_balance": {
        "parameter_patterns": ["heat", "thermal", "contact", "resist", "temperature", "t_amb"],
        "variable_patterns": ["heat", "qh", "q_", "power", "contact", "joule", "temperature"],
        "function_patterns": [],
        "feature_types": ["HeatSource", "HeatFluxBoundary", "ElectrodeCurrent", "NormalCurrentDensity"],
        "sections": ["couplings", "studies", "results", "probes"],
    },
    "solver": {
        "parameter_patterns": [],
        "variable_patterns": [],
        "function_patterns": [],
        "feature_types": [],
        "sections": ["studies", "solvers", "results"],
    },
    "sweep": {
        "parameter_patterns": [],
        "variable_patterns": [],
        "function_patterns": [],
        "feature_types": [],
        "sections": ["studies", "solvers", "results"],
    },
}


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        return [_jsonable(v) for v in value]
    except TypeError:
        return str(value)


def _tags(manager: Any) -> list[str]:
    try:
        return [str(tag) for tag in manager.tags()]
    except Exception:
        return []


def _manager_get(manager: Any, tag: str) -> Any:
    try:
        return manager.get(tag)
    except Exception:
        return manager(tag)


def _read_property(obj: Any, name: str) -> Any:
    for method in ("getString", "getStringArray", "getStringMatrix", "getDouble", "getBoolean"):
        try:
            value = getattr(obj, method)(name)
            if value is not None:
                return _jsonable(value)
        except Exception:
            continue
    return None


def _selection(obj: Any) -> list[int]:
    try:
        return [int(v) for v in obj.selection().entities()]
    except Exception:
        return []


def _feature_type(feature: Any) -> str:
    try:
        return str(feature.getType())
    except Exception:
        return "unknown"


def _feature_shallow_info(feature: Any, include_all: bool = False) -> dict[str, Any]:
    feature_type = _feature_type(feature)
    names: list[str] = []
    if include_all:
        try:
            names = [str(name) for name in feature.properties()]
        except Exception:
            names = []
    else:
        names = DEFAULT_FEATURE_PROPERTIES.get(feature_type, [])
    props = {}
    for name in names:
        value = _read_property(feature, name)
        if value not in (None, "", []):
            props[name] = value
    info = {
        "type": feature_type,
        "label": str(feature.label()),
        "selection": _selection(feature),
        "properties": props,
    }
    try:
        info["active"] = bool(feature.isActive())
    except Exception:
        pass
    return info


def _feature_info(feature: Any, include_all: bool = False) -> dict[str, Any]:
    info = _feature_shallow_info(feature, include_all)
    children = _feature_tree(feature.feature(), include_all)
    if children:
        info["features"] = children
    return info


def _feature_tree(manager: Any, include_all: bool = False) -> dict[str, Any]:
    result = {}
    for tag in _tags(manager):
        result[tag] = _feature_info(_manager_get(manager, tag), include_all)
    return result


def _feature_summary(manager: Any) -> dict[str, Any]:
    result = {}
    for tag in _tags(manager):
        node = _manager_get(manager, tag)
        result[tag] = {"type": _feature_type(node), "label": str(node.label())}
    return result


def _filtered_feature_tree(manager: Any, feature_types: set[str]) -> dict[str, Any]:
    result = {}
    for tag in _tags(manager):
        node = _manager_get(manager, tag)
        children = _filtered_feature_tree(node.feature(), feature_types)
        if _feature_type(node) in feature_types or children:
            info = _feature_shallow_info(node)
            if children:
                info["features"] = children
            result[tag] = info
    return result


def _variables(component: Any, patterns: list[str] | None) -> dict[str, Any]:
    if patterns == []:
        return {}
    result = {}
    for tag in _tags(component.variable()):
        node = component.variable(tag)
        entries = {}
        try:
            names = [str(name) for name in node.varnames()]
        except Exception:
            names = []
        for name in names:
            if patterns and not any(pattern.lower() in name.lower() for pattern in patterns):
                continue
            try:
                expr = str(node.get(name))
            except Exception:
                continue
            try:
                descr = str(node.descr(name))
            except Exception:
                descr = ""
            entries[name] = {"expr": expr, "description": descr}
        result[tag] = {"label": str(node.label()), "entries": entries}
    return result


def _couplings(component: Any) -> dict[str, Any]:
    result = {}
    for tag in _tags(component.cpl()):
        if tag.startswith("builder_"):
            continue
        node = component.cpl(tag)
        result[tag] = {
            "type": _feature_type(node),
            "label": str(node.label()),
            "operator": _read_property(node, "opname"),
            "selection": _selection(node),
        }
    return result


def _parameters(model: Any, patterns: list[str] | None) -> dict[str, Any]:
    if patterns == []:
        return {}
    result = {}
    try:
        names = [str(name) for name in model.param().varnames()]
    except Exception:
        names = []
    for name in names:
        if patterns and not any(pattern.lower() in name.lower() for pattern in patterns):
            continue
        entry = {"expr": str(model.param().get(name))}
        try:
            entry["description"] = str(model.param().descr(name))
        except Exception:
            pass
        try:
            entry["value"] = float(model.param().evaluate(name))
        except Exception:
            pass
        result[name] = entry
    return result


def _functions_info(model: Any, patterns: list[str] | None) -> dict[str, Any]:
    if patterns == []:
        return {}
    result = {}
    for tag in _tags(model.func()):
        node = _manager_get(model.func(), tag)
        label = str(node.label())
        values = {name: _read_property(node, name) for name in ("funcname", "source", "filename", "expr", "args", "argunit", "fununit")}
        searchable = " ".join([tag, label, *[str(value) for value in values.values() if value]])
        if patterns and not any(pattern.lower() in searchable.lower() for pattern in patterns):
            continue
        result[tag] = {
            "type": _feature_type(node),
            "label": label,
            "properties": {name: value for name, value in values.items() if value not in (None, "", [])},
        }
    return result


def _study_info(model: Any) -> dict[str, Any]:
    result = {}
    for tag in _tags(model.study()):
        study = model.study(tag)
        features = {}
        for feature_tag in _tags(study.feature()):
            feature = study.feature(feature_tag)
            props = {}
            for prop in ("pname", "plistarr", "plist", "tlist", "useinitsol", "solnum"):
                value = _read_property(feature, prop)
                if value not in (None, "", []):
                    props[prop] = value
            features[feature_tag] = {"type": _feature_type(feature), "label": str(feature.label()), "properties": props}
        result[tag] = {"label": str(study.label()), "features": features}
    return result


def _results_info(model: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"datasets": {}, "numerical": {}, "tables": {}}
    for group, manager in (
        ("datasets", model.result().dataset()),
        ("numerical", model.result().numerical()),
        ("tables", model.result().table()),
    ):
        for tag in _tags(manager):
            node = _manager_get(manager, tag)
            props = {}
            for prop in RESULT_PROPERTIES:
                value = _read_property(node, prop)
                if value not in (None, "", []):
                    props[prop] = value
            result[group][tag] = {"type": _feature_type(node), "label": str(node.label()), "properties": props}
    return result


def _solvers_info(model: Any) -> dict[str, Any]:
    result = {}
    for tag in _tags(model.sol()):
        node = _manager_get(model.sol(), tag)
        result[tag] = {"label": str(node.label()), "features": _feature_summary(node.feature())}
    return result


def _probes(component: Any) -> dict[str, Any]:
    result = {}
    try:
        manager = component.probe()
    except Exception:
        return result
    for tag in _tags(manager):
        node = component.probe(tag)
        props = {}
        for prop in ("expr", "unit", "descr", "table", "window"):
            value = _read_property(node, prop)
            if value not in (None, "", []):
                props[prop] = value
        result[tag] = {"type": _feature_type(node), "label": str(node.label()), "properties": props}
    return result


def audit_model(model: Any, source: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    scope = options.get("scope", "summary")
    if scope not in {"summary", "targeted", "full"}:
        raise ValueError("Audit scope must be summary, targeted, or full")
    preset_name = options.get("preset")
    if preset_name and preset_name not in AUDIT_PRESETS:
        raise ValueError(f"Unknown audit preset: {preset_name}")
    preset = AUDIT_PRESETS.get(preset_name, {})
    include_all = bool(options.get("include_all_feature_properties", False))
    default_patterns = None if scope == "full" else []
    param_patterns = options.get("parameter_patterns", preset.get("parameter_patterns", default_patterns))
    variable_patterns = options.get("variable_patterns", preset.get("variable_patterns", default_patterns))
    function_patterns = options.get("function_patterns", preset.get("function_patterns", default_patterns))
    sections = set(options.get("sections", preset.get("sections", [])))
    feature_types = set(options.get("feature_types", preset.get("feature_types", [])))
    components = {}
    for component_tag in _tags(model.component()):
        component = model.component(component_tag)
        physics = {}
        for physics_tag in _tags(component.physics()):
            node = component.physics(physics_tag)
            feature_info = (
                _feature_tree(node.feature(), include_all)
                if scope == "full"
                else _filtered_feature_tree(node.feature(), feature_types)
                if feature_types
                else _feature_summary(node.feature())
                if scope == "summary"
                else {}
            )
            physics[physics_tag] = {"label": str(node.label()), "features": feature_info}
            if scope == "full":
                physics[physics_tag]["selection"] = _selection(node)
        component_info: dict[str, Any] = {"physics": physics}
        if variable_patterns or scope == "full":
            component_info["variables"] = _variables(component, variable_patterns)
        if "couplings" in sections or scope == "full":
            component_info["couplings"] = _couplings(component)
        if "probes" in sections or scope == "full":
            component_info["probes"] = _probes(component)
        components[component_tag] = component_info
    report: dict[str, Any] = {
        "tool_version": TOOL_VERSION,
        "source": source,
        "label": str(model.label()),
        "scope": scope,
        "preset": preset_name,
        "parameters": _parameters(model, param_patterns),
        "components": components,
    }
    if "functions" in sections or scope == "full":
        report["functions"] = _functions_info(model, function_patterns)
    if "studies" in sections or scope in {"summary", "full"}:
        report["studies"] = _study_info(model)
    if "solvers" in sections or scope == "full":
        report["solvers"] = _solvers_info(model)
    if "results" in sections or scope in {"summary", "full"}:
        report["results"] = _results_info(model)
    return report


def _targeted_audit(model: Any, item: dict[str, Any]) -> dict[str, Any]:
    targeted: dict[str, Any] = {"parameters": {}, "variables": {}, "features": {}}
    for name in item.get("parameters", []):
        targeted["parameters"][name] = str(model.param().get(name))
    for spec in item.get("variables", []):
        variable_tag = spec.get("variable", spec.get("group"))
        node = model.component(spec["component"]).variable(variable_tag)
        key = f'{spec["component"]}.{variable_tag}'
        targeted["variables"][key] = {name: str(node.get(name)) for name in spec.get("names", [])}
    for spec in item.get("features", []):
        node = _feature(model, spec)
        feature_path = spec.get("features") or [spec.get("feature")]
        key = ".".join([spec["component"], spec["physics"], *[str(v) for v in feature_path if v]])
        targeted["features"][key] = {
            name: _read_property(node, name) for name in spec.get("properties", [])
        }
    return {key: value for key, value in targeted.items() if value}


def _require_modelutil() -> Any:
    try:
        from com.comsol.model.util import ModelUtil  # type: ignore
    except Exception as exc:
        raise RuntimeError("This action must run inside a COMSOL sim-cli exec session") from exc
    return ModelUtil


def _load_model(path: str, tag: str) -> tuple[Any, Any]:
    modelutil = _require_modelutil()
    try:
        modelutil.remove(tag)
    except Exception:
        pass
    return modelutil, modelutil.load(tag, str(Path(path)))


def _write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def action_audit(config: dict[str, Any]) -> dict[str, Any]:
    reports = []
    for index, item in enumerate(config["models"]):
        tag = item.get("tag", f"mph_audit_{index + 1}")
        modelutil, model = _load_model(item["path"], tag)
        try:
            options = {**config.get("options", {}), **item.get("options", {})}
            report = audit_model(model, item["path"], options)
            targeted = _targeted_audit(model, item)
            if targeted:
                report["targeted"] = targeted
            reports.append(report)
        finally:
            modelutil.remove(tag)
    payload = {"action": "audit", "tool_version": TOOL_VERSION, "models": reports}
    _write_json(config["output"], payload)
    return payload


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        result = {}
        for key in sorted(value):
            child = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten(value[key], child))
        return result
    if isinstance(value, list):
        return {prefix: value}
    return {prefix: value}


def recursive_diff(left: Any, right: Any, ignore: set[str] | None = None) -> list[dict[str, Any]]:
    ignore = ignore or set()
    left_flat = _flatten(left)
    right_flat = _flatten(right)
    result = []
    for key in sorted(set(left_flat) | set(right_flat)):
        if key in ignore or any(key.startswith(prefix + ".") for prefix in ignore):
            continue
        left_value = left_flat.get(key, "<missing>")
        right_value = right_flat.get(key, "<missing>")
        if left_value != right_value:
            result.append({"path": key, "left": left_value, "right": right_value})
    return result


def action_diff(config: dict[str, Any]) -> dict[str, Any]:
    left = json.loads(Path(config["left"]).read_text(encoding="utf-8"))
    right = json.loads(Path(config["right"]).read_text(encoding="utf-8"))
    payload = {
        "action": "diff",
        "tool_version": TOOL_VERSION,
        "differences": recursive_diff(left, right, set(config.get("ignore", []))),
    }
    _write_json(config["output"], payload)
    return payload


def _feature(model: Any, spec: dict[str, Any]) -> Any:
    component = model.component(spec["component"])
    node = component.physics(spec["physics"])
    feature_path = spec.get("features")
    if feature_path is None and spec.get("feature") is not None:
        feature_path = [spec["feature"]]
    for tag in feature_path or []:
        node = node.feature(tag)
    return node


def _value(spec: dict[str, Any]) -> Any:
    if "value" in spec:
        return spec["value"]
    if "expr" in spec:
        return spec["expr"]
    raise ValueError("Operation requires value or expr")


def _apply_operation(model: Any, operation: dict[str, Any]) -> None:
    kind = operation["op"]
    if kind == "set_param":
        model.param().set(operation["name"], _value(operation))
        return
    if kind == "set_variable":
        variable_tag = operation.get("variable", operation.get("group"))
        node = model.component(operation["component"]).variable(variable_tag)
        node.set(operation["name"], _value(operation))
        if operation.get("description") is not None:
            node.descr(operation["name"], operation["description"])
        return
    if kind == "set_feature":
        _feature(model, operation).set(operation["property"], _value(operation))
        return
    if kind == "create_heat_source":
        component = model.component(operation["component"])
        physics = component.physics(operation.get("physics", "ht"))
        tag = operation["tag"]
        try:
            physics.feature().remove(tag)
        except Exception:
            pass
        node = physics.feature().create(tag, "HeatSource", 3)
        node.label(operation.get("label", tag))
        if "selection_from_physics" in operation:
            entities = component.physics(operation["selection_from_physics"]).selection().entities()
            node.selection().set([int(v) for v in entities])
        else:
            node.selection().set(operation["selection"])
        node.set("Q0", operation["Q0"])
        return
    if kind == "create_probe":
        component = model.component(operation["component"])
        tag = operation["tag"]
        try:
            component.probe().remove(tag)
        except Exception:
            pass
        node = component.probe().create(tag, "GlobalVariable")
        node.label(operation.get("label", tag))
        for prop in ("expr", "unit", "descr", "table", "window"):
            if prop in operation:
                node.set(prop, operation[prop])
        return
    raise ValueError(f"Unsupported patch operation: {kind}")


def ensure_save_as(source: str, output: str) -> None:
    if Path(source).resolve() == Path(output).resolve():
        raise ValueError("Patch output must differ from the source .mph path")


def _assertion_value(model: Any, assertion: dict[str, Any]) -> Any:
    kind = assertion["kind"]
    if kind == "param_expr":
        return str(model.param().get(assertion["name"]))
    if kind == "variable_expr":
        variable_tag = assertion.get("variable", assertion.get("group"))
        return str(model.component(assertion["component"]).variable(variable_tag).get(assertion["name"]))
    if kind == "feature_property":
        return _read_property(_feature(model, assertion), assertion["property"])
    if kind == "probe_expr":
        node = model.component(assertion["component"]).probe(assertion["tag"])
        return _read_property(node, "expr")
    if kind == "feature_exists":
        manager = model.component(assertion["component"]).physics(assertion["physics"]).feature()
        return assertion["tag"] in _tags(manager)
    raise ValueError(f"Unsupported assertion kind: {kind}")


def verify_model(model: Any, assertions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for assertion in assertions:
        actual = _assertion_value(model, assertion)
        expected = assertion.get("expected", assertion.get("equals", True))
        results.append({**assertion, "actual": actual, "passed": actual == expected})
    return results


def action_patch(config: dict[str, Any]) -> dict[str, Any]:
    source = config["source"]
    output = config["output_model"]
    ensure_save_as(source, output)
    modelutil, model = _load_model(source, config.get("tag", "mph_patch"))
    tag = config.get("tag", "mph_patch")
    try:
        for operation in config.get("operations", []):
            _apply_operation(model, operation)
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        model.save(output)
    finally:
        modelutil.remove(tag)
    verify_tag = tag + "_verify"
    _, saved = _load_model(output, verify_tag)
    try:
        assertions = verify_model(saved, config.get("assertions", []))
    finally:
        modelutil.remove(verify_tag)
    payload = {"action": "patch", "tool_version": TOOL_VERSION, "source": source, "output_model": output, "assertions": assertions}
    if any(not item["passed"] for item in assertions):
        raise RuntimeError("Saved model failed one or more reload assertions")
    if config.get("output"):
        _write_json(config["output"], payload)
    return payload


def action_verify(config: dict[str, Any]) -> dict[str, Any]:
    tag = config.get("tag", "mph_verify")
    modelutil, model = _load_model(config["source"], tag)
    try:
        assertions = verify_model(model, config.get("assertions", []))
    finally:
        modelutil.remove(tag)
    payload = {"action": "verify", "tool_version": TOOL_VERSION, "source": config["source"], "assertions": assertions}
    if config.get("output"):
        _write_json(config["output"], payload)
    return payload


def action_smoke(config: dict[str, Any]) -> dict[str, Any]:
    tag = config.get("tag", "mph_smoke")
    modelutil, model = _load_model(config["source"], tag)
    numerical_tag = "__mph_tool_eval"
    try:
        study = model.study(config.get("study", "std1"))
        for override in config.get("overrides", []):
            feature_tag = override.get("feature", override.get("study_feature"))
            study.feature(feature_tag).set(override["property"], override["value"])
        study.run()
        try:
            model.result().numerical().remove(numerical_tag)
        except Exception:
            pass
        node = model.result().numerical().create(numerical_tag, "EvalGlobal")
        expressions = config.get("expressions", config.get("metrics"))
        node.set("expr", [item["expr"] for item in expressions])
        node.set("unit", [item["unit"] for item in expressions])
        if config.get("solnum") is not None:
            node.set("solnum", config["solnum"])
        if config.get("outersolnum") is not None:
            node.set("outersolnum", config["outersolnum"])
        datasets = [config["dataset"]] if config.get("dataset") else list(reversed(_tags(model.result().dataset())))
        data = []
        used_dataset = None
        dataset_errors = {}
        for dataset in datasets:
            try:
                node.set("data", dataset)
                data = node.getReal()
                if len(data):
                    used_dataset = dataset
                    break
            except Exception as exc:
                dataset_errors[dataset] = str(exc)
        if not data:
            raise RuntimeError(
                "Smoke solve completed but no evaluable result dataset was found. "
                f"Tried: {dataset_errors}"
            )
        metrics = {
            item["name"]: {"values": [float(v) for v in values], "unit": item["unit"]}
            for item, values in zip(expressions, data)
        }
    finally:
        try:
            model.result().numerical().remove(numerical_tag)
        except Exception:
            pass
        modelutil.remove(tag)
    payload = {
        "action": "smoke",
        "tool_version": TOOL_VERSION,
        "source": config["source"],
        "saved": False,
        "dataset": used_dataset,
        "metrics": metrics,
    }
    _write_json(config["output"], payload)
    return payload


def validate_config(config: dict[str, Any]) -> None:
    action = config.get("action")
    required = {
        "audit": ["models", "output"],
        "diff": ["left", "right", "output"],
        "patch": ["source", "output_model"],
        "verify": ["source", "assertions"],
        "smoke": ["source", "output"],
    }
    if action not in required:
        raise ValueError(f"Unsupported action: {action}")
    missing = [name for name in required[action] if name not in config]
    if missing:
        raise ValueError(f"Missing config keys for {action}: {', '.join(missing)}")
    if action == "smoke" and not (config.get("expressions") or config.get("metrics")):
        raise ValueError("Smoke config requires expressions or metrics")
    if action == "smoke":
        expressions = config.get("expressions", config.get("metrics", []))
        missing_units = [item.get("name", item.get("expr", "<unnamed>")) for item in expressions if not item.get("unit")]
        if missing_units:
            raise ValueError(f"Smoke expressions require explicit units: {', '.join(missing_units)}")


def run(config: dict[str, Any]) -> dict[str, Any]:
    validate_config(config)
    return {
        "audit": action_audit,
        "diff": action_diff,
        "patch": action_patch,
        "verify": action_verify,
        "smoke": action_smoke,
    }[config["action"]](config)


def _config_path(argv: list[str]) -> str:
    env_path = os.environ.get("MPH_TOOL_CONFIG")
    if env_path:
        return env_path
    injected_path = globals().get("MPH_TOOL_CONFIG")
    if injected_path:
        return str(injected_path)
    if __name__ == "builtins":
        sim_path = Path.cwd() / ".sim" / "mph_tool_config.json"
        if not sim_path.is_file():
            raise FileNotFoundError(
                f"sim exec requires {sim_path}; copy the active task config there before --file execution"
            )
        return str(sim_path)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="UTF-8 JSON configuration file")
    return parser.parse_args(argv).config


def main(argv: list[str] | None = None) -> int:
    path = _config_path(sys.argv[1:] if argv is None else argv)
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    payload = run(config)
    print(json.dumps({"ok": True, "action": payload["action"], "output": config.get("output")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
elif __name__ == "builtins":
    main([])
