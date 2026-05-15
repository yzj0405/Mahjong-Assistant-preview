# 任务目标：开发 AR-Mahjong-Assistant 的 Android 手机客户端

你现在是一个资深的 Android (Kotlin) 开发专家。我需要你基于现有的项目，为其开发一个全新的 Android 手机端客户端。

## 1. 业务场景与核心逻辑
原项目通过 AR 眼镜录制图像并传给 FastAPI 后端进行 YOLOv8 识别与牌效计算。
现在，我们要将“AR眼镜录制”改为“手机屏幕实时采集”。
- 目标：监控手机上正在运行的麻将小程序或麻将游戏 App（通常在后台运行或作为前台游戏）。
- 形式：客户端通过【前台服务】常驻后台捕获屏幕，通过【全局悬浮窗】在游戏画面上层实时绘制“切牌建议”和“进张数”。

## 2. 客户端技术栈
- 开发语言：Kotlin
- UI 框架：Jetpack Compose (用于主界面和悬浮窗内容渲染)
- 核心机制：MediaProjection (免Root截屏) + WindowManager (系统全局悬浮窗) + Foreground Service (防杀前台服务)
- 网络通信：Retrofit2 + OkHttp3 + Gson

## 3. 复用原项目的服务端接口规范
请参考原项目 `app/` 目录下的 FastAPI 逻辑，我们需要对接以下现有接口：
- **目标 URL**: `http://<YOUR_SERVER_IP>:8000/predict` (或原项目定义的识别接口)
- **请求格式**: `POST` 请求，通常传输包含屏幕截图的 `MultipartForm` 或 `Base64` 字符串（请按照原项目最通用的图像接收格式设计，支持 `file: MultipartBody.Part`）。
- **返回 JSON 结构体格式**（请在客户端定义对应的 Response Data Class）：
  ```json
  {
    "shanten": 1, 
    "recommend_comb": ["1m", "2m"],
    "is_agari": false,
    "predictions": [...] 
  }
  ```
  *(注：渲染时优先展示 shanten 向听数 和 recommend_comb 推荐切牌组合)*

---

# 🛠️ 完整的项目代码生成计划

请依次为我生成以下 4 个核心文件/模块的完整可运行代码。请不要使用伪代码，确保类型和导入（Imports）完整：

## 步骤 1：配置文件 (AndroidManifest.xml)
请配置好网络、悬浮窗、前台服务（Android 14+ 要求的媒体投影特定类型 MEDIA_PROJECTION）等所有权限。

## 步骤 2：数据层与网络请求 (Network & Data Layer)
- 定义 Response 数据类 `MahjongResponse`。
- 创建 Retrofit 接口 `MahjongApiService`（包含上传图片/Bitmap 文件的 `POST` 请求）。
- 创建单例 `RetrofitClient`，提供动态修改服务器 IP 的能力。

## 步骤 3：核心后台服务 (ScreenCaptureService.kt)
- 继承自 `LifecycleService`，启动时显示常驻通知（Notification Channel）。
- 接收 `MediaProjection` 授权，利用 `VirtualDisplay` 和 `ImageReader` 实现每 2 秒定时捕获屏幕。
- 捕获后，将 Bitmap 自动裁剪缩放至 YOLO 适用的比例，调用 `MahjongApiService` 发送请求。
- 收到响应后，通过 LiveData/StateFlow 或直接通知悬浮窗更新 UI。

## 步骤 4：全局悬浮窗与主界面 (FloatingWindow & UI Layer)
- 实现 `FloatingWindowManager`，使用 `WindowManager` 创建一个可拖动的全局悬浮窗（TYPE_APPLICATION_OVERLAY）。
- 悬浮窗内部使用 Compose 或原生 View 渲染：显示当前的“向听数”和“推荐切牌”。
- 实现 `MainActivity`，包含：动态申请悬浮窗权限、请求屏幕捕捉权限、输入服务器 IP 地址、一键启动/停止服务的控制按钮。

