package com.aveline.ai.mobile.services.foreground

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 通知深链的角色解析。
 *
 * 后端 proactive_message 下发的 conversation_id 有两类形态：
 * - QQ / shared 侧：private_10001__persona__core_aveline；
 * - App 自己的会话：web_role_aveline（RoleScopedPreferences.defaultSessionId）。
 *
 * 两类都与 NavGraph 的 chat 深链参数不一致（深链没有 ?session_id=），必须解析成 role
 * 才能走 aveline://chat?role= 深链，否则点了通知没反应；角色解析不出来时主动消息还会被
 * 整条丢弃（只弹通知、不落库），表现为「有通知，点进去却没有这条消息」。
 */
class WebSocketCommandCoordinatorRoleTest {

    @Test
    fun `parses role from qq persona conversation id`() {
        assertEquals(
            "aveline",
            WebSocketCommandCoordinator.roleIdFromConversationId(
                "private_10001__persona__core_aveline"
            )
        )
    }

    @Test
    fun `parses role without core prefix`() {
        assertEquals(
            "ling",
            WebSocketCommandCoordinator.roleIdFromConversationId("shared__persona__ling")
        )
    }

    /**
     * App 自己的角色会话 id。
     *
     * Active Care 把 App 会话当主会话时，下发的 target 就是 web_role_<slug>，
     * **不含** `__persona__`。此前解析不出角色 → 只弹通知不归档 → 点通知进去没有这条消息。
     */
    @Test
    fun `parses role from local web role session id`() {
        assertEquals(
            "aveline",
            WebSocketCommandCoordinator.roleIdFromConversationId("web_role_aveline")
        )
    }

    /** slug 里的下划线属于角色名本身，不能被截断。 */
    @Test
    fun `keeps underscores inside web role slug`() {
        assertEquals(
            "sylas_ai",
            WebSocketCommandCoordinator.roleIdFromConversationId("web_role_sylas_ai")
        )
    }

    /** web_role_ 前缀的大小写不敏感（roleSlug 已小写，但旧数据可能不是）。 */
    @Test
    fun `parses web role session id case insensitively`() {
        assertEquals(
            "aveline",
            WebSocketCommandCoordinator.roleIdFromConversationId("WEB_ROLE_Aveline")
        )
    }

    /**
     * 非 ASCII 角色名会退化成 16 位十六进制摘要，那不是角色 id。
     * 若当 role 用会凭空建出一个假会话，必须判为解析不出。
     */
    @Test
    fun `rejects hashed web role session id`() {
        assertNull(
            WebSocketCommandCoordinator.roleIdFromConversationId("web_role_3f2a9c1d5e6b7a80")
        )
    }

    @Test
    fun `returns null when persona marker missing`() {
        assertNull(WebSocketCommandCoordinator.roleIdFromConversationId("mobile_user"))
        assertNull(WebSocketCommandCoordinator.roleIdFromConversationId("private_123456789"))
        assertNull(WebSocketCommandCoordinator.roleIdFromConversationId("web_core_aveline.json"))
        assertNull(WebSocketCommandCoordinator.roleIdFromConversationId("web_role_"))
        assertNull(WebSocketCommandCoordinator.roleIdFromConversationId(null))
        assertNull(WebSocketCommandCoordinator.roleIdFromConversationId(""))
    }
}
