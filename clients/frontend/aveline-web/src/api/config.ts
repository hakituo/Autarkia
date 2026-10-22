// API配置文件

// 环境类型定义
export type Environment = 'development' | 'production' | 'staging';

// 获取当前环境 - 使用Vite推荐的方式
const getCurrentEnvironment = (): Environment => {
  // 在浏览器环境中，我们通过检测URL或其他方式来判断环境
  try {
    // 检查是否在开发服务器环境
    if (typeof window !== 'undefined' && window.location) {
      const port = window.location.port;
      
      // Web 前端统一使用 3000；不再兼容历史默认端口。
      if (port === '3000') {
        return 'development';
      }
    }
  } catch (e) {
    // 忽略错误，默认返回开发环境
  }
  
  // 默认返回开发环境
  return 'development';
};

// 环境配置
const hostname = (typeof window !== 'undefined' && window.location) ? window.location.hostname : '127.0.0.1';
const origin = (typeof window !== 'undefined' && window.location) ? window.location.origin : 'http://localhost:3000';
const port = (typeof window !== 'undefined' && window.location) ? window.location.port : '';
const isDevServer = port === '3000';
// 本机回环访问：直连 8000；非回环（局域网 / Tailscale 100.x / MagicDNS）走同源代理。
const isLoopbackHost = ['localhost', '127.0.0.1', '::1', '[::1]'].includes(hostname);

// 动态构建API地址
// 前端开发端口固定为 3000，后端 API 固定为 8000。
let apiBase = origin;

// 1. 优先读取 LocalStorage 配置 (Android/用户自定义)
try {
  if (typeof window !== 'undefined') {
    const customUrl = localStorage.getItem('AVELINE_API_URL');
    if (customUrl && customUrl.trim() !== '') {
      apiBase = customUrl.trim();
      // 如果自定义了 URL，我们直接使用它，不再进行后续的自动探测
      // 但我们需要标记这是一个 overrides，以便调试
      console.log('[Config] Using custom API URL:', apiBase);
    } else {
        // Fallback to auto-detection logic
        performAutoDetection();
    }
  } else {
    performAutoDetection();
  }
} catch (e) {
  performAutoDetection();
}

function performAutoDetection() {
  if (isDevServer) {
    if (isLoopbackHost) {
      // 本机开发：前端 3000 直连后端 8000。
      // 强制将 localhost 转换为 127.0.0.1 以规避 Windows IPv6 优先级导致的连接失败问题。
      const effectiveHostname = hostname === 'localhost' ? '127.0.0.1' : hostname;
      apiBase = `http://${effectiveHostname}:8000`;
    } else {
      // 局域网 / Tailscale（100.x / *.ts.net）远端访问：保持同源，由本机 Vite 代理转发
      // 到 127.0.0.1:8000。这样 Origin 与页面一致，不依赖 CORS 白名单，
      // 媒体 cookie 也按 `Path=/output` 正常携带。
      apiBase = origin;
      console.log('[Config] Remote dev host detected, using same-origin Vite proxy:', apiBase);
    }
  }

  // 自动适配：如果当前前端就在 8000-8005 端口运行（打包后的单端口模式），API 指向自己。
  if (port >= '8000' && port <= '8005') {
    apiBase = `http://${hostname}:${port}`;
  }

  // Electron 环境下的特殊处理
  if (typeof window !== 'undefined' && navigator.userAgent.toLowerCase().includes('electron') && origin.startsWith('file://')) {
    apiBase = 'http://127.0.0.1:8000';
  }
}

const environments = {
  development: {
    apiBaseUrl: apiBase,
    debug: true,
    timeout: 120000,
  },
  production: {
    apiBaseUrl: apiBase,
    debug: false,
    timeout: 120000,
  },
  staging: {
    apiBaseUrl: apiBase,
    debug: true,
    timeout: 45000,
  },
};

// 当前环境配置
const currentEnv = getCurrentEnvironment();
const config = environments[currentEnv];

// 导出配置
export default {
  ...config,
  environment: currentEnv,
};
