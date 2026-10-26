"""双角色互聊配置加载器

职责：加载多QQ配置（master_qq_id / 角色 QQ 号 / persona 文件名 / 角色名）。

从 peer_script_generator.py 的 _load_peer_config 拆分，纯函数、无宿主依赖。
"""

import os as _os

from typing import Any, Dict


class PeerConfigLoader:
    """双角色互聊配置加载器"""

    def load(self, role_id: str, peer_role_id: str) -> Dict[str, Any]:
        """阶段1：加载多QQ配置（master_qq_id / 角色 QQ 号 / persona 文件名）

        通过 get_multi_qq_role_config() 强类型访问 + 环境变量读取，
        回退到 personas 权威源(N 角色动态)。
        """
        # 局部导入：避免 config 包循环导入（本模块可能在 config 完成初始化前被导入）
        from config.settings_adapters import get_multi_qq_role_config

        role_cfg = get_multi_qq_role_config(role_id)
        peer_cfg = get_multi_qq_role_config(peer_role_id)

        master_qq_id = _os.getenv("AUTARKIA_QQ_MASTER_ID", "").strip()

        # 角色 QQ 号:N 角色通用读法
        role_qq_id = self._resolve_role_qq(role_id, role_cfg)
        peer_role_qq_id = self._resolve_role_qq(peer_role_id, peer_cfg)

        # profile_filename:优先用强类型配置,缺失时从 personas 查 config_filename
        role_persona_fn = self._resolve_profile_filename(role_id, role_cfg)
        peer_persona_fn = self._resolve_profile_filename(peer_role_id, peer_cfg)

        # role_name:优先用强类型配置,缺失时从 personas 查 cn_name
        role_name = self._resolve_role_name(role_id, role_cfg)
        peer_name = self._resolve_role_name(peer_role_id, peer_cfg)

        return {
            "master_qq_id": master_qq_id,
            "role_qq_id": role_qq_id,
            "peer_role_qq_id": peer_role_qq_id,
            "role_persona_fn": role_persona_fn,
            "peer_persona_fn": peer_persona_fn,
            "role_name": role_name,
            "peer_name": peer_name,
        }

    def load_multi(
        self,
        participants: list,
        *,
        role_id: str = "",
    ) -> Dict[str, Any]:
        """加载多角色互聊配置（任意 2-3 人）。

        与 ``load`` 的差异：
        - 不再要求 master_qq_id 非空（本地通道不需要 QQ）；
        - 返回 ``by_role`` 映射，QQ 通道按角色取 persona/qq_id；
        - 保留 ``role_id`` 的发起方字段，兼容旧调用方读取方式。

        Returns:
            {
              "master_qq_id": str,
              "by_role": {role_id: {"role_id","role_name","profile_filename","qq_id"}},
              "role_id": 发起者,
              "role_name": 发起者中文名,
              "peer_role_id": 第一个其他参与者（向后兼容）,
              "peer_name": 对应中文名,
            }
        """
        members = [str(p).strip().lower() for p in participants if str(p).strip()]
        initiator = str(role_id or (members[0] if members else "")).strip().lower()
        master_qq_id = _os.getenv("AUTARKIA_QQ_MASTER_ID", "").strip()

        # 局部导入：与 load 一致，避免 config 包循环导入
        from config.settings_adapters import get_multi_qq_role_config

        by_role: Dict[str, Dict[str, str]] = {}
        for rid in members:
            cfg_obj = get_multi_qq_role_config(rid)
            by_role[rid] = {
                "role_id": rid,
                "role_name": self._resolve_role_name(rid, cfg_obj),
                "profile_filename": self._resolve_profile_filename(rid, cfg_obj),
                "qq_id": self._resolve_role_qq(rid, cfg_obj),
            }

        peers = [rid for rid in members if rid != initiator]
        peer_role_id = peers[0] if peers else ""
        return {
            "master_qq_id": master_qq_id,
            "by_role": by_role,
            "role_id": initiator,
            "role_name": by_role.get(initiator, {}).get("role_name", initiator),
            "peer_role_id": peer_role_id,
            "peer_name": by_role.get(peer_role_id, {}).get("role_name", peer_role_id),
        }

    def _resolve_role_qq(self, rid: str, cfg_obj) -> str:
        """从 config 或 env var 解析角色 QQ 号(N 角色通用)"""
        if cfg_obj is not None:
            val = str(getattr(cfg_obj, "role_qq_id", "") or "").strip()
            if val:
                return val
        # 向后兼容:aveline/ling 用旧 env var 名
        if rid == "aveline":
            val = _os.getenv("AUTARKIA_QQ_BOT_NUMBER", "").strip()
            if val:
                return val
        elif rid == "ling":
            val = _os.getenv("AUTARKIA_QQ_BOT_NUMBER_LING", "").strip()
            if val:
                return val
        # N 角色通用:AUTARKIA_QQ_BOT_NUMBER_{ROLE_ID_UPPER}
        return _os.getenv(f"AUTARKIA_QQ_BOT_NUMBER_{rid.upper()}", "").strip()

    @staticmethod
    def _resolve_profile_filename(rid: str, cfg_obj) -> str:
        """从 config 或 personas 权威源解析 persona 文件名"""
        from core.services.dual_role.personas import get_persona

        if cfg_obj is not None:
            val = str(getattr(cfg_obj, "profile_filename", "") or "").strip()
            if val:
                return val
        p = get_persona(rid)
        if p:
            return p.config_filename
        return ""

    @staticmethod
    def _resolve_role_name(rid: str, cfg_obj) -> str:
        """从 config 或 personas 权威源解析角色名"""
        from core.services.dual_role.personas import get_persona

        if cfg_obj is not None:
            val = str(getattr(cfg_obj, "role_name", "") or "").strip()
            if val:
                return val
        p = get_persona(rid)
        if p:
            return p.cn_name
        return ""