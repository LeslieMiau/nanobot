from nanobot.coding_tasks.router import (
    ParsedCodingTaskRequest,
    is_start_coding_request,
    parse_start_coding_request,
)


def test_parse_start_coding_request_with_inline_path_and_goal() -> None:
    parsed = parse_start_coding_request("开始编程 /Users/miau/Documents/demo 修复登录回调")

    assert parsed == ParsedCodingTaskRequest(
        repo_path="/Users/miau/Documents/demo",
        goal="修复登录回调",
        title=None,
    )


def test_parse_start_coding_request_with_structured_fields() -> None:
    parsed = parse_start_coding_request(
        "开始编程\n仓库: /Users/miau/Documents/demo\n目标: 修复设置页闪退\n标题: 设置页修复"
    )

    assert parsed == ParsedCodingTaskRequest(
        repo_path="/Users/miau/Documents/demo",
        goal="修复设置页闪退",
        title="设置页修复",
    )


def test_is_start_coding_request_matches_only_expected_prefix() -> None:
    assert is_start_coding_request("开始编程 /tmp/repo 做点事") is True
    assert is_start_coding_request("帮我看看这个 repo") is False
