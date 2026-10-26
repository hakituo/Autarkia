package com.aveline.ai.mobile.presentation.mall

import com.aveline.ai.mobile.domain.models.RecipientOption
import com.aveline.ai.mobile.domain.repository.PersonaRepository
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive

/**
 * 「给谁买 / 给谁吃 / 送给谁」的候选：完全来自后端 persona 列表，只含注册过角色的条目。
 *
 * 商城与库存两个 ViewModel 共用这一份口径；后端新增 / 删除角色后自动跟随，本地不维护
 * 角色 id → 名称映射。
 */
internal suspend fun loadRecipientOptions(
    personaRepository: PersonaRepository
): List<RecipientOption> {
    val personas = runCatching { personaRepository.getPersonasRawCached() }
        .getOrNull()
        ?.getOrNull()
        .orEmpty()
    val options = mutableListOf<RecipientOption>()
    personas.forEach { element ->
        val obj = element as? JsonObject ?: return@forEach
        val roleId = runCatching {
            obj["role_id"]?.jsonPrimitive?.contentOrNull?.trim().orEmpty()
        }.getOrDefault("")
        // 未注册到角色注册表的人设不下发 role_id，跳过
        if (roleId.isEmpty()) return@forEach
        val label = runCatching {
            obj["name"]?.jsonPrimitive?.contentOrNull?.trim().orEmpty()
        }.getOrDefault("").ifEmpty { roleId }
        if (options.none { it.id == roleId }) {
            options.add(RecipientOption(roleId, label))
        }
    }
    return options
}
