package com.aveline.ai.mobile.presentation.settings

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.Settings
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import com.aveline.ai.mobile.services.AvelineAccessibilityService
import rikka.shizuku.Shizuku

internal enum class ShizukuState {
    NOT_INSTALLED,
    NOT_RUNNING,
    NOT_AUTHORIZED,
    AUTHORIZED
}

/**
 * 设备级权限状态：无障碍与 Shizuku 都要读系统状态，放在界面层检测，
 * ViewModel 只负责使用统计 / 通知监听两项（它们在 ContextRepository 里）。
 */
internal data class DevicePermissionStatus(
    val accessibilityRunning: Boolean = false,
    val accessibilityEnabledInSystem: Boolean = false,
    val shizuku: ShizukuState = ShizukuState.NOT_INSTALLED
) {
    val accessibilityReady: Boolean
        get() = accessibilityRunning || accessibilityEnabledInSystem

    /** Shizuku 三步里已经完成的步数：安装 → 启动服务 → 授权。 */
    val shizukuStepsDone: Int
        get() = when (shizuku) {
            ShizukuState.NOT_INSTALLED -> 0
            ShizukuState.NOT_RUNNING -> 1
            ShizukuState.NOT_AUTHORIZED -> 2
            ShizukuState.AUTHORIZED -> 3
        }

    val shizukuReady: Boolean
        get() = shizuku == ShizukuState.AUTHORIZED
}

@Composable
internal fun rememberDevicePermissionStatus(refreshKey: Int): DevicePermissionStatus {
    val context = LocalContext.current
    var status by remember { mutableStateOf(evaluateDevicePermissionStatus(context)) }
    LaunchedEffect(refreshKey) {
        status = evaluateDevicePermissionStatus(context)
    }
    return status
}

internal fun evaluateDevicePermissionStatus(context: Context): DevicePermissionStatus {
    val running = runCatching { AvelineAccessibilityService.isRunning() }.getOrDefault(false)
    val enabledInSystem = if (running) {
        true
    } else {
        runCatching { isAccessibilityServiceEnabledInSettings(context) }.getOrDefault(false)
    }

    val installed = runCatching {
        context.packageManager.getPackageInfo(SHIZUKU_PACKAGE, 0)
        true
    }.getOrDefault(false)

    val shizuku = try {
        when {
            !installed -> ShizukuState.NOT_INSTALLED
            !Shizuku.pingBinder() -> ShizukuState.NOT_RUNNING
            Shizuku.checkSelfPermission() != PackageManager.PERMISSION_GRANTED ->
                ShizukuState.NOT_AUTHORIZED
            else -> ShizukuState.AUTHORIZED
        }
    } catch (e: Exception) {
        if (installed) ShizukuState.NOT_RUNNING else ShizukuState.NOT_INSTALLED
    }

    return DevicePermissionStatus(
        accessibilityRunning = running,
        accessibilityEnabledInSystem = enabledInSystem,
        shizuku = shizuku
    )
}

/**
 * 系统「已启用无障碍服务」字段格式是 `pkg/svc:pkg/svc:...`，
 * 部分 ROM 用 `;` 分隔。服务进程被杀后这里仍为 true，可与 running 区分。
 */
private fun isAccessibilityServiceEnabledInSettings(context: Context): Boolean {
    val target = ComponentName(
        context.packageName,
        AvelineAccessibilityService::class.java.name
    ).flattenToString()
    val enabledServices = Settings.Secure.getString(
        context.contentResolver,
        Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES
    ) ?: return false
    val splitter = if (enabledServices.contains(":")) ":" else ";"
    return enabledServices.split(splitter).any { it.equals(target, ignoreCase = true) }
}

/**
 * 权限向导里的系统跳转。
 *
 * 全部静默兜底：国产 ROM 常把某个设置页裁掉，失败时不能让设置页崩掉。
 */
internal object DevicePermissionActions {

    fun openAccessibilitySettings(context: Context) {
        val intent = Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        runCatching { context.startActivity(intent) }.onFailure {
            runCatching {
                context.startActivity(
                    Intent(Settings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                )
            }
        }
    }

    fun openShizukuMarket(context: Context) {
        val market = Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=$SHIZUKU_PACKAGE"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        runCatching { context.startActivity(market) }.onFailure {
            runCatching {
                context.startActivity(
                    Intent(
                        Intent.ACTION_VIEW,
                        Uri.parse("https://play.google.com/store/apps/details?id=$SHIZUKU_PACKAGE")
                    ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                )
            }
        }
    }

    fun launchShizukuApp(context: Context) {
        val direct = Intent().apply {
            setClassName(SHIZUKU_PACKAGE, "moe.shizuku.manager.MainActivity")
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        runCatching { context.startActivity(direct) }.onFailure {
            runCatching {
                context.packageManager.getLaunchIntentForPackage(SHIZUKU_PACKAGE)
                    ?.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    ?.let(context::startActivity)
            }
        }
    }

    fun requestShizukuPermission() {
        runCatching { Shizuku.requestPermission(SHIZUKU_PERMISSION_REQUEST_CODE) }
    }
}

private const val SHIZUKU_PACKAGE = "moe.shizuku.privileged.api"
private const val SHIZUKU_PERMISSION_REQUEST_CODE = 1001
