from pathlib import Path

from scripts.validate_document_paths import audit, validate_document


def write_file(root: Path, relative: str, content: str = "") -> Path:
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")
    return destination


def test_nested_references_are_document_relative_and_resources_are_skill_relative(tmp_path):
    write_file(tmp_path, "skills/builtin/example/SKILL.md")
    write_file(tmp_path, "skills/shared/guide.md")
    write_file(tmp_path, "skills/builtin/example/scripts/run.py")
    document = write_file(
        tmp_path, "skills/builtin/example/references/guide.md",
        "`../../../shared/guide.md` and `scripts/run.py`\n"
        "[shared](../../../shared/guide.md)\n`../../shared/guide.md`\n",
    )
    issues, checked = validate_document(document, tmp_path)
    assert checked == 4
    assert [(issue.line, issue.reference) for issue in issues] == [(3, "../../shared/guide.md")]


def test_root_paths_in_commands_and_prompts_are_checked(tmp_path):
    write_file(tmp_path, "skills/shared/scripts/run.py")
    document = write_file(
        tmp_path, "agents/workspace/SOUL.md",
        "```bash\npython skills/shared/scripts/run.py --help\n"
        "python skills/shared/scripts/missing.py\n```\n",
    )
    issues, checked = validate_document(document, tmp_path)
    assert checked == 2
    assert len(issues) == 1
    assert issues[0].line == 3


def test_links_ignore_fragments_urls_and_fenced_examples(tmp_path):
    write_file(tmp_path, "docs/guide.md")
    document = write_file(
        tmp_path, "README.md",
        "[guide](docs/guide.md#section) [external](https://example.com/guide)\n"
        "```markdown\n[example](not-a-real-file.md)\n```\n"
        "`![example](images/generated.jpg)` `![example](图片)`\n"
        "`skills/builtin/<skill>/scripts/run.py` `outputs/new/result.png`\n"
        "`skills/shared/scripts/models/sh.rnnn`\n",
    )
    assert validate_document(document, tmp_path) == ([], 1)


def test_sdk_resources_resolve_to_vendor_package_root(tmp_path):
    write_file(tmp_path, "skills/builtin/video/SKILL.md")
    write_file(tmp_path, "skills/builtin/video/vendor/sdk/references/fx.md")
    document = write_file(
        tmp_path, "skills/builtin/video/vendor/sdk/docs/guide.md", "`references/fx.md`",
    )
    assert validate_document(document, tmp_path) == ([], 1)


def test_old_repository_paths_are_rejected_but_native_openclaw_paths_are_valid(tmp_path):
    document = write_file(
        tmp_path, "agents/workspace/AGENTS.md",
        "`~/.openclaw/workspace-easel` `~/.openclaw-easel/workspace`\n"
        "`skills/openclaw/example/SKILL.md` `openclaw/workspace/AGENTS.md`\n",
    )
    issues, _ = validate_document(document, tmp_path)
    assert len([issue for issue in issues if issue.reason == "obsolete repository path"]) == 2
    assert all(issue.line == 2 for issue in issues)


def test_audit_includes_nested_skill_docs_shared_and_all_prompt_files(tmp_path):
    paths = [
        "README.md", "docs/nested/guide.md", "agents/workspace/AGENTS.md",
        "agents/workspace/SOUL.md", "skills/shared/README.md",
        "skills/builtin/example/references/nested/guide.md",
    ]
    for relative in paths:
        write_file(tmp_path, relative, "`skills/shared/missing.py`")
    write_file(tmp_path, "skills/builtin/example/node_modules/dependency/README.md")
    issues, checked, sources = audit(tmp_path)
    assert len(issues) == checked == sources == len(paths)


def test_optional_configuration_and_bare_resource_labels_are_not_missing_dependencies(tmp_path):
    document = write_file(
        tmp_path, "README.md",
        "`scripts/` `references/` `assets/`\n"
        "`skills/builtin/skill-wechat-publisher/wechat-publisher.yaml`\n"
        "`skills/shared/scripts/models`\n"
        "`skills/shared/missing/`\n",
    )
    issues, checked = validate_document(document, tmp_path)
    assert checked == 1
    assert issues[0].reference == "skills/shared/missing/"


def test_concrete_images_are_checked_but_fenced_placeholder_images_are_not(tmp_path):
    document = write_file(
        tmp_path, "README.md",
        "![preview](assets/missing.png)\n```markdown\n![example](图片)\n```\n",
    )
    issues, checked = validate_document(document, tmp_path)
    assert checked == 1
    assert issues[0].line == 1


def test_documented_command_scripts_resolve_relative_to_skill_root(tmp_path, monkeypatch):
    from scripts import validate_skill_commands

    monkeypatch.setattr(validate_skill_commands, "ROOT", tmp_path)
    write_file(tmp_path, "skills/builtin/example/SKILL.md")
    script = write_file(tmp_path, "skills/builtin/example/scripts/run.py")
    document = write_file(tmp_path, "skills/builtin/example/references/nested/commands.md")
    assert validate_skill_commands.resolve_script(document, "scripts/run.py") == script
    assert validate_skill_commands.resolve_script(
        document, "skills/builtin/example/scripts/run.py",
    ) == script
    assert validate_skill_commands.resolve_script(document, "$ROOT/scripts/run.py") is None


def test_windows_repository_paths_are_checked_on_any_host(tmp_path):
    write_file(tmp_path, "agents/workspace/AGENTS.md")
    document = write_file(
        tmp_path, "README.md",
        r"`agents\workspace\AGENTS.md` `skills\openclaw\example\SKILL.md`",
    )
    issues, checked = validate_document(document, tmp_path)
    assert checked == 2
    assert len([issue for issue in issues if issue.reason == "obsolete repository path"]) == 1
