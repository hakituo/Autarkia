package com.aveline.ai.mobile.data.local.preferences

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 本地会话 → persona filename 的反查。
 *
 * 主动消息（Active Care）的 payload 不带 profile_filename、且 conversation_id 就是 App
 * 自己的角色会话（web_role_aveline）时，归档只能靠这条反查拿到归属角色；拿不到就只能
 * 弹通知、写不进聊天记录。
 */
class PersonaSessionIndexTest {

    private fun snapshot(vararg pairs: Pair<String, Any?>): Map<String, Any?> =
        pairs.toMap()

    @Test
    fun `finds persona filename by local session id`() {
        val entries = snapshot(
            "persona_session:core_aveline.json" to "web_role_aveline",
            "persona_session:variants/lin_b.json" to "web_role_lin",
            "session:deadbeef" to "web_role_aveline",
            "unrelated_key" to "web_role_aveline"
        )

        assertEquals(
            "core_aveline.json",
            PersonaSessionIndex.profileFilenameForSession(entries, "web_role_aveline")
        )
    }

    @Test
    fun `ignores keys outside the persona session prefix`() {
        val entries = snapshot("session:deadbeef" to "web_role_aveline")

        assertNull(PersonaSessionIndex.profileFilenameForSession(entries, "web_role_aveline"))
    }

    /** 后端 cid 不是本地会话，不允许拿它反查。 */
    @Test
    fun `refuses non local session ids`() {
        val entries = snapshot("persona_session:core_aveline.json" to "web_role_aveline")

        assertNull(
            PersonaSessionIndex.profileFilenameForSession(
                entries,
                "private_10001__persona__core_aveline"
            )
        )
        assertNull(PersonaSessionIndex.profileFilenameForSession(entries, "mobile_user"))
    }

    @Test
    fun `tolerates blank and unknown session ids`() {
        val entries = snapshot("persona_session:core_aveline.json" to "web_role_aveline")

        assertNull(PersonaSessionIndex.profileFilenameForSession(entries, ""))
        assertNull(PersonaSessionIndex.profileFilenameForSession(entries, "web_role_unknown"))
        assertNull(PersonaSessionIndex.profileFilenameForSession(emptyMap(), "web_role_aveline"))
    }

    /** 值不是字符串（旧版本可能写过非字符串）时不能崩，直接跳过。 */
    @Test
    fun `skips non string values`() {
        val entries = snapshot(
            "persona_session:core_aveline.json" to 42,
            "persona_session:core_ling.json" to "web_role_ling"
        )

        assertEquals(
            "core_ling.json",
            PersonaSessionIndex.profileFilenameForSession(entries, "web_role_ling")
        )
    }

    /** 会话 id 前后空白不影响命中（prefs 里存的是原始串）。 */
    @Test
    fun `trims incoming session id`() {
        val entries = snapshot("persona_session:core_aveline.json" to "web_role_aveline")

        assertEquals(
            "core_aveline.json",
            PersonaSessionIndex.profileFilenameForSession(entries, "  web_role_aveline  ")
        )
    }
}
