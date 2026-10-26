# -*- coding: utf-8 -*-
"""``routers/v1/notifications.py`` 与 ``routers/v1/roles.py`` 的单元测试。

两个模块都是纯聚合层：通知走内存 ``NotificationManager``，角色走
``core/character/configs`` 扫描 + ``companion_data/role_profiles.json`` 覆盖。
测试里替换掉扫描与落盘两个边界，断言接口契约与「非破坏性读取」这一关键语义
（通知中心刷新后列表不能变空）。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.v1.notifications as notifications_mod
import routers.v1.roles as roles_mod
from core.managers.notification_manager import get_notification_manager


@pytest.fixture()
def notifications_client():
    app = FastAPI()
    app.include_router(notifications_mod.router)
    manager = get_notification_manager()
    manager.notifications.clear()
    manager.last_poll_time.clear()
    yield TestClient(app)
    manager.notifications.clear()
    manager.last_poll_time.clear()


def test_list_notifications_is_non_destructive(notifications_client):
    created = notifications_client.post(
        "/notifications",
        json={"title": "提醒", "content": "该喝水了", "user_id": "u1"},
    )
    assert created.status_code == 200
    assert created.json()["status"] == "success"

    first = notifications_client.get("/notifications", params={"user_id": "u1"}).json()
    second = notifications_client.get("/notifications", params={"user_id": "u1"}).json()

    assert first["data"]["total"] == 1
    assert second["data"]["total"] == 1, "通知中心刷新不应消费队列"
    assert second["data"]["unread"] == 1
    assert second["data"]["items"][0]["title"] == "提醒"


def test_mark_notifications_read(notifications_client):
    for index in range(2):
        notifications_client.post(
            "/notifications",
            json={"title": f"n{index}", "content": "x", "user_id": "u2"},
        )

    marked = notifications_client.post("/notifications/read", json={"user_id": "u2"}).json()
    assert marked["data"]["marked"] == 2
    assert marked["data"]["unread"] == 0

    listed = notifications_client.get("/notifications", params={"user_id": "u2"}).json()
    assert all(item["read"] for item in listed["data"]["items"])


def test_create_notification_rejects_empty(notifications_client):
    response = notifications_client.post(
        "/notifications", json={"title": "  ", "content": " "}
    ).json()
    assert response["status"] == "error"
    assert "不能同时为空" in response["message"]


def test_peek_does_not_break_pending_consumer():
    manager = get_notification_manager()
    manager.notifications.clear()
    manager.add_notification("u3", "text", "标题", "正文")

    assert len(manager.peek_notifications("u3")) == 1
    assert len(manager.get_pending_notifications("u3")) == 1
    assert manager.peek_notifications("u3") == []


@pytest.fixture()
def roles_client(monkeypatch):
    overrides: dict = {}

    def fake_scan():
        return {
            "aveline": {
                "scope": "aveline",
                "name": "Aveline",
                "aliases": ["Aveline"],
                "persona_file": "core_aveline.json",
                "voice_file": "voice_aveline.json",
                "config_relative_path": "core/character/configs/aveline/core_aveline.json",
            },
            "secret_role": {
                "scope": "secret_role",
                "name": "未登记角色",
                "aliases": [],
                "persona_file": "core_secret_role.json",
                "voice_file": "",
                "config_relative_path": "core/character/configs/secret/core_secret_role.json",
            },
        }

    async def fake_read():
        return dict(overrides)

    async def fake_write(data):
        overrides.clear()
        overrides.update(data)

    monkeypatch.setattr(roles_mod, "_scan_role_configs_sync", fake_scan)
    monkeypatch.setattr(roles_mod, "get_registered_role_scopes", lambda: {"aveline"})
    monkeypatch.setattr(roles_mod, "_read_overrides", fake_read)
    monkeypatch.setattr(roles_mod, "_write_overrides", fake_write)

    app = FastAPI()
    app.include_router(roles_mod.router)
    yield TestClient(app), overrides


def test_list_roles_only_returns_registered(roles_client):
    client, _ = roles_client
    payload = client.get("/roles").json()

    scopes = [item["scope"] for item in payload["data"]["roles"]]
    assert scopes == ["aveline"], "未登记 scope 不应出现在角色清单里"
    assert payload["data"]["roles"][0]["display_name"] == "Aveline"


def test_update_role_profile_persists_override(roles_client):
    client, overrides = roles_client
    response = client.put(
        "/roles/aveline",
        json={"display_name": "Aveline", "avatar": "🌙", "voice_id": "Aveline"},
    ).json()

    assert response["status"] == "success"
    assert response["data"]["role"]["display_name"] == "Aveline"
    assert response["data"]["role"]["overridden"] is True
    assert overrides["aveline"]["voice_id"] == "Aveline"

    listed = client.get("/roles/aveline").json()
    assert listed["data"]["role"]["avatar"] == "🌙"


def test_update_role_rejects_bad_scope(roles_client):
    client, _ = roles_client
    response = client.put("/roles/Bad-Scope", json={"display_name": "x"}).json()
    assert response["status"] == "error"
    assert "非法" in response["message"]


def test_update_role_rejects_unknown_scope(roles_client):
    client, _ = roles_client
    response = client.put("/roles/ling", json={"display_name": "x"}).json()
    assert response["status"] == "error"
    assert "不存在" in response["message"]
