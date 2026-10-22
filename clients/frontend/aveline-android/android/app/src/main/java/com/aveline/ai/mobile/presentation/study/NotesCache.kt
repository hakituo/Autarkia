package com.aveline.ai.mobile.presentation.study

import android.content.Context
import com.aveline.ai.mobile.domain.models.LibraryNote
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put
import java.io.File

/**
 * 学习库笔记本地磁盘缓存（单向：后端 → 手机本地，只读镜像）。
 *
 * 解决两个体验问题：
 * - 后端每次都要全盘扫描 Study 目录，库大时列表要等几秒 → 列表快照先秒开；
 * - 同一篇大笔记反复展开时不再每次走网络 → 正文按需镜像 + 离线可读。
 *
 * 存储结构：
 * - <filesDir>/study-library/<rel_path>   镜像笔记正文（只缓存用户打开过的）
 * - <filesDir>/study-library/index.json    rel_path -> 正文对应的后端 updated_ts（毫秒）
 * - <filesDir>/study-library/library.json  列表快照：notes + version + saved_at
 *
 * 注意：后端 updated_ts 是文件 mtime（毫秒整数），本身是可靠的"内容是否变化"判据，
 * 因此以它为准做增量，不做内容 hash 比较（省 IO）。
 */
class NotesCache(context: Context) {
    private val rootDir = File(context.filesDir, "study-library").apply { mkdirs() }
    private val indexFile = File(rootDir, "index.json")
    private val listFile = File(rootDir, "library.json")

    private val json = Json { encodeDefaults = true }

    /** 本地列表快照。 */
    data class CachedLibrary(
        val notes: List<LibraryNote>,
        val version: String?,
        val savedAt: Long
    )

    /** 读取 index：rel_path -> updated_ts */
    private fun readIndex(): MutableMap<String, Long> {
        if (!indexFile.isFile) return mutableMapOf()
        return runCatching {
            val obj = json.parseToJsonElement(indexFile.readText()).jsonObject
            obj.mapValues { (_, v) -> v.jsonPrimitive.longOrNull ?: 0L }.toMutableMap()
        }.getOrDefault(mutableMapOf())
    }

    private fun writeIndex(index: Map<String, Long>) {
        runCatching {
            val arr = buildJsonArray {
                index.forEach { (path, ts) ->
                    add(buildJsonObject {
                        put("path", path)
                        put("ts", ts)
                    })
                }
            }
            indexFile.writeText(arr.toString())
        }
    }

    /** 本地是否存在该路径的正文文件 */
    private fun localFile(relPath: String): File = File(rootDir, relPath)

    /**
     * 读取列表快照；不存在或解析失败返回 null。
     *
     * 调用方应在 IO 线程调用（内部是阻塞文件读取）。
     */
    fun readLibrary(): CachedLibrary? {
        if (!listFile.isFile) return null
        return runCatching {
            val obj = json.parseToJsonElement(listFile.readText()).jsonObject
            val version = obj["version"]?.jsonPrimitive?.contentOrNull
            val savedAt = obj["saved_at"]?.jsonPrimitive?.longOrNull ?: 0L
            val notes = obj["notes"]?.jsonArray?.mapNotNull { item ->
                val note = item.jsonObject
                val relPath = note["rel_path"]?.jsonPrimitive?.contentOrNull.orEmpty()
                if (relPath.isBlank()) return@mapNotNull null
                LibraryNote(
                    subject = note["subject"]?.jsonPrimitive?.contentOrNull.orEmpty(),
                    filename = note["filename"]?.jsonPrimitive?.contentOrNull.orEmpty(),
                    relPath = relPath,
                    updatedTs = note["updated_ts"]?.jsonPrimitive?.longOrNull ?: 0L
                )
            }.orEmpty()
            CachedLibrary(notes = notes, version = version, savedAt = savedAt)
        }.getOrNull()
    }

    /** 写入列表快照（notes 需已过滤隐藏项）。调用方应在 IO 线程调用。 */
    fun writeLibrary(notes: List<LibraryNote>, version: String?) {
        runCatching {
            val arr = buildJsonArray {
                notes.forEach { note ->
                    add(buildJsonObject {
                        put("subject", note.subject)
                        put("filename", note.filename)
                        put("rel_path", note.relPath)
                        put("updated_ts", note.updatedTs)
                    })
                }
            }
            val payload = buildJsonObject {
                put("version", version ?: "")
                put("saved_at", System.currentTimeMillis())
                put("notes", arr)
            }
            listFile.writeText(payload.toString())
        }
    }

    /**
     * 本地正文是否与后端最新 ts 一致。
     *
     * 文件存在但 index 记录的是旧 ts，说明后端已改过，不能直接展示旧正文。
     */
    fun isContentFresh(relPath: String, latestTs: Long): Boolean {
        val local = localFile(relPath)
        if (!local.isFile || local.length() == 0L) return false
        return readIndex()[relPath] == latestTs
    }

    /** 读取本地缓存内容；不存在或读取失败返回 null */
    fun readContent(relPath: String): String? {
        return runCatching { localFile(relPath).takeIf { it.isFile }?.readText() }.getOrNull()
    }

    /**
     * 写入正文缓存：内容存到镜像路径，ts 更新进 index。
     *
     * @param ts 后端列表里的 updated_ts（毫秒），不是本地写入时间——
     *           写成本地时间会让 [isContentFresh] 永远判定不一致，导致每次打开都走网络。
     */
    fun write(relPath: String, content: String, ts: Long) {
        runCatching {
            val file = localFile(relPath)
            file.parentFile?.mkdirs()
            file.writeText(content)
            val index = readIndex()
            index[relPath] = ts
            writeIndex(index)
        }
    }
}
