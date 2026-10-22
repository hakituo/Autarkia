package com.aveline.ai.mobile.presentation.study

import com.aveline.ai.mobile.domain.models.LibraryNote

/**
 * 学习库笔记文件夹树节点。
 */
sealed class NoteTreeNode {
    abstract val name: String
    abstract val path: String

    /** 文件夹节点 */
    data class Folder(
        override val name: String,
        override val path: String,
        val children: List<NoteTreeNode>
    ) : NoteTreeNode()

    /** 文件节点 */
    data class File(
        override val name: String,
        override val path: String,
        val note: LibraryNote
    ) : NoteTreeNode()

    /** 递归统计该节点下（含子目录）的 .md 文件数量 */
    fun fileCount(): Int = when (this) {
        is File -> 1
        is Folder -> children.sumOf { it.fileCount() }
    }
}

/** 判断笔记路径是否包含隐藏目录/文件（防御性过滤） */
fun LibraryNote.isHidden(): Boolean =
    relPath.split("/").any { it.startsWith(".") } || filename.startsWith(".")

/**
 * 将扁平的 [LibraryNote] 列表构建为文件夹树。
 *
 * 顶层节点为科目文件夹（subject），下面按 relPath 的目录层级递归展开。
 * 返回结果按名称排序。
 */
fun buildNoteTree(notes: List<LibraryNote>): List<NoteTreeNode.Folder> {
    // 按 subject 分组，组内按 relPath 排序
    val grouped = notes.groupBy { it.subject }.toSortedMap(String.CASE_INSENSITIVE_ORDER)
    return grouped.map { (subject, subjectNotes) ->
        // 把每个 note 的 relPath 去掉 subject 前缀后的部分作为相对路径
        val root = mutableMapOf<String, NoteTreeNode>()
        subjectNotes.sortedBy { it.relPath.lowercase() }.forEach { note ->
            val parts = note.relPath.split("/")
            // parts[0] 为 subject，剩余部分为子路径
            val tailParts = parts.drop(1)
            insertNote(root, tailParts, note)
        }
        NoteTreeNode.Folder(
            name = subject,
            path = subject,
            children = root.values.sortedWith(compareBy({ it !is NoteTreeNode.Folder }, { it.name.lowercase() }))
        )
    }
}

/**
 * 递归把文件插入到文件夹树。
 *
 * @param map 当前层级的节点映射（path -> node）
 * @param remainingParts 当前 note 在 subject 之下的剩余路径段
 * @param note 原始笔记
 */
private fun insertNote(
    map: MutableMap<String, NoteTreeNode>,
    remainingParts: List<String>,
    note: LibraryNote
) {
    if (remainingParts.isEmpty()) return
    val head = remainingParts.first()
    // 当前层级的完整路径：用原 relPath 截断到当前深度
    val depth = note.relPath.split("/").size - remainingParts.size
    val pathParts = note.relPath.split("/").take(depth + 1)
    val nodePath = pathParts.joinToString("/")

    if (remainingParts.size == 1) {
        // Ye：文件
        map[nodePath] = NoteTreeNode.File(
            name = head.removeSuffix(".md"),
            path = note.relPath,
            note = note
        )
    } else {
        // 中间节点：文件夹
        val folder = map[nodePath] as? NoteTreeNode.Folder
            ?: NoteTreeNode.Folder(name = head, path = nodePath, children = emptyList())
        val childMap = folder.children.toMutableMapByPath()
        insertNote(childMap, remainingParts.drop(1), note)
        map[nodePath] = folder.copy(
            children = childMap.values.sortedWith(compareBy({ it !is NoteTreeNode.Folder }, { it.name.lowercase() }))
        )
    }
}

/** 把节点列表转成以 path 为 key 的 MutableMap，便于插入子节点 */
private fun List<NoteTreeNode>.toMutableMapByPath(): MutableMap<String, NoteTreeNode> =
    this.associateBy { it.path }.toMutableMap()
