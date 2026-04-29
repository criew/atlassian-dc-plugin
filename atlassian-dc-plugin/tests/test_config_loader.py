"""Config loader behaviour — focused on error clarity for weak LLMs."""
from __future__ import annotations

import json
import pytest

from _common import (
    ConfigError,
    load_instance,
    load_rules,
)


def test_missing_file_lists_searched_paths(isolated_config, monkeypatch):
    # Point to a path that doesn't exist
    monkeypatch.setenv("ATLASSIAN_INSTANCES_FILE", str(isolated_config / "missing.json"))
    with pytest.raises(ConfigError) as exc:
        load_instance("jira")
    msg = str(exc.value)
    assert "instances.json not found" in msg
    assert "missing.json" in msg
    # The error must point the user to the example file
    assert "example" in msg.lower()


def test_invalid_json_names_the_file(write_instances, isolated_config):
    bad = isolated_config / "instances.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_instance("jira")
    assert str(bad) in str(exc.value)
    assert "Invalid JSON" in str(exc.value)


def test_unknown_alias_lists_available(write_instances):
    write_instances({
        "default": "prod",
        "instances": {
            "prod": {"jira": {"url": "http://x", "token": "t"}},
            "staging": {"jira": {"url": "http://y", "token": "t"}},
        },
    })
    with pytest.raises(ConfigError) as exc:
        load_instance("jira", alias="nonexistent")
    msg = str(exc.value)
    assert "nonexistent" in msg
    # weak LLMs must see what IS available
    assert "prod" in msg
    assert "staging" in msg


def test_missing_product_in_instance(write_instances):
    write_instances({
        "default": "prod",
        "instances": {"prod": {"confluence": {"url": "x", "token": "t"}}},
    })
    with pytest.raises(ConfigError) as exc:
        load_instance("jira", alias="prod")
    msg = str(exc.value)
    assert "no 'jira' configuration" in msg
    assert "confluence" in msg  # show what IS configured


def test_missing_url_or_token_is_explicit(write_instances):
    write_instances({
        "default": "prod",
        "instances": {"prod": {"jira": {"url": "", "token": "t"}}},
    })
    with pytest.raises(ConfigError) as exc:
        load_instance("jira", alias="prod")
    assert "missing url or token" in str(exc.value)


def test_no_default_and_no_alias(write_instances):
    write_instances({
        "instances": {"prod": {"jira": {"url": "x", "token": "t"}}},
    })
    with pytest.raises(ConfigError) as exc:
        load_instance("jira")
    assert "default" in str(exc.value)


def test_explicit_alias_overrides_env(write_instances, monkeypatch):
    write_instances({
        "default": "prod",
        "instances": {
            "prod": {"jira": {"url": "http://prod", "token": "p"}},
            "staging": {"jira": {"url": "http://stg", "token": "s"}},
        },
    })
    monkeypatch.setenv("ATLASSIAN_INSTANCE", "staging")
    inst = load_instance("jira", alias="prod")
    assert inst.alias == "prod"
    assert "prod" in inst.url


def test_env_alias_used_when_no_explicit(write_instances, monkeypatch):
    write_instances({
        "default": "prod",
        "instances": {
            "prod": {"jira": {"url": "http://prod", "token": "p"}},
            "staging": {"jira": {"url": "http://stg", "token": "s"}},
        },
    })
    monkeypatch.setenv("ATLASSIAN_INSTANCE", "staging")
    inst = load_instance("jira")
    assert inst.alias == "staging"


def test_default_used_when_neither_arg_nor_env(write_instances, monkeypatch):
    write_instances({
        "default": "prod",
        "instances": {
            "prod": {"jira": {"url": "http://prod", "token": "p"}},
        },
    })
    monkeypatch.delenv("ATLASSIAN_INSTANCE", raising=False)
    inst = load_instance("jira")
    assert inst.alias == "prod"


# -----------------------------------------------------------------------------
# Rules loader
# -----------------------------------------------------------------------------

def test_rules_missing_returns_found_false_with_searched_paths(isolated_config):
    result = load_rules("local")
    assert result["found"] is False
    assert result["instance"] == "local"
    assert result["content"] == ""
    assert any("local.md" in p for p in result["searched"])


def test_rules_loads_full_file_when_no_project(write_rules):
    write_rules("local", "# Rules\n\n## Global\n- one\n\n## Project FOO\n- two\n")
    r = load_rules("local")
    assert r["found"] is True
    assert "## Global" in r["content"]
    assert "## Project FOO" in r["content"]
    assert "one" in r["content"] and "two" in r["content"]


def test_rules_filters_to_global_and_named_project(write_rules):
    write_rules("local",
                "# Rules\n\n"
                "## Global\n- glob-rule\n\n"
                "## Project HALLO\n- hallo-rule\n\n"
                "## Project FOO\n- foo-rule\n")
    r = load_rules("local", project="HALLO")
    assert "glob-rule" in r["content"]
    assert "hallo-rule" in r["content"]
    assert "foo-rule" not in r["content"]


def test_rules_filtered_does_not_match_unrelated_project(write_rules):
    write_rules("local", "## Project FOO\n- only-foo\n")
    r = load_rules("local", project="BAR")
    assert "only-foo" not in r["content"]
